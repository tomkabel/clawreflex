# Release and GA checklist

Current version: 0.2.0a1, alpha. No package has been published and no GA sign-off exists.
Use the implementation ledger and raw evidence; do not replace missing results with
checkmarks. The demo baseline is locally tagged v0.1.0-demo.

## Local release candidate

1. Run the full Python suite, Ruff and expanded mypy checks.
2. Run the security corpus, actual sandbox tests, Apply/Revert and 100 forced
   concurrent-save interleavings. Review retained recovery limits.
3. Require >=85% product coverage and >=70% engine mutation score from receipts.
4. Run Node plugin contracts, real-browser monitor tests and OpenClaw metadata
   validation. No external message is necessary for these checks.
5. Build `python -m build`; inspect wheel/npm contents for secrets, missing resources
   and unnecessary runtime dependencies. Generate hashes and an SBOM.
6. Run `python -m clawreflex.release_check dist/clawreflex-0.2.0a1-py3-none-any.whl
   --output install-receipt.json` from the source tooling environment. It installs
   into a fresh venv and runs the actual offline sandbox repair check away from the
   checkout. This is same-host evidence; record OS and elapsed time.
7. Confirm the real film with ffprobe remains <=60 seconds and event/branding facts
   match CLAUDE.md. No synthetic UI or projection may be labelled measured evidence.
8. Review changes, changelog, license/notices and configuration migration. Create a
   scoped release commit only after preserving unrelated working changes.

## External beta gates

- [ ] Fresh Ubuntu and macOS CI runs pass the same suite with actual sandbox support.
- [ ] Independent reader installs and reaches a verified repair in <=10 minutes.
- [ ] >=80% provider-generated accepted repairs over the 20 pinned seeded tasks in
      three real repositories; scope and upstream-suite checks pass.
- [ ] Paired live n>=30 benchmark: Cerebras and two GPU baselines, matched initial
      requests, full reasoning replay, queue-separated timings, failures retained,
      bootstrap confidence intervals and raw hashed receipts.
- [ ] Quiet-endpoint p50 <=2 seconds, p95 <=5 seconds, or explicitly published failed
      targets and measured limitations. A trivial worker measurement is insufficient.
- [ ] Stable provider model ID, budget, operator disclosure/retention policy and source
      consent verified. No guessed model identifier or third-party retention claim.
- [ ] External security reviewer evaluates sandbox, malicious input, verification
      tampering, HTTP controls and file-application races against exact artifact hashes.

## Pilot and GA

Follow `../plans/clawreflex-product/PILOT.md`. Obtain 5–10 consented independent
participants for >=14 days; include failures and withdrawals. Run the local pilot
collector without uploading private source or identities. Require >=90% installs,
>=70% acceptance, zero false applies, >=99% crash-free sessions and p95 at target.
Audit the event provenance; metrics generated from fixtures do not qualify.

- [ ] All release-candidate and beta gates have actual receipts.
- [ ] All security findings are fixed/retested or explicitly accepted by an owner.
- [ ] Public API and migration policy frozen.
- [ ] Pilot metrics and external review accepted in writing.
- [ ] Maintainer approves exact wheel/npm hashes, changelog, SBOM and provenance.
- [ ] Authorized publication creates signed version tags and package registry releases.

Reviewer/signature: pending. Date: pending. Artifact/commit hashes: pending.
Publishing, recruiting participants and contacting reviewers are external actions;
no such actions were performed by writing this checklist.

## Retention and uninstall

Private state contains source/candidates, receipts and recovery snapshots. Keep it
local with restrictive permissions. There is no automatic telemetry upload or provider
retention guarantee. Inspect conflicts and retain backups until developer work is
reconciled. Remove a workspace's private state directory only when no run is active
and recovery data is no longer needed. Uninstall the CLI/plugin separately; deleting
a package does not silently delete recovery history.
