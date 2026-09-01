# Judging Criteria and Winning Priorities

This is the internal truth-based scorecard. The official hackathon page currently
lists four criteria and does not publish numeric weights:

Source checked on 2026-09-01: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon

1. **P&L Performance** - the submitted agent's paper-trading performance and
   the effectiveness of its strategy through competition trading activity.
2. **Technology Implementation** - how effectively the agent uses Alpaca's
   Trading API, MCP server or CLI, and required technologies.
3. **Creativity & Originality** - originality of the concept, strategy, agent
   behavior, and overall approach.
4. **Presentation & Execution** - how clearly the idea, live agent behavior,
   trading reasoning, and results are communicated.

| Official criterion | Current proof | Main gap | Highest-value next action |
|---|---|---|---|
| P&L Performance | Fresh competition account is verified at $100,000 with zero activity; seeded simulations, adverse-fill replay, two real option snapshots, and a conservative shadow ledger are disclosed | No paper trades, fills, or realized competition P&L exist yet | Complete the no-go gates, then send only approved paper trades and capture their lifecycle/P&L evidence |
| Technology Implementation | Featherless strict-schema decision boundary, Alpaca Trading API and MCP reads, deterministic risk/lifecycle engine, one-minute pullback/reversal gate, exit-first entry block, read-only order/fill reconciliation, real-source exact-leg shadow accounting at 1/5/15 minutes, tested exact-leg inverse close preview, hash-chained local/GCS audit backends, generation-guarded distributed GCS lock, 140 tests, and worker/dashboard image configuration | Open-market AI shadow run, deployed durable audit, broker close submission, and external URL are not verified | Run one explicitly approved live shadow inference, accumulate at least 10 conservative 15-minute cohorts, show the same evidence-to-risk trace, then let CI/deployment prove the packaged app |
| Creativity & Originality | AI is structurally unable to bypass capital controls; debit and max loss are recomputed from evidence; every failure becomes abstention; real-source-only shadow accounting | Differentiator must be obvious in the first 20 seconds and behavior must be demonstrated | Lead with “AI proposes; deterministic gates decide,” then show malformed/stale/closed-market failure becoming `NO_TRADE` |
| Presentation & Execution | 16:9 cover, polished six-slide PDF/PPTX, validated narrated 1080p H.264/AAC MP4, 3–4 minute script, submission copy, five post drafts, a read-only decision-trace dashboard, and a static public-safe judge overview at `/demo` | The MP4 does not yet show a live dashboard and there is no external URL | Use a concise live-dashboard cut after an approved deployment; lead with the evidence-to-gate trace, limitations, paper-P&L evidence, and next step |

## P&L evidence: the highest-priority gap

- Seeded same-path strategy comparison, adverse-fill replay, negative SPY/QQQ
  holdouts disclosed, two exact-symbol real option snapshots, and a conservative
  real-source shadow ledger are available.
- The main missing evidence is actual competition-account paper activity,
  multi-date option observations with matching exact legs, signal provenance,
  and open-interest history.
- The next market sessions should increase sample quality and produce a small,
  risk-bounded paper-trading record, not tune parameters until a favorable
  result appears.

## Submission claims we can defend now

- A real Alpaca paper account is fresh at `$100,000`, Level 3, and zero activity.
- Alpaca Trading API and Alpaca MCP option-chain/quote/IV/Greeks reads work.
- Every strategy is options-only and defined-risk.
- The model cannot place an order or override risk limits.
- Execution defaults are off behind two approvals and an independent kill switch.
- The closed-market live shadow path terminates at `NO_TRADE` with no AI call or order.
- Local submission artifacts and secret scanning pass.

## Business-value framing

The first target user is a small systematic trader, research team, or fintech
builder who wants an autonomous options workflow but cannot responsibly hand an
LLM unrestricted broker authority. The product value is a reviewable control
layer: it converts market evidence into a testable proposal, recomputes loss,
records the decision, and abstains when evidence is weak. A future commercial
path is a hosted risk-and-audit API or team dashboard; this hackathon build is a
paper-only proof and makes no revenue or market-size claim.

## Claims intentionally withheld

- No historical options alpha or statistically significant P&L claim yet.
- No broker fill-quality claim before paper fills exist.
- No “working cloud URL” claim before approved deployment and external health check.
- No open-market AI shadow success claim before one paid inference is approved and logged.

The winning presentation should treat these limitations as evidence of research
discipline, while using the next market sessions to close the P&L gap rather
than manufacturing a backtest from sparse data.
