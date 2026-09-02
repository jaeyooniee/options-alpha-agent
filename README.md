# Options Alpha Agent

An autonomous, explainable, risk-gated options paper-trading agent for the
Alpaca AI Trading Agents Hackathon.

The project is deliberately fail-closed. It starts in paper mode with order
execution disabled, and every proposed trade must pass deterministic risk gates
before the broker adapter can be reached.

## Competition compliance

- Autonomous AI trading agent using Alpaca Trading API
- Options are part of every trading strategy
- Read-only Alpaca MCP evidence and reproducible CLI commands are included
- Dedicated fresh paper account with a $100,000 starting balance
- One-page explanation of AI logic, risk gates, and Alpaca infrastructure
- MIT-licensed public source code

See [docs/compliance-matrix.md](docs/compliance-matrix.md) for the auditable
requirements matrix.

For a judge-friendly, claim-limited route through the implementation, start with
[docs/evidence-index.md](docs/evidence-index.md).

Verified official requirements, MCP evidence, strategy evaluation, cloud options,
the first-order checklist, local Git setup, and final-submission runbook are
maintained under `docs/`.

The latest sanitized live shadow evidence is recorded in
[`docs/live-shadow-evidence.md`](docs/live-shadow-evidence.md). It proves the
closed-market fail-closed path without exposing an account ID or consuming an AI
inference credit.

The frozen multi-session collection protocol and internal judging priorities are
documented in [`docs/market-session-capture-plan.md`](docs/market-session-capture-plan.md)
and [`docs/judging-scorecard.md`](docs/judging-scorecard.md).
The organizer-facing one-page technical PDF is generated at
`output/pdf/options-alpha-one-page.pdf` from the reproducible ReportLab builder.

## Safety defaults

- Paper trading only
- Execution disabled unless paper approval and execution flags are enabled and the kill switch is off
- Emergency kill switch defaults to on (`TRADING_KILL_SWITCH=true`)
- Defined-risk option positions only
- Maximum loss calculated before entry
- AI confidence floor before any proposal can reach the risk engine
- Per-trade, portfolio, daily-drawdown, liquidity, and position-count gates
- AI-independent profit/stop/expiry exit policy with stale-quote manual review
- No credentials in source control

## Local setup

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m options_alpha_agent.cli risk-demo
.venv\Scripts\python -m options_alpha_agent.cli simulate --regime neutral
.venv\Scripts\python -m options_alpha_agent.cli robustness --paths 1000
.venv\Scripts\python -m options_alpha_agent.cli doctor
.venv\Scripts\python -m options_alpha_agent.cli ai-doctor
.venv\Scripts\python -m options_alpha_agent.cli market-evidence
.venv\Scripts\python -m options_alpha_agent.cli capture-bars --underlying SPY --output data/underlying.capture.csv
.venv\Scripts\python -m options_alpha_agent.cli capture-option-snapshot --underlying SPY --expiration 2026-09-04 --output data/options/spy.indicative.next.csv
.venv\Scripts\python -m options_alpha_agent.cli monitor
.venv\Scripts\python -m options_alpha_agent.cli ai-smoke
.venv\Scripts\python -m options_alpha_agent.cli shadow-demo
.venv\Scripts\python -m options_alpha_agent.cli demo
.venv\Scripts\python -m options_alpha_agent.cli shadow-cycle --underlying SPY
.venv\Scripts\python -m options_alpha_agent.cli shadow-performance --horizon-hours 24
.venv\Scripts\python -m options_alpha_agent.cli short-shadow --minimum-cohorts 10
powershell -ExecutionPolicy Bypass -File scripts\run-shadow-only.ps1 -Cycles 5 -IntervalSeconds 60
.venv\Scripts\python -m options_alpha_agent.cli option-snapshot-check --csv data/options/spy.indicative.2026-08-28T1948Z.csv
.venv\Scripts\python -m options_alpha_agent.cli option-snapshot-compare --entry data/options/spy.indicative.2026-08-28T1948Z.csv --exit data/options/spy.indicative.2026-08-28T1957Z.csv
.venv\Scripts\python -m options_alpha_agent.cli replay --csv data/replay.sample.csv
.venv\Scripts\python -m options_alpha_agent.cli walk-forward --csv data/underlying.sample.csv
.venv\Scripts\python -m options_alpha_agent.cli submission-check
# Offline preflight (no network, order, or AI inference)
powershell -ExecutionPolicy Bypass -File scripts\verify-offline.ps1
```

To inspect the local read-only console, run
`.venv\Scripts\python -m options_alpha_agent.cli dashboard` and open
`http://127.0.0.1:8501`. The same server exposes `/demo`, a static judge-facing
overview with no account ID, credential, or broker route. The console exposes
only paper-mode, execution, AI, and audit-chain health; it has no order route.

`shadow-performance` reads the verified audit chain and reconstructs virtual
option cohorts from real Alpaca indicative evidence only. It requires fresh
quotes for the exact same legs, records entry at long ask/short bid, and marks
liquidation at long bid/short ask. Synthetic demos are excluded, and missing
marks remain explicitly unmarked instead of being assigned an inferred P&L.

`short-shadow` is the production-horizon validation command. It uses only fresh
Alpaca-source audit events and exact same-leg quote timestamps to measure the
1-, 5-, and 15-minute marks. It is research-only and returns
`CONTINUE_SHADOW` until at least 10 real 15-minute cohorts have at least 90%
coverage and positive conservative mean P&L.

The repository also includes a real, versioned 22-contract SPY indicative
snapshot with IV and Greeks. `option-snapshot-check` validates its schema,
timestamps, OCC symbols, quotes, and hash. It is one observation only and is
therefore not presented as a historical return.

`capture-option-snapshot` repeats that path through the official Alpaca SDK. It
uses IEX for the underlying and the free indicative options feed, rejects stale
or incomplete rows, refuses absolute/parent paths and existing output files,
and returns a SHA-256 checksum with `order_sent=false`. Use a new timestamped
filename for every observation; snapshots are immutable by design.

Two matching 22-contract snapshots are included. `option-snapshot-compare`
matches exact OCC symbols and applies conservative entry/exit quote sides to
long options and every bounded debit-spread pair. The bundled interval is only
581.99 seconds and lacks signal selection and open-interest history, so its
output is permanently labelled `not_backtest=true` and does not claim edge.

For a scheduled, one-shot worker, use `shadow-cycle` once per minute. It reconciles the account
metadata conservatively, collects fresh read-only market evidence, calls the
configured AI boundary, and returns either `NO_TRADE` or an unexecuted preview.
The broker adapter remains behind the paper approval, execution, and kill-switch
gates. `Dockerfile.worker` is the matching
container entry point for a later Cloud Run Job deployment.

For a Cloud Run deployment, configure `DURABLE_STATE_BACKEND=gcs` and a private
`GCS_STATE_BUCKET`. The optional backend persists the exact hash-chained audit
object with Cloud Storage generation preconditions and replaces the local
worker lock with a time-bounded distributed GCS lock. Run
`options-alpha cloud-preflight` before deployment; it performs no cloud or
broker request and refuses a configuration that enables execution or omits
durable storage.

The default AI provider is Featherless through its OpenAI-compatible API. Set
`FEATHERLESS_API_KEY` in the local `.env`; the selected default model is
`mistralai/Mistral-Large-Instruct-2411`, validated with the repository's
`ai-smoke` contract test. The AI boundary is intentionally small and
fail-closed: it accepts evidence, returns one strict JSON decision, and can
only produce `NO_TRADE` or an unexecuted proposal. It cannot call Alpaca or
change risk limits. Provider calls are capped by count and estimated daily
cost. Credential-like field names and text are rejected before provider/audit
handling, and successful or failed calls are recorded in the hash-chained local
file configured by `AI_AUDIT_LOG_PATH` (ignored by Git).

`OPENAI_API_KEY` is optional in the default configuration. It is only needed
if `AI_PROVIDER=openai` is deliberately selected; a Featherless key is the
only AI provider credential required for the default setup.

The intended cycle is: read-only Alpaca contract and indicative-quote collection
→ candidate catalog → Featherless decision → strict validation → deterministic
risk gates → non-executing MLeg preview. No step in this path sends an order.

Keep `TRADE_EXECUTION_ENABLED=false` and `PAPER_ORDER_APPROVED=false` until
the account, option level, market data, strategy, and emergency-stop behavior
have all been validated.

## Current status

The repository contains the safety kernel, sanitized fresh-account diagnostics,
free indicative option-data diagnostics, a reproducible scenario simulator, a
normalized option-observation replay, and the Featherless strict-schema AI
boundary with fail-closed behavior, daily cost guards, hash-chained audit
logging, an offline risk-checked option order preview, an explicit paper-order
adapter, account/P&L reconciliation, and an AI-independent exit policy. The account is verified
fresh at $100,000 with Level 3 options and zero activity. Read-only Alpaca
contract/quote normalization, a debit-spread production selector with four-candidate
research comparison, look-ahead-safe regime
signals, the local read-only dashboard, draft submission copy/slides, a
deterministic multi-regime strategy robustness sweep, and provenance-documented
SPY/QQQ underlying walk-forward holdouts, plus a conservative exact-leg shadow
P&L reconstruction command and dashboard summary, are implemented. The observed
underlying holdouts are negative and are disclosed rather than presented as
options performance. Historical multi-date option replay data, a scheduled AI
loop over live evidence, and cloud deployment remain pending. A narrated
158.99-second H.264/AAC 1080p MP4 has been generated from the visually checked
deck and decoded frame-by-frame; it is a presentation artifact, not a claim of
live trading performance. The cover asset, slide PDF, and MP4 pass local
validation. The public repository is live and the latest GitHub Actions run is
green; future release pushes and external submission remain approval-gated. The
project is therefore still NO-GO for its first paper order.
