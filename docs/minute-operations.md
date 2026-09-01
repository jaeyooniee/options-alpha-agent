# One-Minute Options Operations

## Purpose

This is a short-horizon paper-trading operating policy for the hackathon. It
does **not** mean one order per minute. The worker performs a read-only scan
once per minute and abstains unless every deterministic gate agrees.

## Entry policy

1. The worker runs `options-alpha shadow-cycle --underlying SPY` once per minute
   while the US equity market is open.
2. A 90-day daily-bar signal establishes the large direction: bullish or bearish.
3. The same cycle reads the latest 90 one-minute SPY bars. A new entry is eligible
   only after a short pullback/reversal: recorded 5-minute versus 20-minute EMA
   context, a 20-minute z-score discount/premium of at least 0.50 standard
   deviations, at least 21 completed minute bars, and a confirming one-minute
   rebound/rejection. The setup must
   agree with the daily direction.
4. New entries are permitted only from 09:45 through 15:30 America/New_York.
   The first 15 minutes and final 30 minutes are scan-only.
5. Before an AI call, the worker also requires fresh indicative option quotes,
   adequate open interest, acceptable spread, 2--10 DTE, defined loss, and all
   portfolio risk gates. Failed checks produce an auditable `NO_TRADE`.

This makes abstention the normal behavior. The AI provider is called only after
the deterministic daily/minute alignment gate, preventing a paid model call for
every one-minute scan.

## Validation protocol

Before any paper order is considered, run `options-alpha short-shadow`. It
accepts only audit events sourced from the Alpaca paper account plus indicative
option quotes. For each preview-ready cohort it finds the first fresh quote for
the exact same legs at 1, 5, and 15 minutes, allowing at most two minutes of
scheduling lag.

Entry is marked at the recorded debit. Alpaca-vs-local timestamp skew up to 60
seconds is tolerated; larger future timestamps are rejected. Exit is adverse:
long-leg bid minus
short-leg ask, floored at zero, with P&L floored at the defined maximum loss.
Midpoints, synthetic events, different contracts, and late marks do not count.
The initial review gate requires at least 10 closed 15-minute cohorts, at least
90% mark coverage, and positive mean conservative P&L. The command can only
recommend `REVIEW_FOR_NEXT_GATE`; it never authorizes or sends an order.

```powershell
.venv\Scripts\python -m options_alpha_agent short-shadow --minimum-cohorts 10
```

An empty result is expected before an open-market shadow session. It means
`CONTINUE_SHADOW`, not zero profitability and not permission to trade.

For a finite local market-session run, use the hardened shadow-only wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run-shadow-only.ps1 -Cycles 30 -IntervalSeconds 60
```

It forces execution off, paper approval off, and the kill switch on in the
child process before every one-minute cycle. It is a validation runner, not a
paper-order launcher.

## Position policy

- Current entry structures are only one-contract SPY call or put debit spreads;
  long options remain research-only comparators. Maximum loss is the paid net debit.
- The AI-independent exit policy reviews a 25% of maximum-loss profit target,
  a 35% of maximum-loss stop, a 15-minute holding cap, and a 15:45
  America/New_York session-close flatten instruction. Existing positions are
  reviewed before every new-entry decision; until the paper close adapter is
  completed, an exit instruction fails closed to manual review rather than
  placing a close order.
- The risk engine still applies per-trade, portfolio, drawdown, liquidity, DTE,
  and position-count limits. It is the only layer allowed to approve an order
  preview.
- An exact-leg inverse close preview is available in
  `src/options_alpha_agent/close_preview.py`. It requires fresh quotes for both
  legs, rejects a different contract or a non-positive executable credit, and
  always returns `sent=false`. Broker close submission remains separately gated
  until a real paper-fill lifecycle test is approved.

## Deployment boundary

For cloud operation, use a scheduler that invokes one short-lived worker every
minute and rely on the distributed run lock to prevent overlap. Do not run an
infinite loop on a personal PC. Cloud deployment and paper-order enablement are
separate approval-gated steps; this repository remains paper-only with
`TRADE_EXECUTION_ENABLED=false`, `PAPER_ORDER_APPROVED=false`, and the kill
switch enabled.

## Evidence standard

Every scan records whether it was market-closed, blocked for an existing-position
exit review before an AI call, rejected by risk, or produced a non-executing
preview. A minute scan is not a
claim of alpha or P&L. Only confirmed paper orders, fills, exits, and account
reconciliation may be reported as paper-trading activity.
