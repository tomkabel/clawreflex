import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.doctor import main, self_check


class InstallDoctorTests(unittest.TestCase):
    def test_actual_offline_installation_selfcheck_preserves_all_gates(self):
        result = self_check()
        self.assertTrue(result['passed'], result)
        self.assertTrue(all(result['gates'].values()))
        self.assertGreater(result['tests_run'], 0)
        self.assertFalse(result['live_model_acceptance_measured'])

    def test_cli_records_failure_instead_of_inventing_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.json'
            with mock.patch('sys.argv', ['doctor', '--output', str(path)]), \
                    mock.patch('clawreflex.doctor.self_check', return_value={'passed': False}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
            self.assertFalse(json.loads(path.read_text())['passed'])


if __name__ == '__main__':
    unittest.main()
