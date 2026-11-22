# Contributing

From the repository root, use Python 3.10 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/ruff check clawreflex
.venv/bin/mypy
.venv/bin/coverage run -m pytest
.venv/bin/coverage report
.venv/bin/python -m build
```

The single pytest command includes the historical demo and engine tests. For stdlib
only discovery, use `python3 -m unittest discover -s clawreflex -p 'test_*.py'`.
Use `python -m ...` for Windows/PowerShell equivalents after activating the environment.
The product's sandbox support is documented separately; passing Python tests on a host
never implies the host provides a supported execution sandbox.

Preserve RED assertion failures with zero errors, the passing independent reference,
and GREEN exploit/regression/held-out checks. Never execute provider-generated code on
the host to make tests pass. Add regression reproductions for security changes.

Run `graphify update .` after code edits. Keep generated benchmark data honest: live,
recorded, synthetic and projected results must be clearly distinguished. Never add keys
or source containing secrets to fixtures, receipts, screenshots or git history.
