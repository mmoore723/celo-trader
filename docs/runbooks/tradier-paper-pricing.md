# Tradier prices with paper orders

## What this configuration does

Celo can keep simulated order execution in Alpaca while using Tradier's
production endpoint as the authoritative source for current option chains and
exact-contract bid/ask prices.

This does **not** place an order in the funded Tradier account while all three
of these settings remain true:

- Broker: `Alpaca`
- Mode: `Paper`
- Signal-only mode: optional; it does not change price routing

The Tradier production token is used only by the market-data client in this
configuration. Alpaca's paper endpoint remains the order destination.

## Why the sandbox token could not price paper entries

Tradier's sandbox supports simulated orders but supplies delayed market data.
Tradier documents the sandbox as using delayed data, while its production
endpoint supplies real-time market data:

- <https://docs.tradier.com/docs/endpoints>
- <https://docs.tradier.com/docs/getting-started>

On September 2–3, 2026, the application received exact-contract quotes about
904–912 seconds old. The `stale_entry_quote` safeguard rejected them before an
order reached Alpaca. This was correct fail-closed behavior: accepting a
15-minute-old ask as a current paper entry would manufacture unrealistic fills
and contaminate strategy profit-factor and slippage analysis.

## Required credentials

In **Settings → API Credentials → Tradier**:

- Sandbox token: authenticates Tradier simulated orders only when Tradier is
  selected as the paper broker.
- Sandbox account ID: identifies the Tradier paper account.
- Live token: supplies current Tradier market prices; it is also reserved for a
  future explicitly approved switch to Tradier live execution.
- Live account ID: required only for live Tradier orders.

Never paste tokens into chat, logs, tickets, or source control. Celo stores
them encrypted and returns only masked values to the browser.

## Healthy verification

Before allowing paper entries, verify all of the following:

1. The selected broker is Alpaca and mode is Paper.
2. The Tradier production token authenticates against
   `https://api.tradier.com/v1`.
3. A current SPY quote has positive bid and ask values.
4. The quote includes a broker timestamp no more than 120 seconds old while
   the market is open.
5. The next qualified setup records an `authoritative_quote` event before any
   broker `submit_attempt`.

Expected failure meanings:

- `401 Unauthorized`: the saved production token is invalid, inactive,
  revoked, or was copied incorrectly. Generate/copy the Production Account
  Access token again from <https://web.tradier.com/user/api>.
- `stale_entry_quote`: authentication worked, but the quote timestamp is too
  old. Confirm the production endpoint/token is being used rather than the
  sandbox endpoint/token.
- `entry_quote_unavailable`: no valid exact-contract quote was returned. Keep
  entry blocked and investigate the upstream response; do not substitute a
  fabricated price.

## Rollback and safety rule

If live Tradier pricing becomes unavailable, leave the stale/missing-quote
safeguard enabled. The safe rollback is no new entries while collection and
diagnostics continue. Never restore trading by accepting delayed quotes.
