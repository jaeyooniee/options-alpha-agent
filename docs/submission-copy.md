# Submission Copy Draft

This file is a local draft. It contains no paper account ID, credentials, or
external submission link.

## Project title

**Options Alpha: The Guarded Agent**

## Short description

An autonomous Alpaca options paper-trading agent where AI proposes and deterministic risk gates decide. Every decision is evidence-backed, fail-closed, and auditable.

## Long description

Options Alpha is an autonomous, explainable options paper-trading agent built
for the Alpaca AI Trading Agents Hackathon. Its core idea is a hard boundary
between probabilistic reasoning and capital protection: Featherless AI receives
sanitized, timestamped Alpaca market evidence and returns one strict JSON
decision, while a deterministic risk engine independently recomputes option
debit and maximum loss before any order could be considered.

Every strategy is options-only and defined-risk: long calls, long puts, call
debit spreads, or put debit spreads. The system filters contracts by freshness,
bid/ask spread, open interest, days to expiry, and bounded loss. It supports
read-only Alpaca contract and indicative quote collection, Alpaca MCP evidence,
reproducible scenario evaluation, and a local hash-chained audit log covering
evidence, model metadata, prompt/response hashes, risk decisions, estimated
cost, read-only order/fill lifecycle records with hash-redacted broker references,
and the invariant `order_sent=false`.

Its reproducibility evidence also includes two hashed, exact-symbol SPY option
snapshots from Alpaca's indicative feed and a conservative quote-path comparison
that uses entry asks/bids and later liquidation bids/asks. The result is clearly
labelled `not_backtest` because the brief interval has no signal selection or
open-interest history.

The demo package includes the complete AI-to-risk shadow cycle and a read-only
safety console. Paper execution remains disabled by default, live trading is
prohibited in configuration, and failures or malformed model output become
`NO_TRADE`. An independent kill switch is normally on in addition to the two
execution approvals. This makes the agent useful as a transparent research
system while keeping the broker boundary deterministic, bounded, and reviewable.
A separate paper executor is implemented with explicit two-flag approval and
client-order-id deduplication, but it is not activated in the demo.

The initial target users are small systematic traders, research teams, and fintech
builders who need an autonomous options workflow without handing an LLM
unrestricted broker authority. A future hosted risk-and-audit API or team
dashboard is the product path; this submission makes no unsupported market-size
or revenue claim.

## Suggested tags

`Alpaca` · `Options` · `Paper Trading` · `AI Agents` · `Risk Management` ·
`Featherless` · `Python`

## Build-in-public drafts

These are drafts only; do not publish until the final user approval.

1. **Architecture:** Built an options-only Alpaca agent with a strict separation
   between Featherless AI proposals and deterministic risk gates. The model can
   explain a trade, but it cannot send one. @AlpacaHQ @lablabai #Alpaca #lablabai
2. **Safety:** Added fail-closed JSON validation, paper-only configuration,
   daily AI cost limits, stale-data rejection, and hash-chained audit events.
   Invalid output becomes `NO_TRADE`. @AlpacaHQ @lablabai #AI #Options
3. **Data:** Verified Alpaca's read-only indicative option chain, quotes, IV,
   and Greeks, then added contract metadata normalization and four defined-risk
   candidate structures. @AlpacaHQ @lablabai #Alpaca #Trading
4. **Demo:** The shadow cycle now goes market evidence → AI decision → loss
   recomputation → risk gates → non-executing MLeg preview. No broker order is
   sent in the demo. @AlpacaHQ @lablabai #BuildInPublic
5. **Results:** Comparing long options and debit spreads on identical seeded
   scenarios, with P&L, drawdown-tail, win rate, and return-on-risk metrics.
   Historical replay and paper results will be disclosed separately. @AlpacaHQ
   @lablabai #Quant
