# Versioned Alpaca Option Snapshot

This records the first two matching real option-market observations in the
repository. They are read-only snapshots, not completed trades, a historical
backtest, or a strategy P&L claim.

## Provenance

- Source: official Alpaca Codex MCP plugin
- Underlying quote tool: `alpaca_get_stock_latest_quote`
- Underlying feed: IEX
- Underlying: SPY
- Underlying quote timestamp: `2026-08-28T19:47:36.877102+00:00`
- Option tool: `alpaca_get_option_chain`
- Option feed: `indicative`
- Expiration: `2026-09-04`
- Strike range: 765–775 inclusive
- Records: 22 (11 calls, 11 puts)
- Option quote interval: `2026-08-28T19:48:00.922493+00:00` through
  `2026-08-28T19:48:04.057457+00:00`
- Local file: `data/options/spy.indicative.2026-08-28T1948Z.csv`
- SHA-256: `0b981c61850601d0eb91a0b2b88d3aad0b259c873f2d3a6dac31b2141e155841`
- Captured: 2026-08-29 KST

The same exact 22 symbols were captured again:

- Underlying quote timestamp: `2026-08-28T19:57:18.870903+00:00`
- Option quote interval: `2026-08-28T19:57:19.075443+00:00` through
  `2026-08-28T19:57:20.243743+00:00`
- Local file: `data/options/spy.indicative.2026-08-28T1957Z.csv`
- SHA-256: `3237f9dddda26fef251b730f05cd52586a1ecab25928e23f12181d2d70ec6098`

The file contains timestamps, underlying bid/ask, option bid/ask and sizes,
implied volatility, delta, gamma, theta, and vega. It contains no credentials,
account ID, order, position, or personal information.

## Validation

```powershell
.venv\Scripts\python -m options_alpha_agent.cli option-snapshot-check `
  --csv data/options/spy.indicative.2026-08-28T1948Z.csv
```

The validator requires the exact schema, timezone-aware timestamps, valid OCC
symbols, one internally consistent underlying quote, non-crossed positive
markets, finite IV/Greeks, valid delta bounds, non-negative gamma/vega, and no
duplicate symbols. It prints the dataset hash and always reports
`order_sent=false`.

Future snapshots can be captured without manually transforming MCP output:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli capture-option-snapshot `
  --underlying SPY `
  --expiration 2026-09-04 `
  --strike-window-pct 0.02 `
  --max-age-seconds 300 `
  --output data/options/spy.indicative.next.csv
```

The command is read-only and refuses to overwrite an existing file. The output
must use a new timestamped filename for each observation. It accepts only a
1–45 DTE expiration, fresh IEX underlying quote, fresh indicative option
quotes, complete IV/Greeks, valid OCC symbols, and internally consistent rows.

The exact-symbol quote path is reproducible with:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli option-snapshot-compare `
  --entry data/options/spy.indicative.2026-08-28T1948Z.csv `
  --exit data/options/spy.indicative.2026-08-28T1957Z.csv
```

Observed interval: 581.993801 seconds. SPY midpoint moved from 769.22 to
769.82 (+0.0007800). Entry values use long ask/short bid; later liquidation
uses long bid/short ask. The 11 long-call observations were positive over this
brief upward move, while the 11 long-put observations were negative. Debit
spread results include all valid strike pairs, not a selected strategy. The
output fixes `selection_edge_claimed=false`, `open_interest_available=false`,
and `not_backtest=true`.

## Limitations and next observation

The MCP chain payload does not include contract open interest, so these snapshots
cannot independently satisfy the live liquidity gate or reconstruct the exact
candidate catalog. The second observation permits a short quote-path check but
not a strategy backtest. Multiple observations across dates and regimes, plus
entry-time open interest and signal provenance, are required before the
normalized replay can be called historical evidence.
