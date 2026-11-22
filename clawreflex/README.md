# ClawReflex

ClawReflex watches a configured Python repository, asks a model to demonstrate a bug,
then verifies a proposed repair in an OS sandbox. It defaults to proposals. Apply and
Revert are explicit, hash-guarded actions with recovery snapshots.

**Status: `0.2.0a1`, alpha.** The original hackathon demo is frozen as `v0.1.0-demo`.
Local security, workspace, HTTP and integration checks exist; the live performance,
external security review, multi-OS execution and developer pilot gates are still open.
See [IMPLEMENTATION.md](IMPLEMENTATION.md) for measured progress.

A probe must assertion-fail on the saved source, with no test errors, and pass a trusted
independent reference. A repair must pass that exploit, independent regression and
held-out tests, and the configured repository suite. An empty or skipped suite cannot
silently count as GREEN. Rejected checks leave the target unchanged. Generated tests
stay inside private run artifacts, away from developer-owned tests.

## Install from this checkout

Python >=3.10 is supported by package metadata. Linux requires working Bubblewrap;
macOS requires a working Docker/Podman VM and a digest-pinned Python sandbox image.
Windows native execution is unsupported; use WSL2 with the Linux setup. No generated
code runs if the sandbox is unavailable.

```sh
python3 -m venv .venv-clawreflex
.venv-clawreflex/bin/python -m pip install -e '.[dev]'
.venv-clawreflex/bin/clawreflex --version
.venv-clawreflex/bin/python -m unittest discover -s clawreflex -p 'test_*.py'
```

For an isolated CLI install, build the wheel with `python -m build` and use
`pipx install /absolute/path/to/dist/clawreflex-0.2.0a1-py3-none-any.whl`.
`pipx install clawreflex` is a future publication command; this project has not been
published to PyPI in this implementation. The wheel works outside the source tree.
Uninstall with `pipx uninstall clawreflex` or `python -m pip uninstall clawreflex`.
Review/delete the workspace's private run directory separately if you want to remove
history and recovery backups; never remove a backup before inspecting a conflict.

Container fallback provisioning (Docker example):

```sh
docker pull python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
export CLAWREFLEX_SANDBOX_IMAGE=python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
```

The configured image must already exist locally; the product never silently pulls it.
The fallback was smoke-tested on Docker/Linux. macOS execution is a CI/release gate.

## Configure a repository

Copy [example.clawreflex.toml](example.clawreflex.toml) to `.clawreflex.toml` in the
repository and adapt its target rules. Read [WORKSPACES.md](WORKSPACES.md) for the full
configuration and adapter contract. Provide an independent trusted reference and
regression/held-out test files for each target rule. These oracles remain local and
must not be supplied by the model being judged. Configure the repository's own tests.

```sh
clawreflex watch /absolute/path/to/repository
```

Ordinary saves are debounced and queued by content hash. Each run uses a bounded
private copy; credentials and verification oracles are excluded. State normally lives
under `.git/clawreflex` so a rejected repair does not dirty the repository. Non-git
repositories use the local state directory. The server uses an available loopback port
and writes a private connection file containing the access token.

Source disclosure requires `workspace.provider_consent=true`. Configure the provider's
HTTPS base URL, model and API-key environment-variable name. Keep credentials outside
tracked files. Built-in secret patterns and optional local patterns sanitize outgoing
content, but cannot detect every secret. Review the provider's own retention terms;
ClawReflex makes no retention promise on its behalf. Auto-apply requires an explicit
`apply_mode="apply"`; proposals are the default. See [SECURITY.md](SECURITY.md).

## Review, apply and undo

Open the local monitor and enter its access token. It shows actual proof, diff, test
counts and state, with Apply/Revert/Cancel controls and history filtering. A verified
proposal is distinct from an applied patch. Hash checks reject newer saves; atomic
exchange retains displaced data for recovery. Arbitrary open-file-descriptor and
repeated-writer limits are documented in the security model.

For OpenClaw, install the bundled skill/plugin and use `/clawreflex status`,
`/clawreflex apply RUN_ID`, `/clawreflex revert RUN_ID`, or `/clawreflex cancel RUN_ID`.
See [OPENCLAW.md](OPENCLAW.md). Model tools can propose and verify; explicit action
commands bypass the model. Optional git mode creates a new repair branch without
changing your current branch or index. No external messages are sent automatically.

## Performance evidence

| Measurement | Observed result | Scope |
| --- | --- | --- |
| Original filmed save-to-done | 173.9 s | OpenClaw path, includes queue waits |
| Historical best direct loop | 5.15 s | Direct two-turn API/tools, excludes OpenClaw |
| Historical Cerebras decode median | 360 tok/s, n=5 | Trial endpoint under load |
| Historical cold probe / patch | 287.8 / 191.8 ms | Demo runner |
| Current warm worker p50 / p95 | 31.903 / 50.482 ms, n=50 | One trivial unittest; busy Linux host; misses <20 ms worker target |
| Current cold worker median | 318.76 ms, n=10 | Same trivial unittest workload |

Warm-worker startup was 312.29 ms. Each check uses a fresh fork inside the sandbox;
module state and private temporary files do not carry across checks. The repository
adapter retains cold isolation. The [retained worker receipt](../plans/clawreflex-product/worker-benchmark-loaded.json)
records the exact measurement scope and environment (load average 23.88 on four CPUs).
Reproduce with `python -m clawreflex.worker_benchmark`. The worker gate remains open;
these results supersede a faster preliminary measurement before dispatcher hardening.
A separate reported 29.50 ms run has no retained raw receipt and is not release evidence.
The warm result does not establish a sub-second
repair. The old 1.24 s estimate and advertised 2,000 tok/s product performance are not
measured results. No paired wall-clock GPU speedup is claimed from separate decode runs.

The release targets remain p50 <=2 s and p95 <=5 s on a quiet endpoint, with queue time
reported separately. They require live paired n>=30 measurements, matched initial
requests, two GPU baselines, failures retained, raw receipts and bootstrap intervals.
Cerebras credentials and a stable model/budget are required; replay tests cannot pass
that live gate. See [the execution evidence](../plans/clawreflex-product/EXECUTION.md).

## Tests and release checks

```sh
python -m unittest discover -s clawreflex -p 'test_*.py'
ruff check clawreflex
mypy
coverage run -m unittest discover -s clawreflex -p 'test_*.py'
coverage report
node --test clawreflex/openclaw/test_plugin.mjs
node --test clawreflex/openclaw/test_monitor.mjs
python -m build
```

Browser tests use the repository's Puppeteer dev dependency. CI is configured for Linux
and macOS, but configuration alone is not a green remote run. The quality targets are
>=85% product coverage and >=70% engine mutation score. The initial validator mutation
baseline missed that target; current receipts and the implementation ledger report
results honestly.

The real-source corpus contains 20 seeded tasks across pinned more-itertools, boltons
and cachetools releases. All seeded assertion RED/reference GREEN dataset checks and
affected upstream module baselines pass. That is not >=80% model repair acceptance;
provider-generated results and upstream suite checks are still required. See
[CORPUS.md](../plans/clawreflex-product/CORPUS.md).

## Limits and support

- Python unittest/pytest only. JS/TS has an explicit unsupported adapter seam.
- A trusted verification oracle is required; unknown arbitrary code cannot be proven
  correct without one. Conservative AST policy rejects reflection, dynamic imports,
  decorators, filesystem operations and other unsupported patterns.
- Local sandboxing reduces exposure; it is not a substitute for external review.
- Cancellation is bounded/cooperative during provider and test execution.
- History is restored read-only after restart; new verification is required for actions.
- macOS, stranger install timing, live quiet-endpoint performance, external review and
  the 5–10 developer pilot remain unverified release gates.

Troubleshooting: a missing sandbox fails closed; provision Bubblewrap or the pinned
container. A missing reference rule is a configuration error. A rejected test must be
fixed rather than bypassed. A `target_changed` conflict means inspect the run's backup
and current editor bytes. Never retry by deleting user data or disabling verification.

## The historical demo and film

The film at `out/agent-film/clawreflex-story/clawreflex-story.mp4` is real, 46.0 seconds
by `ffprobe`, with labelled waits. The tag retains its original code and collateral.
The source checkout intentionally removed the superseded film scripts; use
`git show v0.1.0-demo:clawreflex/README.md` for the frozen demo reproduction instructions.
The explicit fixture watcher is `python -m clawreflex.watch --demo ...`.

The hackathon demo uses standard OpenClaw, Kimi K3.1 Pro on Cerebras, model
`moonshotai-kimi-k3.1-pro-trial` at `https://api.cerebras.ai/v1`. Event facts and branding
remain governed by [CLAUDE.md](../CLAUDE.md); the video kit is optional inspiration.

Apache-2.0. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md),
[CONTRIBUTING.md](CONTRIBUTING.md), and the root LICENSE.
