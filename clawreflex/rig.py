#!/usr/bin/env python3
"""Film a real ClawReflex take: Zed (left) and the OpenClaw Control UI (right) on a private virtual screen.

A virtual X display keeps notifications, personal tabs and other windows out of the shot. Nothing here is
simulated: the keystrokes go to Zed, Zed saves the file, watch.py (running in Zed's terminal) hands the save to
the stage OpenClaw gateway, and server.py rewrites app.py only after the tests pass. ffmpeg records it all.

  python3 clawreflex/rig.py up       # display, Zed, Control UI, watcher
  python3 clawreflex/rig.py take     # record one take: edit, save, wait for the repair
  python3 clawreflex/rig.py shot     # screenshot of the display, for framing
  python3 clawreflex/rig.py down
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAGE = Path(os.environ.get("CLAWREFLEX_STAGE", ROOT / "out" / "clawreflex" / "stage"))
REPO = Path("/tmp/shop-app")  # outside any git repo: a clean title bar and prompt
TAKES = ROOT / "out" / "clawreflex" / "takes"
DISPLAY = ":77"
W, H = 2560, 1440
SPLIT = 1500  # Zed gets the left 1500 px, the Control UI the rest
PIDS = STAGE / "rig-pids.json"
X = dict(os.environ, DISPLAY=DISPLAY)
X.pop("WAYLAND_DISPLAY", None)

sys.path.insert(0, str(ROOT / "clawreflex"))
if __package__:
    from .fixtures import fixture  # noqa: E402
else:
    from fixtures import fixture  # noqa: E402
if __package__:
    from .server import EXPLOIT_FILENAME  # noqa: E402
else:
    from server import EXPLOIT_FILENAME  # noqa: E402

SPEC = fixture("sql", "shop")
# The developer's edit, as typed: the safe query becomes an f-string, and execute() loses its parameters.
SAFE_QUERY = '    query = "SELECT name FROM users_shop WHERE name = ? AND password = ?"'
EDIT_QUERY = '''query = f"SELECT name FROM users_shop WHERE name = '{username}' AND password = '{password}'"'''
EDIT_EXEC = 'result = db.execute(query).fetchone()'


def xdo(*args):
    return subprocess.run(["xdotool", *map(str, args)], env=X, capture_output=True, text=True).stdout.strip()


def spawn(name, argv, env, log):
    proc = subprocess.Popen(argv, env=env, stdout=open(STAGE / log, "w"), stderr=subprocess.STDOUT, start_new_session=True)
    pids = json.loads(PIDS.read_text()) if PIDS.exists() else {}
    pids[name] = proc.pid
    PIDS.write_text(json.dumps(pids))
    return proc


def window(pattern, tries=120):
    for _ in range(tries):
        found = xdo("search", "--onlyvisible", "--name", pattern).split()
        if found:
            return found[-1]
        time.sleep(0.25)
    raise SystemExit(f"no window matching {pattern!r}")


def up():
    assert SPEC["reference"].splitlines()[6] == SAFE_QUERY, "fixture changed: update the typed edit"
    spawn("xvfb", ["Xvfb", DISPLAY, "-screen", "0", f"{W}x{H}x24", "-nolisten", "tcp", "-dpi", "96"], X, "xvfb.log")
    time.sleep(1.5)
    REPO.mkdir(parents=True, exist_ok=True)
    (REPO / "app.py").write_text(SPEC["reference"], encoding="utf-8")
    (REPO / EXPLOIT_FILENAME).unlink(missing_ok=True)
    zed_env = dict(X, XDG_CONFIG_HOME=str(STAGE / "zed-config"))
    spawn("zed", ["zeditor", "--foreground", "--user-data-dir", str(STAGE / "zed-data"), str(REPO), str(REPO / "app.py")], zed_env, "zed.log")
    zed = window("app.py")
    time.sleep(2)
    xdo("windowmove", zed, 0, 0)
    xdo("windowsize", zed, SPLIT, H)
    subprocess.run(["node", str(ROOT / "clawreflex" / "rig-chrome.mjs"), str(STAGE)], cwd=ROOT, check=True, timeout=90)
    port = json.loads((STAGE / "openclaw.json").read_text())["gateway"]["port"]
    chrome = subprocess.check_output(["node", "-e", "import('./tools/chrome.mjs').then(m=>console.log(m.findChrome()))"], cwd=ROOT, text=True).strip()
    scale = 1.3
    spawn("chrome", [chrome, f"--user-data-dir={STAGE / 'chrome-profile'}", f"--app=http://127.0.0.1:{port}/chat/main",
                     f"--window-position={round(SPLIT / scale)},0", f"--window-size={round((W - SPLIT) / scale)},{round(H / scale)}",
                     f"--force-device-scale-factor={scale}", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
                     "--disable-session-crashed-bubble", "--disable-infobars", "--password-store=basic",
                     "--disable-features=Translate,MediaRouter"], X, "chrome.log")
    time.sleep(8)
    # Zed's terminal runs the watcher, in plain view.
    xdo("windowfocus", "--sync", zed)
    xdo("key", "ctrl+grave")
    time.sleep(2)
    xdo("type", "--delay", "8", f"clear; python3 /tmp/clawreflex/watch.py --demo --dir {REPO}")
    xdo("key", "Return")
    time.sleep(2)
    xdo("windowfocus", "--sync", zed)
    print("up: display", DISPLAY)


def shot(path=None):
    path = path or STAGE / "shot.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", f"{W}x{H}", "-i", DISPLAY, "-frames:v", "1", str(path)], check=True)
    print(path)


def take():
    zed = window("app.py")
    before = set(TAKES.glob("*")) if TAKES.exists() else set()
    name = time.strftime("rec-%Y%m%dT%H%M%SZ", time.gmtime())
    out = TAKES / name
    out.mkdir(parents=True)
    rec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "30", "-video_size", f"{W}x{H}",
                            "-draw_mouse", "0", "-i", DISPLAY, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14",
                            "-pix_fmt", "yuv420p", str(out / "screen.mp4")], stdin=subprocess.PIPE)
    marks = {"record_epoch": time.time()}
    time.sleep(2.5)
    # Focus the editor (not the terminal), go to the query line and rewrite it, as a developer would.
    xdo("windowfocus", "--sync", zed)
    xdo("mousemove", "--window", zed, 900, 640); xdo("click", 1)  # focus the editor pane, as a person would
    time.sleep(0.4)
    xdo("key", "ctrl+g"); time.sleep(0.5); xdo("type", "7"); xdo("key", "Return"); time.sleep(0.4)
    xdo("key", "ctrl+alt+shift+h"); xdo("key", "ctrl+alt+shift+e"); time.sleep(0.3)  # whole logical line (keymap.json)
    marks["type_start_epoch"] = time.time()
    xdo("type", "--delay", "28", EDIT_QUERY)
    time.sleep(0.4)
    xdo("key", "ctrl+g"); time.sleep(0.4); xdo("type", "8"); xdo("key", "Return"); time.sleep(0.3)
    xdo("key", "ctrl+alt+shift+h"); xdo("key", "ctrl+alt+shift+e"); time.sleep(0.3)
    xdo("type", "--delay", "28", EDIT_EXEC)
    time.sleep(0.8)
    marks["save_epoch"] = time.time()
    xdo("key", "ctrl+s")
    # Wait for the watcher's take directory and its finish marker.
    run = None
    deadline = time.time() + 900
    while time.time() < deadline:
        new = [p for p in TAKES.glob("2*") if p not in before]
        run = new[0] if new else None
        if run and (run / "take.json").exists():
            break
        time.sleep(0.5)
    marks["done_epoch"] = time.time()
    time.sleep(5)
    rec.communicate(b"q", timeout=30)
    marks["stop_epoch"] = time.time()
    marks["run"] = str(run.relative_to(ROOT)) if run else None
    (out / "marks.json").write_text(json.dumps(marks, indent=2))
    print(json.dumps({"take": str(out.relative_to(ROOT)), **marks}, indent=2))


def race():
    """Record the live side-by-side race page full screen, over the editor."""
    out = TAKES / time.strftime("race-%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True)
    env = dict(os.environ)
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"')
    server = subprocess.Popen([sys.executable, str(ROOT / "clawreflex" / "race.py"), "--out", str(out)], cwd=ROOT / "clawreflex", env=env,
                              stdout=subprocess.PIPE, text=True)
    url = server.stdout.readline().strip()
    chrome = subprocess.check_output(["node", "-e", "import('./tools/chrome.mjs').then(m=>console.log(m.findChrome()))"], cwd=ROOT, text=True).strip()
    rec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "30", "-video_size", f"{W}x{H}",
                            "-draw_mouse", "0", "-i", DISPLAY, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14",
                            "-pix_fmt", "yuv420p", str(out / "screen.mp4")], stdin=subprocess.PIPE)
    marks = {"record_epoch": time.time()}
    browser = subprocess.Popen([chrome, f"--user-data-dir={STAGE / 'race-profile'}", f"--app={url}", "--window-position=0,0",
                                f"--window-size={W},{H}", "--force-device-scale-factor=1", "--no-first-run", "--hide-scrollbars",
                                "--disable-session-crashed-bubble", "--password-store=basic"], env=X, start_new_session=True)
    marks["open_epoch"] = time.time()
    log = out / "race.jsonl"
    deadline = time.time() + 600
    while time.time() < deadline:
        if log.exists() and log.read_text().count('"type": "done"') + log.read_text().count('"type": "error"') >= 2:
            break
        time.sleep(0.5)
    time.sleep(4)
    rec.communicate(b"q", timeout=30)
    os.killpg(browser.pid, 15)
    server.terminate()
    marks["stop_epoch"] = time.time()
    (out / "marks.json").write_text(json.dumps(marks, indent=2))
    print(out)


def down():
    try:  # close Chrome gently first, so its profile never asks to restore pages
        xdo("windowclose", window("OpenClaw", tries=2))
        time.sleep(1.5)
    except SystemExit:
        pass
    for name, pid in (json.loads(PIDS.read_text()) if PIDS.exists() else {}).items():
        try:
            os.killpg(pid, 15)
        except ProcessLookupError:
            pass
    PIDS.unlink(missing_ok=True)


if __name__ == "__main__":
    {"up": up, "take": take, "shot": shot, "race": race, "down": down}[sys.argv[1]]()
