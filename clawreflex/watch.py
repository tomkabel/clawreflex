#!/usr/bin/env python3
"""Watch a configured Python workspace; --demo selects the historical fixture take."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

if __package__:
    from .fixtures import fixture
else:
    from fixtures import fixture
if __package__:
    from .server import EXPLOIT_FILENAME
else:
    from server import EXPLOIT_FILENAME

ROOT = Path(__file__).resolve().parents[1]
RED, GREEN, DIM, BOLD, OFF = "\033[1;31m", "\033[1;32m", "\033[2m", "\033[1m", "\033[0m"

MESSAGE = """Saved app.py. Check it before it ships.

```python
{code}```

Contract: {contract}

1. Call clawreflex_probe with a unittest (import only unittest and app) that proves the bug: it must fail on this code and pass on a correct version.
2. Then call clawreflex_patch with the complete repaired module and a one-line summary.
Answer in one short line per step. Never claim success unless clawreflex_patch returns ok=true and applied=true."""


def say(text, colour=""):
    print(f"{colour}{text}{OFF}", flush=True)


def ran(output):
    found = re.search(r"Ran (\d+) tests?", output or "")
    return int(found.group(1)) if found else 0


def report_agent_exit(returncode):
    if returncode:
        say(f"Kimi did not finish (exit {returncode}; see agent.json).", DIM)


def demo_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=ROOT / "out" / "clawreflex" / "demo-repo")
    parser.add_argument("--fixture", default="sql", choices=["sql", "path", "ledger"])
    parser.add_argument("--nonce", default="shop")
    parser.add_argument("--stage", type=Path, default=Path(os.environ.get("CLAWREFLEX_STAGE", ROOT / "out" / "clawreflex" / "stage")))
    parser.add_argument("--reset", action="store_true", help="write the safe version of app.py first")
    args = parser.parse_args()
    spec = fixture(args.fixture, args.nonce)
    target = (args.dir / "app.py").resolve()
    args.dir.mkdir(parents=True, exist_ok=True)
    if args.reset:
        target.write_text(spec["reference"], encoding="utf-8")
        (args.dir / EXPLOIT_FILENAME).unlink(missing_ok=True)
    port = int(json.loads((args.stage / "openclaw.json").read_text())["gateway"]["port"]) + 1
    env = dict(os.environ, OPENCLAW_STATE_DIR=str(args.stage / "state"), OPENCLAW_CONFIG_PATH=str(args.stage / "openclaw.json"),
               OPENCLAW_GATEWAY_TOKEN=(args.stage / "gwtoken").read_text().strip(), CLAWREFLEX_TOKEN=(args.stage / "tooltoken").read_text().strip())
    say(f"ClawReflex is watching {target.name}", BOLD)
    seen = target.stat().st_mtime_ns
    while True:
        time.sleep(0.05)
        mtime = target.stat().st_mtime_ns
        if mtime == seen:
            continue
        seen = mtime
        if target.read_text(encoding="utf-8") != spec["code"]:
            continue
        saved = time.time()
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(saved))
        run = ROOT / "out" / "clawreflex" / "takes" / stamp
        run.mkdir(parents=True)
        say(f"\nsaved {target.name}. Kimi is checking it on Cerebras...", BOLD)
        server = subprocess.Popen([sys.executable, str(ROOT / "clawreflex" / "server.py"), "--fixture", args.fixture, "--nonce", args.nonce,
                                   "--out", str(run), "--port", str(port), "--target", str(target), "--apply"],
                                  cwd=ROOT / "clawreflex", env=env, stdout=(run / "server.log").open("w"), stderr=subprocess.STDOUT)
        (run / "message.md").write_text(MESSAGE.format(code=spec["code"], contract=spec["contract"]), encoding="utf-8")
        agent = subprocess.Popen(["openclaw", "agent", "--agent", "main", "--thinking", "low", "--json", "--timeout", "600",
                                  "--message-file", str(run / "message.md")],
                                 cwd=ROOT, env=env, stdout=(run / "agent.json").open("w"), stderr=(run / "agent.err").open("w"))
        shown = set()
        while True:
            probe, patch = run / "probe" / "receipt.json", run / "patch" / "receipt.json"
            if probe.exists() and probe.stat().st_mtime_ns not in shown:
                shown.add(probe.stat().st_mtime_ns)
                receipt = json.loads(probe.read_text())
                if receipt["ok"]:
                    say(f"RED    the attack test broke in. Bug proven.   +{receipt_time(receipt, saved):.1f}s", RED)
                else:
                    say("       attack test rejected; Kimi tries again", DIM)
            if patch.exists() and patch.stat().st_mtime_ns not in shown:
                shown.add(patch.stat().st_mtime_ns)
                receipt = json.loads(patch.read_text())
                if receipt["applied"]:
                    tests = ran(receipt["verification"]["output"])
                    say(f"GREEN  {tests}/{tests} tests pass. Fix saved to {target.name}.   +{receipt_time(receipt, saved):.1f}s", GREEN)
                elif receipt["target_changed"]:
                    say(f"       fix passed, but {target.name} changed while Kimi worked. Your newer save was left untouched.", DIM)
                else:
                    say("       fix rejected: a test failed. Nothing was changed.", DIM)
            if agent.poll() is not None:
                break
            time.sleep(0.05)
        server.terminate()
        server.wait()
        with (run / "take.json").open("w", encoding="utf-8") as take_file:
            json.dump({"saved_epoch": saved, "done_epoch": time.time(), "agent_exit": agent.returncode}, take_file)
        report_agent_exit(agent.returncode)
        say(f"{DIM}receipts: {run.relative_to(ROOT)}{OFF}")


def receipt_time(receipt, saved):
    from datetime import datetime
    return datetime.fromisoformat(receipt["created_utc"]).timestamp() - saved


def main():
    """Watch configured repositories by default; fixtures require explicit --demo."""
    if "--demo" in sys.argv[1:]:
        sys.argv.remove("--demo")
        return demo_main()
    if __package__:
        from .workspace import main as workspace_main
    else:
        from clawreflex.workspace import main as workspace_main
    return workspace_main()


if __name__ == "__main__":
    main()
