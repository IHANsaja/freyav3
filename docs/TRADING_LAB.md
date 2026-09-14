# Freya Trading Lab and mission reliability

## Launch

From `F:\Projects\Freya\freyav3`:

```powershell
.\venv\Scripts\python.exe server.py
```

In a second PowerShell:

```powershell
Set-Location F:\Projects\Freya\freyav3\freya-ui
npm install
npm run dev
```

Open <http://localhost:3000/trading>. The regular server provides the shared voice
socket. Do not press START FREYA unless you want to start your microphone session.
For practice without audio/desktop dependencies, replace `server.py` with:

```powershell
.\venv\Scripts\python.exe -m uvicorn core.trading.api:app --host 127.0.0.1 --port 8000
```

The standalone service supports all Trading Lab HTTP routes, but has no Freya
voice/socket endpoints. Use the regular server for cross-client events and voice.
Only run one backend on port 8000. An initial frontend production build needs
network access for the project's existing Google Fonts; built assets are local.

## Verify the initial practice flow

1. Start sample replay. Choose BTC-USD or ETH-USD, 15 minutes or 1 hour.
2. Record a thesis and invalidation. In independent practice, analysis and orders
   are unavailable until the thesis is saved. Coached practice permits analysis first.
3. Submit a virtual buy for `0.01`. Confirm it is pending and cash is reserved.
4. Advance one candle. Inspect the fill, fee, position, cash and order marker.
5. Choose Offline lesson and Explain decision. Inspect the six stages and snapshot.
6. Advance again: the old explanation is labelled stale. Reload: the account and
   latest explanation recover from SQLite without resubmitting any command.
7. Open Progress to record a self-assessed plan-adherence review, then Journal.
8. Reset creates another account with $10,000. Old decisions remain in Journal;
   a session link reopens the old account.

## Simulation contract

- All prices, quantities, cash, fees and reservations use Python Decimal. JSON
  money values are strings. Indicators use floating point, never account math.
- SQLite `BEGIN IMMEDIATE` serializes mutations. Each command requires a revision
  and unique idempotency key. An identical retry returns its original response;
  a changed request with the same key, or stale revision, is rejected.
- Full account state (orders, fills, ledger, portfolio and unrevealed data) is
  persisted atomically in the session row. Analyses and journal are separate
  tables, protected against update/delete by SQLite triggers. This is local audit
  history, not tamper-proof storage against a database administrator.
- The server sends only revealed candles. Replay starts with 30 visible candles
  from a 500-candle deterministic synthetic series, clearly labelled as sample
  data. Both the chart and immutable AI snapshot use the same visible prefix.
- Market orders execute at the *next* candle open, with adverse slippage and fees.
  Buy reservations use the visible reference price plus costs. If a gap makes a
  fill unaffordable after other reservations, the order is rejected in full.
- Limits and stops are eligible only after submission. Limits improve to a better
  gap open and never execute worse than their limit. Stops gap to the worse open.
- A sell bracket reserves one position quantity, with a stop below a target.
  If both are touched, the stop wins and the fill is marked ambiguous, even if
  an alternative intrabar path might have hit the target first.
- No partial fills, order book, queue priority or market impact is modeled.
  A touched price assumes sufficient liquidity. Fees and slippage are configured
  per account at creation; changing configuration cannot rewrite old fills.
- Missing time intervals are not fabricated. A missing interval rejects eligible
  orders rather than guessing their execution. Visible gaps veto new orders.
- Reset is a new session, not deletion. Spot positions cannot become short;
  multiple sell orders cannot reserve the same quantity.
- EMA(20) begins at SMA of the first 20 closes. Wilder RSI(14) begins after 14
  close changes; a flat series yields 50. Wilder ATR(14) begins after 14 true
  ranges (first range is high minus low). Earlier indicator values are null.
- Candle timestamps/IDs identify the candle *open*. Snapshot `as_of` is the end
  of the last visible candle. Sample data is educational, not historical earnings.

## Analysis, risk and budgets

Scout captures an immutable visible snapshot. Data validator checks OHLCV and time
continuity. Analyst/Skeptic supplies observations with candle evidence, zones,
contrasting scenarios, invalidation and a lesson. Risk checker retains any data
or analysis veto. Coach explains; Recorder appends the audit. These are visible
responsibility stages, not six independently running LLMs. Deterministic code owns
validation, balances and execution; providers receive **no tools**.

The code-computed OHLCV/indicators are measured facts; model observations, zones
and scenarios are interpretations to check against their cited candles. No model
confidence score is presented as a probability of profit. A model cannot override
the execution service's data, balance or reservation checks.

Gemini is the default for the UI, API and voice analysis tool. The default
`trading.gemini_model` is `gemini-3.5-flash`; the existing `GEMINI_API_KEY`
is sufficient. Optional agent/memory keys still fall back to that main key.
Offline lessons are an explicit choice, cost zero and use no network or credentials. The adapter checks the account's available models before generation.
OpenAI is optional: set backend `OPENAI_API_KEY` and `trading.openai_model` to an ID
returned by that API account, then explicitly select OpenAI. Its UI option is hidden
until both are configured. Gemini errors never route to another provider. A ChatGPT subscription is not an API key or credit.
No API credentials are included in browser requests or snapshots.

The default per-session budget is 20 distinct analyses, including errors and
cancelled attempts. Identical provider/model/prompt/image/snapshot requests are
cached. Generation has a 45-second timeout and bounded output tokens. Automatic
provider retries are deliberately disabled, preventing surprise repeated costs.
Invalid, truncated, empty, or out-of-snapshot evidence produces an analysis error
and veto. Usage tokens are recorded when returned; unavailable billed dollar cost
is shown as unavailable, never estimated without pricing data. Cancelling stops
the local request; a provider may still bill work already accepted.

Optional user-selected PNG/JPEG chart images are limited to 2 MB and 16 megapixels,
validated on the backend. Image text is untrusted data; image-derived levels are
labelled approximate. No desktop capture is performed. The server cannot know
whether a user-selected image itself contains later data; independent replay
integrity therefore applies to server candles, not arbitrary uploaded images.

## Historical data and current observation

Load Coinbase history requests 500 candle intervals from the selected date. The
read-only Exchange adapter paginates at 299 intervals (within the 300-candle limit),
sorts and deduplicates timestamps, and reports missing intervals. It never invents
traded candles for empty intervals.

Markets: BTC, ETH, SOL, XRP, DOGE, ADA, AVAX, LINK and LTC against USD, on
1m, 5m, 15m or 1h candles. All data is Coinbase's public API; no key is needed.

The sidebar and header stream tick-by-tick prices from Coinbase's public
WebSocket feed in the browser; `GET /trading/live` is polled every 5 s as a
fallback and so the backend (and Freya) know the price. Live sessions draw the
still-forming candle from `GET /trading/live/candle`, updated with each tick.
Live prices and the forming candle are display only and never drive fills.

## Freya as a teacher

Freya teaches in plain words and assumes no prior knowledge. Her progress notes
about the learner live in long-term memory as one `fact` item, "Trading knowledge
profile" (level, concepts understood, struggles, current topic, notes), managed by
`core/trading/learner.py`. Voice tools: `get_trading_learner_profile` and
`update_trading_learner_profile`; she updates it as understanding grows, so later
lessons build on earlier ones. Edit or delete it in the Memory panel.

The page includes a compact copy of the chart drawings in each workspace sync
(brush strokes keep only start/end), so `get_trading_lab_context` lists the
user's drawings and hers. `draw_on_chart` validates kind and point count, snaps
times to the candle interval and emits a `trading` `draw` event; the page adds it
in violet as Freya's drawing and saves it with the session's drawings.
`clear_my_drawings` removes only hers (limit 30 on a chart).

## Talking with Freya

Talk to Freya (header) or Talk with Freya (right panel) starts the normal voice
session; the microphone and speakers are those of the machine running server.py.
The page reports its workspace every 20 s and whenever voice starts. The first
report during a voice session injects a one-time briefing, so Freya acknowledges
the open chart, then answers later questions via `get_trading_lab_context`
(recent candles, market summary, indicators, live price, orders). No screenshots
are used. The typed Ask Freya guide was replaced by this voice panel; the
`/trading/guide` HTTP route remains for API use.

Live market (observation) creates a **separate** virtual account using closed
Coinbase candles. The page polls for newly closed candles every 15 s while
visible; Refresh now polls immediately. A poll before the next candle closes is a
no-op. Low-volume markets can have 1m intervals with no trades, which fail closed
as gaps; prefer BTC/ETH or a longer timeframe there. After two candle intervals
without fresh data, new orders are refused as stale. Backfill is deduplicated;
missing intervals fail closed without simulated executions across unknown time.
Observation accounts cannot advance with replay controls. A long outage beyond
the bounded historical range requires a new observation session.

## Configuration

`config/freya_config.example.json` documents `trading.enabled`, `fee_rate`,
`slippage_rate`, provider model IDs, `analysis_timeout_s` and
`max_analyses_per_session`. Existing installs receive an in-memory enabled default
for this simulation-only skill; their config files are not rewritten. Explicit
`trading.enabled: false` disables voice tools and HTTP services.

Voice tools: `open_trading_lab`, `record_trading_thesis`, `analyze_chart`,
`paper_order`, `advance_replay`, `get_paper_portfolio`, `review_trades`.
Voice and UI use the same service. Live voice chart analysis is scheduled in the
background; it does not block the voice receive loop. It has no order authority.

The shared route-level socket receives small trading invalidations with session,
sequence and revision. The client fetches authoritative state after reconnect.
Large candle histories never enter the event replay buffer. Slow dashboard clients
have bounded queues and are disconnected rather than blocking voice events.

## Mission fixes and evidence

`python -m test_scripts.reproduce_mission_baseline` reads the original
`release-prep` source and reproduces, without network/tools:

- Verifier exception returned `verified=True`.
- Filtered declaration output was discarded, advertising a disabled tool.
- An exhausted executor returned an ordinary success-shaped string.

The supplied local logs did not contain an attributable mission failure trace;
these are reproduced code defects, not a claim about a specific past user run.
Source inspection additionally confirmed whole-step retries, awaited speech,
asynchronous browser acknowledgements, and agent failures labelled done.

Planner menus and executor allowlists now share filtered declarations (including
the legacy terminal tool). Dispatch enforces skill gates. Executor errors,
exhaustion, denial, timeout and verification error cannot certify completion.
Mission speech is independent and bounded. Approval cancellation cleans pending
requests and timeout tasks. Worker tools are marshalled to the owning loop for
approval/event ownership. Browser tasks are awaited by background callers.

Automatic whole-step execution retries are disabled. This intentionally favors
stopping with evidence over duplicating side effects. A verifier error requires
inspection, never a rerun of the completed write. Tool evidence and longer prior
step summaries preserve returned artifact paths between steps. Arbitrary synchronous
Python handlers already executing in a thread cannot be forcibly killed by asyncio;
a timeout cancels waiting, not necessarily the underlying side effect. Inspect
evidence before manually retrying such a step.

## Validation commands

```powershell
.\venv\Scripts\python.exe -m test_scripts.reproduce_mission_baseline
.\venv\Scripts\python.exe -m unittest test_scripts.test_mission_reliability test_scripts.test_trading_extended test_scripts.test_dashboard_recovery -v
.\venv\Scripts\python.exe test_scripts/test_smoke.py
Set-Location freya-ui
npx tsc --noEmit
npx eslint app/trading app/components/FreyaSocketProvider.tsx app/layout.tsx app/components/MissionPanel.tsx
npm run lint
npm run build
```

The regression suites use temporary databases and mocked model/browser/data calls.
The final suite contains 30 passing tests; the existing smoke suite also passes.
Actual Coinbase historical fetch, a small Gemini mission, and Gemini analysis of
synthetic data were also exercised separately. OpenAI, live microphone latency,
real browser side effects and continuous live-market operation are not certified
by those mocked tests. Full-repository lint has existing React-effect violations
outside this work; the new Trading Lab files pass targeted lint.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for pinned inspiration and sources.
