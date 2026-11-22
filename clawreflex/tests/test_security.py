"""Adversarial policy and actual OS-isolation regression corpus."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.sandbox import SandboxUnavailable, run_unittest, sandbox_command
from clawreflex.server import RepairRun
from clawreflex.validation import validate_test_source, validate_patch_source

PREFIX = 'import unittest, app\nclass E(unittest.TestCase):\n def test_escape(self):\n'
SUFFIX = '\n  self.assertFalse(app.authenticate("missing", "\' OR 1=1 --"))\n'
# These are adversarial data, never executed on the host.
ESCAPES = [
    'app.__builtins__["eval"]("1+1")',
    'app.__dict__["__builtins__"]["eval"]("1+1")',
    'getattr(app, "__builtins__")',
    'eval("1+1")', 'exec("pass")', 'compile("pass", "x", "exec")',
    'open("/tmp/clawreflex-escape", "w")', '__import__("os")',
    'globals()', 'locals()', 'vars(app)', 'setattr(app,"x",1)',
    'breakpoint()', 'input()', 'app.__class__.__mro__',
    '().__class__.__bases__', 'unittest.mock.patch("builtins.open")',
    'unittest.TestCase.run(self)', 'self.run()', 'self.fail = app.authenticate',
    'app.authenticate = bool', 'f = app.authenticate\n  f("a","b")',
    'x = "__builtins__"\n  app[x]', 'import os', 'import socket',
    'import subprocess', 'import ctypes', 'from app import authenticate',
    'import app as x', 'while True: pass',
]


class SecurityTests(unittest.TestCase):
    def test_thirty_escape_payloads_rejected_before_execution(self):
        self.assertGreaterEqual(len(ESCAPES), 20)
        for payload in ESCAPES:
            with self.subTest(payload=payload), self.assertRaises((ValueError, SyntaxError)):
                validate_test_source(PREFIX + '  ' + payload + SUFFIX, {'authenticate'})

    def test_unknown_calls_decorators_metaclasses_and_rebinding_rejected(self):
        sources = [
            PREFIX + '  danger()' + SUFFIX,
            'import unittest, app\n@eval("1")\nclass E(unittest.TestCase):\n def test_x(self): self.fail()\n',
            'import unittest, app\nclass E(unittest.TestCase, metaclass=type):\n def test_x(self): self.fail()\n',
            PREFIX + '  unittest = app' + SUFFIX,
            PREFIX + '  app.missing()' + SUFFIX,
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_test_source(source, {'authenticate'})

    def test_patch_policy_cannot_import_process_modules_or_modify_modules(self):
        for source, allowed in [('import os\nos.system("id")', {'os'}),
                                ('eval("1")', set()),
                                ('import json\njson.dumps = str', {'json'}),
                                ('from pathlib import Path\nPath("/tmp/x").write_text("x")', {'pathlib'})]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_patch_source(source, allowed)

    def test_fail_closed_without_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch('clawreflex.sandbox.shutil.which', return_value=None):
            with self.assertRaises(SandboxUnavailable):
                sandbox_command(Path(tmp))

    def test_actual_sandbox_hides_host_file_environment_and_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / 'secret'
            secret.write_text('must remain private')
            host_marker = Path(tmp) / 'escape'
            source = f'''import os, socket

def isolated():
    assert not os.path.exists({str(secret)!r})
    assert 'CLAWREFLEX_PRIVATE_TEST' not in os.environ
    try:
        open({str(host_marker)!r}, 'w').write('escape')
        return False
    except OSError:
        pass
    try:
        open('/work/app.py', 'w').write('tamper')
        return False
    except OSError:
        pass
    s = socket.socket()
    s.settimeout(.2)
    try:
        s.connect(('1.1.1.1', 53))
        return False
    except OSError:
        return True
    finally:
        s.close()
'''
            test = 'import unittest, app\nclass T(unittest.TestCase):\n def test_isolated(self): self.assertTrue(app.isolated())\n'
            with mock.patch.dict('os.environ', {'CLAWREFLEX_PRIVATE_TEST': 'private-value'}):
                result = run_unittest(source, {'test_isolation.py': test})
            self.assertTrue(result['passed'], result)
            self.assertFalse(host_marker.exists())

    def test_real_assertion_counts_distinguish_errors_passes_and_red(self):
        for body, expected in [('self.assertEqual(1,2)', True),
                               ('raise ValueError("AssertionError")', False),
                               ('self.assertTrue(True)', False)]:
            with self.subTest(body=body):
                result = run_unittest('', {'test_count.py':
                    'import unittest\nclass T(unittest.TestCase):\n def test_x(self): ' + body + '\n'})
                self.assertEqual(result['assertion_failure'], expected, result)

    def test_timeout_is_not_green(self):
        result = run_unittest('import time\ntime.sleep(10)', {
            'test_timeout.py': 'import unittest, app\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(True)\n'
        }, timeout=.3)
        self.assertFalse(result['passed'])
        self.assertFalse(result['assertion_failure'])
        self.assertEqual(result['exit_code'], 124)

    def test_failed_escape_probe_leaves_no_accepted_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = RepairRun('sql', 'security', tmp)
            result = run.probe(PREFIX + '  ' + ESCAPES[0] + SUFFIX)
            self.assertFalse(result['ok'])
            self.assertIsNone(run.probe_receipt)
            self.assertTrue((Path(tmp) / 'probe' / 'receipt-01.json').exists())

class PolicyEdgeTests(unittest.TestCase):
    def test_unsafe_aliases_and_imported_module_paths_are_rejected(self):
        test_payloads = ['for str in [eval]: str("1")', 'x = globals',
                         'with self.assertRaises(ValueError) as app: pass']
        for payload in test_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_test_source(PREFIX + '  ' + payload + SUFFIX)
        for source in [
            'import json\nx = json.codecs.sys.modules',
            'import json.encoder', 'import math\nx = math.__dict__',
            'str = globals\nstr()', 'from json import encoder',
            'import sqlite3\nx = sqlite3.connect(":memory:").load_extension("x")',
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_patch_source(source, {'json', 'sqlite3', 'math'})

    def test_invalid_source_and_test_path_never_execute(self):
        for source in ('', ' '*10, 42):
            with self.subTest(source=source), self.assertRaises(ValueError):
                validate_test_source(source)
        with self.assertRaises(ValueError):
            run_unittest('', {'../outside.py': ''})
        with self.assertRaises(ValueError):
            run_unittest('', {}, timeout=0)

    def test_container_fallback_requires_digest_and_restricts_resources(self):
        def which(name):
            return '/usr/bin/podman' if name == 'podman' else None
        with tempfile.TemporaryDirectory() as tmp, mock.patch('clawreflex.sandbox.shutil.which', side_effect=which):
            with mock.patch.dict('os.environ', {'CLAWREFLEX_SANDBOX_IMAGE': 'python:latest'}):
                with self.assertRaises(SandboxUnavailable):
                    sandbox_command(Path(tmp))
            with mock.patch.dict('os.environ', {'CLAWREFLEX_SANDBOX_IMAGE': 'python@sha256:' + 'a'*64}):
                command, backend = sandbox_command(Path(tmp))
                self.assertEqual(backend, 'container')
                for flag in ('--network=none', '--read-only', '--pids-limit=16', '--cap-drop=ALL'):
                    self.assertIn(flag, command)

class RegressionDiscoveryTests(unittest.TestCase):
    def test_empty_regression_group_cannot_be_reported_green(self):
        result = run_unittest('', {
            'test_exploit.py': 'import unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(True)\n',
            'test_regression.py': '# accidentally empty regression file\n',
        })
        self.assertFalse(result['passed'], result)
        self.assertEqual(result['tests_run'], 1)


class VerificationTamperRegressionTests(unittest.TestCase):
    def test_type_hint_evaluation_cannot_disable_assertions(self):
        source = "import typing\ndef payload() -> 'exec(\"import unittest; unittest.TestCase.assertEqual = lambda *args: None\")':\n    pass\ntyping.get_type_hints(payload)\ndef double(x): return x\n"
        with self.assertRaises(ValueError):
            validate_patch_source(source, {'typing'})
