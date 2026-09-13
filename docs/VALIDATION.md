# Validation record

Local branch: `codex/missions-trading-lab`, based on clean `release-prep`.
No deployment, merge, wallet connection, or real order was performed.

## Reproduced baseline defects

The read-only baseline reproduction script printed:

```
BASELINE verifier outage certified success: True
BASELINE disabled tool advertised: True
BASELINE exhausted executor returned ordinary text: True
```

Source inspection additionally confirmed awaited progress speech, an approval
announcement before cancellation cleanup, whole-step retries sharing evidence,
browser acknowledgements preceding terminal work, and background exceptions
published as done. Existing local logs contained no attributable mission failure
trace, so no specific historical incident is asserted.

## Automated checks

- 30 regression tests passed across mission reliability, simulator/API/provider
  behavior, persistence, data backfill, cancellation and dashboard recovery.
- Existing `test_smoke.py`: all checks passed; 24 skill modules loaded, 115
  declarations, no duplicates, handlers present, safety refusals preserved.
- `npx tsc --noEmit`: passed.
- Targeted ESLint for Trading Lab, provider, layout and mission panel: passed.
- `npm run build`: passed; `/trading` included in prerendered output.
- `git diff --check`: passed.
- Full `npm run lint`: eight existing React-effect errors and one existing unused
  variable warning in the wider UI. These were not suppressed or changed by this work.

The unit suites use temporary databases and mock network/model/browser behavior.
The optional OpenAI HTTP adapter was tested with a mocked model list and response,
including no tool access and `store:false`.

## Separate live checks

- Listed available Gemini models without displaying credentials.
- A harmless arithmetic mission completed planning, execution and verification
  with `gemini-2.5-flash`: mission done, step success.
- Gemini analyzed synthetic candles with a validated structured result: three
  observations, no veto, reported usage 5,191 tokens. Dollar cost unavailable.
  Initial live tests exposed SDK model-list and structured-schema incompatibilities;
  these were fixed. Invalid/partial responses correctly produced errors and vetoes.
- Coinbase returned 30 requested public historical BTC-USD candles with no gaps.

## Browser checks

Verified the rendered candlestick chart and TradingView attribution, thesis gating,
virtual order submission, pending state, next-candle fill, fees/balances, six-stage
offline explanation, stale labeling after replay, portfolio/analysis recovery after
reload, and Progress metrics. The full backend reported one shared socket client
with voice off. Current observation/backfill correctness was tested with mocked
data, not through a sustained live-feed soak test.

## Remaining limits

Live OpenAI generation, image interpretation by a live provider, microphone latency,
real browser missions with side effects, and long-running current-market operation
were not runtime-tested. Python cannot forcibly stop arbitrary synchronous handlers
already running in a thread; mission timeout/cancellation stops waiting and does not
retry the side effect. Provider costs may remain unknown, including cancellation.
Current observation uses explicit manual polling. Initial production builds require
network access for existing Google Fonts. Simulation liquidity assumptions are
documented in [TRADING_LAB.md](TRADING_LAB.md).

The dependency installer reported nine audit findings in the resolved frontend
dependency tree (two moderate, six high, one critical). A broad dependency upgrade
was not included; no automatic `npm audit fix --force` was run.

## Gemini defaults update — 2026-09-13

- 35 regression tests passed, including model migration, default Gemini routing, optional-provider availability and no cross-provider fallback.
- TypeScript, targeted ESLint, production build and git diff whitespace checks passed.
- Live Gemini 3.5 Flash: structured chart analysis validated locally, image recognition passed, tool-call round trip returned the supplied value.
- Live Gemini 3.5 Flash-Lite: JSON generation passed.
- Gemini 3.8 Flash appeared in the account model list but returned repeated 503 overload errors; 3.5 Flash is the verified working default.
- Browser: Gemini selected by default; OpenAI absent without configuration. Backend provider endpoint agreed.
- Voice model remains Gemini 3.1 Flash Live; microphone/audio were not retested in this update. Existing embedding vectors were preserved.
- See [Gemini model policy](GEMINI_MODELS.md) for official sources and role assignments.
