#!/usr/bin/env python3
"""A live side-by-side race: the same request streamed to Kimi on Cerebras and on a GPU host (via OpenRouter).

Serves a page at http://127.0.0.1:<port>/ that starts both streams when opened and draws every token as it
arrives. Each lane shows its own wait before the first token (Cerebras' wait is the hackathon queue: refused
requests retried), then a clock that starts at its first token. Every event is logged to <out>/race.jsonl.
"""
from __future__ import annotations

import argparse
import http.client
import http.server
import json
import os
from pathlib import Path
import queue
import ssl
import threading
import time
from urllib.parse import urlsplit

if __package__:
    from .benchmark import endpoint_config
else:
    from benchmark import endpoint_config
if __package__:
    from .fixtures import fixture
else:
    from fixtures import fixture
if __package__:
    from .throughput import PROMPT
else:
    from throughput import PROMPT

PAGE = Path(__file__).resolve().parent / "web" / "race.html"


def stream(lane, events, max_tokens):
    started = time.time()
    try:
        endpoint = endpoint_config(lane)
        body = {"model": endpoint["model"], "stream": True, "stream_options": {"include_usage": True}, "max_tokens": max_tokens,
                "temperature": 0, "reasoning_effort": "low",
                "messages": [{"role": "user", "content": PROMPT.format(code=fixture("sql", "shop")["code"])}]}
        url = urlsplit(endpoint["base_url"])
        refused = 0
        while True:
            conn = http.client.HTTPSConnection(url.hostname, 443, timeout=180, context=ssl.create_default_context())
            conn.request("POST", url.path.rstrip("/") + "/chat/completions", json.dumps(body).encode(),
                         {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ[endpoint["key_env"]]})
            response = conn.getresponse()
            if response.status == 429:
                refused += 1
                response.read()
                events.put({"lane": lane, "type": "refused", "count": refused, "t": time.time() - started})
                time.sleep(1.5)
                continue
            if response.status != 200:
                events.put({"lane": lane, "type": "error", "status": response.status, "t": time.time() - started})
                return
            break
        tokens = 0
        for raw in response:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            event = json.loads(line[5:])
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                text = delta.get("content") or ""
                if text or delta.get("reasoning") or delta.get("reasoning_content"):
                    events.put({"lane": lane, "type": "text", "text": text, "t": time.time() - started})
            if event.get("provider"):
                events.put({"lane": lane, "type": "provider", "name": event["provider"]})
            if event.get("usage"):
                tokens = event["usage"].get("completion_tokens", tokens)
        events.put({"lane": lane, "type": "done", "tokens": tokens, "refused": refused, "t": time.time() - started})
    except Exception as exc:
        events.put({"lane": lane, "type": "error", "status": str(exc) or type(exc).__name__, "t": time.time() - started})


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/fonts/"):
            name = {"/fonts/manrope.ttf": "manrope-600.ttf", "/fonts/mono.ttf": "sometype-mono-600.ttf"}.get(self.path)
            body = (Path(__file__).resolve().parents[1] / "skills" / "cerebras-demo-basics" / "assets" / "fonts" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "font/ttf")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/events":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        events = queue.Queue()
        for lane in ("cerebras", "baseline"):
            threading.Thread(target=stream, args=(lane, events, self.server.max_tokens), daemon=True).start()
        done = 0
        with (self.server.out / "race.jsonl").open("a") as log:
            log.write(json.dumps({"type": "start", "epoch": time.time()}) + "\n")
            while done < 2:
                event = events.get()
                log.write(json.dumps(event) + "\n")
                done += event["type"] in ("done", "error")
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18795)
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.out, server.max_tokens = args.out, args.max_tokens
    print(f"http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
