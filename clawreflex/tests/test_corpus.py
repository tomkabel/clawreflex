import hashlib
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex.corpus import main, manifest, materialize


class CorpusTests(unittest.TestCase):
    def test_manifest_pins_twenty_distinct_tasks_across_three_repositories(self):
        data = manifest()
        self.assertEqual(len(data["tasks"]), 20)
        self.assertEqual(len({task["id"] for task in data["tasks"]}), 20)
        self.assertEqual(len(data["repositories"]), 3)
        for repo in data["repositories"].values():
            self.assertEqual(len(repo["commit"]), 40)
        for task in data["tasks"]:
            compile(task["test_source"], "corpus-test", "exec")
            self.assertNotEqual(task["before"], task["after"])

    def test_materialize_excludes_untracked_files_and_records_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "cache" / "repo"
            source.mkdir(parents=True)
            raw = b"def value():\n    return 1\n"
            (source / "app.py").write_bytes(raw)
            (source / ".env").write_text("PRIVATE=do-not-copy")
            data = {
                "repositories": {"repo": {"commit": "abc", "pythonpath": "."}},
                "tasks": [{"id": "task", "repository": "repo", "target": "app.py",
                           "source_sha256": hashlib.sha256(raw).hexdigest(),
                           "before": "return 1", "after": "return 0", "contract": "returns one",
                           "test_source": "# independent test\n"}],
            }
            calls = [mock.Mock(stdout="abc\n"), mock.Mock(stdout=""), mock.Mock(stdout=b"app.py\0")]
            with mock.patch("clawreflex.corpus.manifest", return_value=data), \
                    mock.patch("clawreflex.corpus.subprocess.run", side_effect=calls):
                result = materialize(root / "cache", root / "out", "task")
            self.assertEqual((root / "out" / "app.py").read_text(), "def value():\n    return 0\n")
            self.assertFalse((root / "out" / ".env").exists())
            self.assertFalse(result["model_acceptance_measured"])
            stored = json.loads((root / "out" / "clawreflex-corpus-input.json").read_text())
            self.assertEqual(stored["seeded_sha256"], result["seeded_sha256"])

    def test_unknown_task_fails_without_executing_git(self):
        with mock.patch("clawreflex.corpus.subprocess.run") as run, self.assertRaises(ValueError):
            materialize(Path("missing"), Path("missing-output"), "missing")
        run.assert_not_called()

    def test_cli_lists_pinned_manifest_and_requires_complete_materialize_arguments(self):
        output = io.StringIO()
        with mock.patch("sys.argv", ["corpus", "--list"]), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(len(json.loads(output.getvalue())["tasks"]), 20)
        with mock.patch("sys.argv", ["corpus"]), contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)

    def test_mismatched_checkout_cannot_create_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            data = manifest()
            task = data["tasks"][0]
            for commit, dirty in (("wrong", ""), (data["repositories"][task["repository"]]["commit"], " M source.py")):
                with mock.patch("clawreflex.corpus.subprocess.run", side_effect=[
                    mock.Mock(stdout=commit), mock.Mock(stdout=dirty),
                ]), self.assertRaises(ValueError):
                    materialize(Path(tmp), output, task["id"])
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
