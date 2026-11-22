"""Fail-closed OS sandbox for untrusted Python tests.

No host home, workspace, credentials, network or writable host mount is exposed.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
import shutil
import subprocess  # nosec B404 # isolated runtime launch with a constructed argv, never shell=True
import sys
import tempfile
import time
from typing import Any

RUNNER = '''import contextlib, io, json, resource, sys, unittest
resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
resource.setrlimit(resource.RLIMIT_AS, (384*1024*1024, 384*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (1024*1024, 1024*1024))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
sys.path.insert(0, '/work')
stream = io.StringIO()
with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
    suite = unittest.defaultTestLoader.discover('/work', pattern='test_*.py')
    module_counts = {}
    def count_suite(item):
        if isinstance(item, unittest.TestSuite):
            for child in item: count_suite(child)
        else:
            module = item.__class__.__module__
            module_counts[module] = module_counts.get(module, 0) + 1
    count_suite(suite)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
value = dict(module_counts=module_counts, tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
             skipped=len(result.skipped), unexpected_successes=len(result.unexpectedSuccesses),
             expected_failures=len(result.expectedFailures), output=stream.getvalue()[-12000:])
print(json.dumps(value))
sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
'''


class SandboxUnavailable(RuntimeError):
    pass


def sandbox_command(work: Path) -> tuple[list[str], str]:
    bwrap = shutil.which('bwrap') if sys.platform.startswith('linux') else None
    if bwrap:
        command = [bwrap, '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL']
        # Runtime mounts only. Never bind /, /home, /etc or the developer workspace.
        roots = ['/usr', '/lib', '/lib64']
        base = str(Path(sys.base_prefix).resolve())
        if base != '/usr' and not base.startswith('/usr/'):
            roots.append(base)
        for directory in roots:
            if Path(directory).exists():
                command += ['--ro-bind', directory, directory]
        interpreter = str(Path(getattr(sys, '_base_executable', sys.executable)).resolve())
        command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',  # nosec B108 # private namespace tmpfs
                    '--ro-bind', str(work), '/work', '--chdir', '/work', '--clearenv',
                    '--setenv', 'HOME', '/tmp', '--setenv', 'PATH', '/usr/bin',  # nosec B108 # private tmpfs
                    '--setenv', 'PYTHONHASHSEED', '0', '--', interpreter, '-I', '-S', '/work/_runner.py']
        return command, 'bubblewrap'
    # A digest is mandatory; this module never silently pulls a mutable image.
    image = os.environ.get('CLAWREFLEX_SANDBOX_IMAGE', '')
    runtime = shutil.which('podman') or shutil.which('docker')
    if runtime and re.fullmatch(r'[^\s]+@sha256:[a-f0-9]{64}', image):
        command = [runtime, 'run', '--name', 'clawreflex-' + uuid.uuid4().hex, '--rm', '--pull=never', '--network=none', '--read-only',
                   '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=16',
                   '--memory=384m', '--cpus=1', '--user=65534:65534',
                   '--tmpfs=/tmp:rw,noexec,nosuid,size=16m', '--env=HOME=/tmp',
                   '--env=PYTHONHASHSEED=0', '--mount', f'type=bind,src={work},dst=/work,ro',
                   '--workdir=/work', image, 'python3', '-I', '-S', '/work/_runner.py']
        return command, 'container'
    raise SandboxUnavailable('No sandbox: install bubblewrap on Linux or provision a digest-pinned '
                             'Python container and set CLAWREFLEX_SANDBOX_IMAGE')


def run_unittest(source: str, tests: dict[str, str], timeout: float = 8.0, *,
                 support_files: dict[str, bytes] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    if not 0 < timeout <= 120:
        raise ValueError('timeout must be between 0 and 120 seconds')
    for name in tests:
        if not name.startswith('test_') or not name.endswith('.py') or Path(name).name != name:
            raise ValueError('test filenames must be test_*.py basenames')
    for name in support_files or {}:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'repo':
            raise ValueError('support files must stay under repo/')
    if sum(len(value) for value in (support_files or {}).values()) > 100000000:
        raise ValueError('sandbox support files exceed 100 MB')
    with tempfile.TemporaryDirectory(prefix='clawreflex-sandbox-') as temporary:
        # The outer directory remains 0700 on the host. The mounted child is
        # searchable by the unprivileged container uid without exposing host inputs.
        work = Path(temporary) / 'work'
        work.mkdir(mode=0o755)
        (work / 'app.py').write_text(source, encoding='utf-8')
        (work / '_runner.py').write_text(RUNNER, encoding='utf-8')
        for name, test in tests.items():
            (work / name).write_text(test, encoding='utf-8')
        for name, content in (support_files or {}).items():
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        command, backend = sandbox_command(work)
        launch_env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        if backend == 'container':
            # These configure the trusted runtime client, never container env.
            for name in ('HOME', 'XDG_RUNTIME_DIR', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'CONTAINER_HOST'):
                if name in os.environ:
                    launch_env[name] = os.environ[name]
        with tempfile.TemporaryFile() as output:
            try:
                process = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output,  # nosec B603 # constructed sandbox argv
                                         stderr=subprocess.STDOUT, timeout=timeout,
                                         env=launch_env, check=False)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                returncode = 124
            finally:
                if backend == 'container':
                    # Killing docker/podman CLI does not kill a daemon-owned container.
                    name = command[command.index('--name') + 1]
                    subprocess.run([command[0], 'rm', '--force', name], stdin=subprocess.DEVNULL,  # nosec B603 # generated container name
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=10, check=False, env=launch_env)
            output.seek(0)
            raw = output.read(1048576).decode('utf-8', errors='replace')
    value: dict[str, Any] = {}
    try:
        candidate = json.loads(raw.strip())
        if isinstance(candidate, dict) and all(type(candidate.get(k)) is int for k in
                                               ('tests_run', 'failures', 'errors', 'skipped',
                                                'unexpected_successes', 'expected_failures')):
            value = candidate
    except json.JSONDecodeError:
        pass
    count = value.get('tests_run', 0)
    failures = value.get('failures', 0)
    errors = value.get('errors', 0)
    groups = value.get('module_counts', {})
    discovered_all = isinstance(groups, dict) and all(type(groups.get(Path(name).stem)) is int
                                                     and groups[Path(name).stem] > 0 for name in tests)
    clean = (discovered_all and value.get('skipped', 0) == 0 and value.get('unexpected_successes', 0) == 0
             and value.get('expected_failures', 0) == 0)
    passed = returncode == 0 and count > 0 and failures == 0 and errors == 0 and clean
    duration = round((time.perf_counter() - started) * 1000, 3)
    return {
        'passed': passed, 'ok': passed, 'exit_code': returncode, 'returncode': returncode,
        'tests_run': count, 'failures': failures, 'errors': errors, 'module_counts': groups,
        'assertion_failure': returncode == 1 and failures > 0 and errors == 0 and clean,
        'duration_ms': duration, 'wall_ms': duration, 'sandbox': backend,
        'output': value.get('output', raw[-12000:]) + ('\nTEST TIMEOUT' if returncode == 124 else ''),
    }
