"""Install a built wheel in a fresh environment and measure the offline repair check."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess  # nosec B404 # fixed interpreter/pip/selfcheck argv
import tempfile
import time
from typing import Any
import venv

from .privacy import redact


def check_wheel(wheel: Path) -> dict[str, Any]:
    wheel = wheel.resolve(strict=True)
    if wheel.suffix != '.whl':
        raise ValueError('expected a wheel artifact')
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='clawreflex-fresh-install-') as tmp:
        base = Path(tmp)
        environment = base / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        # Remove Python import overrides: the judge must import the installed wheel.
        env = {key: value for key, value in os.environ.items() if not key.startswith('PYTHON')}
        env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
        result = subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--no-index', str(wheel)],  # nosec B603 # fixed local install argv
                                cwd=base, env=env, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError('wheel install failed: ' + redact(result.stderr).text[-1500:])
        output = base / 'selfcheck.json'
        result = subprocess.run([str(python), '-I', '-m', 'clawreflex.doctor', '--output', str(output)],  # nosec B603 # installed self-check, no source cwd
                                cwd=base, env=env, capture_output=True, text=True, timeout=120)
        if not output.exists():
            raise RuntimeError('installed repair check failed: ' + redact(result.stderr).text[-1500:])
        checked = json.loads(output.read_text())
        version = subprocess.run([str(python), '-I', '-m', 'clawreflex', '--version'],  # nosec B603 # installed package entry point
                                 cwd=base, env=env, capture_output=True, text=True, timeout=10)
        elapsed = (time.perf_counter() - started) * 1000
        return {'schema': 'clawreflex-fresh-wheel-check/v1', 'mode': 'local-offline-install',
                'artifact': wheel.name, 'artifact_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                'version': version.stdout.strip(), 'elapsed_ms': round(elapsed, 3),
                'selfcheck': checked, 'passed': result.returncode == 0 and checked['passed'] and elapsed <= 600000,
                'limitation': 'Same-host fresh venv, offline deterministic repair; no stranger, live provider or second-OS result.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = check_wheel(args.wheel)
    raw = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(raw)
    print(raw, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
