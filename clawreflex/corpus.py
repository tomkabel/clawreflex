"""Materialize reproducible seeded bugs from pinned open-source checkouts.

This prepares evaluation inputs. Reference restoration is never a model result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


def manifest() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("corpus.json").read_text(encoding="utf-8"))


def materialize(cache: Path, output: Path, task_id: str) -> dict[str, Any]:
    data = manifest()
    tasks = {task["id"]: task for task in data["tasks"]}
    if task_id not in tasks:
        raise ValueError("unknown corpus task")
    task = tasks[task_id]
    repo = data["repositories"][task["repository"]]
    source = cache / task["repository"]
    commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if commit != repo["commit"]:
        raise ValueError("corpus checkout does not match pinned commit")
    tracked = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
        check=True, capture_output=True, text=True,
    ).stdout
    if tracked:
        raise ValueError("corpus checkout has modified tracked files")
    raw = (source / task["target"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != task["source_sha256"]:
        raise ValueError("corpus target hash mismatch")
    original = raw.decode("utf-8")
    if original.count(task["before"]) != 1:
        raise ValueError("seed mutation must match exactly once")
    if output.exists():
        raise ValueError("output must not exist")
    # Copy tracked files only: local caches/untracked credentials cannot leak in.
    paths = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"], check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for name in paths:
        if not name:
            continue
        relative = Path(name.decode("utf-8"))
        candidate = source / relative
        if relative.is_absolute() or ".." in relative.parts or candidate.is_symlink():
            raise ValueError("unsafe path in corpus repository")
    output.mkdir(parents=True)
    for name in paths:
        if name:
            relative = Path(name.decode("utf-8"))
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, destination)
    mutated = original.replace(task["before"], task["after"], 1)
    (output / task["target"]).write_text(mutated, encoding="utf-8")
    (output / "test_clawreflex_corpus.py").write_text(task["test_source"], encoding="utf-8")
    result = {
        "schema": "clawreflex-corpus-input/v1", "task": task_id,
        "repository": task["repository"], "commit": commit, "target": task["target"],
        "contract": task["contract"], "source_sha256": task["source_sha256"],
        "seeded_sha256": hashlib.sha256(mutated.encode()).hexdigest(),
        "pythonpath": repo["pythonpath"], "model_acceptance_measured": False,
    }
    (output / "clawreflex-corpus-input.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        print(json.dumps(manifest(), indent=2))
        return 0
    if not all((args.cache, args.output, args.task)):
        parser.error("--cache, --output and --task are required")
    print(json.dumps(materialize(args.cache, args.output, args.task), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
