# Demo Script Draft

Target length: 3–4 minutes. This is a local draft; no live order should be sent.

1. **Problem and thesis — 20 seconds**
   “Options agents can reason well but still fail at the broker boundary. Options
   Alpha puts probabilistic reasoning behind deterministic capital controls.”

2. **Account and safety posture — 30 seconds**
   Run `options-alpha doctor`. Show paper mode, execution disabled, sanitized
   `$100,000` account state, zero activity, Level 3 options, and indicative-data
   availability. Do not show the raw paper account ID.

3. **Alpaca MCP evidence — 30 seconds**
   Show the read-only MCP call names and the repository evidence file. Explain
   that the chain/quote/IV/Greeks calls are data reads only.

4. **Market evidence and candidate catalog — 35 seconds**
   Run `options-alpha market-evidence`. Show that contract metadata and
   indicative quotes are normalized into long-call, long-put, call-debit-spread,
   and put-debit-spread candidates, with DTE, spread, OI, and loss fields.

5. **AI boundary — 35 seconds**
   Run `options-alpha ai-doctor`, then show the exact JSON contract. Explain the
   Featherless OpenAI-compatible call, daily cost guard, invalid-output rejection,
   and `NO_TRADE` fallback. Run `options-alpha ai-smoke` only once if a provider
   inference is intentionally authorized.

6. **Deterministic shadow decision — 35 seconds**
   Run `options-alpha demo`. Show the complete offline path: synthetic bars →
   bullish regime signal → four-candidate options catalog → strict decision →
   recomputed debit and maximum loss → risk gate → simple/MLeg preview with
   `paper=true`, `sent=false`. Then optionally show `shadow-demo` as the smaller
   preview-only variant.

7. **Audit and dashboard — 25 seconds**
   Open the local dashboard and show the audit-chain health, execution disabled,
   order sent = no, latest event, and the aggregate shadow-cohort P&L card. Run
   `options-alpha shadow-performance --horizon-hours 24` and explain that only
   fresh, exact-leg Alpaca indicative marks count; synthetic demos are excluded.
   Never show `.env` or raw audit evidence containing private data.

8. **Results and limits — 25 seconds**
   Run the exact-symbol `option-snapshot-compare` and show the two dataset hashes,
   conservative quote sides, and `not_backtest=true`; then show the seeded
   simulator. Explain the missing multi-date signal/OI history and remaining
   validation gates before any paper execution.

9. **Close — 15 seconds**
   “The differentiator is not giving an LLM a broker key. It is making the AI
   useful while keeping the final capital decision deterministic, bounded, and
   auditable.”
