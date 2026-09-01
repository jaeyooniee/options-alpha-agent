# Historical Underlying Walk-Forward Evidence

This is a reproducibility record for the underlying signal only. It is not an
options P&L backtest, a trading recommendation, or a claim of future returns.

## Dataset provenance

- Source: Alpaca MCP `alpaca_get_stock_bars`
- Symbol: SPY
- Feed: IEX
- Timeframe: 1Day
- Request: 90 calendar days, 60-record limit, ascending order, UTC timestamps
- Records: 60 bars from 2026-06-01 through 2026-08-25
- Local file: `data/spy.iex.daily.2026-06-01_2026-08-25.csv`
- SHA-256: `1fd5aea493f1c8ad36b166925add9fd7d6c742682a2f90c336112a4f6b738923`
- Retrieved: 2026-08-29 KST

The same capture was repeated for QQQ:

- Local file: `data/qqq.iex.daily.2026-06-01_2026-08-25.csv`
- SHA-256: `29a5e5d9af3e7e82b5e4ae8e284a15428ecfca205494d002225cf91006c39c87`
- Records: 60 bars from 2026-06-01 through 2026-08-25

The MCP response included OHLCV, trade count, and VWAP. The evaluator uses only
the timestamp and close columns. No option quotes, implied volatility, Greeks,
corporate-action adjustment flag, or fill assumption is inferred from this file.

## Reproduction

To capture a fresh, read-only IEX sample with the official SDK:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli capture-bars `
  --underlying SPY `
  --output data/underlying.capture.csv `
  --days 90 `
  --limit 60
```

The command writes only `timestamp,close`, prints a SHA-256 checksum, and
never reaches the order client.

To reproduce the recorded result:

```powershell
.venv\Scripts\python -m options_alpha_agent.cli walk-forward `
  --csv data/spy.iex.daily.2026-06-01_2026-08-25.csv `
  --horizon-bars 3 `
  --holdout-bars 10
```

Observed output at retrieval:

- Evaluation points: 28
- Holdout bars: 10
- Holdout evaluation points: 7
- Holdout directional hit rate: 0.3333333333333333
- Holdout mean signed return: -0.0032358388
- Directional points: 13
- Neutral points: 15
- Directional hit rate: 0.4615384615384615
- Mean forward return: 0.0018599825
- Mean signed signal return: -0.0024435619
- `lookahead_safe`: `true`
- `order_sent`: `false`

QQQ observed output with the same 3-bar horizon and 10-bar holdout:

- Evaluation points: 28
- Holdout evaluation points: 7
- Directional hit rate: 0.4
- Holdout directional hit rate: 0.25
- Mean signed signal return: -0.0036381173
- Holdout mean signed return: -0.0082050233
- `lookahead_safe`: `true`
- `order_sent`: `false`

The negative signed results on both underlyings are retained as a limitation.
They support the look-ahead and data-pipeline audit, not a profitability claim.
A separate versioned historical option-observation dataset, corporate-action
policy, and paper-fill reconciliation are required before selecting parameters
for paper execution.
