# ClawReflex

Sandboxed, evidence-driven repair verification for Python repositories, built with OpenClaw and Kimi K3.1 Pro on Cerebras.

ClawReflex asks a model to demonstrate a bug, requires assertion RED on the saved source and GREEN on a trusted independent reference, then verifies a proposed repair against the exploit, regression, held-out and repository tests. It defaults to proposals; Apply and Revert are explicit, hash-guarded actions with recovery snapshots.

**Status: 0.2.0a1, alpha.** This is a hackathon project, not a production-ready release. Coverage, mutation, worker-performance, live-provider, second-OS, external-security and developer-pilot gates remain open. See the [implementation ledger](clawreflex/IMPLEMENTATION.md) for measured results and failures.

## Install and verify

Requirements: Python 3.10+, Linux with Bubblewrap, or macOS with a working Docker/Podman VM. Windows native execution is unsupported; use WSL2.

```sh
git clone https://github.com/tomkabel/clawreflex.git
cd clawreflex
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/clawreflex --version
.venv/bin/python -m pytest -q
```

For an isolated CLI install, run `.venv/bin/python -m build`, then `pipx install dist/clawreflex-0.2.0a1-py3-none-any.whl`. The package has not been published to PyPI.

## Use

Copy [`clawreflex/example.clawreflex.toml`](clawreflex/example.clawreflex.toml) to `.clawreflex.toml` in your repository, configure trusted verification references and tests, then run:

```sh
clawreflex watch /absolute/path/to/repository
```

Read the [workspace guide](clawreflex/WORKSPACES.md) before configuring a real repository. Source disclosure requires explicit provider consent. Review the [security model](clawreflex/SECURITY.md) and [provider boundaries](clawreflex/PROVIDERS.md); generated code must never run without a working sandbox.

## Documentation

- [Full product README](clawreflex/README.md)
- [OpenClaw integration](clawreflex/OPENCLAW.md)
- [Release checklist](clawreflex/RELEASE.md)
- [Evaluation corpus](plans/clawreflex-product/CORPUS.md)
- [Historical readiness audit](2026-11-22-clawreflex-product-readiness.md)
- [Demo submission](https://x.com/picknewusername/status/2124563684127097215)

Apache-2.0. See [LICENSE](LICENSE) and [third-party notices](clawreflex/THIRD_PARTY_NOTICES.md).
