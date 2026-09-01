# Read-only Monitoring and P&L

`options-alpha monitor` performs a paper-account reconciliation without calling
any order mutation endpoint. It reads account equity/cash/buying power, order
status counts, open positions, and position-level unrealized P&L. The snapshot is
written as an `account_reconciliation` event into the same hash-chained audit log.

The command is intentionally conservative:

- Existing positions consume the full configured portfolio-risk budget until their
  individual defined-risk ledger is available.
- Account-level day P&L is `equity - last_equity`; it is not labelled realized P&L.
- Account IDs, API keys, and secrets are never included in the public JSON output.
- A reconciliation failure is an error, not permission to trade.

The scheduled `shadow-cycle` uses this same reconciliation snapshot before it
collects new option evidence. A complete competition deployment still needs a
durable fill/position ledger and an external persistent audit sink because the
local filesystem of a disposable worker is not durable.

`options-alpha shadow-performance --horizon-hours 24` adds a separate,
non-executing research view. It reconstructs virtual cohorts from verified
`shadow_risk_decision` events only when the source is
`alpaca_paper_contracts+indicative_options`. Entry is the recorded conservative
debit (long ask minus short bid); a later exact-leg mark uses long bid minus
short ask and is floored at zero. Stale, synthetic, malformed, and different-leg
events cannot produce P&L. The dashboard exposes only aggregate cohort counts
and marked P&L; detailed option symbols stay out of its API response.

For the short-horizon operating window, `options-alpha short-shadow
--minimum-cohorts 10` evaluates the same audit chain at 1, 5, and 15 minutes.
It requires fresh quote timestamps for both exact legs, allows at most two
minutes of scheduler lag, and remains research-only with `order_sent=false`.
