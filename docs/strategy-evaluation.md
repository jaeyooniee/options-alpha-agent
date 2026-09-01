# Strategy Candidates and Evaluation

## Proposed competition agent

The leading design is a regime-adaptive, defined-risk index-options agent. A
daily deterministic signal sets the large direction, then a 90-bar one-minute
SPY pullback/reversal confirmation records 5/20 EMA context and requires a 20-minute
z-score discount/premium plus one-minute rebound/rejection before an AI call or
new-entry preview. The worker scans once per minute but may
enter only from 09:45 through 15:30 America/New_York. The AI layer summarizes
that aligned evidence into a structured proposal. For production, deterministic
controls allow only the matching debit spread; long options remain research-only
payoff comparators until separately validated:

| Regime | Candidate | Role |
|---|---|---|
| Bullish trend | Call debit spread | Bounded directional upside with reduced theta cost |
| Bearish trend | Put debit spread | Bounded downside exposure with reduced premium cost |
| Bullish/bearish research comparison only | Long call / long put | Defined-risk payoff comparators; never selected by the production agent |

The agent should abstain when no candidate clears edge, liquidity, data-freshness, and
risk thresholds. Abstention is a valid action and must be logged.

The production path uses only 2--10 DTE contracts and a 15-minute maximum holding
period. The broader 1--45 DTE range in snapshot and simulation utilities is
research-only and cannot create a production order preview.

## Evaluation ladder

1. **Static safety tests:** reject live mode, undefined loss, invalid quantity, stale
   data, wide spread, excessive risk, drawdown breach, and position-count breach.
2. **Signal integrity tests:** require enough history, remove future bars, and
   classify bullish/bearish/neutral regimes deterministically before AI reasoning.
3. **Reproducible scenarios:** compare all four structures on identical seeded price
   paths using `options-alpha simulate`. This validates payoff math and sensitivity;
   it is explicitly not evidence of historical edge.
4. **Underlying walk-forward test:** calibrate signals only on past SPY/QQQ bars and
   evaluate the next period with no look-ahead. The repository now provides
   `options-alpha walk-forward --csv <path>` and emits a machine-readable
   `lookahead_safe` result and supports a separate `--holdout-bars` reporting
   window. The repository includes a provenance-documented SPY IEX sample in
   `docs/historical-walk-forward.md`; its negative signed result is disclosed
   and is not called an options performance result.
5. **Historical option replay:** export a normalized CSV of Alpaca option
   observations and run `options-alpha replay --csv <path>`. The replay applies
   the same paper-only risk gates, quote-freshness rejection, adverse entry/exit
   slippage, and daily drawdown policy to every row. `data/replay.sample.csv` is a
   synthetic fixture for plumbing tests only; it is not a historical backtest.
6. **Scenario robustness sweep:** run `options-alpha robustness --paths 1000` to
   compare the same four strategies across fixed bullish, bearish, neutral,
   volatility, and holdout-style stress cases. The output reports average rank,
   positive-mean case count, return-on-risk stability, and worst 5th-percentile
   P&L. It is research-only and does not establish historical edge.
7. **One-minute paper shadow mode:** `run_shadow_cycle` first respects the Alpaca
   market clock, gathers the daily regime and one-minute pullback/reversal setup,
   and calls the AI only when both directions agree inside the entry window. An
   existing reconciled position blocks a new AI entry for exit review. It then reconstructs loss
   from the candidate chain and creates a proposed MLeg order preview while execution
   remains disabled. Read-only order/fill lifecycle reconciliation is implemented;
   live scheduled shadow runs and real paper-fill observations are still pending.
8. **Small-risk paper execution:** only after every go/no-go item is green and the
   user explicitly approves enabling paper execution.

The audit log can now be evaluated with
`options-alpha shadow-performance --horizon-hours 24`. This is a shadow-cohort
measurement, not broker P&L: it accepts only real Alpaca indicative evidence,
requires fresh quotes for the exact same legs, uses adverse bid/ask sides, and
reports missing future marks as unmarked rather than inventing a return. It now
also emits marked return on maximum loss and a closed-cohort drawdown sequence.
Expected shortfall at 5% is intentionally `null` until at least 20 closed
cohorts exist; this avoids presenting a tiny sample as a risk estimate.

For the production 15-minute claim, use the stricter
`options-alpha short-shadow --minimum-cohorts 10` evaluator. It reports
separate 1-, 5-, and 15-minute metrics from the same exact option legs, rejects
late or missing marks, and requires ten closed 15-minute cohorts plus 90%
coverage and positive conservative mean P&L before recommending review of the
next safety gate. This remains research evidence and does not approve paper
execution.

Real option observations can be accumulated with the immutable
`capture-option-snapshot` command and validated with `option-snapshot-check`.
The first 22-contract SPY snapshot is versioned, but no historical performance
claim is permitted until later snapshots supply matching exact-leg exit marks.

The repository now includes two exact-symbol SPY snapshots 581.99 seconds apart
and an `option-snapshot-compare` command. It verifies conservative quote-side
payoff behavior across long calls, long puts, and all valid debit-spread pairs.
Because there is no signal selection or open-interest history and the interval
is extremely short, the result remains quote-path evidence with
`not_backtest=true`, not historical edge.

## Selection metrics

- Net P&L and return on maximum loss
- Maximum drawdown and expected shortfall
- Win rate, payoff ratio, and profit factor
- Turnover, rejected-trade rate, and exposure time
- Fill sensitivity at midpoint, conservative limit, and adverse slippage
- Parameter stability across symbols, dates, volatility regimes, and seeds
- Audit completeness and reproducibility

## Current simulation status

The repository contains a deterministic Black–Scholes entry-price plus lognormal
terminal-path simulator with fixed seeds and conservative entry slippage. It compares
the four allowlisted structures on identical paths and reports mean/median P&L, win
rate, 5th percentile, expected shortfall, and return on maximum loss. It also contains
a normalized observation replay that reports accepted/rejected rows, realized P&L,
profit factor, drawdown, and gate reasons, plus a multi-regime robustness sweep for
parameter sensitivity. Neither tool should be labelled a historical backtest until a
versioned, provenance-documented Alpaca dataset is added.
