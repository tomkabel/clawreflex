"""Legacy API compatibility; all verification runs through server.RepairRun."""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from .server import RepairRun, save_json
    from .sandbox import run_unittest
    from .validation import module_imports, validate_patch_source, validate_test_source
else:
    from server import RepairRun, save_json
    from sandbox import run_unittest
    from validation import module_imports, validate_patch_source, validate_test_source

__all__ = ['ClawReflexRun', 'save_json', 'run_unittest', 'module_imports', 'validate_source']


def validate_source(source: str, allowed_imports: set[str]) -> None:
    if allowed_imports == {'unittest', 'app'}:
        validate_test_source(source)
    else:
        validate_patch_source(source, allowed_imports)


class ClawReflexRun(RepairRun):
    def __init__(self, fixture_name: str, nonce: str, output_dir: Path):
        super().__init__(fixture_name, nonce, output_dir)
        self.fixture = self.spec

    @property
    def red_confirmed(self) -> bool:
        return self.probe_receipt is not None

    @property
    def green(self) -> bool:
        return self.verified_source is not None

    def patch(self, source: str, summary: str = '') -> dict[str, Any]:
        try:
            return super().patch(source, summary)
        except ValueError as exc:
            return {'ok': False, 'applied': False, 'error': str(exc)}
