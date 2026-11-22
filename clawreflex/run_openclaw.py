#!/usr/bin/env python3
"""Run one genuine ClawReflex repair through standard OpenClaw."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

if __package__:
    from .fixtures import fixture
else:
    from fixtures import fixture
if __package__:
    from .server import save_json, utc_now
else:
    from server import save_json, utc_now


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=["sql", "path", "ledger"], default="sql")
    parser.add_argument("--nonce", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--model", default="cerebras/moonshotai-kimi-k3.1-pro-trial")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    nonce = args.nonce or secrets.token_hex(8)
    output = Path(args.out or root / "out" / "clawreflex" / f"openclaw-{args.fixture}-{utc_now().replace(':', '-')}")
    output.mkdir(parents=True, exist_ok=True)
    spec = fixture(args.fixture, nonce)
    task = f'''You are ClawReflex, running inside standard OpenClaw. Repair this owned vulnerable module.

Fresh fixture nonce: {nonce}
File: {spec['file']}
Contract: {spec['contract']}

```python
{spec['code']}```

First call clawreflex_probe with a concise unittest that proves the vulnerability. The tool executes it against the vulnerable module, where it must fail with an assertion, and against a withheld independent reference repair, where it must pass. Import only unittest and app.

After the probe is accepted, call clawreflex_patch once with the complete minimally repaired Python module and a short summary. It will run your accepted exploit, existing regressions and hidden regressions. The file is applied only if every test passes.

Do not read files, search, or use other tools. Do not ask for the reference repair or hidden tests. If either tool rejects your submission, report the actual rejection. Never claim success unless clawreflex_patch returns ok=true and applied=true. Finish with the actual RED/reference-GREEN/patch-GREEN outcome.
'''
    (output / "task.md").write_text(task, encoding="utf-8")

    port = free_port()
    token = secrets.token_hex(24)
    environment = os.environ.copy()
    environment["CLAWREFLEX_TOKEN"] = token
    environment["CLAWREFLEX_URL"] = f"http://127.0.0.1:{port}"
    environment["OPENCLAW_STATE_DIR"] = str(output / "openclaw-state")
    environment["OPENCLAW_CONFIG_PATH"] = subprocess.check_output(["openclaw", "config", "file"], text=True).strip()
    save_json(output / "monitor.json", {"url": environment["CLAWREFLEX_URL"]})
    server_log = (output / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, str(root / "clawreflex" / "server.py"), "--fixture", args.fixture,
         "--nonce", nonce, "--out", str(output), "--port", str(port)],
        cwd=root / "clawreflex", env=environment, stdout=server_log, stderr=subprocess.STDOUT,
    )
    started = time.perf_counter()
    started_utc = utc_now()
    result = None
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("verification backend exited before OpenClaw started")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("verification backend did not become healthy")

        with (output / "stdout.json").open("w", encoding="utf-8") as stdout, (output / "stderr.log").open("w", encoding="utf-8") as stderr:
            process = subprocess.run(
                ["openclaw", "agent", "--local", "--model", args.model, "--thinking", "low",
                 "--timeout", str(args.timeout), "--json", "--message-file", str(output / "task.md")],
                cwd=root, env=environment, stdout=stdout, stderr=stderr, timeout=args.timeout + 30,
            )
        elapsed = time.perf_counter() - started
        patch_receipt_path = output / "patch" / "receipt.json"
        patch_receipt = json.loads(patch_receipt_path.read_text()) if patch_receipt_path.exists() else None
        result = {
            "project": "ClawReflex",
            "fixture": args.fixture,
            "nonce": nonce,
            "model": args.model,
            "harness": "standard OpenClaw --local",
            "started_utc": started_utc,
            "openclaw_wall_s": round(elapsed, 3),
            "exit_code": process.returncode,
            "success": process.returncode == 0 and bool(patch_receipt and patch_receipt["ok"] and patch_receipt["applied"]),
            "probe_receipt": str(output / "probe" / "receipt.json"),
            "patch_receipt": str(patch_receipt_path) if patch_receipt else None,
            "stdout": str(output / "stdout.json"),
            "stderr": str(output / "stderr.log"),
        }
        save_json(output / "openclaw-result.json", result)
        print(json.dumps(result, indent=2))
        return 0 if result["success"] else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        server_log.close()


if __name__ == "__main__":
    sys.exit(main())
