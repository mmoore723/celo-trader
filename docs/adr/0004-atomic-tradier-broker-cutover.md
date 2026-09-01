# ADR 0004: Atomic Tradier broker cutover

- Status: accepted; activation pending external readiness
- Date: 2026-09-01
- Supersedes: ADR 0001 when `broker_provider=tradier`

## Context

The existing paper system selects and prices option contracts with Tradier but
submits orders and manages positions with Alpaca. The 31-trade audit proved
that cross-feed price differences are large enough to obscure entry and exit
quality. Tradier sandbox prices are also delayed, so using the sandbox alone
would make a paper fill operationally unlike a current live decision.

## Decision

- One `broker_provider` setting owns account state, entries, exits,
  reconciliation, and emergency flattening. It cannot select different entry
  and exit brokers.
- In Tradier paper mode, a sandbox token submits simulated orders and a live
  Tradier token supplies current market data. Both are Tradier accounts; no
  Alpaca shadow execution path remains after activation.
- In Tradier live mode, the live Tradier token and live account own both market
  data and execution.
- Changing provider or paper/live mode is rejected while the bot is running.
- Tradier activation is atomic and fails closed unless read-only checks prove:
  the expected environment, account balance, positions, orders, market clock,
  positive bid/ask, and a timestamped quote no more than 120 seconds old.
- Every entry rechecks exact-contract quote freshness. Emergency exits may use
  market fallback, but a local trade is never marked closed without a
  confirmed broker fill or explicit proof that the broker position is absent.
- The default remains Alpaca until the readiness checks pass. No automatic
  credential migration or order is permitted.

## Consequences

- The application can be deployed before activation without interrupting the
  currently running Alpaca route.
- Tradier paper parity requires both sandbox and production tokens. This is a
  limitation of Tradier's delayed sandbox market data, not a simulated price.
- A Tradier balance or order-state outage prevents activation/start instead of
  falling back to invented buying power.
- Broker reconciliation and Journal labels follow the selected provider.

## Verification

- Unit tests cover market timestamp normalization, hourly aggregation, token
  separation, atomic entry/exit routing, delayed-data rejection, missing
  balance rejection, confirmed-fill emergency close behavior, and activation
  refusal before settings persistence.
- The complete backend and frontend suites must pass before deployment.
