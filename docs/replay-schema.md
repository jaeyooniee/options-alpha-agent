# Normalized Replay Input

`options-alpha replay` is a research-only evaluator. It accepts a CSV of completed
option observations; it never calls Alpaca and never sends an order.

Required columns:

| Column | Meaning |
|---|---|
| `timestamp` | ISO-8601 timestamp with timezone |
| `underlying` | Uppercase ASCII symbol such as `SPY` |
| `strategy` | One of the four options-only strategies |
| `entry_debit_usd` | Total debit for one position at entry |
| `exit_value_usd` | Total conservative exit value for one position |
| `max_loss_usd` | Defined maximum loss for one position |
| `days_to_expiry` | DTE at entry |
| `bid_ask_spread_pct` | Worst leg spread fraction at entry |
| `min_open_interest` | Minimum OI across the legs |
| `defined_risk` | `true` only for bounded-loss structures |

Optional columns are `quantity`, `thesis`, `entry_quote_age_seconds`,
`exit_quote_age_seconds`, `entry_quote_fresh`, and `exit_quote_fresh`. Stale or
over-age entry/exit quotes are rejected before P&L is counted. Values are
multiplied by `quantity` only after the same deterministic risk gates used by the
paper path pass.

Example:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli replay `
  --csv data/replay.sample.csv `
  --entry-slippage-pct 0.03 `
  --exit-slippage-pct 0.03 `
  --max-quote-age-seconds 300
```

The replay applies the entry slippage percentage as an adverse cost increase and
the exit slippage percentage as an adverse proceeds reduction. These assumptions
are printed in the summary and are not a claim about actual fills.

The CLI prints a SHA-256 checksum for the input dataset. The sample is a synthetic
plumbing fixture. A competition-quality historical result must also include the
source period, Alpaca endpoint/feed, timestamp convention, quote freshness policy,
and fill/slippage assumption. Until those are versioned, reports must remain
labelled `research_only`, not `backtest`.

Use `capture-option-snapshot` to accumulate immutable real quote/IV/Greeks
observations. Snapshot rows are intentionally not accepted directly as replay
trades: a replay row requires both a defensible entry and a later exact-leg exit
mark plus the entry-time open-interest gate. This separation prevents a single
market snapshot from being mislabeled as completed P&L.
