# Market-Session Research Capture Plan

This protocol grows real Alpaca indicative option evidence without sending an
order or changing strategy parameters after seeing outcomes.

## Frozen protocol

- Underlyings: `SPY`, then `QQQ`
- Feed: Alpaca IEX underlying quote plus free indicative options feed
- Contract window: the existing ±2% strike window
- Quote age: no more than 300 seconds
- DTE policy: 1–45 days; use the nearest eligible weekly expiration consistently
- Session times: 5 minutes after open, 90 minutes after open, midday, and 15
  minutes before close
- Entry/liquidation convention: long ask and short bid at entry; long bid and
  short ask at liquidation
- Missing, stale, crossed, incomplete-Greeks, or different-leg observations:
  reject or leave unmarked; never impute a favorable price
- Strategy and signal parameters: frozen before the first capture of the day

The next Alpaca open observed by the live market-clock probe is
`2026-08-31 09:30 ET` (`2026-08-31 22:30 KST`). Suggested KST capture times for
that session are 22:35, 00:00, 02:00, and 04:45. Check the Alpaca clock again
before relying on these times because exchange calendars can change.

## One-shot capture

Run once for each symbol at each scheduled observation. The script creates a
new UTC-timestamped path, refuses overwrites through the underlying CLI, and
immediately runs the strict validator.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/capture-research-snapshot.ps1 -Underlying SPY -Expiration 2026-09-04
powershell -ExecutionPolicy Bypass -File scripts/capture-research-snapshot.ps1 -Underlying QQQ -Expiration 2026-09-04
```

This reads market data only. It neither calls the AI provider nor reaches an
order mutation endpoint.

## Evaluation after collection

1. Validate every file with `option-snapshot-check` and retain its SHA-256.
2. Match only exact OCC symbols across observation times.
3. Run `option-snapshot-compare` for short-horizon plumbing evidence.
4. Run the signal-selected `shadow-cycle` only after one provider inference is
   explicitly approved; record rejected and `NO_TRADE` decisions too.
5. Run `shadow-performance` after later exact-leg marks exist.
6. Report sample count, marked/unmarked count, net P&L, return on maximum loss,
   maximum drawdown, expected shortfall, and spread sensitivity.
7. Keep the short 2026-08-28 pair labelled `not_backtest=true`; do not merge it
   into a strategy-return claim without matching signal and OI provenance.

No collected result changes the first-order decision by itself. All items in
`docs/go-no-go-checklist.md` must still be green and the user must separately
approve paper execution.
