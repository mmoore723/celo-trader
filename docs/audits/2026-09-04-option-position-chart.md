# Option-price position chart

Selecting an open position's ticker opens its exact option chart automatically.
Option price / Stock price switches preserve the stock setup chart. A position
picker distinguishes multiple contracts on a ticker; polling does not override
a manual stock choice. Calls and puts are both bought options here.

The chart uses recorded Tradier bid/ask observations, not synthesized candles.
Actual entry/exit fills are separate markers. Missing observations stay missing;
gaps over two minutes are not connected. Old capture times are labeled, and
capture time is not presented as exchange quote time. The price, one-contract
value (×100), and entire position value are separate. Open P&L uses the recorded
bid; closed P&L uses the immutable journal value. Values are before fees.

Green/red areas and totals are **reference** target/stop levels from the trade.
Missing or inverted levels are not invented. These are not editable orders and
do not alter the strategy's actual exit policy (including timed exits). No
broker, credential, order, strategy, risk, or schema changes are included.

`GET /api/trades/{id}/option-chart?mode=paper|live` requires a valid session and
reads only that user's DB, exact trade/account/mode and exact contract. Missing
account fails closed. It uses a read-only snapshot and never fetches brokerage
data or writes a DB. Read errors return a retryable 503 without private details.
At most the latest 5,000 source rows are returned; truncation is disclosed.

The existing chart palette supplies light/dark colors. Real HTML buttons support
keyboard selection; SVG includes a descriptive accessible name, and totals are
also readable text. Prices/history and reference caveats remain visible on
320px screens; secondary quote details are collapsed by default.

Validation: account/mode/user separation, expired/revoked authentication, malformed
IDs/modes, null/nonfinite/crossed/foreign/unknown-source quotes, closed-trade
boundaries, read-only behavior, TypeScript, frontend unit tests, production build,
and browser fixture checks for auto-selection, manual override after polling,
call/put identity, mobile/dark, stale/empty/error/retry and no page errors.
Fixtures are clearly marked UI test data and are excluded from the built app.
