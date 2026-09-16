# Gemini 3.8 Live and automatic Complex Tasks mode

Freya's default voice model is `gemini-3.8-live`. The fallback is `gemini-3.1-flash-live-preview`. Complex Tasks uses `gemini-3.8-live-extended-thinking` with high thinking depth. These are Live voice models; existing text models for missions, memory and chart analysis are unchanged.

## Using it

1. Update dependencies with `python -m pip install -r requirements.txt` (Google GenAI SDK 2.23.0 or newer is required).
2. Restart the backend and dashboard. Existing installations using the previous 3.1 default are upgraded once. Local paths, keys, voices, other modes and text-model pins are preserved. The migration marker lets later manual model selections remain selected.
3. Speak normally. Freya is instructed to call `switch_mode(complex_tasks)` before difficult debugging, multi-step reasoning, architecture or research that needs comparison and verification. Simple commands and casual chat stay on the normal model. This is model-directed routing; there is no additional classifier API request and no guarantee every subjective complexity judgment is correct.
4. You can also choose **Complex Tasks** in the mode tabs or ask Freya to switch. Ask her to stay in the mode if you want several complex tasks in succession. Otherwise she is instructed to return to Default after completing the task.

Automatic voice-driven switching retains the same transcript collector and reconnects the Live session with its recent conversation and tool outcomes. It never reuses a different model's resumption token. The original request continues after entering Complex Tasks. A mode switch is not a substitute for starting a requested mission. Repeated requests for the already active mode do not reconnect again.

The existing dashboard mode button still uses its normal full restart behavior; voice-directed switches use the new transcript-preserving handoff. Native microphone/speaker behavior needs a Windows check after pulling.

## Configuration

`config/freya_config.json` is local and untracked. The shipped example includes:

```json
"live": {
  "defaults_version": 1,
  "fallback_model": "gemini-3.1-flash-live-preview",
  "auto_complex_mode": true,
  "thinking_level": "high"
}
```

Set `auto_complex_mode` to false for manual switching only. Complex Tasks can override `thinking_level` in its mode definition: `low`, `medium` or `high`. `minimal` is rejected. Regular 3.8 Live omits thinking configuration altogether.

## Protocol and fallback

- Normal 3.8 Live explicitly uses blocking tool declarations for compatibility. Extended Thinking uses non-blocking declarations without response scheduling fields. Tool execution runs in a separate, serialized worker so the receive loop can keep processing speech, status and cancellations while preserving desktop action order.
- Spoken turn completion and interaction completion are tracked separately. Extended Thinking stays in the thinking state until `interaction_status=IDLE`; audio playback remains independent. Final audio bundled with a turn-complete frame is played. Proactive messages do not interrupt background reasoning just because a spoken filler ended.
- Unavailable models, rate/quota limits and service errors can trigger fallback. Normal order: **3.8 Live → 3.1 Live**. Complex order: **3.8 Extended Thinking → 3.8 Live → 3.1 Live**. A selected fallback remains in use for that selection until restart or a mode/model change, and is announced in the dashboard transcript/console. Existing bounded reconnect retries still apply if the final candidate fails.
- Authentication failures, malformed configuration and generic policy closures are not silently treated as successful fallback or normal session rotation. A shared exhausted project quota may affect every candidate; switching models does not create more quota.
- A handoff that could not connect can continue on a fallback. An uncertain task from an already connected session is not automatically replayed. Cancellation suppresses late tool responses; it cannot undo a desktop action that already executed.

## Verification

Offline tests cover setup compatibility, one-time migration, mode resolution, bounded fallback, preserving the transcript through handoff/fallback, clearing cross-model resumption tokens, streaming during a slow tool, final-frame audio, duplicate/cancelled calls, and Extended Thinking state transitions. No real Gemini call, paid quota or Windows audio device is used by these tests. Live model access depends on the user's Google project.

Official references checked September 16, 2026:

- [Gemini 3.8 Live migration](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live)
- [Gemini 3.8 Live Extended Thinking](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live-extended-thinking)
- [Thinking in the Live API](https://ai.google.dev/gemini-api/docs/live-api/thinking)
