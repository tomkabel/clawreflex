import tempfile
import unittest
from pathlib import Path

from clawreflex.fixtures import fixture
from clawreflex.server import RepairRun, validate_test_source


PROBES = {
    "sql": '''import unittest, app
class Exploit(unittest.TestCase):
    def test_injection_is_denied(self):
        self.assertFalse(app.authenticate("missing", "' OR 1=1 --"))
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
        app.charge("a", 20)
        self.assertEqual(app.charge("a", 20), {"charged": False, "balance": 80})
''',
}


class RepairRunTests(unittest.TestCase):
    def test_all_fixtures_require_red_reference_green_and_patch_green(self):
        for name in ("sql", "path", "ledger"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                spec = fixture(name, "ownednonce")
                run = RepairRun(name, "ownednonce", tmp)
                with self.assertRaises(ValueError):
                    run.patch(spec["reference"])
                self.assertFalse((Path(tmp) / "applied" / "app.py").exists())

                probe = run.probe(PROBES[name])
                self.assertTrue(probe["ok"], probe)
                self.assertTrue(probe["red_confirmed"], probe["red"]["output"])
                self.assertTrue(probe["reference_green"], probe["reference"]["output"])

                rejected = run.patch(spec["code"])
                self.assertFalse(rejected["ok"])
                self.assertFalse(rejected["applied"])
                self.assertFalse((Path(tmp) / "applied" / "app.py").exists())

                accepted = run.patch(spec["reference"], "minimal owned repair")
                self.assertTrue(accepted["ok"], accepted["verification"]["output"])
                self.assertTrue(accepted["applied"])
                self.assertEqual((Path(tmp) / "applied" / "app.py").read_text(), spec["reference"])
                self.assertTrue((Path(tmp) / "probe" / "receipt-01.json").exists())
                self.assertTrue((Path(tmp) / "patch" / "receipt-01.json").exists())
                self.assertTrue((Path(tmp) / "patch" / "receipt-02.json").exists())

    def test_editor_file_changes_only_after_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = fixture("sql", "ownednonce")
            target = Path(tmp) / "repo" / "app.py"
            target.parent.mkdir()
            target.write_text(spec["code"])
            existing_test = target.parent / "test_exploit.py"
            existing_test.write_text("# the developer's own test\n")
            run = RepairRun("sql", "ownednonce", Path(tmp) / "run", target, apply_mode="apply")
            run.probe(PROBES["sql"])
            self.assertFalse((target.parent / "test_clawreflex_exploit.py").exists())
            self.assertEqual((run.output_dir / "probe" / "test_exploit.py").read_text(), PROBES["sql"])
            self.assertEqual(existing_test.read_text(), "# the developer's own test\n")
            run.patch(spec["code"])
            self.assertEqual(target.read_text(), spec["code"])  # a rejected patch never touches the editor's file
            run.patch(spec["reference"])
            self.assertEqual(target.read_text(), spec["reference"])

    def test_newer_editor_work_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = fixture("sql", "ownednonce")
            target = Path(tmp) / "repo" / "app.py"
            target.parent.mkdir()
            target.write_text(spec["code"])
            run = RepairRun("sql", "ownednonce", Path(tmp) / "run", target, apply_mode="apply")
            run.probe(PROBES["sql"])
            newer_work = spec["code"] + "\n# saved while the repair was running\n"
            target.write_text(newer_work)

            receipt = run.patch(spec["reference"])

            self.assertTrue(receipt["ok"], receipt["verification"]["output"])
            self.assertFalse(receipt["applied"])
            self.assertTrue(receipt["target_changed"])
            self.assertEqual(target.read_text(), newer_work)
            self.assertFalse((target.parent / ".app.py.clawreflex").exists())

    def test_error_is_not_a_valid_red_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RepairRun("sql", "ownednonce", tmp)
            probe = run.probe('''import unittest, app
class Exploit(unittest.TestCase):
    def test_missing_name(self):
        self.assertFalse(app.authenticate("missing", "wrong"))
''')
            self.assertFalse(probe["ok"])
            self.assertFalse(probe["red_confirmed"])

    def test_probe_imports_are_restricted(self):
        with self.assertRaises(ValueError):
            validate_test_source("import os\nimport unittest, app\n")


if __name__ == "__main__":
    unittest.main()
