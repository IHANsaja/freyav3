# Trading workspace and Freya guide

Open `http://localhost:3000/trading` with the normal Freya server running. For development without microphone/desktop dependencies, run `python -m uvicorn core.trading.api:app --port 8000` and `npm run dev` in `freya-ui`.

The TradingView-inspired layout uses Lightweight Charts, not TradingView's proprietary terminal. It includes candlestick/line views, pan/zoom, EMA(20), volume, RSI(14), fill markers, chart fit, horizontal levels and two-click trendlines. Annotations are stored in this browser per session (50 maximum), with undo/clear. They do not submit orders. Market/timeframe/source selectors apply when starting a new session.

The ticket, replay controls and orders/positions/fills/journal/progress/analysis panels share the existing authoritative simulator. Record a thesis and invalidation, place a virtual order, then reveal eligible candles. Cancel pending orders in Orders. Play pauses for order submission and guide/analysis requests. Observation uses manually polled closed candles. No brokerage execution is added.

## Grounded help without screenshots

- Quick help is the default. Candles, EMA, RSI, balances, pending orders, drawings and getting started use local explanations with zero model requests.
- Gemini custom questions are explicit, read-only requests. They receive the selected visible candle, computed indicators, current account, recent orders/fills and workspace help. They cannot execute tools or access future candles. Replies show provider/token metadata and flag earlier revisions as historical.
- Independent practice requires a thesis before custom Gemini interpretation. Mechanical help remains available before the thesis.
- Custom requests use the shared quota limiter, a 45-second timeout, a 1,200-token output cap and `trading.max_guide_questions_per_session` (default 20). Failed/cancelled attempts consume this session budget. Successful identical snapshot/question responses are cached. Quick help remains available after the cap. Guide tokens appear on replies; existing Progress analysis totals exclude guide calls.
- Focused visible tabs publish session, panel and selected candle every 30 seconds and on selection/focus changes. `get_trading_lab_context` resolves this context for voice without vision. Context expires after 90 seconds. Multiple active sessions require an explicit session ID. Leaving the page releases focus; expiry covers abrupt browser termination.
- Voice still needs the normal Freya Live connection and consumes that model's normal usage. The context tool itself makes no model call. Restart Freya after updating to load the tool and prompt.

HTTP additions: `POST /trading/workspace`, `GET /trading/context?session_id=...`, `POST /trading/guide/{session_id}`. These follow the existing local server's access model.

## Validation

`python -m unittest test_scripts.test_trading_guide` covers local help, visibility, active-tab ambiguity/expiry, the independent gate, mocked Gemini caching/budget and API validation. Run `npx tsc --noEmit` and `npx eslint app/trading` in `freya-ui` for UI checks.

Live Gemini answer quality, Windows microphone/voice integration and upstream market-data availability require testing in the user's configured environment. Local browser verification uses sample data and local/offline help.

Verified on this branch: 72 Python tests passed (guide, simulator, quota, mission, CLI-first and related regressions), TypeScript passed, and trading UI lint passed. Chromium smoke testing passed thesis/order/fill/cancellation, rapid drawing anchors, annotation persistence across reload, chart controls, guide context lookup, replay playback, offline analysis, and desktop/mobile overflow checks with zero page runtime errors. Standalone mode was used, so the microphone/Live WebSocket path was not exercised.
