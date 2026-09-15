# Trading Lab research and practice tools

The root navigation strip is removed. Only the home HUD (`/`) uses a fixed `100dvh` frame with a scrolling content area; Trading Lab remains a scrolling workspace.

## Chart ranges and drawings

The range controls are **1Y, 1W, 1D, 1h and 1m** (one minute), plus All. They change the visible range of loaded, already revealed candles. They do not download a year of data or reveal future replay candles. Limited history and ranges shorter than one candle are labeled. Candle resolution is a separate session setting; 6-hour and daily candles join the existing minute/hour resolutions supported by [Coinbase candles](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles).

The existing drawing groups remain available. New controls add:

- OHLC magnet snapping for new anchors.
- Drawing object list with hide/show, lock/unlock and deletion. Locked drawings survive Clear and cannot be erased or edited until unlocked.
- Exact UTC time/price coordinate editing, colors and line widths.
- Undo and redo for local drawing edits, capped at 30 history entries. Incoming Freya drawing events reset local undo history to prevent stale restoration.
- Fibonacci fan and editable reward/risk ratios for position drawings.

This extends the existing tools toward familiar TradingView workflows, including [Fibonacci tools](https://www.tradingview.com/support/solutions/43000518158-fibonacci-retracement-drawing-tool/). It is not full TradingView parity: direct anchor dragging, custom Fibonacci levels and cross-device drawing synchronization are not included. Drawings and checklists are stored in the current browser.

## Current financial news

The News panel and Freya's `get_market_news` tool read dated headlines from CoinDesk, Cointelegraph and the Federal Reserve. No AI request is needed to load the panel. Source requests have a five-minute cache, a ten-second timeout, a one-MB response limit and a fixed HTTPS publisher allowlist. Errors are explicit; previously fetched results are labeled stale and empty failures never produce invented headlines. Failed sources are retried after one minute when requested again.

The panel refreshes every five minutes while open and offers a symbol filter. Asset matching uses title keywords; Federal Reserve releases are macro context. This is a headline feed, not comprehensive market coverage or automated sentiment scoring. Source dates and outbound article links are shown.

Historical replay requires explicitly choosing to show today's news, with a warning that it is outside the replay timeline. Current headlines are not injected into historical chart-analysis context. Freya can retrieve news when asked, with the same current-context label.

## Two beginner tools

1. **Practice position calculator:** editable entry, stop, target and hypothetical risk percentage. Calculates a cash-capped quantity and estimated reward/risk with session fees and slippage. The default 1% is an example. Copying a quantity only fills the order ticket; it never places an order or creates a stop. Gaps may exceed the estimate.
2. **Pre-trade checklist:** five questions covering thesis, order behavior, exits, costs/data freshness and independent reasoning. Saved per practice session in the browser; it is a self-review aid, not a trade signal.

## Verification

- TypeScript and focused ESLint checks.
- Python trading, guide, teacher, quota and news tests; news cases cover dated safe links, cache reuse, stale fallback and unavailable sources.
- Node helper tests for cost-aware sizing, invalid inputs, visible ranges and drawing validation.
- Browser smoke checks for ranges, drawing creation/editing/locks/undo/redo, checklist persistence, news replay opt-in, mobile overflow and root viewport sizing. Browser news rendering uses a labeled fixture; public RSS retrieval is checked separately.
- Native Windows microphone/voice execution is not exercised in the browser harness.
