"""Debounced workspace queue, isolated snapshots and authenticated run registry."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from typing import Any, Callable, cast
from urllib.parse import urlsplit
import uuid

from .adapters import adapter_for
from .config import WorkspaceConfig, load_config, safe_path
from .privacy import provider_source, redact
from .server import Handler, RepairRun, RunServer, save_json


def content_hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def default_state_dir(root: Path) -> Path:
    git = root / ".git"
    if git.is_dir() and not git.is_symlink():
        return git / "clawreflex"
    if git.is_file() and not git.is_symlink():
        value = git.read_text(encoding="utf-8").strip()
        if value.startswith("gitdir: "):
            directory = (root / value[8:]).resolve()
            if directory.is_dir():
                return directory / "clawreflex"
    # Non-git workspaces also retain history outside the source tree.
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "clawreflex" / content_hash(str(root).encode())[:20]


@dataclass
class WorkspaceRun:
    id: str
    path: str
    source_sha256: str
    saved_source: str
    saved_epoch: float
    output_dir: Path
    status: str = "queued"
    engine: RepairRun | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    timings: dict[str, float] = field(default_factory=dict)
    error: str | None = None

    def public(self) -> dict[str, Any]:
        status = self.status
        if self.engine is not None and status not in {"cancelled", "failed", "deadline_exceeded"}:
            status = self.engine.state()["state"] if self.engine.verified_source else status
        return {"id": self.id, "path": self.path, "source_sha256": self.source_sha256,
                "status": status, "saved_epoch": self.saved_epoch, "timings": self.timings,
                "error": self.error, "cancelled": self.cancel.is_set()}


Driver = Callable[[WorkspaceRun, WorkspaceConfig], None]


class Workspace:
    def __init__(self, config: WorkspaceConfig, state_dir: Path | None = None):
        self.config = config
        self.root = config.root
        self.output_dir = (state_dir or default_state_dir(self.root)).resolve()
        if self.output_dir.is_relative_to(self.root) and not self.output_dir.is_relative_to(self.root / ".git"):
            raise ValueError("run state must live outside source tree or under .git")
        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            import fcntl
            self._lease = (self.output_dir / "workspace.lock").open("a+b")
            fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError) as exc:
            if hasattr(self, "_lease"):
                self._lease.close()
            raise ValueError("workspace already running or platform file locking unavailable") from exc
        self.started_epoch = time.time()
        self.http_lock = threading.Lock()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pending: queue.Queue[str] = queue.Queue(maxsize=config.queue_depth)
        self.runs: dict[str, WorkspaceRun] = {}
        self.history: dict[str, dict[str, Any]] = {}
        for receipt in sorted((self.output_dir / "runs").glob("*/workspace.json")):
            try:
                value = json.loads(receipt.read_text())
                if (not isinstance(value, dict) or value.get("id") != receipt.parent.name
                        or not isinstance(value.get("path"), str)):
                    continue
                # History carries no restored execution or apply authority.
                public = {key: value[key] for key in ("id", "path", "source_sha256", "saved_epoch",
                          "status", "timings", "cancelled") if key in value}
                public["historical"] = True
                if public.get("status") in {"queued", "running", "preparing", "awaiting_provider", "waiting"}:
                    public["status"] = "interrupted"
                self.history[receipt.parent.name] = public
            except (OSError, ValueError):
                continue
        self.identities: dict[tuple[str, str], str] = {}
        self.seen: dict[str, str] = {}
        self.debounce: dict[str, tuple[str, str, float, float]] = {}
        self.worker: threading.Thread | None = None
        self.active: str | None = None
        self.watch_errors: dict[str, str] = {}
        self._prime()

    def _files(self) -> dict[str, Path]:
        result = {}
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}
                       and not (Path(directory) / name).is_symlink()]
            for name in files:
                path = Path(directory) / name
                relative = path.relative_to(self.root).as_posix()
                if self.config.allowed(relative) and not path.is_symlink():
                    result[relative] = path
        return result

    def _prime(self) -> None:
        for relative, path in self._files().items():
            try:
                if path.stat().st_size <= self.config.max_file_bytes:
                    self.seen[relative] = content_hash(path.read_bytes())
            except OSError:
                pass

    def poll(self, now: float | None = None) -> list[str]:
        """Observe content, including saves during an active run and file recreation."""
        now = time.monotonic() if now is None else now
        current = self._files()
        for missing in set(self.seen) - set(current):
            self.seen.pop(missing, None)
            self.debounce.pop(missing, None)
        for relative, path in current.items():
            try:
                if path.stat().st_size > self.config.max_file_bytes:
                    continue
                raw = path.read_bytes()
                source = raw.decode("utf-8")
            except (OSError, UnicodeError):
                continue
            digest = content_hash(raw)
            if self.seen.get(relative) != digest:
                self.seen[relative] = digest
                self.debounce[relative] = (digest, source, now, time.time())
        launched = []
        for relative, (_, source, changed, epoch) in list(self.debounce.items()):
            if (now - changed) * 1000 >= self.config.debounce_ms:
                try:
                    record = self.enqueue(relative, source=source, saved_epoch=epoch)
                except queue.Full:
                    continue  # retain latest pending save until capacity is available
                except ValueError as exc:
                    self.watch_errors[relative] = redact(str(exc)).text
                    self.debounce.pop(relative, None)
                    continue
                self.debounce.pop(relative, None)
                launched.append(record.id)
        return launched

    def enqueue(self, relative: str, *, source: str | None = None,
                saved_epoch: float | None = None) -> WorkspaceRun:
        if not self.config.allowed(relative):
            raise ValueError("target is outside allowlist")
        self.config.rule_for(relative)
        target = safe_path(self.root, relative)
        if source is None and target.stat().st_size > self.config.max_file_bytes:
            raise ValueError("target exceeds file budget")
        source = target.read_text(encoding="utf-8") if source is None else source
        if len(source.encode()) > self.config.max_file_bytes:
            raise ValueError("target exceeds file budget")
        digest = content_hash(source.encode())
        with self.lock:
            previous = self.identities.get((relative, digest))
            if previous:
                return self.runs[previous]
            if self.pending.full():
                raise queue.Full("workspace queue is full")
            run_id = uuid.uuid4().hex
            record = WorkspaceRun(run_id, relative, digest, source, saved_epoch or time.time(),
                                  self.output_dir / "runs" / run_id)
            record.output_dir.mkdir(parents=True, mode=0o700)
            self.runs[run_id] = record
            self.identities[(relative, digest)] = run_id
            self.pending.put_nowait(run_id)
            self._save(record)
            return record

    def _save(self, record: WorkspaceRun) -> None:
        save_json(record.output_dir / "workspace.json", record.public())

    def _snapshot(self, record: WorkspaceRun) -> Path:
        destination = record.output_dir / "tree"
        destination.mkdir()
        total = count = 0
        withheld = set(self.config.rule_for(record.path).verification_paths(record.path).values())
        oracle_prefixes = [template.split("{", 1)[0] for rule in self.config.rules
                           for template in (rule.reference, rule.regression, rule.heldout)]
        for directory, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in {".git", ".venv", "venv", "node_modules", "__pycache__", ".ssh", ".aws"}
                       and not (Path(directory) / name).is_symlink()]
            for name in files:
                original = Path(directory) / name
                relative = original.relative_to(self.root).as_posix()
                if (relative in withheld or any(prefix and relative.startswith(prefix) for prefix in oracle_prefixes)
                        or original.is_symlink()
                        or any(fnmatch.fnmatchcase(relative, pattern) for pattern in self.config.ignore)):
                    continue
                if name.endswith((".pem", ".key")) or name in {"id_rsa", "id_ed25519"}:
                    continue
                if original.stat().st_size + total > self.config.max_snapshot_bytes:
                    raise ValueError("workspace snapshot exceeds configured budget")
                raw = original.read_bytes()
                total += len(raw)
                count += 1
                if total > self.config.max_snapshot_bytes or count > self.config.max_snapshot_files:
                    raise ValueError("workspace snapshot exceeds configured budget")
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(raw)
        target = destination / record.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(record.saved_source, encoding="utf-8")
        return destination

    def prepare(self, record: WorkspaceRun) -> RepairRun:
        started = time.monotonic()
        rule = self.config.rule_for(record.path)
        spec = {name: safe_path(self.root, path).read_text(encoding="utf-8")
                for name, path in rule.verification_paths(record.path).items()}
        spec.update(code=record.saved_source, title=record.path, contract=rule.contract)
        snapshot = self._snapshot(record)
        adapter = adapter_for(self.config, snapshot, record.path)
        # Workspace queue owns the apply policy: cancel/deadline checks happen
        # before opt-in application after the driver returns.
        engine = RepairRun("workspace", record.id, record.output_dir / "evidence",
                           safe_path(self.root, record.path), spec=spec, apply_mode="propose",
                           executor=adapter.execute)
        record.engine = engine
        record.timings["snapshot_ms"] = (time.monotonic() - started) * 1000
        return engine

    def prompt(self, record: WorkspaceRun) -> str:
        if not self.config.provider_consent:
            raise ValueError("provider disclosure requires workspace.provider_consent=true")
        contract = self.config.rule_for(record.path).contract
        raw = f"Check saved Python module {record.path}. Contract: {contract}\n\n{record.saved_source}\n"
        return provider_source(raw, self.config.redaction_patterns)

    def process_next(self, driver: Driver | None = None) -> WorkspaceRun | None:
        try:
            run_id = self.pending.get_nowait()
        except queue.Empty:
            return None
        record = self.runs[run_id]
        self.active = run_id
        started = time.monotonic()
        try:
            if record.cancel.is_set():
                record.status = "cancelled"
                return record
            record.status = "preparing"
            self.prepare(record)
            record.status = "awaiting_provider"
            self._save(record)
            if driver is not None:
                if not self.config.provider_consent:
                    raise ValueError("provider disclosure requires explicit consent")
                record.status = "running"
                driver(record, self.config)
                if record.cancel.is_set() or self.stop.is_set():
                    record.status = "cancelled"
                elif time.monotonic() - started > self.config.deadline_s:
                    record.status = "deadline_exceeded"
                elif record.engine is not None and record.engine.verified_source:
                    record.status = "verified"
                    if self.config.apply_mode == "apply":
                        result = record.engine.apply("workspace-" + record.id)
                        record.status = "applied" if result["applied"] else "conflict"
                else:
                    record.status = "rejected"
        except Exception as exc:
            record.status = "cancelled" if record.cancel.is_set() else "deadline_exceeded" if time.time() - record.saved_epoch >= self.config.deadline_s else "failed"
            record.error = redact(str(exc)).text
        finally:
            record.timings["save_to_done_ms"] = max(0, (time.time() - record.saved_epoch) * 1000)
            record.timings["active_ms"] = (time.monotonic() - started) * 1000
            self._save(record)
            self.active = None
            self.pending.task_done()
        return record

    def start(self, driver: Driver | None = None) -> None:
        if self.worker is not None:
            raise ValueError("workspace worker already started")
        def work() -> None:
            try:
                while not self.stop.wait(.05):
                    self.process_next(driver)
            finally:
                self._release_lease()
        self.worker = threading.Thread(target=work, name="clawreflex-workspace", daemon=True)
        self.worker.start()

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        record = self.runs[run_id]
        record.cancel.set()
        if record.status in {"queued", "awaiting_provider"}:
            record.status = "cancelled"
        self._save(record)
        return {"ok": True, "id": run_id, "status": record.status}

    def close(self) -> None:
        self.stop.set()
        for record in self.runs.values():
            if record.status in {"queued", "running", "preparing", "awaiting_provider"}:
                record.cancel.set()
        if self.worker:
            self.worker.join(timeout=5)
        if self.worker is None or not self.worker.is_alive():
            self._release_lease()

    def _release_lease(self) -> None:
        if not self._lease.closed:
            self._lease.close()

    def state(self) -> dict[str, Any]:
        with self.lock:
            runs = [*self.history.values(), *[record.public() for record in self.runs.values()]]
            runs.sort(key=lambda value: value.get("saved_epoch", 0), reverse=True)
            return {"project": "ClawReflex", "state": "workspace", "started_epoch": self.started_epoch,
                    "queue_depth": self.pending.qsize(), "queue_capacity": self.config.queue_depth,
                    "active": self.active, "runs": runs,
                    "watch_errors": dict(self.watch_errors)}


class WorkspaceHandler(Handler):
    def do_GET(self) -> None:
        workspace = cast(Workspace, self.server.repair)
        route = urlsplit(self.path).path
        if route.startswith("/runs/"):
            if not self._boundary():
                return
            parts = route.strip("/").split("/")
            if len(parts) != 3 or parts[2] != "state":
                self.send_json(404, {"ok": False, "error": "run_route_not_found"})
                return
            record = workspace.runs.get(parts[1])
            if record is None:
                historical = workspace.history.get(parts[1])
                self.send_json(200 if historical else 404, historical or {"ok": False, "error": "run_not_found"})
            else:
                value = record.engine.state() if record.engine else {}
                value.update(record.public())
                self.send_json(200, value)
            return
        super().do_GET()

    def do_POST(self) -> None:
        workspace = cast(Workspace, self.server.repair)
        if not self._boundary():
            return
        parts = urlsplit(self.path).path.strip("/").split("/")
        if len(parts) not in {3, 4} or parts[0] != "runs":
            self.send_json(404, {"ok": False, "error": "run_route_required"})
            return
        record = workspace.runs.get(parts[1])
        if record is None:
            self.send_json(404, {"ok": False, "error": "run_not_found"})
            return
        try:
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length") or []) != 1:
                raise ValueError("exactly one Content-Length is required")
            length = int(self.headers["Content-Length"])
            if length > 65536:
                self.send_json(413, {"ok": False, "error": "request_too_large"})
                return
            if length <= 0:
                raise ValueError("nonempty JSON object required")
            params = json.loads(self.rfile.read(length))
            if not isinstance(params, dict):
                raise ValueError("JSON body must be an object")
            action = "/".join(parts[2:])
            if action in {"cancel", "action/cancel"}:
                if action == "cancel" and params:
                    raise ValueError("cancel takes an empty object")
                if action == "action/cancel" and (set(params) != {"idempotency_key"}
                        or not isinstance(params["idempotency_key"], str)
                        or not 1 <= len(params["idempotency_key"]) <= 128):
                    raise ValueError("cancel requires an idempotency key")
                self.send_json(200, workspace.cancel_run(record.id))
                return
            if record.cancel.is_set():
                raise ValueError("run is cancelled")
            if record.engine is None:
                raise ValueError("run is not prepared")
            fields = {"test_source"} if action == "tool/clawreflex_probe" else {"source", "summary"} if action == "tool/clawreflex_patch" else {"idempotency_key"}
            if set(params) - fields or not fields - {"summary"} <= set(params) or not all(isinstance(v, str) for v in params.values()):
                raise ValueError("invalid action parameters")
            if "idempotency_key" in params and not 1 <= len(params["idempotency_key"]) <= 128:
                raise ValueError("idempotency key must contain 1–128 characters")
            engine = record.engine
            if not engine.http_lock.acquire(blocking=False):
                self.send_json(429, {"ok": False, "error": "run_busy"})
                return
            try:
                if action == "tool/clawreflex_probe":
                    result = engine.probe(params["test_source"])
                elif action == "tool/clawreflex_patch":
                    result = engine.patch(params["source"], params.get("summary", ""))
                elif action == "action/apply":
                    result = engine.apply(params["idempotency_key"])
                elif action == "action/revert":
                    result = engine.revert(params["idempotency_key"])
                else:
                    self.send_json(404, {"ok": False, "error": "unknown_action"})
                    return
                self.send_json(200 if result["ok"] else 422, result)
            finally:
                engine.http_lock.release()
        except (ValueError, SyntaxError, KeyError, UnicodeError) as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})


def make_server(workspace: Workspace, token: str, port: int = 0) -> RunServer:
    server = RunServer(("127.0.0.1", port), workspace, token)  # type: ignore[arg-type]
    server.RequestHandlerClass = WorkspaceHandler
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--config", default=".clawreflex.toml")
    parser.add_argument("--once", metavar="PATH", help="queue one target and wait for external tool calls")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--external-tools", action="store_true", help="wait for OpenClaw tools instead of calling the configured provider")
    args = parser.parse_args()
    workspace = Workspace(load_config(args.root, args.config))
    token = os.environ.get("CLAWREFLEX_TOKEN") or secrets.token_urlsafe(32)
    server = make_server(workspace, token, args.port)
    # Token is stored privately, never put into a URL, console log or process argv.
    connection = workspace.output_dir / "connection.json"
    connection.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "token": token}) + "\n")
    connection.chmod(0o600)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if args.once:
        workspace.enqueue(args.once)
    driver = None
    if not args.external_tools:
        from .provider import WorkspaceDriver
        try:
            driver = WorkspaceDriver(workspace)
        except ValueError:
            workspace.close()
            server.shutdown()
            server.server_close()
            connection.unlink(missing_ok=True)
            raise
    workspace.start(driver)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "connection_file": str(connection),
                      "provider": "external tools" if driver is None else workspace.config.provider["model"]}), flush=True)
    try:
        while not workspace.stop.wait(.05):
            workspace.poll()
    except KeyboardInterrupt:
        pass
    finally:
        workspace.close()
        if driver is not None:
            driver.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        connection.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
