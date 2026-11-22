import os
from pathlib import Path
import tempfile
import unittest

from clawreflex.fixtures import fixture
from clawreflex.server import RepairRun
from clawreflex.test_server import PROBES
from clawreflex.warm_worker import WarmWorker


class WarmWorkerTests(unittest.TestCase):
    def test_fresh_forks_preserve_reference_red_and_green_gates(self):
        with tempfile.TemporaryDirectory() as tmp, WarmWorker() as worker:
            run = RepairRun('sql', 'warmnonce', tmp, executor=worker.executor)
            self.assertTrue(run.probe(PROBES['sql'])['ok'])
            result = run.patch(fixture('sql', 'warmnonce')['reference'])
            self.assertTrue(result['ok'])
            self.assertGreater(result['verification']['tests_run'], 0)

    def test_untrusted_state_cannot_persist_between_children(self):
        with WarmWorker() as worker:
            first = worker.run('VALUE=42\n', {'test_x.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_x(self):\n  app.VALUE=99\n  self.assertEqual(app.VALUE,99)\n'})
            second = worker.run('VALUE=42\n', {'test_x.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(app.VALUE,42)\n'})
            self.assertTrue(first['passed'])
            self.assertTrue(second['passed'])

    def test_timeout_and_missing_tests_cannot_be_green(self):
        with WarmWorker() as worker:
            result = worker.run('while True: pass\n', {'test_x.py': 'import unittest,app\n'}, timeout=.1)
            self.assertFalse(result['passed'])
            self.assertEqual(result['returncode'], 124)
            result = worker.run('VALUE=42\n', {'test_empty.py': '# no tests\n'})
            self.assertFalse(result['passed'])
            # A timed-out child cannot poison the next request.
            result = worker.run('VALUE=42\n', {'test_x.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(app.VALUE,42)\n'})
            self.assertTrue(result['passed'])

    def test_private_tmp_files_cannot_persist_between_requests(self):
        with WarmWorker() as worker:
            test = {'test_x.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(app.result)\n'}
            first = worker.run("open('/tmp/persist', 'w').write('private')\nresult=True\n", test)
            second = worker.run("import os\nresult=not os.path.exists('/tmp/persist')\n", test)
            self.assertTrue(first['passed'])
            self.assertTrue(second['passed'])

    def test_dispatcher_protocol_pipes_and_memory_are_private(self):
        # Deliberately bypass AST restrictions: /proc must not let a child
        # consume requests or inject replies into the persistent protocol.
        source = '''import os
def protected():
 for path in ('/proc/1/fd/0', '/proc/1/fd/1', '/proc/1/mem'):
  try:
   fd = os.open(path, os.O_RDONLY)
  except OSError:
   continue
  else:
   os.close(fd)
   return False
 return os.getppid() == 1
'''
        tests = {'test_x.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(app.protected())\n'}
        with WarmWorker() as worker:
            self.assertTrue(worker.run(source, tests)['passed'])
            self.assertTrue(worker.run(source, tests)['passed'])

    def test_host_file_and_environment_remain_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret = Path(tmp) / 'secret'
            secret.write_text('private')
            os.environ['CLAWREFLEX_WORKER_SECRET'] = 'private'
            try:
                # Deliberately bypass the policy to test the OS boundary itself.
                source = f'import os\ndef isolated():\n return not os.path.exists({str(secret)!r}) and "CLAWREFLEX_WORKER_SECRET" not in os.environ\n'
                with WarmWorker() as worker:
                    result = worker.run(source, {'test_x.py': 'import unittest,app\nclass T(unittest.TestCase):\n def test_x(self): self.assertTrue(app.isolated())\n'})
                self.assertTrue(result['passed'])
            finally:
                del os.environ['CLAWREFLEX_WORKER_SECRET']

    def test_invalid_paths_deadlines_and_closed_worker_fail(self):
        worker = WarmWorker()
        try:
            for tests, timeout in (({'../test_x.py': ''}, 1), ({'test_x.py': ''}, 0), ({}, 1)):
                with self.assertRaises(ValueError):
                    worker.run('', tests, timeout)
        finally:
            worker.close()
        with self.assertRaises(RuntimeError):
            worker.run('', {'test_x.py': ''})


if __name__ == '__main__':
    unittest.main()
