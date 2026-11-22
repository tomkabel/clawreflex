import json
from pathlib import Path
import tempfile
import unittest

from clawreflex.core import ClawReflexRun


PROBES = {
    "sql": '''import unittest, app
class Exploit(unittest.TestCase):
    def test_injection_is_denied(self):
        self.assertFalse(app.authenticate("' OR 1=1 --", "wrong"))
''',
    "path": '''import unittest, app
class Exploit(unittest.TestCase):
    def test_parent_is_rejected(self):
        with self.assertRaises(ValueError):
            app.report_path("../private.txt")
''',
    "ledger": '''import unittest, app
class Exploit(unittest.TestCase):
    def test_retry_does_not_debit_twice(self):
        app.reset()
        app.charge("request-1", 20)
        self.assertEqual(app.charge("request-1", 20), {"charged": False, "balance": 80})
''',
}


class ClawReflexCoreTest(unittest.TestCase):
    def make_run(self, name):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return ClawReflexRun(name, "test-nonce-1", Path(temporary.name))

    def test_all_fixtures_have_genuine_red_then_green_evidence(self):
        for name in PROBES:
            with self.subTest(fixture=name):
                run = self.make_run(name)
                probe = run.probe(PROBES[name])
                self.assertTrue(probe["ok"], probe)
                self.assertTrue(probe["vulnerable"]["assertion_failure"], probe)
                self.assertTrue(probe["reference_check"]["ok"], probe)
                patch = run.patch(run.fixture["reference"], "reference repair")
                self.assertTrue(patch["ok"], patch)
                self.assertTrue(patch["applied"], patch)
                self.assertGreaterEqual(patch["verification"]["tests_run"], 5)
                self.assertTrue((run.output_dir / "applied" / "app.py").exists())
                state = json.loads((run.output_dir / "run.json").read_text())
                self.assertEqual(state["state"], "green_verified")

    def test_patch_cannot_run_before_cross_checked_red(self):
        run = self.make_run("sql")
        result = run.patch(run.fixture["reference"], "too early")
        self.assertFalse(result["ok"])
        self.assertFalse((run.output_dir / "applied" / "app.py").exists())

    def test_erroring_probe_is_not_accepted_as_red(self):
        run = self.make_run("sql")
        result = run.probe("import unittest, app\nclass Exploit(unittest.TestCase):\n    def test_missing(self): app.missing()\n")
        self.assertFalse(result["ok"])
        self.assertFalse(run.red_confirmed)

    def test_failed_patch_is_not_applied(self):
        run = self.make_run("ledger")
        self.assertTrue(run.probe(PROBES["ledger"])["ok"])
        result = run.patch(run.fixture["code"], "unchanged")
        self.assertFalse(result["ok"])
        self.assertFalse(result["applied"])
        self.assertFalse((run.output_dir / "applied" / "app.py").exists())

    def test_probe_imports_are_restricted(self):
        run = self.make_run("path")
        result = run.probe("import os\nimport unittest, app\n")
        self.assertFalse(result["ok"])
        self.assertIn("imports are limited", result["error"])


if __name__ == "__main__":
    unittest.main()
