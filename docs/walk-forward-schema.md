# Underlying Walk-Forward Schema

`options-alpha walk-forward` consumes a research CSV with exactly the following
required columns:

```csv
timestamp,close
2026-01-02T21:00:00+00:00,100
```

Timestamps must include a timezone and close values must be positive. Rows are
sorted and duplicate timestamps are deduplicated before evaluation.

`data/underlying.sample.csv` is a synthetic fixture for exercising the command;
it is not historical market data and must not be used as a performance claim.

Pass `--holdout-bars N` to reserve the final N observed bars as a separate
out-of-sample reporting window. The holdout is reported independently from the
full rolling series; it does not turn the result into an options backtest.

For each evaluation point, the signal receives only bars at or before its
`as_of` timestamp. The bar at `horizon-bars` in the future is used only as the
evaluation target. The output is a research diagnostic, not a broker result or
historical performance claim. A real dataset must include provenance, market
calendar handling, corporate-action treatment, a recorded SHA-256 checksum, and a
separate holdout period. The CLI prints the checksum of the input CSV.
