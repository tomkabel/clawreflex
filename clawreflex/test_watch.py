import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from clawreflex import watch
from clawreflex.fixtures import fixture


class WatchTests(unittest.TestCase):
    def test_nonzero_agent_exit_is_reported(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            watch.report_agent_exit(1)
            watch.report_agent_exit(0)
        self.assertIn("Kimi did not finish", output.getvalue())
        self.assertIn("agent.json", output.getvalue())
        self.assertEqual(output.getvalue().count("Kimi did not finish"), 1)

    def test_save_during_run_is_not_marked_seen(self):
        class SecondRun(Exception):
            pass

        class Server:
            def terminate(self):
                pass

            def wait(self):
                return 0

        class Agent:
            returncode = 0

            def __init__(self):
                self.polls = iter([None, 0])

            def poll(self):
                return next(self.polls)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            stage = root / "stage"
            repo.mkdir()
            stage.mkdir()
            target = repo / "app.py"
            spec = fixture("sql", "ownednonce")
            target.write_text(spec["reference"])
            (stage / "openclaw.json").write_text(json.dumps({"gateway": {"port": 18790}}))
            (stage / "gwtoken").write_text("test-gateway-token")
            (stage / "tooltoken").write_text("test-tool-token")
            sleeps = 0
            launches = 0

            def sleep(_):
                nonlocal sleeps
                sleeps += 1
                if sleeps == 1:
                    target.write_text(spec["code"])
                elif sleeps == 2:
                    os.utime(target)
                elif sleeps >= 4:
                    self.fail("a save made during the run was marked as seen")

            def popen(*_, **__):
                nonlocal launches
                launches += 1
                if launches == 1:
                    return Server()
                if launches == 2:
                    return Agent()
                raise SecondRun

            argv = ["watch.py", "--demo", "--dir", str(repo), "--stage", str(stage), "--nonce", "ownednonce"]
            with mock.patch.object(watch, "ROOT", root), \
                    mock.patch.object(watch.sys, "argv", argv), \
                    mock.patch.object(watch.time, "sleep", side_effect=sleep), \
                    mock.patch.object(watch.time, "strftime", side_effect=["20261122T000000Z", "20261122T000001Z"]), \
                    mock.patch.object(watch.subprocess, "Popen", side_effect=popen), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SecondRun):
                    watch.main()
            self.assertEqual(launches, 3)


if __name__ == "__main__":
    unittest.main()
