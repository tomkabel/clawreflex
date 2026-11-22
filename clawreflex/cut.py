#!/usr/bin/env python3
"""Cut a real screen recording into the ClawReflex story: an edit decision list (JSON) in, a 1920x1080 MP4 out.

Every frame comes from a recording. The edit only chooses which seconds to show, how fast (labelled when not 1x),
where the camera looks (an eased crop of the 2560x1440 capture), and what the captions say. A skipped wait is
never hidden: the edit list must name it, and a card on screen says what was cut and for how long.

EDL: {"fps": 30, "out": "clip.mp4", "segments": [
  {"layers": [{"src": "screen.mp4", "from": 12.0, "speed": 1, "cam": [[0, x, y, w], [1.5, x, y, w]],
               "dest": [0, 0, 1920, 1080]}],
   "dur": 4.0, "captions": [[0, 4, "Tom changes one line."]], "badge": "REAL TIME", "card": "Skipped 41 s: ..."}]}
cam rows are [time into the segment, left, top, width] of a 16:9 window in the source (height follows the dest's shape).
Caption text may colour words: {red|RED}, {green|GREEN}, {orange|Cerebras}.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FONTS = Path(__file__).resolve().parents[1] / "skills" / "cerebras-demo-basics" / "assets" / "fonts"
COLOURS = {"red": (255, 92, 92), "green": (72, 216, 144), "orange": (255, 122, 69), "white": (255, 255, 255), "dim": (190, 198, 208)}


def font(size, weight=800):
    return ImageFont.truetype(str(FONTS / f"manrope-{weight}.ttf"), size)


def ease(t):
    return t * t * (3 - 2 * t)


def cam_at(cam, t):
    if t <= cam[0][0]:
        return cam[0][1:]
    for a, b in zip(cam, cam[1:]):
        if t <= b[0]:
            k = ease((t - a[0]) / max(1e-6, b[0] - a[0]))
            return [p + (q - p) * k for p, q in zip(a[1:], b[1:])]
    return cam[-1][1:]


def spans(text):
    out = []
    for colour, plain, rest in re.findall(r"\{(\w+)\|([^}]*)\}|([^{]+)", text):
        out.append((COLOURS[colour], plain) if colour else (COLOURS["white"], rest))
    return out


def caption_image(text, size=58):
    """A caption: bold words on a dark rounded plate, centred, wrapped to two lines at most."""
    f = font(size)
    words = []
    for colour, chunk in spans(text):
        for i, word in enumerate(chunk.split(" ")):
            if word:
                words.append((colour, word, i > 0 or chunk.startswith(" ") or not words))
    lines, line, width, max_w = [], [], 0, W - 260
    space = f.getlength(" ")
    for colour, word, _ in words:
        w = f.getlength(word)
        if line and width + space + w > max_w:
            lines.append(line)
            line, width = [], 0
        width += (space if line else 0) + w
        line.append((colour, word, w))
    lines.append(line)
    line_h = int(size * 1.28)
    widths = [sum(w for _, _, w in l) + space * (len(l) - 1) for l in lines]
    pad_x, pad_y = 44, 24
    box_w, box_h = int(max(widths)) + 2 * pad_x, line_h * len(lines) + 2 * pad_y - int(size * 0.18)
    img = Image.new("RGBA", (box_w + 40, box_h + 40), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([20, 26, 20 + box_w, 26 + box_h], 30, fill=(0, 0, 0, 120))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, 20 + box_w, 20 + box_h], 30, fill=(13, 19, 26, 236))
    y = 20 + pad_y - int(size * 0.12)
    for l, lw in zip(lines, widths):
        x = 20 + (box_w - lw) / 2
        for colour, word, w in l:
            d.text((x, y), word, font=f, fill=colour)
            x += w + space
        y += line_h
    return img


def pill(text, colour=(255, 255, 255), bg=(13, 19, 26, 215), size=30):
    f = font(size, 700)
    w = int(f.getlength(text))
    img = Image.new("RGBA", (w + 48, size + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w + 47, size + 29], (size + 30) // 2, fill=bg)
    d.ellipse([18, (size + 30) // 2 - 5, 28, (size + 30) // 2 + 5], fill=colour)
    d.text((36, 13), text, font=f, fill=(235, 238, 242))
    return img


def card_image(title, body):
    """The 'we cut a wait' card: what was skipped, how long, and why."""
    img = Image.new("RGBA", (W, H), (8, 12, 17, 225))
    d = ImageDraw.Draw(img)
    tf, bf = font(72), font(40, 600)
    tw = d.textlength(title, font=tf)
    d.text(((W - tw) / 2, H / 2 - 90), title, font=tf, fill=(255, 204, 102))
    for i, line in enumerate(body.split("\n")):
        lw = d.textlength(line, font=bf)
        d.text(((W - lw) / 2, H / 2 + 20 + i * 58), line, font=bf, fill=(220, 226, 232))
    return img


class Layer:
    def __init__(self, spec, fps, dur):
        self.spec, self.fps = spec, fps
        self.src_w, self.src_h = [int(v) for v in subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", spec["src"]],
            text=True).strip().split(",")]
        speed = spec.get("speed", 1)
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-ss", str(spec["from"]), "-t", str(dur * speed + 1), "-i", spec["src"],
             "-vf", f"setpts=PTS/{speed},fps={fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.last = None
        self.dest = spec.get("dest", [0, 0, W, H])

    def frame(self):
        raw = self.proc.stdout.read(self.src_w * self.src_h * 3)
        if len(raw) == self.src_w * self.src_h * 3:
            self.last = Image.frombuffer("RGB", (self.src_w, self.src_h), raw)
        return self.last  # a segment longer than its source holds the last frame

    def close(self):
        self.proc.kill()
        self.proc.wait()


def render(edl, out):
    fps = edl.get("fps", 30)
    enc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
                            "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
                           stdin=subprocess.PIPE)
    timeline = []
    t0 = 0.0
    for seg in edl["segments"]:
        n = round(seg["dur"] * fps)
        layers = [Layer(l, fps, seg["dur"]) for l in seg["layers"]]
        caps = [(a, b, caption_image(text, seg.get("caption_size", 58))) for a, b, text in seg.get("captions", [])]
        badge = pill(seg["badge"], COLOURS.get(seg.get("badge_colour", "red"))) if seg.get("badge") else None
        skip = pill(seg["skip"], (255, 204, 102), (40, 30, 8, 240), 36) if seg.get("skip") else None
        cap_top = seg.get("caption_pos") == "top"
        badge_xy = (40, 36) if seg.get("badge_pos", "top") == "top" else ((W - badge.width) // 2 if badge else 0, H - (badge.height if badge else 0) - 14)
        card = card_image(*seg["card"]) if seg.get("card") else None
        timeline.append({"at": round(t0, 3), "dur": seg["dur"], "note": seg.get("note", ""), "badge": seg.get("badge"), "skip": seg.get("skip"), "captions": seg.get("captions", []),
                         "sources": [{k: l[k] for k in ("src", "from") } | {"speed": l.get("speed", 1)} for l in seg["layers"]]})
        for i in range(n):
            t = i / fps
            canvas = Image.new("RGB", (W, H), (13, 19, 26))
            for layer in layers:
                img = layer.frame()
                if img is None:
                    continue
                dx, dy, dw, dh = layer.dest
                x, y, w = cam_at(layer.spec.get("cam", [[0, 0, 0, layer.src_w]]), t)
                h = w * dh / dw
                canvas.paste(img.crop((round(x), round(y), round(x + w), round(y + h))).resize((dw, dh), Image.LANCZOS), (dx, dy))
            canvas = canvas.convert("RGBA")
            if badge:
                canvas.alpha_composite(badge, badge_xy)
            if skip and t < seg.get("skip_s", 2.6):
                k = min(1, t / 0.15, (seg.get("skip_s", 2.6) - t) / 0.3)
                faded = skip.copy()
                faded.putalpha(faded.getchannel("A").point(lambda v: int(v * k)))
                canvas.alpha_composite(faded, ((W - skip.width) // 2, 110))
            for a, b, img in caps:
                if a <= t < b:
                    alpha = min(1, (t - a) / 0.18, (b - t) / 0.18)
                    faded = img.copy()
                    faded.putalpha(faded.getchannel("A").point(lambda v: int(v * alpha)))
                    canvas.alpha_composite(faded, ((W - img.width) // 2, 0 if cap_top else H - img.height - 40))
            if card:
                k = min(1, t / 0.2, (seg["dur"] - t) / 0.2)
                faded = card.copy()
                faded.putalpha(faded.getchannel("A").point(lambda v: int(v * k)))
                canvas.alpha_composite(faded)
            enc.stdin.write(canvas.convert("RGB").tobytes())
        for layer in layers:
            layer.close()
        t0 += n / fps
    enc.stdin.close()
    enc.wait()
    Path(str(out) + ".timeline.json").write_text(json.dumps({"duration_s": round(t0, 3), "segments": timeline}, indent=2))
    print(out, round(t0, 2), "s")


if __name__ == "__main__":
    edl = json.loads(Path(sys.argv[1]).read_text())
    render(edl, Path(sys.argv[2] if len(sys.argv) > 2 else edl["out"]))
