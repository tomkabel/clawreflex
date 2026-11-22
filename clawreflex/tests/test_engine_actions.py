import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from clawreflex.fixtures import fixture
from clawreflex.server import RepairRun
from clawreflex.test_server import PROBES


class EngineActionsTests(unittest.TestCase):
    def test_propose_default_then_explicit_apply_and_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'app.py'
            spec = fixture('sql', 'actions')
            target.write_text(spec['code'])
            developer_test = root / 'test_clawreflex_exploit.py'
            developer_test.write_text('# developer-owned file\n')
            run = RepairRun('sql', 'actions', root / 'run', target)
            self.assertTrue(run.probe(PROBES['sql'])['ok'])
            receipt = run.patch(spec['reference'])
            self.assertTrue(receipt['ok'], receipt)
            self.assertFalse(receipt['applied'])
            self.assertEqual(target.read_text(), spec['code'])
            self.assertEqual(developer_test.read_text(), '# developer-owned file\n')
            self.assertTrue(run.apply('action-1')['applied'])
            self.assertEqual(target.read_text(), spec['reference'])
            self.assertTrue(run.revert('action-2')['applied'])
            self.assertEqual(target.read_text(), spec['code'])

    def test_receipt_hash_checks_canonical_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RepairRun('sql', 'hashes', tmp)
            receipt = run.probe(PROBES['sql'])
            claimed = receipt.pop('receipt_sha256')
            raw = json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()
            self.assertEqual(claimed, hashlib.sha256(raw).hexdigest())

    def test_custom_trusted_spec_uses_same_engine_and_reference(self):
        spec = {
            'code': 'def double(x): return x\n', 'reference': 'def double(x): return x*2\n',
            'title': 'Arithmetic bug', 'contract': 'double returns twice x',
            'regression': 'import unittest, app\nclass R(unittest.TestCase):\n def test_zero(self): self.assertEqual(app.double(0),0)\n',
            'heldout': 'import unittest, app\nclass H(unittest.TestCase):\n def test_negative(self): self.assertEqual(app.double(-3),-6)\n',
        }
        probe = 'import unittest, app\nclass E(unittest.TestCase):\n def test_double(self): self.assertEqual(app.double(2),4)\n'
        with tempfile.TemporaryDirectory() as tmp:
            run = RepairRun('workspace', 'generic', tmp, spec=spec)
            self.assertTrue(run.probe(probe)['ok'])
            self.assertTrue(run.patch(spec['reference'])['ok'])

class EngineEdgeTests(unittest.TestCase):
    def test_invalid_config_and_missing_spec_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            for kwargs in ({'apply_mode': 'unsafe'}, {'spec': {'code': 'x'}}, {'nonce': 'bad/nonce'}):
                values = {'fixture_name': 'sql', 'nonce': 'safe', 'output_dir': tmp}
                values.update(kwargs)
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    RepairRun(**values)

    def test_legacy_validator_facade(self):
        from clawreflex.core import validate_source
        validate_source(PROBES['sql'], {'unittest', 'app'})
        validate_source('def f(): return 1', set())
        with self.assertRaises(ValueError):
            validate_source('import os', set())

    def test_unverified_actions_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RepairRun('sql', 'safe', tmp)
            with self.assertRaises(ValueError):
                run.apply('x')
            with self.assertRaises(ValueError):
                run.revert('x')
