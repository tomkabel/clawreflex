# External pilot and GA protocol

Status: not started. No external participants have been contacted or enrolled by this
implementation. No security reviewer has signed off. GA remains blocked on evidence.

Recruit 5–10 independent Python developers for at least 14 days. Obtain informed
consent before recording events; explain provider source handling and retention terms.
Give each participant a random pseudonym and store only its SHA-256 digest in metrics.
Keep the identity mapping outside this repository. Participation is voluntary and
withdrawal deletes local participant records. There is no background telemetry upload.

Record local JSONL events with `participant` (64-character hex digest), `event`
(`install`, `repair`, `session`), `success` (boolean), `consent: true`, and timezone-aware
`timestamp`. Repair events also require `accepted`, `false_apply` and `latency_ms`.
Do not include source, filenames, prompts, provider responses, email or credentials.
Every participant must have install, repair and session events. Include unsuccessful
installs, rejected repairs and crashes; do not select only successful events.

Run `python -m clawreflex.pilot pilot-events.jsonl --output pilot-summary.json`.
This computes install success >=90%, acceptance >=70%, zero false applies,
crash-free sessions >=99%, p95 <=5 seconds, 5–10 participants and 14 observed days.
The CLI always leaves external security sign-off pending. A maintainer must obtain a
written independent report and review the raw pilot evidence before release; a local
metrics function is not a substitute for that review.

The external security reviewer must evaluate the sandbox runtime mounts, network and
resource isolation, AST policy bypasses, malicious repository inputs, HTTP origin/auth,
apply/revert races and symlinks, privacy filtering, and supply chain. Record review
scope, exact commit/artifact hashes, findings, fixes, retest evidence and reviewer
approval. Any accepted residual risk needs an explicit owner and written rationale.

Before GA, freeze the public API, attach the live paired benchmark and cross-platform
install receipts, resolve security findings, and sign the release checklist. No metrics
or sign-off may be inferred from deterministic fixtures or the historical demo film.
