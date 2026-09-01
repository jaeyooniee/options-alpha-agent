# Judge Evidence Index

This index is the shortest truthful path through the repository. It intentionally
contains no credentials, paper account ID, or broker order payload.

## Start here (three minutes)

1. Open the static, public-safe overview at the local dashboard route `/demo`.
   It states the product thesis: **AI proposes; deterministic gates decide.**
2. Read [the one-page technical write-up](one-page-writeup.md) for the AI,
   risk, and Alpaca architecture required by the event.
3. Run the dependency-free end-to-end proof:

   ```powershell
   .venv\Scripts\python -m options_alpha_agent.cli demo
   ```

   The output is explicitly synthetic, `paper=true`, and `order_sent=false`.
4. Run the full local verification bundle:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\verify-offline.ps1
   .venv\Scripts\python -m options_alpha_agent.cli submission-check
   ```

   These commands do not call a broker or AI provider.

## Official judging criteria → repository proof

| Criterion | Evidence | Truthful current limit |
|---|---|---|
| Application of Technology | Strict-schema AI boundary in `src/options_alpha_agent/ai.py`; Alpaca SDK/MCP evidence; deterministic risk and lifecycle modules; hash-chained audit log; reproducible test suite | An open-market paid AI shadow run and deployed durable audit are pending |
| Presentation | `/demo` overview; local safety console; [six-slide deck](../submission/options-alpha-slides.pdf); narrated [MP4](../submission/demo.mp4); [demo script](demo-script.md) | No external demo URL until approved deployment |
| Business Value | [Judging scorecard](judging-scorecard.md) explains the target user: systematic traders, research teams, and fintech builders needing a reviewable control layer | No revenue, TAM, or return claim is made |
| Originality | [One-page write-up](one-page-writeup.md): AI has no broker access; stale or malformed evidence becomes `NO_TRADE`; loss is recomputed from evidence | No historical alpha claim is made |

The official page publishes these four qualitative criteria, without numeric
weights or a standalone P&L ranking rule. See
[official-requirements.md](official-requirements.md) for the checked source and
submission constraints.

## Alpaca and options evidence

- [MCP evidence](alpaca-mcp-evidence.md): read-only chain, quote, IV, and Greeks
  calls through the installed Alpaca plugin.
- [Option snapshot provenance](option-snapshot-provenance.md): two normalized,
  hash-verified SPY indicative option snapshots.
- [Live closed-market shadow evidence](live-shadow-evidence.md): real paper
  account reconciliation reaches `NO_TRADE` without market-data collection, AI
  inference, or an order.
- [Strategy evaluation](strategy-evaluation.md): reproducible simulator,
  holdout, adverse-fill replay, and conservative exact-leg shadow-P&L rules.
- [Minute operations](minute-operations.md): the 1/5/15-minute exact-leg
  shadow protocol and its no-order review gate.

## Safety and reproducibility evidence

- [Compliance matrix](compliance-matrix.md): every explicit event requirement
  with its evidence and status.
- [First-order go/no-go checklist](go-no-go-checklist.md): currently **NO-GO**;
  paper execution remains disabled.
- [Market-session capture plan](market-session-capture-plan.md): frozen protocol
  for accumulating real option observations without changing parameters after
  results are observed.
- [Final-submission runbook](final-submission-runbook.md): approval-gated path
  for GitHub, deployment, posts, and the private account-ID field.

## What is deliberately not claimed

- No live trading, live endpoint, or unsupervised paper order.
- No historical options alpha, statistically significant P&L, or broker-fill
  quality claim.
- No working external URL before deployment is explicitly approved and checked.
- No public paper account ID, API key, or secret.

This evidence-first framing is intentional: in this agent, abstention is a
successful safety outcome when evidence or controls are insufficient.
