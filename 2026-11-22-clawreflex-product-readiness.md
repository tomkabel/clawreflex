# ClawReflex: product-readiness audit and phased build plan

> Historical audit of the pre-hardening demo. Implementation began on 2026-11-22;
> see [the current ledger](clawreflex/IMPLEMENTATION.md),
> [execution evidence](plans/clawreflex-product/EXECUTION.md), and
> [the corrected product specification](1.md). Findings below describe the audited
> baseline and remain intact for comparison. A phase is not passed until its stated
> measurements or external evidence exist.

Date: 2026-11-22
Scope: this checkout (`a01f479` plus the uncommitted clawreflex work), the shipped demo,
the claims in `1.md` and `clawreflex/README.md`, and the test/benchmark evidence on disk.
Verdict first: **ClawReflex is a working hackathon demo, not a product.** It is roughly
**25% of the way to general public use**, and **0 of the 8 public-use gates** below pass.
The verification loop is real. Everything around it (generality, isolation, packaging,
benchmarks, integrations, operations) is missing or demo-only.

---

## 0. The one-page verdict

| Gate for "100% ready for general public use" | Status | Why |
|---|---|---|
| 1. Works on a real repository, not one owned fixture | FAIL | The watcher fires only when the saved bytes equal the synthetic vulnerable fixture (`watch.py:76`). A real user's save never triggers. |
| 2. Safe to run model-generated code | FAIL | A model-supplied unittest can execute arbitrary host code. Confirmed below: `app.__builtins__["eval"](...)` was accepted as a valid RED probe. |
| 3. Installable by a stranger | FAIL | No `pyproject.toml`, no console scripts, no package, no version, no install docs. `stage.sh` requires a hand-built OpenClaw config and `~/.openclaw/openclaw.json`. |
| 4. Honest, reproducible performance evidence | FAIL | The only real take is 173.9 s save-to-done. Best direct loop is 5.15 s. Median decode is 360 tok/s, not 2,000. The 1.24 s figure is a projection, labelled as such. |
| 5. Full test suite | FAIL | 13 tests exist; the documented command runs 8. Coverage is 43%. No HTTP, OpenClaw plugin, concurrency, or security tests. |
| 6. Full benchmark suite | FAIL | One endpoint per run, no paired statistics, no committed reproducible run, no CI, and the benchmark strips `reasoning_content` against the Cerebras replay rule. |
| 7. Cross-platform | FAIL | `resource`, `preexec_fn`, `setsid`, `xxd`, bash and a POSIX `~/.openclaw` layout. Linux-only in practice. |
| 8. Operable and supportable | FAIL | No logs beyond files, no metrics, no traces, no queue handling, no rate limit, no budget, no cancel, no undo, no revert, no backup. |

What is genuinely done: the RED/GREEN gate is real, the exploit must assert-fail on
vulnerable code and pass a withheld reference, the patch must pass exploit + regression +
held-out tests, write-back is atomic, a newer save is detected and left alone, receipts are
hashed, the film is real (46.0 s, `ffprobe`-verified), and the repo is Apache-2.0.

The gap is not "a few features". The product claim in `1.md` is "sub-second, on-save
adversarial self-healing compiler for any monitored repo". What exists is a single-file,
single-fixture, single-language demo with a cold subprocess runner. Closing the gap is a
5–7 engineer-week build to beta and roughly 10–12 to GA, not a weekend of polish.

---

## 1. How this was verified (reproducible)

Run from the repo root on 2026-11-22. Every number below came from a command, not memory.

```bash
python3 --version                       # 3.14.9
node --version                          # 26.13.1
openclaw --version                      # OpenClaw 2026.11.6 (06afb10)
ffprobe -v error -show_entries format=duration -of default=nw=1 \
  out/agent-film/clawreflex-story/clawreflex-story.mp4   # 46.000000

python3 -m unittest discover -s clawreflex -p 'test_*.py'
# Ran 8 tests ... OK          <- the command in README.md
python3 -m unittest discover -s clawreflex/tests -p 'test_*.py'
# Ran 5 tests ... OK          <- never run by the documented command

# coverage, both suites, coverage.py 7.x in a scratch venv
coverage run --source=. -m unittest discover -s . -p 'test_*.py'
coverage run --append --source=. -m unittest discover -s tests -p 'test_*.py'
coverage report
# TOTAL 1559 statements, 894 missed, 43%
# server.py 59%, watch.py 75%, core.py 89%, service.py 0%, benchmark.py 17%,
# throughput.py 20%, rig.py 0%, cut.py 0%, run_openclaw.py 0%
```

Live receipts on disk:

- `out/clawreflex/takes/20261122T062524Z/take.json`: save → done = **173.9 s**, agent exit 0.
  Probe 287.8 ms, patch 191.8 ms, both green, patch applied.
- `out/clawreflex/tput-060521/cerebras/summary.json`: median **360 tok/s** client decode,
  **12.4 s** TTFT, n=5; individual runs had 0–34 queue refusals, TTFT up to 53.8 s.
- `out/clawreflex/tput-060521/baseline/summary.json`: median **117 tok/s**, n=3,
  0.73 s TTFT.
- `out/clawreflex/20261122T053407Z-sql-direct-cerebras-shared/cerebras/loop.json`:
  best direct two-turn loop **5.15 s** wall, API turns 1.21 s + 3.70 s, 361 output tokens.
  Most other direct attempts failed with `429 queue_exceeded` or a 184 s timeout.

HTTP surface smoke test (server started on a temp fixture, then terminated):

```
/health 200 | /state 200 | POST no auth 401 | POST wrong token 401 | POST bad payload 400
```

The HTTP contract behaves. Nothing else about the process lifecycle is tested.

Security proof (the important one). This test source was accepted as a **valid RED probe**
(`ok=True`, `red_confirmed=True`, `reference_green=True`) and wrote a file on the host:

```python
import unittest, app
class E(unittest.TestCase):
    def test_injection_is_denied(self):
        app.__builtins__["eval"]("__import__('pathlib').Path('/tmp/escape-proof').write_text('x')")
        self.assertFalse(app.authenticate("missing", "' OR 1=1 --"))
```

The AST check in `server.py:79-110` blocks `eval` as a bare name and blocks a few
attribute calls (`system`, `popen`, `remove`, `unlink`, `rmtree`), but not subscripted
`__builtins__`. `core.py:45-46` blocks dunder attributes, but the product path uses
`server.py`, and `service.py` (which uses `core.py`) is dead code. The execution itself
(`server.py:43-76`) runs in a plain subprocess with no rlimits, no namespaces, no seccomp,
no network isolation, and inherited `PATH`.

---

## 2. Offered vs built

"Offered" means the claim in `1.md` or the README. "Built" is what the code does.

| Offered | Built | Evidence | Status |
|---|---|---|---|
| On-save adversarial loop | Yes, for one fixture | `watch.py`, `server.py` | Partial |
| Any monitored repo / any file save | No | `watch.py:76` requires exact fixture bytes; `server.py:340` requires `--fixture` | Missing |
| 3 realistic bug classes in a real repo | 3 minimal synthetic fixtures in a temp dir | `fixtures.py`; README says "owned and synthetic" | Demo only |
| Parallel Exploit Hunter + Root-Cause Analyst | Single sequential agent, two turns | `watch.py:87`, `benchmark.py` | Missing |
| Pre-warmed sandbox, <15 ms tool overhead | Cold `python3 -m unittest` per probe/patch | 287.8 ms / 191.8 ms measured; `server.py:43-76` | Missing |
| ≤1.4 s end-to-end, sub-second | 173.9 s real take; 5.15 s best direct loop | receipts above | Not achieved |
| 2,000 TPS Cerebras | 360 tok/s median on the trial queue | `tput-060521` | Not achieved |
| 13×–46× vs GPU | 117 tok/s GPU baseline; 3.1× decode ratio; queue dominates | `tput-060521` | Not demonstrated |
| OpenClaw Skill in `skills/claw-reflex/` | A plugin loaded by path, plus scripts | `openclaw/index.mjs`, `stage.sh` | Partial |
| Channel card with `/apply`, `/revert` | Local web monitor + JSON receipts only | `web/index.html` | Missing |
| Git / PR commit trigger, git diff | No git calls anywhere | `grep` | Missing |
| Multi-language | Python stdlib `unittest` only | `server.py:43-76` | Missing |
| Reproducible benchmark suite | Two manual scripts, single endpoint, no pairing | `benchmark.py`, `throughput.py` | Partial |
| Full test suite | 13 tests, 43% coverage, 8 run by docs | above | Partial |
| Installable product | Manual 10-minute reproduction, Linux assumptions | `README.md:19-36`, `stage.sh` | Missing |
| Privacy / data handling | Full file sent to provider; no scan or consent | `watch.py:25-34` | Missing |
| Cross-platform | Linux/POSIX only | `core.py:10,87`, `stage.sh` | Missing |

---

## 3. Findings by severity

### P0 — blocks public use

1. **Arbitrary host code execution from model-supplied tests.**
   Confirmed above. `server.py:79` allowlists imports but not `__builtins__`; `run_tests`
   (`server.py:43-76`) has no isolation or rlimits. `core.py:45` is stricter but unused by
   the product path. A model (or a prompt-injected file) can read keys, exfiltrate source,
   or modify the repo. This alone makes "run it on your repo" unsafe.

2. **The watcher only fires on the synthetic fixture.**
   `watch.py:76` skips every save whose bytes differ from `spec["code"]`. There is no path
   from "developer edits their own file" to "ClawReflex runs". This is the difference
   between a demo and a product.

3. **Lost-update race on write-back.**
   `server.py:218-228` reads the target, then writes a staged temp and `os.replace`s it.
   A save between the read and the replace is silently clobbered. The existing test only
   covers a change *before* `patch()` is called (`test_server.py:76-93`). There is no
   lock, no content hash compare-and-swap, and no undo snapshot.

4. **The headline performance claim is not the measured path.**
   173.9 s for the filmed repair; 5.15 s best direct loop; 360 tok/s median. The 1.24 s
   number is a projection from an optimistic 1,900 tok/s and a 15 ms sandbox that does not
   exist. Shipping "sub-second" now would be a false claim.

### P1 — blocks a credible beta

5. **Three divergent verification backends.**
   `core.py` (`ClawReflexRun`), `server.py` (`RepairRun`), `service.py` (`RepairRun` again).
   They differ in sandboxing, RED detection, rlimits, and API. `service.py` is referenced
   nowhere; `core.py` is exercised only by the undiscovered `tests/test_core.py`.
   `server.py:143` treats any output containing `"AssertionError"` as RED, so an erroring
   test can be accepted; `core.py:109` correctly requires `failures>0` and `errors==0`.
   Pick one engine.

6. **Test suite is incomplete and partly undiscovered.**
   13 tests, 43% coverage. The README command misses `tests/test_core.py` because `tests/`
   is not a package. No tests for the HTTP endpoints (only my manual smoke test), the
   OpenClaw plugin, `service.py`, `benchmark.py`, `throughput.py`, `run_openclaw.py`,
   concurrency, validator escapes, or the web monitor. No coverage gate, no mutation
   testing, no fuzzing.

7. **No benchmark suite, and the one benchmark is methodologically weak.**
   `benchmark.py` runs one endpoint per invocation and sets `full_user_targets_pass:
   False`; it strips `reasoning`/`reasoning_content` before replay (`benchmark.py:202-203`)
   although the Cerebras rule requires replaying the full assistant message; it relies on
   `tool_choice: "required"` and `parallel_tool_calls: false` without verifying those are
   supported. `throughput.py` measures raw streaming, not the product loop. There is no
   paired same-request comparison, no n≥30, no confidence interval, no committed receipt.

8. **No CI, linting, typing, or release process.**
   No `.github/`, no `pyproject.toml`, no `ruff`/`mypy` config, no version, no changelog.
   The working tree has 13 modified/deleted and 2 untracked clawreflex files, so the
   shipped demo is not even a reproducible checkout.

9. **Linux-only.**
   `core.py:10` imports `resource`; `core.py:87` uses `preexec_fn`; `stage.sh` uses
   `setsid`, `xxd`, bash arrays-of-heredocs and `~/.openclaw/openclaw.json`. No macOS or
   Windows path, no container image, no WSL guidance.

10. **No safe apply/undo surface.**
    The verified patch overwrites the editor file with no `.bak`, no git branch/commit, no
    revert. `test_clawreflex_exploit.py` is written next to the user's file and overwritten
    on every accepted probe (`server.py:164`). There is no policy for "auto-apply" vs
    "propose only".

11. **Privacy and secrets.**
    The full saved file is pasted into the prompt (`watch.py:25-34`) and sent to Cerebras,
    with no secret scan, redaction, path allowlist, or consent. For a public tool this is a
    data-loss vector.

12. **Queue and budget are not product concerns.**
    `benchmark.py` and `race.py` retry `429 queue_exceeded`; the product path relies on
    OpenClaw and a 600 s timeout. No user-visible queue status, no deadline, no cancel, no
    per-save budget, no debounce. Under hackathon load the save-to-done was 174 s.

### P2 — polish and operability

13. `ThreadingHTTPServer` with unsynchronized `RepairRun` state; concurrent tool calls can
    interleave `probe_attempts` and file writes (`server.py:245-335`).
14. Fixed verifier port `gateway+1` (`watch.py:65`), so two watchers collide; orphaned
    server if the watcher is killed.
15. `watch.py` crashes if the watched file is deleted (`target.stat()` at line 72).
16. `README.md` is a demo script, not docs: no install, config reference, threat model,
    limitations, troubleshooting, or upgrade path.
17. Film collateral is complete (46.0 s) but lives outside any product packaging; the
    deleted `make_film.py`/`narrate.py`/`mix_narration.py` are uncommitted, so the film
    pipeline in the checkout and the README no longer match.
18. Brand/font assets are loaded from `../skills/cerebras-demo-basics/assets/fonts` by
    both `server.py` and `service.py`; the tool is not relocatable without the whole repo.

---

## 4. What is already good — do not regress it

- RED is not "the test failed". It must be an assertion failure on vulnerable code and a
  pass on the withheld reference (`server.py:137-172`, `core.py:143-188`).
- GREEN requires the exploit, the existing regression, and the held-out tests
  (`server.py:182-205`, `core.py:209-218`).
- The patch is validated as source, must change the module, and is written atomically
  (`server.py:206-233`).
- A newer save is detected and preserved, with `target_changed` recorded.
- Receipts are structured, timestamped, SHA-256 hashed, and preserved per attempt.
- The film is real: 46.0 s, no simulated UI, waits labelled.
- The README labels projections as projections and admits the queue.
- Apache-2.0 at the repo root; no keys committed.

The plan below raises the standard without throwing this away.

---

## 5. Readiness scorecard

Scores are judgement, anchored on the evidence above; they are for prioritisation, not
certification.

| Dimension | Score | Note |
|---|---:|---|
| Verification loop correctness | 70% | Real gates; one engine, one language, synthetic inputs |
| Generality (repo/file/language) | 10% | Exact-fixture trigger, `app.py` only |
| Execution isolation | 15% | AST denylist, bypass confirmed, no sandbox |
| Performance / Cerebras use | 20% | Cold runner, queue-bound, 360 tok/s, no budget/cancel |
| Test suite | 35% | 13 tests, 43%, 5 undiscovered |
| Benchmark suite | 25% | Manual, single-endpoint, no pairing |
| Integration / UX | 20% | Plugin + local monitor; no card, git, apply/revert |
| Packaging / install / docs | 15% | No package, manual stage, Linux-only |
| Observability / ops | 20% | Files only; no metrics/traces/log rotation |
| Privacy / compliance | 20% | Full source to provider, no scan/consent |
| **Overall product readiness** | **~25%** | Demo-grade, not beta-grade |

---

## 6. Phased plan

Assumption: one senior engineer, full-time, with an OpenClaw/Cerebras key and a Linux host.
Multiply calendar time by ~2.5 for part-time. Each phase ends with an executable gate; no
phase is "done" on prose.

### Phase 0 — Freeze the demo and make the baseline reproducible (1–2 days)

Objective: a clean, installable, testable starting point.

Work:
- Commit or deliberately discard the uncommitted clawreflex changes; tag the demo
  `v0.1.0-demo` so the film and its receipts are reproducible.
- Add `pyproject.toml` (hatchling or setuptools), `src/clawreflex/` layout, `__init__.py`,
  console scripts `clawreflex` and `clawreflex-server`, Python `>=3.10`.
- Add `tests/__init__.py` so discovery actually finds `tests/test_core.py`; add a single
  `pytest`/`unittest` entry point that runs all 13 tests.
- Add `ruff`, `mypy` (or pyright), coverage config, and a GitHub Actions matrix
  (ubuntu + macos, Python 3.10–3.13, Node 20/22).
- Add `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`.

Gate: fresh clone → `pip install -e .` → one command runs 13/13 tests on two OSes; CI green;
`clawreflex --version` works; no import depends on the current directory.

### Phase 1 — Make model-generated code safe (3–5 days, critical path)

Objective: the LLM is an untrusted code author; its output never runs with the user's
privileges.

Work:
- One execution engine. Delete `service.py`; pick `server.py` as the engine and fold the
  better RED detection and rlimits from `core.py` into it.
- Replace the AST denylist with a strict allowlist: only `unittest` and the target module;
  reject all dunder attribute access, `__builtins__`, subscripted dunders, `getattr`,
  `setattr`, `vars`, `globals`, `locals`, `eval`, `exec`, `compile`, `open`, `input`,
  `breakpoint`, `importlib`, `ctypes`, `socket`, `subprocess`, `os`, and unknown calls.
  Block before execution, not by substring.
- Execute in a real sandbox: `bwrap` (available on this host) with no network, read-only
  `/`, a per-run tmpfs, dropped capabilities, and `RLIMIT_CPU/AS/FSIZE/NOFILE/NPROC`.
  Provide a Docker/Podman fallback and a macOS `sandbox-exec` profile. Document what is
  not isolated.
- Add an adversarial corpus as tests: at least 20 known escapes, including the confirmed
  `app.__builtins__` route. Gate: zero escapes.
- Fix write-back: lock, content-hash check, `os.replace`, `.bak` snapshot, and an
  idempotency key. Add a 100-iteration concurrent-writer test with zero lost writes.
- Privacy: scan the outgoing text for key-shaped strings (`CEREBRAS_API_KEY`, `sk-`,
  `ghp_`, private keys), redact, require explicit opt-in for auto-apply, and support a
  path allowlist/ignore list.
- Harden the HTTP surface: auth on `/state`, loopback-only default, per-run queue depth,
  request size caps, rate limit, and structured error responses.

Gate: escape corpus 0/20; concurrent-save test 100/100; `bandit`/`pip-audit` clean; a
recorded threat-model review; no source leaves the machine before the redaction step.

### Phase 2 — From one fixture to any repository (5–8 days)

Objective: a developer points ClawReflex at their repo and it works on their code.

Work:
- Remove the exact-bytes trigger (`watch.py:76`). Watch a workspace, debounce saves, map a
  changed path to its module and test command.
- Add `.clawreflex.toml`: target globs, ignore globs, test command, language, model,
  budget, apply mode (`propose` | `apply`), redaction rules.
- One server per workspace with a run registry keyed by `(path, sha256)`; no fixed port;
  a queue; clean shutdown and orphan cleanup.
- Run in a git worktree (or a copy) so the user's tree is never dirty; compute the diff
  against the saved bytes; support multi-file patches only after single-file is proven.
- Test-runner adapter interface: Python `unittest`/`pytest` first; then JS/TS
  (`vitest`/`jest`) as a second adapter to prove the seam.
- Replace synthetic fixtures with a **seeded-bug corpus** of 20 real tasks across 3 OSS
  Python repos, plus the 3 synthetic fixtures retained as `--demo` mode.

Gate: on 3 real repos with seeded bugs, ≥80% of runs produce an accepted patch; zero
changes outside the target file; the repo's own test suite still passes; the user's working
tree is unchanged after a rejected run.

### Phase 3 — Performance and real Cerebras use (3–5 days)

Objective: make the speed claim true, or publish the honest number.

Work:
- Pre-warmed test worker: a persistent process pool or fork server. Target <20 ms per
  test execution; measure against the 287.8 ms / 191.8 ms baseline.
- Stream and keep-alive: one HTTP/2 or pooled connection per provider, streamed tool
  calls, prefill reuse where supported. Remove per-call TLS setup from the hot path.
- Queue as a first-class state: retry `429 queue_exceeded` with jitter and a deadline,
  expose `queued`/`waiting` in the monitor, and never count queue time as decode time.
- Cerebras correctness: configurable model ID; stop hardcoding
  `moonshotai-kimi-k3.1-pro-trial` (`benchmark.py:60-73`, `throughput.py:84-89`); replay
  the full assistant message including `reasoning_content`; verify `reasoning_effort`,
  `tool_choice`, and `parallel_tool_calls` against the live API before relying on them;
  record `time_info` per turn.
- Budget and cancel: per-save token/time budget, abort on deadline, keep the file
  untouched on abort.
- Phase timings in every receipt: save, probe start/done, patch start/done, agent done.

Hard target: p50 ≤ 2.0 s and p95 ≤ 5.0 s save-to-done on a quiet endpoint for a one-file
fix; ≥1,500 tok/s server decode; 0 lost writes. If the queue makes this impossible,
publish p50/p95 with queue time separated and say so.

Gate: paired benchmark, same request bytes, Cerebras vs ≥2 GPU providers, n≥30, paired
bootstrap CI, committed receipts, and a README table generated from the receipts (not
hand-written).

### Phase 4 — OpenClaw-native integration and safe apply (5–7 days)

Objective: the thing a developer actually sees and trusts.

Work:
- Package a real OpenClaw skill/plugin: `SKILL.md`, `openclaw.plugin.json`, install
  command, config schema, compatibility check against OpenClaw 2026.11.x.
- Post a card to Control UI/Discord: RED evidence, diff, test counts, latency, and
  Apply/Revert actions. Policy: auto-apply only when tests pass, the file hash matches,
  and the user opted in; otherwise propose.
- Git mode: optional branch/commit per verified patch; revert via `git revert` or the
  snapshot; never commit secrets; never amend the user's history.
- Local monitor: run history, diff, timings, queue state, cancel, filters; accessible and
  honest (no fake progress).
- Optional VS Code extension later; the file watcher is enough for beta.

Gate: a new user installs in ≤5 minutes, sees a card, applies, reverts, and ends with a
clean `git status`; an end-to-end test drives the monitor with Playwright; an OpenClaw
integration test runs against a recorded provider.

### Phase 5 — Test and benchmark suites that act as the outside judge (4–6 days)

Objective: no claim without an executable check.

Work:
- Unit tests for every product module; HTTP contract tests (401/400/422/413, concurrent
  requests, `/state` auth); property-based tests for the validator; golden tests for the
  three fixtures; concurrency and timeout tests.
- End-to-end: fake OpenClaw + fake provider for CI, recorded real traces for regression.
- Coverage gate ≥85% on product modules; mutation testing (`mutmut`) ≥70% mutation score
  on the engine.
- `clawreflex-bench`: corpora (3 fixtures + 20 seeded bugs), paired providers, warm/cold,
  queue modelling, JSON + Markdown output, regression thresholds, nightly schedule.
- Reproducibility: pinned container, `make bench`, artifacts with hashes, no secrets.

Gate: CI runs the full suite on Linux and macOS; coverage and mutation gates pass; the
benchmark reproduces the README table within ±10%; a second machine reproduces it from a
clean clone.

### Phase 6 — Packaging, docs, release (3–4 days)

Objective: a stranger can adopt it without the author.

Work:
- Publish `pipx install clawreflex`; publish the OpenClaw plugin; optionally a signed
  container image.
- Docs: quickstart, install, config reference, security model, threat model, limitations,
  troubleshooting, architecture, ADRs, FAQ, migration.
- Examples: 3 repos, `--demo` mode, CI mode.
- Legal: confirm Apache-2.0, third-party notices for fonts/brand, privacy policy for code
  sent to providers, trademark guidance.
- Release: semantic version, signed tags, changelog, SBOM, uninstall path.

Gate: on a fresh Ubuntu and a fresh macOS machine, a reader follows the docs to a verified
repair in ≤10 minutes with no manual edits; uninstall leaves no state behind.

### Phase 7 — Pilot and GA gate (2–3 weeks calendar)

Objective: evidence from people who are not the author.

Work:
- 5–10 external developers, 2 weeks, opt-in telemetry.
- External security review of the sandbox and the apply path.
- Metrics: install success ≥90%, repair acceptance ≥70%, false applies 0, crash-free
  sessions ≥99%, p95 latency at target.
- Freeze the API; publish the benchmark; write the GA checklist.

Gate: all metrics met or explicitly waived with a written reason; security sign-off;
GA checklist signed.

### Critical path

`Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 6 → Phase 7`.
Phase 4 can run in parallel with Phase 3 once the engine API is stable. Do not start
Phase 2 before Phase 1: generality multiplies the attack surface.

### Outside judges (one per claim)

| Claim | Judge |
|---|---|
| Model code cannot escape | 20-case escape corpus; 0 escapes; external review |
| Repair is real | Held-out tests + reference + seeded-bug corpus; ≥80% acceptance |
| Patch never corrupts work | 100-iteration concurrent-writer test; 0 lost writes |
| Speed | Paired benchmark n≥30; p50/p95; receipts with hashes |
| No regressions | Target repo's own suite; mutation score ≥70% |
| Installable | Fresh Ubuntu + macOS script; ≤10 min |
| Film ≤60 s | `ffprobe` 46.0 s (already passing) |

---

## 7. Decisions needed before Phase 1

1. **Auto-apply policy.** Does a verified patch ever land without a human? Recommended:
   propose by default; auto-apply opt-in per repo; hard block on secrets, lockfiles,
   CI config, and files outside the allowlist.
2. **Data handling.** Sending source to Cerebras is the product. Decide the redaction
   rules, the retention story, and whether an on-prem/self-hosted model path is required.
3. **Scope.** Python-only beta is defensible. Multi-language is Phase 2+; do not promise
   it in the README until the adapter seam is proven.
4. **Trial model.** `moonshotai-kimi-k3.1-pro-trial` can expire. Get the stable model ID
   and a budget for benchmark runs before publishing numbers.
5. **Benchmark honesty.** If the queue prevents sub-second, ship "p50 5 s on the trial
   queue, 1.8 s on a quiet endpoint" rather than a projection. The demo's credibility
   depends on this.

---

## 8. Definition of done for GA

- [ ] Clean tag, `pipx install`, one-command uninstall.
- [ ] One execution engine; no dead `service.py`; all backends consolidated.
- [ ] Sandboxed execution with 0 escapes in the adversarial corpus.
- [ ] Any Python repo, debounced multi-file watch, git worktree isolation.
- [ ] p50/p95 published from paired receipts; queue separated from decode.
- [ ] Coverage ≥85%, mutation ≥70%, CI on Linux + macOS.
- [ ] Benchmark suite reproducible from a clean clone; nightly run.
- [ ] OpenClaw card with Apply/Revert; no lost writes; undo snapshot.
- [ ] Docs: install, config, security, limitations, troubleshooting.
- [ ] Pilot metrics met; external security sign-off.

---

## 9. Rewritten execution prompt

    Build ClawReflex from the current demo into a beta any Python developer can install.
    First freeze the demo as v0.1.0-demo and make the checkout reproducible. Then replace
    the dual verification backends with one engine, and make model-generated code safe:
    a strict allowlist, a real sandbox (bwrap/nsjail/Docker, no network, rlimits), a
    20-case escape corpus, a content-hash compare-and-swap write-back, a backup, and
    redaction of secrets before any code leaves the machine. Then remove the exact-fixture
    trigger so any saved file in a configured repo can run the loop, with a .clawreflex.toml,
    a workspace server, a run registry, and a git worktree per run. Then make the speed
    claim true or honest: pre-warmed test worker, pooled streaming connections, first-class
    429 queue handling, full reasoning_content replay, per-turn time_info, and a paired
    n>=30 Cerebras-vs-GPU benchmark with committed receipts. Then add the OpenClaw card
    with Apply/Revert and optional git mode. Then raise the suite to >=85% coverage and
    >=70% mutation score, add HTTP, concurrency, validator, and end-to-end tests, and put
    it all in CI on Linux and macOS. Finish with packaging, docs, a fresh-machine install
    test, and a 5-10 developer pilot.

    Pass: 13/13 tests plus the new suites green on two OSes; 0 escapes in the adversarial
    corpus; 100/100 concurrent writes preserved; >=80% repair acceptance on 3 real repos;
    p50 <= 2.0 s and p95 <= 5.0 s on a quiet endpoint with queue time reported separately;
    fresh install to verified repair in <=10 minutes; film still <=60 s (46.0 s today).

---

## 10. Next

Start Phase 0: freeze `v0.1.0-demo`, add the package skeleton, fix test discovery, and put
the 13 existing tests plus ruff/mypy/coverage in CI. That is the cheapest step that turns
this checkout from a demo snapshot into something that can be built on. Phase 1 (sandbox
and write-back) is the first real product decision and should not be skipped.
