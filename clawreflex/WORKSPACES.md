# Configured Python workspaces

Run `clawreflex watch /path/to/repo` with a `.clawreflex.toml` in that repository.
The default path watches content changes in configured files, including deletion and
recreation, debounces rapid saves and retains a later save while another run is active.
`clawreflex workspace` is an alias. The historical fixture watcher requires `--demo`.

Start with `clawreflex/example.clawreflex.toml`. Every eligible target needs exactly
one `[[target]]` rule with an independent reference, regression tests and held-out tests.
Paths stay inside the repository and cannot traverse symlinks. Verification paths can
use `{path}`, `{name}` or `{stem}` templates. Globs use Python fnmatch semantics.
Source must be UTF-8 and within the configured size budget. Configuration changes
require restarting the workspace server.

This oracle requirement is deliberate: ClawReflex does not invent an independent
reference for an unknown bug. Without a trusted reference it cannot claim the original
strong RED/reference/GREEN proof. Python modules must also fit the conservative source
policy in SECURITY.md; dependencies, decorators and private introspection can be rejected.
JS/TS is outside this beta's verified scope. The adapter protocol is present so language
support can be added without introducing another verification engine.

Each run copies the workspace into a bounded private directory, excluding `.git`,
virtual environments, node_modules, ignored paths, common credentials and the run's
verification oracles. This safe copy preserves dirty and untracked source bytes without
checking out files, running git hooks or modifying the developer tree. The exact saved
target bytes overwrite the copy, even if the editor saves again before processing.
The product supports one target per proposal. The sandbox mounts inputs read-only;
only an explicit hash-guarded application can change the original target.

The queue is keyed by `(relative path, source SHA-256)`. Full queues retain the latest
debounced save until capacity becomes available. One process holds a workspace lease.
State lives under `.git/clawreflex` in ordinary git repositories, under the worktree's
git directory for linked worktrees, or under the user's local state directory otherwise.
No run artifact is written next to source files. Source snapshots, hidden tests and
backups are private local data; apply the same disk and retention controls as source.

The Python adapter runs the generated probe, independent regression and held-out
modules, plus the configured repository test suite for reference/candidate GREEN.
The whole check runs in the existing networkless OS sandbox with its resource limits.
`unittest` discovery uses `[tests].path` and `.pattern`. The pytest adapter requires
`pip install 'clawreflex[pytest]'`; it copies the trusted runner dependencies into the
sandbox and disables automatic third-party plugin loading. Repository conftest plugins
still run inside the sandbox and may fail if their dependencies are unavailable.
An empty repository suite never counts as GREEN. Heavy integration suites may exceed
the sandbox's CPU/memory limits; startup latency and the full suite remain measured
costs, not a sub-second promise.

The workspace server binds a random loopback port. A mode-0600 `connection.json`
records its URL and bearer token; the token is never printed or embedded in a URL.
All state and actions require authentication and pass Host/Origin validation. Routes:

- `GET /state`: queue state and run history for this process.
- `GET /runs/<id>/state`: a prepared engine's evidence or queued run metadata.
- `POST /runs/<id>/tool/clawreflex_probe`: `{ "test_source": "..." }`.
- `POST /runs/<id>/tool/clawreflex_patch`: `{ "source": "...", "summary": "..." }`.
- `POST /runs/<id>/action/apply` and `/action/revert`: `{ "idempotency_key": "..." }`.
- `POST /runs/<id>/cancel`: `{}`.

Provider disclosure requires `workspace.provider_consent=true`. Only the target source
and contract enter `Workspace.prompt()`, after the privacy filter; reference and held-out
sources are withheld. The queue currently accepts a driver callback with `(run, config)`;
`run.engine` exposes the shared verifier and `run.cancel` is a cancellation event.
The local server can prepare runs for external tool calls without a provider driver.
The subsequent provider integration attaches to this seam; merely setting provider
configuration does not mean a model was called. Proposed patches never auto-apply.
The opt-in `apply_mode="apply"` path checks cancellation and deadline before application.

History metadata and receipts persist on disk; this phase's action registry lives for
the process lifetime. Restarted-action recovery and richer history UI belong to the
integration phase. `close()` signals pending runs, joins the worker and releases its
lease; active drivers must honor cancellation. No external acceptance or pilot result
is inferred from the deterministic integration test.
