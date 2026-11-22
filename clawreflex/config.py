"""Strict repository configuration and path policy for the Python beta."""
from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import importlib
from pathlib import Path
import sys
from typing import Any

tomllib = importlib.import_module("tomllib" if sys.version_info >= (3, 11) else "tomli")

DEFAULT_IGNORE = (".git/**", ".venv/**", "venv/**", "node_modules/**", "**/__pycache__/**",
                  ".env", ".env.*", "**/.env", "**/.env.*", "*.lock", ".github/**")


def safe_path(root: Path, relative: str, *, existing: bool = True) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("paths must be relative and stay inside the workspace")
    result = root / path
    for part in (result, *result.parents):
        if part == root.parent:
            break
        if part.is_symlink():
            raise ValueError("symlink paths are outside workspace policy")
    if not result.resolve().is_relative_to(root):
        raise ValueError("path leaves workspace")
    if existing and not result.is_file():
        raise ValueError(f"missing workspace file: {relative}")
    return result


@dataclass(frozen=True)
class TargetRule:
    glob: str
    reference: str
    regression: str
    heldout: str
    contract: str

    def verification_paths(self, relative: str) -> dict[str, str]:
        path = Path(relative)
        values = {"path": path.as_posix(), "stem": path.stem, "name": path.name}
        try:
            return {key: getattr(self, key).format(**values) for key in ("reference", "regression", "heldout")}
        except (KeyError, ValueError, IndexError) as exc:
            raise ValueError("invalid verification path template") from exc


@dataclass(frozen=True)
class WorkspaceConfig:
    root: Path
    targets: tuple[str, ...] = ("*.py", "**/*.py")
    ignore: tuple[str, ...] = DEFAULT_IGNORE
    debounce_ms: int = 250
    queue_depth: int = 8
    max_file_bytes: int = 200000
    max_snapshot_bytes: int = 20000000
    max_snapshot_files: int = 2000
    apply_mode: str = "propose"
    provider_consent: bool = False
    language: str = "python"
    test_runner: str = "unittest"
    test_path: str = "tests"
    test_pattern: str = "test_*.py"
    test_timeout_s: float = 20
    token_budget: int = 4096
    deadline_s: float = 60
    rules: tuple[TargetRule, ...] = ()
    provider: dict[str, Any] = field(default_factory=dict)
    redaction_patterns: tuple[str, ...] = ()

    def rule_for(self, relative: str) -> TargetRule:
        matches = [rule for rule in self.rules if fnmatch.fnmatchcase(relative, rule.glob)]
        if len(matches) != 1:
            raise ValueError("target requires exactly one trusted verification rule")
        return matches[0]

    def allowed(self, relative: str) -> bool:
        parts = Path(relative).parts
        if any(part.startswith(".clawreflex") for part in parts):
            return False
        if not any(fnmatch.fnmatchcase(relative, pattern) for pattern in self.targets):
            return False
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in self.ignore):
            return False
        for rule in self.rules:
            # Verification material is never itself an eligible repair target.
            for template in (rule.reference, rule.regression, rule.heldout):
                prefix = template.split("{", 1)[0]
                if ("{" not in template and relative == template) or (prefix and relative.startswith(prefix)):
                    return False
        return True


def load_config(root: Path | str, filename: str = ".clawreflex.toml") -> WorkspaceConfig:
    root = Path(root).resolve(strict=True)
    raw = tomllib.loads(safe_path(root, filename).read_text(encoding="utf-8"))
    if set(raw) - {"workspace", "provider", "tests", "budget", "target", "privacy"}:
        raise ValueError("unknown configuration section")
    sections = {name: raw.get(name, {}) for name in ("workspace", "provider", "tests", "budget", "privacy")}
    if not all(isinstance(value, dict) for value in sections.values()):
        raise ValueError("configuration sections must be tables")
    allowed = {
        "workspace": {"targets", "ignore", "debounce_ms", "queue_depth", "max_file_bytes", "max_snapshot_bytes",
                      "max_snapshot_files", "apply_mode", "provider_consent", "language"},
        "provider": {"model", "base_url", "key_env", "reasoning_effort", "stream"},
        "tests": {"runner", "path", "pattern", "timeout_s"},
        "budget": {"tokens", "deadline_s"}, "privacy": {"redaction_patterns"},
    }
    for name, section_values in sections.items():
        if set(section_values) - allowed[name]:
            raise ValueError(f"unknown {name} configuration key")
    work, tests, budget = sections["workspace"], sections["tests"], sections["budget"]
    values: dict[str, Any] = dict(work)
    for key in ("targets", "ignore"):
        if key in values:
            if not isinstance(values[key], list) or not all(isinstance(item, str) and item for item in values[key]):
                raise ValueError(f"{key} must be a list of nonempty globs")
            values[key] = tuple(values[key])
    values["ignore"] = DEFAULT_IGNORE + values.get("ignore", ())
    for key, low, high in (("debounce_ms", 0, 60000), ("queue_depth", 1, 128),
                           ("max_file_bytes", 1, 200000), ("max_snapshot_bytes", 1, 100000000),
                           ("max_snapshot_files", 1, 10000)):
        if key in values and (type(values[key]) is not int or not low <= values[key] <= high):
            raise ValueError(f"invalid {key}")
    if values.get("apply_mode", "propose") not in {"propose", "apply"}:
        raise ValueError("apply_mode must be propose or apply")
    if type(values.get("provider_consent", False)) is not bool:
        raise ValueError("provider_consent must be boolean")
    if values.get("language", "python") != "python":
        raise ValueError("only Python is supported by the beta")
    if tests.get("runner", "unittest") not in {"unittest", "pytest"}:
        raise ValueError("supported test runners are unittest and pytest")
    for key in ("path", "pattern"):
        if key in tests and (not isinstance(tests[key], str) or not tests[key]):
            raise ValueError(f"invalid test {key}")
    if "path" in tests:
        safe_path(root, tests["path"], existing=False)
    for key, value, limit in (("timeout_s", tests.get("timeout_s", 20), 120),
                              ("deadline_s", budget.get("deadline_s", 60), 3600)):
        if type(value) not in (int, float) or not 0 < value <= limit:
            raise ValueError(f"invalid {key}")
    tokens = budget.get("tokens", 4096)
    if type(tokens) is not int or not 1 <= tokens <= 100000:
        raise ValueError("invalid token budget")
    rules = raw.get("target", [])
    if not isinstance(rules, list) or not rules:
        raise ValueError("at least one [[target]] trusted verification rule is required")
    parsed = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"glob", "reference", "regression", "heldout", "contract"}:
            raise ValueError("invalid target rule fields")
        if not all(isinstance(value, str) and value for value in rule.values()):
            raise ValueError("target rule values must be nonempty strings")
        target_rule = TargetRule(**rule)
        # Validate templates before any watcher or provider is started.
        for path in target_rule.verification_paths("example.py").values():
            safe_path(root, path, existing=False)
        parsed.append(target_rule)
    provider = sections["provider"]
    for key in ("model", "base_url", "key_env"):
        if key in provider and (not isinstance(provider[key], str) or not provider[key]):
            raise ValueError(f"provider {key} must be a nonempty string")
    if "stream" in provider and type(provider["stream"]) is not bool:
        raise ValueError("provider stream must be boolean")
    if "reasoning_effort" in provider and provider["reasoning_effort"] not in {"low", "medium", "high", "max"}:
        raise ValueError("invalid provider reasoning_effort")
    patterns = sections["privacy"].get("redaction_patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise ValueError("redaction_patterns must be strings")
    import re
    for pattern in patterns:
        re.compile(pattern)
    return WorkspaceConfig(root=root, **values, test_runner=tests.get("runner", "unittest"),
                           test_path=tests.get("path", "tests"), test_pattern=tests.get("pattern", "test_*.py"),
                           test_timeout_s=tests.get("timeout_s", 20), token_budget=tokens,
                           deadline_s=budget.get("deadline_s", 60), rules=tuple(parsed),
                           provider=sections["provider"], redaction_patterns=tuple(patterns))
