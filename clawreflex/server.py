#!/usr/bin/env python3
"""One sandboxed RED/reference/GREEN engine and authenticated loopback HTTP API."""
from __future__ import annotations

import argparse
from collections import deque
import datetime as dt
import difflib
import hashlib
import hmac
import http.server
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING or __package__:
    from .apply import guarded_replace, guarded_revert
    from .fixtures import fixture
    from .privacy import redact
    from .sandbox import SandboxUnavailable, run_unittest
    from .validation import module_imports, public_functions, validate_test_source
    from .validation import validate_patch_source as _validate_patch
else:
    from apply import guarded_replace, guarded_revert
    from fixtures import fixture
    from privacy import redact
    from sandbox import SandboxUnavailable, run_unittest
    from validation import module_imports, public_functions, validate_test_source
    from validation import validate_patch_source as _validate_patch

EXPLOIT_FILENAME = 'test_clawreflex_exploit.py'  # legacy name; never writes into a user's tree


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def save_json(path: Path | str, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def run_tests(workdir: Path, app_source: str, tests: dict[str, str], timeout: float = 8.0) -> dict[str, Any]:
    # Durable input artifacts are private; execution always happens in an isolated tmpdir.
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (workdir / 'app.py').write_text(app_source, encoding='utf-8')
    for filename, source in tests.items():
        if Path(filename).name != filename or not filename.startswith('test_') or not filename.endswith('.py'):
            raise ValueError('test paths must be test_*.py basenames')
        (workdir / filename).write_text(source, encoding='utf-8')
    return run_unittest(app_source, tests, timeout)


def validate_patch_source(source: str, fixture_name: str) -> None:
    _validate_patch(source, module_imports(fixture(fixture_name, 'validation')['code']))


class RepairRun:
    """A serialized, independently cross-checked repair of one saved module.

    Custom specs are supplied by trusted workspace configuration, never the model.
    Spec keys: code, reference, regression, heldout, title, contract.
    """
    def __init__(self, fixture_name: str, nonce: str, output_dir: Path | str,
                 target: Path | str | None = None, *, spec: dict[str, str] | None = None,
                 apply_mode: str = 'propose', executor: Callable[..., dict[str, Any]] = run_tests):
        if apply_mode not in {'propose', 'apply'}:
            raise ValueError('apply_mode must be propose or apply')
        if not isinstance(nonce, str) or not nonce or len(nonce) > 128 or not all(c.isalnum() or c in '_-' for c in nonce):
            raise ValueError('nonce must contain only safe characters')
        self.target = Path(os.path.abspath(target)) if target is not None else None
        self.fixture_name = fixture_name
        self.nonce = nonce
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.spec = dict(spec) if spec is not None else fixture(fixture_name, nonce)
        for field in ('code', 'reference', 'regression', 'heldout', 'title', 'contract'):
            if not isinstance(self.spec.get(field), str) or not self.spec[field].strip():
                raise ValueError(f'trusted verification spec requires {field}')
        self.executor = executor
        self.apply_mode = apply_mode
        self.lock = threading.RLock()
        self.http_lock = threading.Lock()
        self.probe_source: str | None = None
        self.probe_receipt: dict[str, Any] | None = None
        self.patch_receipt: dict[str, Any] | None = None
        self.probe_attempts = 0
        self.patch_attempts = 0
        self.applied = False
        self.applied_epoch: float | None = None
        self.started_epoch = time.time()
        self.status = 'WAITING_FOR_PROBE'
        self.verified_source: str | None = None
        self.application: dict[str, Any] | None = None
        self._state(self.status)

    def _state(self, status: str) -> None:
        self.status = status
        state = {'WAITING_FOR_PROBE': 'waiting_for_probe', 'RED_CONFIRMED_REFERENCE_GREEN': 'red_confirmed',
                 'PATCH_REJECTED': 'red_confirmed', 'TARGET_CHANGED': 'conflict',
                 'PATCH_VERIFIED': 'green_verified', 'PATCH_APPLIED': 'green_verified',
                 'PATCH_REVERTED': 'reverted'}.get(status, status.lower())
        save_json(self.output_dir / 'run.json', {
            'project': 'ClawReflex', 'fixture': self.fixture_name, 'title': self.spec['title'],
            'nonce': self.nonce, 'contract': self.spec['contract'], 'created_utc': utc_now(),
            'status': status, 'state': state, 'apply_mode': self.apply_mode,
            'source_sha256': sha256(self.spec['code']),
        })

    def _receipt(self, kind: str, number: int, receipt: dict[str, Any]) -> dict[str, Any]:
        receipt['receipt_sha256'] = sha256(json.dumps(receipt, sort_keys=True, separators=(',', ':')))
        save_json(self.output_dir / kind / f'receipt-{number:02d}.json', receipt)
        save_json(self.output_dir / kind / 'receipt.json', receipt)
        return json.loads(json.dumps(receipt))

    def probe(self, test_source: str) -> dict[str, Any]:
        with self.lock:
            if self.applied:
                raise ValueError('this run already applied a patch; revert before probing again')
            self.probe_attempts += 1
            started = time.perf_counter()
            receipt: dict[str, Any] = {
                'tool': 'clawreflex_probe', 'ok': False, 'fixture': self.fixture_name,
                'nonce': self.nonce, 'created_utc': utc_now(), 'red_confirmed': False,
                'reference_green': False,
            }
            try:
                validate_test_source(test_source, public_functions(self.spec['code']))
                receipt['test_sha256'] = sha256(test_source)
                red = self.executor(self.output_dir / 'probe' / 'vulnerable', self.spec['code'],
                                    {'test_exploit.py': test_source})
                reference = self.executor(self.output_dir / 'probe' / 'reference', self.spec['reference'], {
                    'test_exploit.py': test_source, 'test_regression.py': self.spec['regression'],
                    'test_heldout.py': self.spec['heldout'],
                })
                receipt.update(red=red, vulnerable=red, reference=reference, reference_check=reference,
                               red_confirmed=red['assertion_failure'], reference_green=reference['passed'])
                receipt['ok'] = receipt['red_confirmed'] and receipt['reference_green']
                if receipt['ok']:
                    self.probe_source = test_source
                    self.probe_receipt = receipt
                    self.verified_source = None
                    self.patch_receipt = None
                    (self.output_dir / 'probe' / 'test_exploit.py').write_text(test_source, encoding='utf-8')
                    self._state('RED_CONFIRMED_REFERENCE_GREEN')
                else:
                    receipt['error'] = 'RED requires assertion failures without errors and a passing independent reference'
            except (ValueError, SyntaxError, SandboxUnavailable) as exc:
                receipt['error'] = str(exc)
            receipt['duration_ms'] = round((time.perf_counter() - started) * 1000, 3)
            return self._receipt('probe', self.probe_attempts, receipt)

    def patch(self, source: str, summary: str = '') -> dict[str, Any]:
        with self.lock:
            if not self.probe_source or not self.probe_receipt:
                raise ValueError('a confirmed RED/reference-GREEN probe is required before patching')
            if self.applied:
                raise ValueError('this run already applied a verified patch')
            self.patch_attempts += 1
            started = time.perf_counter()
            receipt: dict[str, Any] = {
                'tool': 'clawreflex_patch', 'ok': False, 'fixture': self.fixture_name,
                'nonce': self.nonce, 'created_utc': utc_now(), 'summary': summary,
                'applied': False, 'target_changed': False,
                'exploit_green': False, 'independent_regressions_green': False,
                'heldout_regressions_green': False,
            }
            self.verified_source = None
            try:
                _validate_patch(source, module_imports(self.spec['code']))
                if source == self.spec['code']:
                    raise ValueError('candidate does not change the vulnerable module')
                receipt['patch_sha256'] = sha256(source)
                receipt['probe_sha256'] = self.probe_receipt['test_sha256']
                result = self.executor(self.output_dir / 'candidate', source, {
                    'test_exploit.py': self.probe_source, 'test_regression.py': self.spec['regression'],
                    'test_heldout.py': self.spec['heldout'],
                })
                receipt['verification'] = result
                if result['passed']:
                    receipt.update(ok=True, exploit_green=True, independent_regressions_green=True,
                                   heldout_regressions_green=True)
                    self.verified_source = source
                    patch_dir = self.output_dir / 'patch'
                    patch_dir.mkdir(exist_ok=True)
                    (patch_dir / 'candidate.py').write_text(source, encoding='utf-8')
                    diff = ''.join(difflib.unified_diff(self.spec['code'].splitlines(keepends=True),
                                                       source.splitlines(keepends=True),
                                                       fromfile='a/app.py', tofile='b/app.py'))
                    (patch_dir / 'patch.diff').write_text(diff, encoding='utf-8')
                    receipt['diff'] = diff
                    receipt['artifact'] = str(patch_dir / 'candidate.py')
                    if self.target is None:
                        # Legacy demo's "applied" is an artifact, never an editor write.
                        artifact = self.output_dir / 'applied' / 'app.py'
                        artifact.parent.mkdir(exist_ok=True)
                        artifact.write_text(source, encoding='utf-8')
                        receipt.update(applied=True, application_scope='artifact', artifact=str(artifact))
                        self.applied = True
                    elif self.apply_mode == 'apply':
                        application = self._apply('auto-' + sha256(source))
                        receipt.update(applied=application['applied'], target_changed=application['target_changed'],
                                       application=application)
                else:
                    receipt['error'] = 'candidate did not pass exploit, regression and held-out tests'
            except (ValueError, SyntaxError, SandboxUnavailable) as exc:
                receipt['error'] = str(exc)
            receipt['duration_ms'] = round((time.perf_counter() - started) * 1000, 3)
            self.patch_receipt = receipt
            self._state('PATCH_APPLIED' if self.applied else 'TARGET_CHANGED' if receipt['target_changed']
                        else 'PATCH_VERIFIED' if receipt['ok'] else 'PATCH_REJECTED')
            return self._receipt('patch', self.patch_attempts, receipt)

    def _apply(self, idempotency_key: str) -> dict[str, Any]:
        if self.target is None or self.verified_source is None:
            raise ValueError('a verified candidate and target are required')
        if redact(self.spec['code']).count or redact(self.verified_source).count:
            return {'ok': False, 'applied': False, 'target_changed': False,
                    'error': 'secret-shaped content blocks apply; review and remove secrets first'}
        result = guarded_replace(self.target, sha256(self.spec['code']), self.verified_source.encode(),
                                 self.output_dir / 'backups', idempotency_key)
        if result.get('idempotent_replay') and self.target.read_bytes() != self.verified_source.encode():
            result.update(applied=False, target_changed=True, historical_applied=True,
                          error='prior idempotent action is no longer the current file content')
        self.application = result
        self.applied = result['applied']
        if self.applied:
            self.applied_epoch = time.time()
        return result

    def apply(self, idempotency_key: str) -> dict[str, Any]:
        with self.lock:
            result = self._apply(idempotency_key)
            self._state('PATCH_APPLIED' if result['applied'] else 'TARGET_CHANGED' if result['target_changed']
                        else 'PATCH_VERIFIED')
            save_json(self.output_dir / 'apply.json', result)
            return result

    def revert(self, idempotency_key: str) -> dict[str, Any]:
        with self.lock:
            if not self.target or not self.verified_source or not self.application or not self.application.get('backup'):
                raise ValueError('no applied patch snapshot is available')
            result = guarded_revert(self.target, sha256(self.verified_source), Path(self.application['backup']),
                                    self.output_dir / 'backups', idempotency_key)
            if result['applied']:
                self.applied = False
                self._state('PATCH_REVERTED')
            save_json(self.output_dir / 'revert.json', result)
            return result

    def state(self) -> dict[str, Any]:
        with self.lock:
            state = json.loads((self.output_dir / 'run.json').read_text())
            state.update(started_epoch=self.started_epoch,
                         elapsed_s=round((self.applied_epoch or time.time()) - self.started_epoch, 3),
                         probe_accepted=self.probe_receipt is not None, applied=self.applied,
                         **{'vulnerable.py': redact(self.spec['code']).text})
            if self.probe_receipt:
                state['probe'] = self.probe_receipt
            if self.patch_receipt:
                state['patch'] = self.patch_receipt
                if 'diff' in self.patch_receipt:
                    state['patch.diff'] = redact(self.patch_receipt['diff']).text
            return state


class RunServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, address: tuple[str, int], repair: RepairRun, token: str,
                 max_concurrency: int = 8, rate_per_minute: int = 120):
        if not ipaddress.ip_address(address[0]).is_loopback:
            raise ValueError('ClawReflex must bind to an IP loopback address')
        if not isinstance(token, str) or len(token) < 24:
            raise ValueError('CLAWREFLEX_TOKEN must contain at least 24 characters')
        self.repair = repair
        self.token = token
        self.started_epoch = repair.started_epoch
        self.slots = threading.BoundedSemaphore(max_concurrency)
        self.rate_per_minute = rate_per_minute
        self.request_times: deque[float] = deque()
        self.rate_lock = threading.Lock()
        super().__init__(address, Handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            body = b'{"ok":false,"error":"server_busy"}'
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n'
                                + f'Content-Length: {len(body)}\r\n\r\n'.encode() + body)
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(http.server.BaseHTTPRequestHandler):
    server: RunServer
    server_version = 'ClawReflex/0.2'

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _boundary(self, auth: bool = True) -> bool:
        host = self.headers.get('Host', '')
        port = self.server.server_address[1]
        allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
        if host not in allowed_hosts or (self.headers.get('Origin') and self.headers['Origin'] != 'http://' + host):
            self.send_json(403, {'ok': False, 'error': 'invalid_host_or_origin'})
            return False
        if auth and not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + self.server.token).encode()):
            self.send_json(401, {'ok': False, 'error': 'unauthorized'})
            return False
        with self.server.rate_lock:
            now = time.monotonic()
            while self.server.request_times and self.server.request_times[0] <= now - 60:
                self.server.request_times.popleft()
            if len(self.server.request_times) >= self.server.rate_per_minute:
                self.send_json(429, {'ok': False, 'error': 'rate_limited'})
                return False
            self.server.request_times.append(now)
        return True

    def do_GET(self) -> None:
        route = urlsplit(self.path).path
        if not self._boundary(auth=route not in {'/health', '/'}):
            return
        if route == '/health':
            self.send_json(200, {'ok': True, 'project': 'ClawReflex'})
        elif route == '/state':
            self.send_json(200, self.server.repair.state())
        elif route == '/':
            body = (Path(__file__).parent / 'web' / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_json(404, {'ok': False, 'error': 'not_found'})

    def do_POST(self) -> None:
        if not self._boundary():
            return
        route = urlsplit(self.path).path
        if route not in {'/tool/clawreflex_probe', '/tool/clawreflex_patch', '/action/apply', '/action/revert'}:
            self.send_json(404, {'ok': False, 'error': 'not_found'})
            return
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length') or []) != 1:
                raise ValueError('exactly one Content-Length is required; transfer encoding is unsupported')
            length = int(self.headers['Content-Length'])
            if length > 65536:
                self.send_json(413, {'ok': False, 'error': 'request_too_large'})
                return
            if length <= 0:
                raise ValueError('nonempty body required')
            params = json.loads(self.rfile.read(length))
            if not isinstance(params, dict):
                raise ValueError('JSON body must be an object')
            fields = {'test_source'} if route.endswith('clawreflex_probe') else {'source', 'summary'} if route.endswith('clawreflex_patch') else {'idempotency_key'}
            required = fields - {'summary'}
            if set(params) - fields or not required <= set(params) or not all(isinstance(v, str) for v in params.values()):
                raise ValueError('invalid tool parameter names or types')
            if any(len(value) > 40000 for value in params.values()):
                raise ValueError('tool parameter too large')
            if 'idempotency_key' in params and not 1 <= len(params['idempotency_key']) <= 128:
                raise ValueError('idempotency_key must be 1–128 characters')
        except (KeyError, ValueError, UnicodeError) as exc:
            self.send_json(400, {'ok': False, 'error': str(exc)})
            return
        if not self.server.repair.http_lock.acquire(blocking=False):
            self.send_json(429, {'ok': False, 'error': 'run_busy'})
            return
        try:
            repair = self.server.repair
            if route.endswith('clawreflex_probe'):
                receipt = repair.probe(params['test_source'])
            elif route.endswith('clawreflex_patch'):
                receipt = repair.patch(params['source'], params.get('summary', ''))
            elif route.endswith('/apply'):
                receipt = repair.apply(params['idempotency_key'])
            else:
                receipt = repair.revert(params['idempotency_key'])
            self.send_json(200 if receipt['ok'] else 422, receipt)
        except (ValueError, SyntaxError) as exc:
            self.send_json(400, {'ok': False, 'error': str(exc)})
        finally:
            self.server.repair.http_lock.release()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', choices=['sql', 'path', 'ledger'], required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--out', '--output', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--target')
    parser.add_argument('--apply', action='store_true', help='explicitly opt into automatic verified application')
    args = parser.parse_args()
    run = RepairRun(args.fixture, args.nonce, args.out, args.target, apply_mode='apply' if args.apply else 'propose')
    server = RunServer((args.host, args.port), run, os.environ.get('CLAWREFLEX_TOKEN', ''))
    url = f'http://{args.host}:{server.server_address[1]}'
    save_json(run.output_dir / 'service.json', {'url': url, 'fixture': args.fixture, 'nonce': args.nonce})
    print(json.dumps({'url': url, 'fixture': args.fixture, 'out': args.out}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
