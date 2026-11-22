"""Pre-warmed sandbox with a fresh fork for every verification request.

The persistent process executes only the trusted dispatcher. Candidate modules run
in disposable children with no network, no host inputs and fresh module state.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import subprocess  # nosec B404 # constructed OS sandbox launch
import tempfile
import threading
import time
from typing import Any

from .sandbox import RUNNER, SandboxUnavailable, sandbox_command

DISPATCHER = r'''
import ctypes, gc, json, os, select, signal, sys, tempfile, time, shutil
import contextlib, io, resource, unittest
RUNNER = __RUNNER__
# Keep disposable children from reopening the dispatcher's protocol pipes or
# memory through /proc. The dispatcher runs as PID 1 inside the PID namespace,
# so there is no same-uid supervisor with inherited protocol descriptors.
if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
    raise RuntimeError('cannot protect sandbox dispatcher')
# The dispatcher creates no reference cycles; children are disposable. Avoid
# repeated collections of the preloaded unittest graph in the request hot path.
gc.collect()
gc.freeze()
gc.disable()
print('{"ready":true}', flush=True)
while True:
    line = sys.stdin.buffer.readline(4000001)
    if not line:
        break
    if len(line) > 4000000:
        break
    payload = json.loads(line)
    readfd, writefd = os.pipe()
    child = os.fork()
    if child == 0:
        os.setsid()
        os.close(readfd)
        os.close(0)
        os.dup2(writefd, 1)
        os.dup2(writefd, 2)
        os.closerange(3, 1024)
        try:
            with tempfile.TemporaryDirectory(prefix='/tmp/check-') as directory:
                os.chdir(directory)
                with open('app.py', 'w') as stream: stream.write(payload['source'])
                for name, source in payload['tests'].items():
                    with open(name, 'w') as stream: stream.write(source)
                code = RUNNER.replace('/work', directory)
                exec(compile(code, '<trusted-runner>', 'exec'), {'__name__': '__main__'})
        except SystemExit as exc:
            sys.stdout.flush()
            os._exit(exc.code if isinstance(exc.code, int) else 1)
        except BaseException:
            os._exit(125)
    os.close(writefd)
    raw = bytearray()
    deadline = time.monotonic() + payload['timeout']
    timedout = False
    while True:
        left = deadline - time.monotonic()
        if left <= 0 or len(raw) > 65536:
            timedout = True
            break
        ready, _, _ = select.select([readfd], [], [], left)
        if not ready:
            timedout = True
            break
        chunk = os.read(readfd, 65537 - len(raw))
        if not chunk:
            break
        raw.extend(chunk)
    try: os.killpg(child, signal.SIGKILL)
    except ProcessLookupError: pass
    _, status = os.waitpid(child, 0)
    os.close(readfd)
    # Kill namespace descendants even if untrusted code changed its process
    # group. The trusted dispatcher is the namespace's PID 1.
    for pid in os.listdir('/proc'):
        if pid.isdigit() and int(pid) > 1 and int(pid) != os.getpid():
            try: os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError: pass
    # /tmp is a private sandbox tmpfs. Never carry files into the next request.
    for name in os.listdir('/tmp'):
        path = '/tmp/' + name
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.unlink(path)
    print(json.dumps({'returncode':124 if timedout else os.waitstatus_to_exitcode(status),
                      'raw':raw.decode('utf-8', errors='replace')}), flush=True)
    payload = None
'''.replace('__RUNNER__', repr(RUNNER))


class WarmWorker:
    def __init__(self, startup_timeout: float = 15):
        self.lock = threading.Lock()
        self.temporary = tempfile.TemporaryDirectory(prefix='clawreflex-worker-')
        self.process: subprocess.Popen[bytes] | None = None
        self.backend = ''
        self.selector = selectors.DefaultSelector()
        self.buffer = bytearray()
        self.startup_timeout = startup_timeout
        try:
            work = Path(self.temporary.name) / 'work'
            work.mkdir(mode=0o755)
            (work / '_runner.py').write_text(DISPATCHER, encoding='utf-8')
            command, backend = sandbox_command(work)
            self.backend = backend
            if backend == 'bubblewrap':
                command.insert(1, '--as-pid-1')
                index = command.index('--tmpfs')
                command[index:index] = ['--size', '16777216']
            if backend == 'container':
                # Persistent protocol requires a pipe to container stdin.
                command.insert(command.index('--rm'), '--interactive')
            self.command = command
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # nosec B603 # constructed sandbox argv
                                            stderr=subprocess.DEVNULL,
                                            env=self._launch_env(backend))
            if self.process.stdout is None:
                raise SandboxUnavailable('worker output pipe unavailable')
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            if json.loads(self._line(startup_timeout)) != {'ready': True}:
                raise SandboxUnavailable('sandbox worker startup failed')
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _launch_env(backend: str) -> dict[str, str]:
        env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        if backend == 'container':
            for key in ('HOME', 'XDG_RUNTIME_DIR', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'CONTAINER_HOST'):
                if key in os.environ:
                    env[key] = os.environ[key]
        return env

    def _line(self, timeout: float) -> bytes:
        deadline = time.monotonic() + timeout
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError('sandbox worker deadline exceeded')
            if self.process is None or self.process.stdout is None:
                raise SandboxUnavailable('worker output pipe closed')
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise SandboxUnavailable('sandbox worker exited')
            self.buffer.extend(chunk)
            if len(self.buffer) > 131072:
                raise ValueError('sandbox worker output exceeded limit')
        line, _, rest = self.buffer.partition(b'\n')
        self.buffer = bytearray(rest)
        return bytes(line)

    def run(self, source: str, tests: dict[str, str], timeout: float = 8) -> dict[str, Any]:
        if not 0 < timeout <= 120:
            raise ValueError('timeout must be between 0 and 120 seconds')
        if not tests or any(Path(name).name != name or not name.startswith('test_') or not name.endswith('.py') for name in tests):
            raise ValueError('tests must use test_*.py basenames')
        payload = json.dumps({'source': source, 'tests': tests, 'timeout': timeout}).encode() + b'\n'
        if len(payload) > 4000000:
            raise ValueError('worker request exceeds limit')
        started = time.perf_counter()
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                raise SandboxUnavailable('worker is closed')
            if self.process.stdin is None:
                raise SandboxUnavailable('worker input pipe closed')
            try:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                envelope = json.loads(self._line(timeout + 2))
                returncode = envelope['returncode']
                try:
                    value = json.loads(envelope['raw'])
                except json.JSONDecodeError:
                    value = {}
            except (OSError, ValueError, TimeoutError, SandboxUnavailable):
                self.close()
                raise
        groups = value.get('module_counts', {})
        counts_valid = all(type(value.get(key)) is int and value[key] >= 0 for key in
                           ('tests_run', 'failures', 'errors', 'skipped', 'unexpected_successes', 'expected_failures'))
        clean = (counts_valid and isinstance(groups, dict)
                 and all(type(groups.get(Path(name).stem)) is int and groups[Path(name).stem] > 0 for name in tests)
                 and all(value[key] == 0 for key in ('skipped', 'unexpected_successes', 'expected_failures')))
        count, failures, errors = (value.get(key, 0) for key in ('tests_run', 'failures', 'errors'))
        passed = clean and returncode == 0 and count > 0 and failures == 0 and errors == 0
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        return {'passed': passed, 'ok': passed, 'returncode': returncode, 'exit_code': returncode,
                'tests_run': count, 'failures': failures, 'errors': errors, 'module_counts': groups,
                'assertion_failure': clean and returncode == 1 and failures > 0 and errors == 0,
                'output': value.get('output', envelope['raw'][-12000:]),
                'duration_ms': elapsed, 'wall_ms': elapsed, 'sandbox': self.backend + '-fork-worker'}

    def executor(self, workdir: Path | str, source: str, tests: dict[str, str]) -> dict[str, Any]:
        Path(workdir).mkdir(parents=True, exist_ok=True)
        return self.run(source, tests)

    def close(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()
            self.process = None
        if self.backend == 'container' and hasattr(self, 'command'):
            name = self.command[self.command.index('--name') + 1]
            subprocess.run([self.command[0], 'rm', '--force', name],  # nosec B603 # generated sandbox container name
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False, env=self._launch_env('container'))
        self.selector.close()
        self.temporary.cleanup()

    def __enter__(self) -> WarmWorker:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
