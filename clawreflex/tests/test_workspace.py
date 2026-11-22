from __future__ import annotations

from dataclasses import replace
import http.client
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest

from clawreflex.config import load_config, safe_path
from clawreflex.adapters import UnsupportedAdapter, adapter_for
from clawreflex.workspace import Workspace, make_server

BROKEN = "def double(x):\n    return x\n"
FIXED = "def double(x):\n    return x * 2\n"
PROBE = "import unittest, app\nclass P(unittest.TestCase):\n def test_double(self): self.assertEqual(app.double(2),4)\n"
REGRESSION = "import unittest, app\nclass R(unittest.TestCase):\n def test_zero(self): self.assertEqual(app.double(0),0)\n"
HELDOUT = "import unittest, app\nclass H(unittest.TestCase):\n def test_negative(self): self.assertEqual(app.double(-3),-6)\n"
CONFIG = '''[workspace]
targets = ["module.py"]
debounce_ms = 100
provider_consent = true
[tests]
path = "tests"
[[target]]
glob = "module.py"
reference = "verification/reference.py"
regression = "verification/regression.py"
heldout = "verification/heldout.py"
contract = "double(x) returns x times two"
'''


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        (self.root / "module.py").write_text(BROKEN)
        (self.root / ".clawreflex.toml").write_text(CONFIG)
        verify = self.root / "verification"
        verify.mkdir()
        for name, source in (("reference", FIXED), ("regression", REGRESSION), ("heldout", HELDOUT)):
            (verify / (name + ".py")).write_text(source)
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_module.py").write_text("import unittest, module\nclass T(unittest.TestCase):\n def test_repo(self): self.assertEqual(module.double(5),10)\n")
        self.config = load_config(self.root)
        self.workspace = Workspace(self.config, self.base / "state")
        self.addCleanup(self.workspace.close)

    def driver(self, record, config):
        self.assertTrue(record.engine.probe(PROBE)["ok"])
        receipt = record.engine.patch(FIXED, "correct multiplication")
        self.assertTrue(receipt["ok"], receipt)
        self.assertTrue(receipt["verification"]["repository_suite"]["included"])

    def test_generic_repo_verified_proposal_apply_and_revert(self):
        initial = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        record = self.workspace.enqueue("module.py")
        self.workspace.process_next(self.driver)
        self.assertEqual(record.status, "verified", record.error)
        self.assertEqual((self.root / "module.py").read_text(), BROKEN)
        snapshot = record.output_dir / "tree"
        self.assertFalse((snapshot / "verification/reference.py").exists())
        self.assertTrue(record.engine.apply("user-apply")["applied"])
        self.assertEqual((self.root / "module.py").read_text(), FIXED)
        self.assertTrue(record.engine.revert("user-revert")["applied"])
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(initial, after)

    def test_any_saved_bytes_trigger_after_debounce_and_duplicate_hash_dedupes(self):
        target = self.root / "module.py"
        target.write_text(BROKEN + "\n# a real arbitrary save\n")
        self.assertEqual(self.workspace.poll(1), [])
        self.assertEqual(self.workspace.poll(1.05), [])
        launched = self.workspace.poll(1.11)
        self.assertEqual(len(launched), 1)
        record = self.workspace.runs[launched[0]]
        self.assertIn("arbitrary save", record.saved_source)
        self.assertIs(self.workspace.enqueue("module.py"), record)

    def test_save_during_active_run_gets_queued_and_latest_debounced(self):
        record = self.workspace.enqueue("module.py")
        def edit_during_driver(item, config):
            (self.root / "module.py").write_text(BROKEN + "# second save\n")
            self.workspace.poll(1)
            (self.root / "module.py").write_text(BROKEN + "# latest save\n")
            self.workspace.poll(1.05)
            self.workspace.poll(1.2)
        self.workspace.process_next(edit_during_driver)
        self.assertEqual(record.status, "rejected")
        queued = [item for item in self.workspace.runs.values() if item.id != record.id]
        self.assertEqual(len(queued), 1)
        self.assertIn("latest save", queued[0].saved_source)

    def test_delete_recreate_and_queue_full_preserve_pending_save(self):
        self.workspace = Workspace(replace(self.config, queue_depth=1), self.base / "state2")
        self.addCleanup(self.workspace.close)
        first = self.workspace.enqueue("module.py")
        target = self.root / "module.py"
        target.unlink()
        self.assertEqual(self.workspace.poll(1), [])
        target.write_text(BROKEN + "# recreated\n")
        self.workspace.poll(2)
        self.assertEqual(self.workspace.poll(2.2), [])
        self.assertIn("module.py", self.workspace.debounce)
        with self.assertRaises(queue.Full):
            self.workspace.enqueue("module.py")
        self.workspace.cancel_run(first.id)
        self.workspace.process_next()
        self.assertEqual(first.status, "cancelled")
        self.assertEqual(len(self.workspace.poll(2.3)), 1)

    def test_consent_and_secret_redaction_at_prompt_boundary(self):
        record = self.workspace.enqueue("module.py", source=BROKEN + "\nAPI_KEY='sk-abcdefghijklmnop'\n")
        prompt = self.workspace.prompt(record)
        self.assertNotIn("sk-abcdefghijklmnop", prompt)
        self.assertNotIn(FIXED, prompt)
        self.workspace.config = replace(self.config, provider_consent=False)
        with self.assertRaises(ValueError):
            self.workspace.prompt(record)

    def test_snapshot_excludes_credentials_and_enforces_budget(self):
        (self.root / ".env").write_text("SECRET=private")
        (self.root / "private.pem").write_text("private")
        record = self.workspace.enqueue("module.py")
        self.workspace.process_next()
        self.assertEqual(record.status, "awaiting_provider", record.error)
        self.assertFalse((record.output_dir / "tree/.env").exists())
        self.assertFalse((record.output_dir / "tree/private.pem").exists())
        tiny = Workspace(replace(self.config, max_snapshot_bytes=1), self.base / "tiny")
        self.addCleanup(tiny.close)
        item = tiny.enqueue("module.py")
        tiny.process_next()
        self.assertEqual(item.status, "failed")
        self.assertIn("budget", item.error)

    def test_cancel_during_verification_never_auto_applies(self):
        workspace = Workspace(replace(self.config, apply_mode="apply"), self.base / "auto")
        self.addCleanup(workspace.close)
        record = workspace.enqueue("module.py")
        def cancel_driver(item, config):
            self.driver(item, config)
            workspace.cancel_run(item.id)
        workspace.process_next(cancel_driver)
        self.assertEqual(record.status, "cancelled")
        self.assertEqual((self.root / "module.py").read_text(), BROKEN)

    def test_repository_suite_rejects_candidate_even_if_injected_tests_pass(self):
        (self.root / "tests/test_module.py").write_text("import unittest, module\nclass T(unittest.TestCase):\n def test_other_contract(self): self.assertEqual(module.double(5),999)\n")
        record = self.workspace.enqueue("module.py")
        self.workspace.process_next()
        receipt = record.engine.probe(PROBE)
        self.assertFalse(receipt["ok"])
        self.assertFalse(receipt["reference_green"])

    def test_pytest_adapter_runs_repository_tests_inside_same_sandbox(self):
        (self.root / "tests/test_module.py").write_text("import module\ndef test_repo():\n assert module.double(7) == 14\n")
        workspace = Workspace(replace(self.config, test_runner="pytest"), self.base / "pytest-state")
        self.addCleanup(workspace.close)
        record = workspace.enqueue("module.py")
        workspace.process_next(self.driver)
        self.assertEqual(record.status, "verified", record.error)

    def test_workspace_lease_and_unverified_language_fail_closed(self):
        with self.assertRaises(ValueError):
            Workspace(self.config, self.base / "state")
        with self.assertRaises(UnsupportedAdapter):
            adapter_for(replace(self.config, language="javascript"), self.base, "module.js")

    def test_stop_and_worker_process_queue_without_leaking_lock(self):
        record = self.workspace.enqueue("module.py")
        self.workspace.start()
        self.workspace.pending.join()
        self.workspace.close()
        self.assertEqual(record.status, "awaiting_provider", record.error)
        reopened = Workspace(self.config, self.base / "state")
        reopened.close()

    def test_config_paths_types_unknown_keys_and_scope_fail_closed(self):
        for text in (CONFIG + "\n[unknown]\nx=1\n", CONFIG.replace('debounce_ms = 100', 'debounce_ms = true'),
                     CONFIG.replace('reference = "verification/reference.py"', 'reference = "../reference.py"'),
                     CONFIG.replace('provider_consent = true', 'provider_consent = "yes"')):
            (self.root / ".clawreflex.toml").write_text(text)
            with self.assertRaises(ValueError):
                load_config(self.root)
        with self.assertRaises(ValueError):
            self.workspace.enqueue("verification/heldout.py")
        with self.assertRaises(ValueError):
            safe_path(self.root, "../outside.py")
        (self.root / "link.py").symlink_to(self.root / "module.py")
        with self.assertRaises(ValueError):
            safe_path(self.root, "link.py")

    def test_workspace_http_history_auth_and_run_specific_cancel(self):
        token = "x" * 32
        server = make_server(self.workspace, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        record = self.workspace.enqueue("module.py")
        def request(method, path, body=None, auth=True):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            headers = {"Authorization": "Bearer " + token} if auth else {}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, path, json.dumps(body) if body is not None else None, headers)
            response = connection.getresponse()
            value = json.loads(response.read())
            connection.close()
            return response.status, value
        self.assertEqual(request("GET", "/state", auth=False)[0], 401)
        status, state = request("GET", "/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["runs"][0]["id"], record.id)
        self.assertEqual(request("POST", f"/runs/{record.id}/cancel", {})[0], 200)
        self.assertTrue(record.cancel.is_set())
        self.assertEqual(request("POST", "/runs/missing/cancel", {})[0], 404)


if __name__ == "__main__":
    unittest.main()


class PersistedHistoryTests(unittest.TestCase):
    def test_restart_restores_readonly_history_without_execution_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve();root=base/'repo';root.mkdir()
            (root/'module.py').write_text(BROKEN)
            (root/'.clawreflex.toml').write_text(CONFIG)
            config=load_config(root)
            workspace=Workspace(config,base/'state')
            record=workspace.enqueue('module.py')
            run_id=record.id
            workspace.close()
            reopened=Workspace(config,base/'state')
            try:
                self.assertEqual(reopened.runs,{})
                self.assertTrue(reopened.history[run_id]['historical'])
                self.assertEqual(reopened.history[run_id]['status'],'interrupted')
                self.assertNotIn('saved_source',reopened.history[run_id])
                self.assertEqual(reopened.state()['runs'][0]['id'],run_id)
            finally:
                reopened.close()
