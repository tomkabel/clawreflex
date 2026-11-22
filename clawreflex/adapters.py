"""Test adapter seam. All repository code executes inside the shared OS sandbox."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Protocol

from .config import WorkspaceConfig
from .sandbox import run_unittest


class TestAdapter(Protocol):
    def execute(self, workdir: Path, source: str, tests: dict[str, str]) -> dict[str, Any]: ...


class UnsupportedAdapter(ValueError):
    pass


class PythonAdapter:
    def __init__(self, config: WorkspaceConfig, snapshot: Path, target: str):
        self.config = config
        self.snapshot = snapshot
        self.target = target

    def execute(self, workdir: Path, source: str, tests: dict[str, str]) -> dict[str, Any]:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        # Probe RED remains a focused exploit check. Reference and candidate GREEN
        # additionally run the real repository's configured suite.
        if len(tests) == 1:
            return run_unittest(source, tests, timeout=self.config.test_timeout_s)
        support = {"repo/" + path.relative_to(self.snapshot).as_posix(): path.read_bytes()
                   for path in self.snapshot.rglob("*") if path.is_file() and not path.is_symlink()}
        support["repo/" + self.target] = source.encode("utf-8")
        config = self.config
        if config.test_runner == "unittest":
            body = (
                "suite = unittest.defaultTestLoader.discover(" + repr("/work/repo/" + config.test_path)
                + ", pattern=" + repr(config.test_pattern) + ")\n"
                "        self.assertGreater(suite.countTestCases(), 0, 'repository suite discovered no tests')\n"
                "        result = unittest.TextTestRunner(verbosity=1).run(suite)\n"
                "        self.assertTrue(result.wasSuccessful(), 'repository suite failed')"
            )
        else:
            support.update(self._pytest_dependencies())
            body = (
                "import os, pytest\n"
                "        os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'\n"
                "        code = pytest.main(['-q', '-p', 'no:cacheprovider', "
                + repr("/work/repo/" + config.test_path) + "])\n"
                "        self.assertEqual(int(code), 0, 'repository pytest suite failed or discovered no tests')"
            )
        repository_test = (
            "import sys, unittest\n"
            "sys.path.insert(0, '/work/repo')\n"
            "sys.path.insert(0, '/work/repo/src')\n"
            "sys.path.insert(0, '/work/repo/.clawreflex_pytest_deps')\n"
            "class RepositoryTests(unittest.TestCase):\n"
            "    def test_repository_suite(self):\n"
            "        " + body + "\n"
        )
        result = run_unittest(source, dict(tests, **{"test_repository.py": repository_test}),
                              timeout=config.test_timeout_s, support_files=support)
        result["repository_suite"] = {"runner": config.test_runner, "path": config.test_path,
                                      "included": True, "passed": result["passed"]}
        return result

    def _pytest_dependencies(self) -> dict[str, bytes]:
        files = {}
        optional = {"tomli", "exceptiongroup", "typing_extensions"}
        for name in ("pytest", "_pytest", "pluggy", "packaging", "iniconfig", "pygments", "py", *sorted(optional)):
            spec = importlib.util.find_spec(name)
            if spec is None or spec.origin is None:
                if name in optional:
                    continue
                raise UnsupportedAdapter("pytest adapter requires pip install 'clawreflex[pytest]'")
            origin = Path(spec.origin)
            if spec.submodule_search_locations is None:
                files["repo/.clawreflex_pytest_deps/" + name + ".py"] = origin.read_bytes()
                continue
            root = origin.parent
            for path in root.rglob("*.py"):
                if not path.is_symlink():
                    files["repo/.clawreflex_pytest_deps/" + name + "/" + path.relative_to(root).as_posix()] = path.read_bytes()
        return files


def adapter_for(config: WorkspaceConfig, snapshot: Path, target: str) -> TestAdapter:
    if config.language != "python":
        raise UnsupportedAdapter("JS/TS adapters are not verified; beta supports Python only")
    return PythonAdapter(config, snapshot, target)
