"""Offline installation self-check: real sandbox, verified proposal, Apply and Revert.

This uses a disclosed deterministic repair. It is not a live model acceptance test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time
from typing import Any

from .config import TargetRule, WorkspaceConfig
from .workspace import Workspace

BROKEN = 'def double(x):\n    return x\n'
FIXED = 'def double(x):\n    return x * 2\n'
PROBE = 'import unittest, app\nclass P(unittest.TestCase):\n def test_double(self): self.assertEqual(app.double(2),4)\n'
REGRESSION = 'import unittest, app\nclass R(unittest.TestCase):\n def test_zero(self): self.assertEqual(app.double(0),0)\n'
HELDOUT = 'import unittest, app\nclass H(unittest.TestCase):\n def test_negative(self): self.assertEqual(app.double(-3),-6)\n'


def self_check() -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='clawreflex-install-check-') as tmp:
        base = Path(tmp).resolve()
        root = base / 'repo'
        root.mkdir()
        target = root / 'module.py'
        target.write_text(BROKEN)
        oracle = root / 'verification'
        oracle.mkdir()
        for name, source in (('reference', FIXED), ('regression', REGRESSION), ('heldout', HELDOUT)):
            (oracle / (name + '.py')).write_text(source)
        tests = root / 'tests'
        tests.mkdir()
        (tests / 'test_module.py').write_text('import unittest,module\nclass T(unittest.TestCase):\n def test_repo(self): self.assertEqual(module.double(5),10)\n')
        config = WorkspaceConfig(root=root, targets=('module.py',), debounce_ms=0, rules=(
            TargetRule('module.py', 'verification/reference.py', 'verification/regression.py',
                       'verification/heldout.py', 'double(x) returns x times two'),))
        before = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in root.rglob('*') if path.is_file()}
        with_workspace = Workspace(config, base / 'state')
        try:
            record = with_workspace.enqueue('module.py')
            # Offline verification deliberately avoids the provider path/consent.
            with_workspace.process_next()
            engine = record.engine
            if engine is None:
                raise RuntimeError(record.error or 'engine preparation failed')
            red = engine.probe(PROBE)
            green = engine.patch(FIXED, 'deterministic installation check')
            untouched_before_apply = target.read_text() == BROKEN
            applied = engine.apply('install-apply') if green['ok'] else {'applied': False}
            correct_after_apply = target.read_text() == FIXED
            reverted = engine.revert('install-revert') if applied['applied'] else {'applied': False}
            after = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in root.rglob('*') if path.is_file()}
            gates = {'assertion_red': red['ok'] and red['red_confirmed'], 'reference_green': red['reference_green'],
                     'independent_green': green['ok'], 'propose_default': untouched_before_apply,
                     'apply_correct': applied['applied'] and correct_after_apply,
                     'revert_exact': reverted['applied'] and before == after}
            return {'schema': 'clawreflex-install-selfcheck/v1', 'mode': 'offline-deterministic',
                    'passed': all(gates.values()), 'gates': gates,
                    'sandbox': green.get('verification', {}).get('sandbox'),
                    'tests_run': green.get('verification', {}).get('tests_run'),
                    'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
                    'live_model_acceptance_measured': False,
                    'limitation': 'Local offline smoke; not a stranger install, live provider run or second OS result.'}
        finally:
            with_workspace.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = self_check()
    raw = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(raw)
    print(raw, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
