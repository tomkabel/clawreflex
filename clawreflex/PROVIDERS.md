# Providers, budgets and measured benchmarks

The default workspace path now attaches a provider driver. Start with a configured
repository and its independent verification material, then explicitly consent to source
disclosure in `.clawreflex.toml`:

```toml
[workspace]
provider_consent = true
apply_mode = "propose"

[provider]
base_url = "https://api.cerebras.ai/v1"
model = "YOUR_ASSIGNED_STABLE_MODEL_ID"
key_env = "CEREBRAS_API_KEY"
stream = true
# Set reasoning_effort only after checking this model's capabilities.

[budget]
tokens = 4096
deadline_s = 60
```

Put the credential in the named environment variable, never in the TOML file or command
arguments. `clawreflex watch /path/to/repo` calls the configured endpoint after ordinary
saves. `--external-tools` leaves execution to explicit OpenClaw tool calls instead.
The historical `--demo` path retains the event's trial model configuration. Product
configuration has no guessed stable model and does not assume optional tool-choice,
parallel-tool or reasoning flags are supported.

Provider disclosure passes through the repository privacy filter. The model sees saved
source, public contract and the generated exploit's sanitized RED diagnostic. It never
receives reference or independent held-out diagnostics. Full assistant fields, including
`reasoning_content` and streamed tool calls, are replayed before the tool result. If a
sensitive value appears in assistant replay, continuation stops rather than altering or
silently dropping reasoning. Local receipts are private operational data and may contain
sanitized source. No provider retention promise is implied; operators must review their
provider's current terms.

One pooled connection is reused per provider client. SSE frames, split tool arguments,
reasoning fields, usage and `time_info` are retained. Responses and requests are bounded.
429 responses expose `queued`, honor numeric Retry-After with jittered fallback, and stop
at attempt/deadline limits. Queue refusal time and retry waits are recorded separately.
Cancel interrupts active socket I/O and retry waits. DNS resolution depends on the host
resolver; it can outlast cancellation before a socket exists. No successful apply is
possible after a cancelled or expired driver run.

`budget.tokens` is a **completion-token budget across both model turns**, enforced from
provider usage and decreasing `max_tokens`. Missing usage aborts before continuing.
This is not a monetary or total-billable-token ceiling: input tokenization, reasoning
accounting and pricing are provider-specific. Set provider account spend limits for a
hard monetary ceiling. The per-save deadline includes workspace queue age; repository
verification itself is bounded by its configured sandbox timeout, so a check already in
progress may finish before the driver notices cancellation. The file remains untouched.

Every run records per-turn request hashes, wall/queue time, TTFT, usage and server
`time_info`, plus probe/patch and workspace timings. Output token rates are distinct from
save-to-done latency. The warm-worker implementation and its measurements are documented
separately; repository adapters keep their independently sandboxed repository suites.

## Paired benchmark

Create a local JSON list with **explicit** endpoint/model/key-variable configuration.
Use `cerebras` and two independently identified GPU provider names. Run all endpoints
with the same model/weights and reasoning settings; verify actual backend identity from
provider receipts or dashboard. Labels alone do not establish GPU execution.

```json
[
  {"name":"cerebras","base_url":"https://api.cerebras.ai/v1","model":"YOUR_ASSIGNED_STABLE_MODEL_ID","key_env":"CEREBRAS_API_KEY"},
  {"name":"gpu-a","base_url":"https://YOUR_GPU_A_ENDPOINT/v1","model":"MATCHED_MODEL_ID","key_env":"GPU_A_API_KEY"},
  {"name":"gpu-b","base_url":"https://YOUR_GPU_B_ENDPOINT/v1","model":"MATCHED_MODEL_ID","key_env":"GPU_B_API_KEY"}
]
```

After configuring credentials and a provider-side spend limit:

```sh
clawreflex-bench --endpoints /private/endpoints.json --runs 30 --output /private/paired-results
# Optional isolated pre-warmed tool worker:
clawreflex-bench --endpoints /private/endpoints.json --runs 30 --warm --output /private/paired-warm
```

The benchmark rotates the three owned fixtures, uses matched initial request material,
randomizes provider order with a recorded deterministic seed, retains failures, and
writes raw turn receipts, rows, generated Markdown, paired bootstrap statistics and a
SHA-256 file manifest. Subsequent transcripts naturally differ with model responses.
The measurements cover **direct API + verification**, excluding workspace debounce,
snapshotting and OpenClaw. `full_user_targets_pass` remains false: a fast direct loop
cannot certify the requested full product save-to-done target.

`--only cerebras` is a single-endpoint diagnostic. The historical trial alias may be
overridden with `CEREBRAS_MODEL`; baseline diagnostics require
`CLAWREFLEX_BASELINE_MODEL`. No paired claim follows from those separate runs.
`--replay rows.json` regenerates summaries but forcibly marks every row as replay, so
recorded or synthetic inputs cannot satisfy live-evidence gates.

No live benchmark was performed during this implementation: Cerebras credentials and
stable provider configuration remain missing. The local provider tests run an actual
HTTP server and real sandboxed verification with deterministic responses. They validate
transport and gates, not provider speed, GPU identity or real model repair acceptance.
