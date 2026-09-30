# Quota and reliability fixes

## Configure from your actual project

Open https://aistudio.google.com/rate-limit and select the project used by Freya.
Copy each text model's RPM into `quota.rpm_by_model` in your local config.
The default 10 RPM is a conservative application setting, **not** a claim about
Google's free tier. If your limit is lower, lower the setting before running.
Keys belonging to the same Google project share quota. Keep the same `quota.project`
label for those keys; Freya deliberately groups all keys by default.

```json
"quota": {
  "project": "default-project",
  "default_rpm": 10,
  "rpm_by_model": {},
  "default_tpm": 200000,
  "tpm_by_model": {},
  "default_rpd": 0,
  "rpd_by_model": {},
  "max_requests_per_mission": 60,
  "max_retries": 2,
  "max_retry_wait_s": 60
}
```

Copy the RPM, TPM and RPD of each text model you use from AI Studio into the
`*_by_model` maps. `default_rpd: 0` means "no local daily cap"; set `rpd_by_model`
to stop just short of your daily limit and move to the fallback model instead of
spending the last requests on refusals.

### What Google's limits count

From the [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) and
[token](https://ai.google.dev/gemini-api/docs/tokens) documentation:

- Limits apply **per project**, not per API key, and differ per model.
- **TPM counts input tokens**, and the system instruction and every tool
  declaration are input on every request.
- **RPD resets at midnight Pacific time**; RPM and TPM use a rolling minute.
- A token is about 4 characters.
- Free-tier numbers are not published as fixed values; AI Studio shows yours.

### Pacing (all background Gemini text calls)

Every call from sub-agents, missions, the browser agent, Trading Lab, ambient
watch, context suggestions, day summaries and memory extraction goes through
`core/quota.py`, which now paces three limits per (project, model):

| Limit | How it is kept |
| :--- | :--- |
| Requests / minute | One request every 60/RPM seconds (as before). |
| Input tokens / minute | Each request reserves its estimated input size in a rolling 60 s window before it is sent, and waits if it would not fit. The reservation is replaced by the exact `prompt_token_count` from the response. |
| Requests / day | Counted per Pacific day in `memory/quota_state.json` (gitignored), so restarts keep the count. After a daily 429, or once `rpd_by_model` is reached, the model is skipped straight to its fallback until the reset instead of spending a request per call to be refused. |

Per-minute 429s are still handled reactively as well; the estimate is local and
other programs can use the same project.

## Sub-agent token budget

Each step of a sub-agent (or mission step) re-sends the system prompt, all tool
declarations and the whole history. Configure under `agent_budget`:

```json
"agent_budget": {
  "max_context_tokens": 6000,
  "max_tokens_per_task": 150000,
  "keep_recent_results": 3,
  "max_tool_result_chars": 4000,
  "trimmed_result_chars": 800,
  "thinking_level": "low",
  "max_concurrent": 2
}
```

| Setting | Effect |
| :--- | :--- |
| `max_context_tokens` | When the next request would exceed it, tool results older than the newest `keep_recent_results` are cut to `trimmed_result_chars`. Only tool output is trimmed: in stateless function calling the model's own turns (with their thought signatures) must be sent back exactly as received ([thinking docs](https://ai.google.dev/gemini-api/docs/thinking)). Trimming happens in one batch, so the prefix stays stable for [implicit caching](https://ai.google.dev/gemini-api/docs/caching). |
| `max_tokens_per_task` | Input tokens one task may spend. When reached - or at the last step - the model is told to answer with what it has, with tools switched off, instead of failing with nothing. |
| `thinking_level` | Thinking tokens are billed as output. `low` suits tool-driven steps; override per agent with `sub_agents.<type>.thinking_level`. Dropped automatically for a model that does not support it. |
| `max_concurrent` | Agents running at once. More share the same per-minute quota, so extras wait in a queue (shown as "queued"). |

Measured on a simulated 8-step research task with 4,000-character tool results,
the defaults cut input tokens by about 17% (41k to 34k) and keep every request
under about 6k tokens, where the untrimmed history reaches about 9k; on a 12-step
task the saving is about 32% (87k to 59k). `check_agents` and the dashboard's
agent events report each job's requests and input tokens (with cached tokens).

A process-wide, thread-safe scheduler paces Gemini text/vision generation from
missions, nested browser agents, Trading Lab, ambient watch, context suggestions,
day summaries and memory extraction. SDK retries are disabled for these clients;
the scheduler owns bounded retries of generation only. Browser 429s no longer
immediately hop models. Explicit user model configuration remains respected.
Gemini Live audio and embedding APIs have separate paths and are not throttled here.

Structured quota details distinguish daily, token-per-minute and request-per-minute
errors. Unknown 429s remain unknown; they are never reported as proven daily exhaustion.
Temporary limits and selected 5xx responses use backoff with jitter and provider retry
delay. Long retry delays, daily exhaustion and the local mission request budget stop
execution. Completed tools are never automatically rerun. Terminal mission snapshots
are saved under `memory/missions/` for inspection; this is evidence preservation, not
an automatic resumable workflow. Restarting a failed mission may repeat actions and
must be preceded by inspecting its evidence.

The Mission panel shows local request attempts and reported total tokens. Counts
include nested browser generation and retries but exclude unreported token usage.
They are per-process estimates, not authoritative remaining Google quota, billing,
or a hard token/spending ceiling. The limiter proactively paces RPM; TPM is handled
reactively from provider errors. Other programs using your project can consume quota.
A configured outer model/tool timeout may terminate a long queue wait.

Research now prefers ordinary search/fetch before an AI browser loop. Final mission
reports are deterministic and consume no extra model call. Verification remains
mandatory; failure to verify never certifies success. Terminal failures finalize
active and pending step states, including quota errors.

## Trading corrections

Observation orders carry actual submission time and first become eligible in a
candle whose open is at or after submission. Thus manual polling never uses an
already-started candle to infer a pre-submission fill or trigger. Replay timing is
unchanged. Legacy pending observation orders without a submission timestamp are
rejected on backfill; resubmit deliberately after checking the account.

Failed/cancelled analysis attempts retain unique immutable audit IDs and count
against the session budget. An explicit retry can call the provider again on the
same snapshot. Successful results are cached, including retries of legacy cached
failures. No automatic provider retry is introduced into the OpenAI adapter.

## Verification

`python -m unittest test_scripts.test_quota_fixes -v` covers timing, successful
analysis cache recovery, quota classification, cancellation during pacing, shared
mission budgets, generation-only retries and mission terminal states. Existing
mission/trading regressions also run with mocked providers. For offline mission
unit tests, supply a dummy `GEMINI_API_KEY` value; no live requests are needed.
No live API quota, Windows microphone or long-running feed behavior is certified
by these tests. Provider documentation: https://ai.google.dev/gemini-api/docs/rate-limits
