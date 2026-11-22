"""Measure cold and optional pre-warmed verification, separately from product latency."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time
from typing import Any

from .sandbox import run_unittest
from .warm_worker import WarmWorker

SOURCE = 'def identity(value):\n return value\n'
TESTS = {'test_identity.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_identity(self): self.assertEqual(app.identity(42),42)\n'}


def measure(warm_n: int = 50, cold_n: int = 10) -> dict[str, Any]:
    if not 1 <= warm_n <= 10000 or not 1 <= cold_n <= 10000:
        raise ValueError('sample counts must be between 1 and 10000')
    environment = {'platform': platform.platform(), 'python': platform.python_version(),
                   'cpu_count': os.cpu_count(), 'load_average': list(os.getloadavg())}
    started = time.perf_counter()
    with WarmWorker() as worker:
        startup_ms = (time.perf_counter() - started) * 1000
        backend = worker.backend
        warm = [worker.run(SOURCE, TESTS) for _ in range(warm_n)]
    cold = [run_unittest(SOURCE, TESTS) for _ in range(cold_n)]

    def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        durations = sorted(row['duration_ms'] for row in rows)
        return {'n': len(rows), 'p50_ms': statistics.median(durations),
                'p95_ms': durations[math.ceil(len(durations) * .95) - 1],
                'all_passed': all(row['passed'] for row in rows), 'durations_ms': durations}

    result: dict[str, Any] = {'schema': 'clawreflex-worker-benchmark/v1',
              'scope': 'one trivial Python unittest; excludes provider, workspace copying, queue and OpenClaw; not product latency',
              'backend': backend, 'environment': environment,
              'warm': summary(warm), 'cold': summary(cold), 'startup_ms': startup_ms,
              'target_warm_p50_ms': 20,
              'worker_source_sha256': hashlib.sha256(Path(__file__).with_name('warm_worker.py').read_bytes()).hexdigest(),
              'workload_sha256': hashlib.sha256(json.dumps({'source': SOURCE, 'tests': TESTS}, sort_keys=True).encode()).hexdigest(),
              'command': 'python -m clawreflex.worker_benchmark --warm-n ' + str(warm_n) + ' --cold-n ' + str(cold_n)}
    result['passed'] = result['warm']['all_passed'] and result['cold']['all_passed'] and result['warm']['p50_ms'] < 20
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--warm-n', type=int, default=50)
    parser.add_argument('--cold-n', type=int, default=10)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = measure(args.warm_n, args.cold_n)
    raw = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(raw, encoding='utf-8')
    print(raw, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
