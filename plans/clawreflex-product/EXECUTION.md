# ClawReflex readiness execution

Started 2026-11-22. The original readiness audit is historical evidence; this ledger
tracks implementation and the independent checks required to supersede its findings.

## Outcome and constraints

Ship an installable Python repair assistant that proposes independently verified fixes,
isolates untrusted execution, preserves developer work, and makes claims from receipts.
Preserve existing user edits, the three demo fixtures, RED/reference/GREEN verification,
hashed receipts, and the existing real film. Execute one subagent at a time.

Altitude ladder: reproduce the demo; make the repair path safe and general; maintain
release readiness with executable gates. Depth starts with source, adversarial inputs,
filesystem interleavings and raw provider receipts. Tests, benchmark statistics,
fresh-environment installs and external review judge the result. Range is skipped.

## Sequential work packages

1. Phase 0: immutable demo snapshot, packaging, complete test discovery, CI and tooling.
2. Phase 1a: one verification engine, strict validation, sandbox and escape corpus.
3. Phase 1b: guarded apply/revert, snapshots, privacy and HTTP contracts.
4. Phase 2: repository configuration, debounced workspace queue, isolated run copies or
   worktrees, test adapter, real repository evaluation harness.
5. Phase 3: provider transport, full reasoning replay, queue/deadline/cancel/budget,
   timings and measured worker performance.
6. Phase 4: installable OpenClaw integration, actions, history and optional git commit.
7. Phase 5: adversarial/HTTP/concurrency/e2e suites, coverage/mutation and paired
   benchmark tools, reproducible receipts.
8. Phase 6: wheel/npm package validation, install/config/security/privacy/limitations
   docs, local fresh-install check and release checklist.
9. Phase 7: pilot protocol, consent and metric collection, external-review checklist;
   external participation and sign-off must actually occur before GA.

Packages may be combined when one engineer must own tightly coupled code. No later
package may weaken a verified security or correctness invariant for convenience.

## Policy decisions

- Propose by default. Auto-apply requires explicit repository configuration.
- Source may reach a configured provider only after the privacy filter. Do not claim
  provider retention guarantees; operators choose a provider and review its terms.
- Python is the beta scope. A second adapter must be tested before advertising support.
- Demo event metadata retains the trial model from CLAUDE.md. Product provider models
  are explicitly configured; no stable model identifier is invented.
- No public release, pilot contact or external messaging is implied by writing release
  artifacts. Publishing and external results are recorded only if actually performed.

## Evidence available at start

- Existing suites: 8 + 5 passing tests on this Linux host.
- Bubblewrap smoke check: successful; Docker server and rootless Podman available.
- Cerebras key unset. OpenRouter key set (value never printed). No live paired result.
- Existing dirty changes span unrelated projects; they must not enter a demo freeze.
- Historical receipts report 173.9 s save-to-done, best direct loop 5.15 s, median
  client decode 360 tok/s and cold probe/patch 288/192 ms. Projections are not results.

## External gates

The following cannot be signed off by code or fixtures alone: two-OS CI execution,
three independently sourced real repositories at >=80% model repair acceptance,
paid/live paired benchmark n>=30 (including GPU baselines and stable models),
stranger install timing, external security review, and 5–10 developer pilot outcomes.
Record measured failures and missing prerequisites explicitly; scaffolding is not a
passing gate. Never substitute deterministic reference repairs for model acceptance.

## Rewritten execution prompt

Build ClawReflex into an installable Python beta, in sequential reviewable packages.
Preserve the working demo and independently reproduce each reported defect. Consolidate
verification, sandbox all generated execution, protect apply/revert, redact provider
inputs, and support configured repositories through isolated runs. Add bounded provider
execution, honest phase timings, OpenClaw actions, and reproducible release tooling.
Judge the result using zero escaped adversarial cases, 100 preserved concurrent saves,
independent RED/reference/GREEN checks, >=85% product coverage, >=70% engine mutation
score, paired n>=30 live latency receipts, fresh-install checks, and the <=60 s film.
Publish no unmeasured performance, adoption, cross-platform or security-review claim.
