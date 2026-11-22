# Security

ClawReflex is an unreleased alpha undergoing security hardening. The original demo
allowed model-generated test code to execute on its host; `v0.1.0-demo` must only be
used with owned synthetic fixtures in a disposable environment.

Model outputs and repository contents are untrusted inputs. AST validation is defense
in depth, not an execution security boundary. Production execution must fail closed
when no supported OS sandbox is available. Provider credentials belong only in the
parent process and must never be mounted or inherited by test workers.

Use propose-only mode unless you have explicitly opted into automatic application.
Sending source to a hosted provider is a disclosure to that provider; local secret
scanning cannot identify every sensitive value. Do not send confidential repositories
without permission from their owner and an appropriate provider data agreement.

For a security report, use the hosting repository's private security advisory facility
when available. Include the version, sandbox backend, reproduction and observed impact.
Do not post credentials or private source in public issues. External security sign-off
remains a GA gate and has not been performed.

## Implemented boundary (2026-11-22)

`server.RepairRun` is the sole verification engine. `core.py` adapts its historical
Python API and `service.py` delegates its historical CLI. Generated tests use an
explicit AST node/call/import allowlist; private/dunder access, builtin reflection,
indirect calls, imported-module traversal, aliasing trusted names and mutation of
unittest internals are rejected before execution. Candidate modules use a conservative
stdlib API subset. This intentionally rejects unsupported Python patterns rather than
silently weakening validation. Not every Python repository is supported by that policy.

All test execution uses `sandbox.py`. On Linux, bubblewrap gets a new user, PID,
network, IPC and UTS namespace, dropped capabilities, read-only interpreter/runtime
mounts (`/usr`, `/lib`, `/lib64`, and an additional Python runtime prefix if needed),
a read-only per-execution `/work`, private `/tmp`, isolated `/proc` and minimal `/dev`.
There is no host `/home`, `/etc`, repository, SSH agent, Docker socket or credential
environment. Runtime installations themselves must be trusted: installed runtime files
are readable. CPU, address-space, file-size, fd and process limits are installed by the
trusted child wrapper before importing generated code. The parent imposes a wall timeout
and reads bounded output. No `preexec_fn` executes in the threaded parent.

The fallback is an unprivileged, read-only Docker/Podman container with no network,
dropped capabilities, no-new-privileges, resource limits and a read-only input mount.
Provision a Python image separately, inspect it and set
`CLAWREFLEX_SANDBOX_IMAGE=registry/image@sha256:<64 hex digest>`; the runner uses
`--pull=never`. A mutable image tag is rejected. macOS requires this container backend;
Windows requires a Linux environment such as WSL2 plus a supported sandbox. Absence or
failure of a sandbox rejects verification. There is no host-execution fallback.
The container backend and macOS atomic swap branch are not runtime-verified here.

## Threat model and review record

| Input or failure | Protection | Local evidence |
| --- | --- | --- |
| Model test reaches builtins or verifier internals | Strict node/import/call/attribute policy | 30 malicious payloads plus alias/module traversal cases rejected |
| Candidate or repository code reaches host | New namespaces, minimal mounts/env, no network, rlimits | Actual sandbox test cannot read a host marker, inherit a test secret, write host or input files, or connect externally |
| A crash, timeout or exception is called RED | Structured unittest counts, nonzero tests, failures >0 and errors ==0 | Assertion/error/pass/timeout tests |
| A probe fails on correct behavior | Trusted reference plus independent regression and held-out tests must pass | Golden fixture and custom-spec tests |
| Editor save races with apply | Content hash, atomic exchange, inspect displaced inode, rollback conflict, linked backups | 100 deliberately raced in-place/atomic editor saves preserved |
| Revert overwrites subsequent work | Expected applied-content hash and same exchange path | Newer save refuses revert |
| Repeated or competing tool requests | Per-run mutex, bounded HTTP threads, idempotency keys | Busy response and mismatched-key tests |
| Hostile web origin or local unauthenticated client | Loopback bind, Host/Origin checks, bearer auth on state and actions, size/rate/time bounds | HTTP contract tests |
| Source disclosure | Local redaction helper and propose default; provider callers must route all outgoing text through it | Redaction tests; transport integration is a later phase |

This is an internal engineering review, not external security sign-off. Runtime mounts,
container daemon security and arbitrary native dependencies remain external review items.
The AST policy is defense in depth; it is not a proof of Python language confinement.

## Apply and recovery semantics

Editor application is propose-only unless explicitly configured with `apply_mode='apply'`
or the server's `--apply` flag. Explicit Apply also requires a verified candidate. Source
that matches the secret scanner blocks application. Exploit tests and patches stay in the
private run directory; they never overwrite developer test files.

Apply checks the saved content hash, stages a same-filesystem file, and atomically swaps
it with the target (Linux `renameat2(RENAME_EXCHANGE)` or macOS `renamex_np(RENAME_SWAP)`).
The displaced inode is checked after the swap. Interference triggers a swap back and
retains both inodes; successful application retains the old inode as a `.bak`. Receipts
record backup/recovery paths and hashes. Unsupported primitives fail closed. The lock
coordinates ClawReflex instances; it does not pretend that editors honor advisory locks.

No filesystem API can serialize arbitrary future writes through another process's open
file descriptor. An editor writing an old fd after a rename writes the retained backup
inode; inspect the backup path in the receipt to recover it. A second editor save during
conflict rollback may also be retained in recovery rather than remain at the target path.
The tested claim is 100 preserved controlled interleavings, not universal linearizable
compare-and-swap against arbitrary programs. Keep propose-only mode when this limitation
is unacceptable. Hash-guarded undo refuses a target changed after the patch.

Run directories and retained backups contain source and test output. Store them in a
private workspace state directory (preferably under `.git`), review access controls,
and remove them deliberately after recovery is no longer needed. No automatic upload
or cleanup destroys those backups.

### Optional pre-warmed worker

`WarmWorker` launches the same OS sandbox once and forks a disposable child for each
verification. The parent executes only the trusted dispatcher as the private PID
namespace's PID 1. It disables dumpability before forking, so disposable children cannot
reopen its protocol descriptors or memory through `/proc`. Child stdin and unrelated
file descriptors are closed; rlimits apply before test discovery; timeout or excess output
kills the child. Descendants in the private PID namespace are killed and the private
16 MB `/tmp` is cleared before the next request. No source or reference is mounted from
the host, and candidates receive only their own request. Failure of the dispatcher or
cleanup fails closed. Tests bypass the AST policy to confirm host-file/environment hiding
and verify module and temporary-file state do not persist between requests. A regression
also checks that child access to dispatcher protocol pipes and memory is denied.

The warm worker currently supports self-contained unittest modules, not the repository
adapter's support-file protocol. Repository suites retain the cold sandbox path. Runtime
and external security review are still required; warm-worker timing does not establish
end-to-end latency or support for every Python package.
