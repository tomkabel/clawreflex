# Readiness implementation record

This record tracks work against `2026-11-22-clawreflex-product-readiness.md`.
That audit remains the historical baseline. Status here means observed evidence,
not the presence of a checklist or a promised future run.

## Phase 0 — reproducible baseline and package

- Frozen original ClawReflex working copy as annotated local tag `v0.1.0-demo`, commit
  `7e63120d791953173e865dd238d430e3ebff1d0b`. A temporary git index and `commit-tree`
  preserved only ClawReflex changes on the original HEAD; the user's branch, index and
  unrelated dirty files were not committed or discarded.
- Archive and SHA-256 file manifest: `out/clawreflex/releases/v0.1.0-demo.tar.gz` and
  `v0.1.0-demo.manifest.json`. These local evidence files are git-ignored.
- Root `pyproject.toml`, Python >=3.10, versioned package, console scripts and wheel
  data. Existing flat `clawreflex/` package retained to preserve the demo's script and
  film paths; package-relative imports support installed operation independent of cwd.
- Unified discovery includes all 13 historical tests with pytest or unittest.
- CI matrix declared for Ubuntu/macOS, Python 3.10–3.13 and Node 20/22. Remote CI and
  macOS execution remain unmeasured in this Linux session.
- Ruff checks all ClawReflex Python files. Mypy initially checks the CLI/package entry
  points; expanding typed coverage to the consolidated engine is subsequent work.
- Linux execution: stdlib discovery 13/13 in 13.839 s; fresh venv pytest 13/13
  in 23.16 s; Ruff passes; mypy passes the two entry-point modules. Coverage baseline
  is 42% (1,079 statements); no coverage gate is claimed yet. Editable install and
  `clawreflex --version` / delegated `watch --help` pass. Isolated sdist and wheel build pass. A second fresh venv installed the wheel,
  then ran `clawreflex --version` and `clawreflex-server --help` successfully from `/tmp`.
  `graphify update .` completed after code edits.

## Remaining phase gates

| Phase | Status | Required evidence |
| --- | --- | --- |
| 1 Safety | Implemented locally; review pending | Sandbox, adversarial/HTTP/apply tests pass; external review and container/macOS validation pending |
| 2 Workspaces | Implemented locally; acceptance pending | Generic content watcher, private copies and unittest/pytest adapter tests pass; live real-repo model acceptance pending |
| 3 Providers/performance | Implemented locally; speed gates open | Provider/queue/replay tests pass; current worker target missed; live latency unmeasured |
| 4 OpenClaw/actions | Implemented locally; external scope open | Authenticated Apply/Revert, plugin and UI tests pass; native channel callbacks and stranger install pending |
| 5 Outside judges | Local quality gates failed; live gate open | Coverage 77% (<85%), mutation 19.49% (<70%); paired live n>=30 pending |
| 6 Release | Local candidate rebuilt and checked; release gates open | Current wheel fresh-install check passes; SBOM/provenance, stranger install and platform evidence pending |
| 7 Pilot/GA | External | 5–10 developers, external security review and signed gates |

No live API benchmark, pilot, external security review or remote OS run is implied by
this implementation. Preserve the 46.0-second historical film and its measured receipts.

## Phase 1 — implemented safety path

- One engine: `server.RepairRun`; `core.py` is a compatibility facade and `service.py`
  is a deprecated CLI alias. Custom trusted `spec=` and `executor=` seams support the
  next workspace phase without creating another verifier.
- Strict AST test policy and conservative stdlib candidate policy; genuine structured
  RED counts; independent reference + regression + held-out GREEN retained.
- Actual bubblewrap sandbox, no network or host workspace/home/credential environment,
  read-only inputs, child-installed rlimits, bounded output and timeout. Digest-pinned
  container fallback is implemented but not runtime-tested on macOS here.
- Propose default for real targets; explicit apply/revert, content hashes, atomic exchange,
  linked backups, idempotency, conflict recovery. No developer test file is created.
  The old demo tests now explicitly opt into editor application and check proof artifacts
  inside the run directory. Artifact-only demo runs retain their historical `applied`
  field with an explicit `application_scope=artifact` receipt.
- HTTP state and mutations authenticated, loopback-only constructor, Host/Origin checks,
  bounded connection/tool concurrency, rate limit, JSON/type/request-size enforcement.
- Local privacy helper redacts key-shaped data; apply blocks secret-shaped source.
  Provider integration must use the filter in its subsequent phase.
- New escape, OS-isolation, timeout, concurrency, apply/revert/idempotency and HTTP tests.
  30 malicious probe payloads plus alias/module-chain cases reject before execution.
  100 deliberately timed editor saves (50 in-place, 50 atomic replacement) retain bytes
  at the target after conflict recovery. This is a bounded tested invariant; see SECURITY
  for open-fd and repeated-writer limitations, rather than a universal CAS claim.
- Preliminary cold sandbox smoke measured ~173 ms. No <20 ms worker or end-to-end
  speed target has been achieved or claimed by this phase.

Phase 1 observed checks on this Linux host: unified suite **62/62 passes** in 9.848 s
(the count includes concurrently added corpus/statistics/pilot tests); six security modules
**86% statement coverage** (740 statements, 102 missed). Ruff passes all ClawReflex
Python files and mypy passes server/core/sandbox/validation/apply/privacy. Bandit on
those six modules is clean after narrow, explained suppressions for the constructed
sandbox subprocess argv and private namespace `/tmp`; no broad checks were disabled.
Full-product coverage, mutation score, dependency audit, container runtime validation,
macOS execution and external security review remain separate unfinished gates.

## Phase 2 — configured workspaces and isolated repository tests

- Added strict `.clawreflex.toml` parsing, target/ignore globs, bounded snapshots,
  debounce/queue/deadline/token settings, provider consent, and trusted per-target
  reference/regression/held-out mappings. Python 3.10 uses the conditional `tomli`
  dependency; Python 3.11+ uses stdlib tomllib. Proposals remain the default.
- `clawreflex watch <repo>` now watches ordinary configured source content. Fixture
  equality is confined to explicit `--demo` mode. Content hashes debounce rapid saves,
  retain later saves while a run is active, handle deletion/recreation, deduplicate runs
  by path/hash and retain pending saves when the bounded queue is full.
- One leased workspace process, an ephemeral loopback server, authenticated per-run
  tools/actions/history, private connection token file and cancellation event. Run
  receipts persist under `.git` or external local state; the active action registry is
  process-lifetime in this phase. Drivers attach through `Workspace.start(driver)` or
  `process_next(driver)`; no model invocation is implied by configuration alone.
- Each run uses a bounded private copy rather than a git checkout, preserving saved
  dirty/untracked bytes without running hooks or modifying the developer tree. Common
  credentials, ignored paths and the run's trusted oracles are excluded. Read-only
  sandbox mounts prevent generated repository tests changing other files.
- The Python adapter uses the same engine and OS sandbox. Reference/candidate GREEN
  includes the configured repository suite in addition to generated exploit and
  independent regression/held-out modules. Unittest and pytest both have actual
  isolated integration tests; pytest disables third-party plugin auto-loading and
  requires the optional runner dependency. Unsupported JS/TS fails explicitly.
- Trusted reference files remain required; the conservative Python source policy can
  reject real modules. This is configured repository support, not autonomous creation
  of trustworthy references for arbitrary unknown bugs.

Observed on Linux: full unified suite **76/76 passes in 23.207 seconds**, including 13
workspace tests and real sandboxed unittest/pytest checks. Generic repo end-to-end
RED/reference/GREEN, proposal/apply/revert leaves every other source file unchanged.
Queue backpressure, active-save retention, deletion/recreation, cancellation, path
policy, private snapshots, lease and HTTP auth are tested. Ruff passes all ClawReflex
Python files; mypy passes config/workspace/adapters/sandbox/CLI. See WORKSPACES.md and
example.clawreflex.toml. The >=80% live model acceptance on 3 real repos remains pending;
reference restoration or the deterministic driver is not a model acceptance result.

## Phase 3 — bounded provider driver and reproducible measurements

- Generic watcher attaches `WorkspaceDriver` after explicit repository disclosure
  consent. A configured endpoint/model and credential environment variable are
  required; no stable model ID is fabricated. `--external-tools` retains the OpenClaw
  tool-driven path, and `--demo` retains historical event configuration.
- Pooled HTTP transport supports bounded SSE/JSON responses, complete reasoning/tool
  replay, provider `time_info`, usage, request hashes, TTFT and per-turn wall time.
  Sanitized requests/receipts pass the privacy filter; reference and held-out
  diagnostics never enter model context. Sensitive assistant replay aborts continuation.
- 429 exposes a queue state with bounded Retry-After/jitter waits. Cancellation
  interrupts active socket I/O and waits; deadlines include workspace queue age.
  Completion tokens are budgeted across turns and missing usage fails closed. This
  is not a monetary ceiling; DNS and an in-progress sandbox check have documented
  cancellation limits in PROVIDERS.md.
- Paired benchmark randomizes endpoint order, matches initial request material,
  retains failed runs, and writes raw receipts, paired bootstrap intervals and
  hashed manifests. Replay is forcibly marked non-live. Direct API/tool timing
  explicitly excludes workspace debounce/copying and OpenClaw, so it cannot certify
  save-to-done targets. No live paired run was performed.
- The optional pre-warmed fork worker is supported by the direct benchmark. Full
  repository verification retains cold isolation; current worker measurements miss
  the <20 ms target on this loaded host. Details and failure receipts follow below.

Observed: provider/workspace/throughput/paired-benchmark/worker suite **26 passed plus
8 subtests** in 13.93 s, including actual local HTTP/SSE and OS-sandbox execution.
Ruff passes; mypy passes provider, warm_worker, worker_benchmark, benchmark and
throughput. The prior full integration run passed **107 tests plus 191 subtests** in
33.34 s before the final dispatcher-isolation test was added. Local deterministic
provider responses do not establish live model repair acceptance or provider speed.

## Additional execution evidence

- Phase 4 local integration: bundled OpenClaw skill, npm package, dependency-free
  tool implementation plus SDK authoring entry, authorized `/clawreflex` commands,
  authenticated browser controls and run selector/filter. Five Node contracts and
  one browser-driven Apply/Revert test pass. OpenClaw 2026.11.6 SDK build and
  `plugins validate` pass. No external messages sent; native channel callbacks and
  stranger install timing remain pending.
- Optional git branch commit uses plumbing with hooks disabled and a temporary index;
  two tests confirm HEAD/index/files stay untouched and new saves/secrets are refused.
- Phase 7 local collector rejects private/unknown data and missing consent, computes
  explicit pilot thresholds and never infers external sign-off. Pilot not started.
- Corpus: 20 genuine assertion RED/reference GREEN seeded tasks across pinned
  more-itertools, boltons and cachetools releases; affected upstream module baseline
  suites pass. Model repair acceptance remains unmeasured. See `../plans/clawreflex-product`.
- Dependency audit: 52 development packages, zero known vulnerabilities. Docker
  digest-pinned fallback smoke also passes on Linux; neither establishes macOS results.
- Initial validator mutation baseline: 76/390 killed, 302 survived, 12 untested. This
  misses the >=70% target and is retained as failure evidence for test improvement.

- Pre-warmed worker: persistent sandbox dispatcher and fresh fork per check; seven tests
  cover full golden verification, timeout/recovery, module reset, tmpfs cleanup, host
  hiding, request validation and dispatcher protocol/memory isolation. The dispatcher
  runs as namespace PID 1 with dumpability disabled. This closes a `/proc` protocol-fd
  access found by a deliberate policy-bypass check. Ruff/mypy pass. The latest retained
  n=50 trivial unittest measurements under full-suite/high host load are warm p50
  **31.903 ms**, p95 **50.482 ms**; cold n=10 p50 **318.76 ms**; startup **312.291 ms**.
  Host load average **23.88** on four CPUs. Receipt:
  `../plans/clawreflex-product/worker-benchmark-loaded.json`. A separately reported
  29.50 ms run has no retained raw receipt and is not used as release evidence.
  Reproduce with `python -m clawreflex.worker_benchmark`.
  The <20 ms worker gate remains open; the earlier pre-hardening 8.83 ms measurement
  cannot certify this implementation. Repository adapter and save-to-done performance
  remain separately measured.

## Final local verification — 2026-11-22 19:53 EET

- Full Python suite: **108 passed, 191 subtests passed** in 45.78 s. Ruff passed;
  mypy passed its configured two entry modules. Expanded whole-package typing remains open.
- Node plugin: five contracts passed. Browser monitor: two actual Apply/Revert tests passed.
- Rebuilt wheel and sdist. The current wheel hash is recorded in
  `../plans/clawreflex-product/fresh-wheel-check.json`; keeping it outside the packaged
  ledger avoids changing the artifact hash by recording it.
  The wheel has 77 entries and no `node_modules`, `.env`, `.pem` or `.key` entries.
  Tests and demo helpers remain packaged; retaining or removing them is a release decision.
- Fresh isolated wheel check passed, including actual sandboxed assertion RED,
  reference GREEN, independent GREEN, proposal default, Apply and exact Revert. The latest
  elapsed time and artifact hash are in `../plans/clawreflex-product/fresh-wheel-check.json`.
  This is same-host offline evidence,
  not a stranger install, live model result or second-OS result.
- Historical film remains 46.000000 s by ffprobe. `graphify update .` completed.
- Product coverage remains 77% and validator mutation score remains 19.49%; both fail
  their gates. The current worker also fails its <20 ms target. These failures, the real
  repository compatibility limitation and every external gate remain open. This is not
  beta or GA sign-off.
