# First Paper Order: Go / No-Go Checklist

The current decision is **NO-GO**. `TRADE_EXECUTION_ENABLED=false`,
`PAPER_ORDER_APPROVED=false`, and `TRADING_KILL_SWITCH=true` remain mandatory.

## Account and infrastructure

- [x] Alpaca credentials are present without being printed.
- [x] Trading client is hard-coded to `paper=True`.
- [x] Account is ACTIVE and not blocked.
- [x] New account has exactly $100,000 equity and cash.
- [x] Order history, filled-order history, and open positions are all zero.
- [x] Options approved level and trading level are both 3.
- [x] Free indicative option chain, quote, IV, and Greeks are readable.
- [x] Alpaca market-clock gate skips market data and AI calls when the market is closed.
- [x] Alpaca Codex plugin market-data call is verified.
- [ ] Production worker is deployed with paper-only secrets and a distributed run lock;
  the local atomic worker lock is implemented.
- [ ] Persistent audit storage and dashboard health endpoint are verified.

## Strategy and validation

- [x] Options-only, defined-risk allowlist exists.
- [x] Reproducible scenario simulator exists and is explicitly labelled not a backtest.
- [x] Historical underlying walk-forward test has no look-ahead leakage; dataset hash and negative limitation are recorded.
- [x] Replay and shadow-cohort engines include spread, stale quote, exact-leg, and
  adverse-fill assumptions; synthetic evidence cannot count as performance.
- [x] Two matching real Alpaca indicative option snapshots are versioned with
  quote, IV, Greeks, strict schema validation, provenance, and SHA-256.
- [x] Exact-symbol quote-path comparison uses conservative executable sides and
  is explicitly marked `not_backtest` with no selection-edge claim.
- [x] A repeatable SDK capture command enforces fresh quotes, 1–45 DTE, immutable
  output paths, complete IV/Greeks, and `order_sent=false`.
- [ ] A versioned historical option-observation dataset supplies enough real entry/exit
  marks for a statistically useful replay.
- [x] Reproducible multi-regime robustness sweep covers all four allowlisted strategies.
- [ ] Strategy parameters pass robustness and holdout tests.
- [x] Entry, exit, expiry, assignment, and partial-fill behavior have deterministic
  policies/tests; assignment remains manual review and broker close wiring is gated.
- [x] Synthetic proposals run through a complete non-executing MLeg order-construction dry run.
- [x] Live paper-account reconciliation and market-clock closure drive the full
  `NO_TRADE` → risk-denied → execution-disabled path without an AI call or order.
- [x] Short-horizon shadow evaluator matches exact legs and quote timestamps at
  1/5/15 minutes, uses adverse bid/ask P&L, and requires 10 real 15-minute
  cohorts plus 90% coverage before the next review gate.
- [ ] Live Alpaca market evidence drives the same shadow path with freshness and fill assumptions.

## AI and deterministic control

- [x] Selected Featherless model credential is configured locally without exposing its value.
- [x] AI output uses an exact strict schema and is rejected or converted to `NO_TRADE` on validation failure.
- [x] AI proposals below the configured confidence floor are rejected before order-preview construction.
- [x] The AI boundary records evidence, provider/model metadata, prompt/response hashes,
  proposal, rejected alternatives, usage, estimated cost, and `order_sent=false`.
- [ ] The complete market-evidence, deterministic risk-decision, order-request, fill,
  and P&L trace is verified end to end.
- [x] AI cannot call the broker directly or override deterministic gates; broker imports
  and execution flags live outside the AI module and are independently tested.
- [x] Kill switch, stale-data gate, duplicate-order prevention, and idempotent client
  order IDs pass fault-injection tests.
- [x] AI-independent exit policy covers profit, stop-loss, expiry, and stale-quote
  manual review; exact-leg inverse close preview construction is tested and
  remains `sent=false`.
- [ ] Broker close-order wiring and a real paper fill/close lifecycle test are
  still gated and pending.

## Final authorization

- [ ] All tests, lint, doctor, data probe, simulation, and shadow runs are green in the
  exact deployment image.
- [ ] Proposed first order is a bounded-loss options order within every configured cap.
- [ ] User reviews the final dry-run payload and explicitly approves paper execution.
- [ ] Only then may a separate deployment secret set `PAPER_ORDER_APPROVED=true` and
  `TRADE_EXECUTION_ENABLED=true` together, with `TRADING_KILL_SWITCH=false` as the
  final deliberate release action.

No checklist item permits live trading. Live endpoint support is prohibited in code.
