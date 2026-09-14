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
  "max_requests_per_mission": 60,
  "max_retries": 2,
  "max_retry_wait_s": 60
}
```

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
