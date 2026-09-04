# Tradier prices with paper orders

## What this configuration does

Celo can keep simulated order execution in Alpaca while using Tradier's
production endpoint as the authoritative source for current option chains and
exact-contract bid/ask prices.

This does **not** place an order in the funded Tradier account while both
of these settings remain true:

- Broker: `Alpaca`
- Mode: `Paper`

Signal-only mode is optional; it does not change price routing.

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

- With Alpaca selected, only the Production token field is needed here.
  It supplies current Tradier market prices; orders stay with Alpaca.
- Sandbox token and account ID fields appear only when the saved broker is
  Tradier and the saved mode is Paper. They authenticate simulated orders,
  not the production market-data feed.
- Live account ID appears only when the saved broker is Tradier Live.

Hiding unused fields does not remove their saved credentials. Saving a token
does not switch the broker or change Paper to Live.

Never paste tokens into chat, logs, tickets, or source control. Celo stores
them encrypted and returns only masked values to the browser.

### Masked values in Settings

Settings never retrieves a complete stored secret. A value such as
`abcd…wxyz` means the credential is saved; it is not the token stored on the
server. Secret inputs load empty and show that mask only as placeholder text.
Entering a value replaces that one credential. Leaving it empty and saving a
different field preserves the original encrypted value.

The API also rejects `…`, bullet, asterisk, and `set` placeholders before any
credential write. This protects credentials when an older cached frontend or
password manager submits display-only text.

## Healthy verification

Before allowing paper entries, verify all of the following:

1. The selected broker is Alpaca and mode is Paper.
2. The Tradier production token authenticates against
   `https://api.tradier.com/v1`.
3. The selected option contract's exact quote has positive bid and ask values.
4. That option quote includes a broker timestamp no more than 120 seconds old while
   the market is open.
5. The next qualified setup records an `authoritative_quote` event before any
   broker `submit_attempt`.

The Network tab separates **Current connections** from **Event history**.
Current connections refresh every minute while that tab is open and show the
check time in Eastern time. A failed refresh, missing timestamp, or check older
than two minutes must not display a cached green connection as current. Old
errors remain in the event history; they do not by themselves mean the token
is still failing. Unused broker rows are hidden, not removed from server checks.

The connection endpoint is an authentication/reachability check, not proof of
an executable option quote or an order fill. Its production-token validator
currently probes a stock quote. The entry pipeline separately checks the exact
option quote and its age. A green connection after hours does not make a closing
quote fresh enough for a new entry.

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

See [September 3 audit](../audits/2026-09-03-paper-entry-followup.md) for the
post-token-repair evidence, offline regression coverage, and remaining checks.
