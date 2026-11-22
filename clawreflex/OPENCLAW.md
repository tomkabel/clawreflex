# OpenClaw integration and repair controls

The package targets OpenClaw 2026.11.x and Node >=20. Local validation used
OpenClaw 2026.11.6. No Discord or other external message has been sent by the tests.

From the repository:

```sh
openclaw plugins install ./clawreflex/openclaw
openclaw plugins validate --root clawreflex/openclaw --entry entry.mjs --json
```

Set `CLAWREFLEX_URL` to the workspace's loopback HTTP origin and `CLAWREFLEX_TOKEN`
to its private connection token before starting the gateway. The workspace writes a
private connection file in its state directory. Never put the token in a URL or a
committed config. Restart/reload the gateway after installation as directed by OpenClaw.
The package contains `skills/claw-reflex/SKILL.md`; it can also be installed through
`openclaw skills install ./clawreflex/openclaw/skills/claw-reflex`.

The agent receives only two optional tools: `clawreflex_probe` and `clawreflex_patch`.
Apply/Revert/Cancel are authorized user commands that bypass model generation:

```text
/clawreflex status [run-id]
/clawreflex history
/clawreflex apply [run-id]
/clawreflex revert [run-id]
/clawreflex cancel [run-id]
```

Workspace runs require the run ID; the one-run demo can omit it. A channel card is
plain evidence text with the diff, actual test counts, elapsed time and commands.
The local web monitor provides the clickable Apply/Revert/Cancel controls, run history
and filtering. Native Discord button callbacks are not implemented or advertised.
The commands return structured receipts; a verified proposal is never described as
an applied edit unless the apply receipt says so.

Open the local server URL, paste the token and connect. The browser keeps the token
only in memory, never in query strings, localStorage or telemetry. Apply/Revert actions
use idempotency keys. If a connection fails, inspect the recorded receipt; the UI does
not infer success from a timeout. History persists on disk and is restored read-only after restart; executable run state
is not restored. Cancel is cooperative with bounded provider/test deadlines.

Optional git mode creates a commit on a new `clawreflex/<run-id>` branch while leaving
the user's current branch, index and working files untouched:

```sh
python -m clawreflex.gitops --repo /path/to/repo --target module.py \
  --candidate /private/run/evidence/patch/candidate.py --expected-sha256 SAVED_SHA256 \
  --run-id RUN_ID --message 'Verified ClawReflex repair'
```

Use only a candidate with a passing verification receipt. This command refuses newer
saved bytes, staged work, unrelated tracked changes and secret-shaped content. It uses
git plumbing with hooks disabled and no checkout/filter execution. Review the branch
before explicitly merging or cherry-picking. It does not amend history or automatically
change your branch. Revert of an applied working-file patch uses the recorded snapshot;
revert refuses a newer save. A completed Apply/Revert cycle restores clean git status
when the target was clean before application.

Checks run locally: five Node contract tests; browser-driven authenticate/proposal/
Apply/Revert test; SDK metadata build and validation against installed OpenClaw.
A stranger's installation timing, live channel delivery and native channel button
interactions remain unmeasured.
