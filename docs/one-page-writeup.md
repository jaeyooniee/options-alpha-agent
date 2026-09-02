# Options Alpha Agent — One-Page Technical Summary

## AI logic

The agent combines a look-ahead-safe daily directional regime with a one-minute
SPY pullback/reversal gate: a 20-minute z-score discount or premium and a
confirming one-minute rebound or rejection. It uses liquid short-horizon (2--10
DTE) option-chain filtering and structured model reasoning. The Featherless model
is called through an OpenAI-compatible provider boundary and receives sanitized,
timestamped evidence. It must return one exact JSON object containing either
`NO_TRADE` or a defined-risk options proposal. Invalid, incomplete, stale, or
unsupported output fails closed. A provider-added single JSON markdown fence may
be normalized, but surrounding prose or multiple objects still fail closed.
Prompt/response hashes, evidence, model metadata, rejected alternatives, token usage, estimated cost, and
`order_sent=false` are written to a hash-chained audit log. The model may
propose and explain trades, but it cannot place an order or override
deterministic controls.

## Risk gates

Every production proposal must be the daily-signal-matched call or put debit
spread; long options are research comparators only. Pre-trade checks limit
maximum loss per trade, aggregate portfolio risk, daily drawdown, concurrent
positions, 2--10 DTE, bid/ask spread, and open interest. The
system rejects AI confidence below the configured floor before proposal
construction. It is paper-only and order execution starts disabled behind two independent
approval flags: `PAPER_ORDER_APPROVED` and `TRADE_EXECUTION_ENABLED`, plus a
normally-on emergency kill switch `TRADING_KILL_SWITCH`.
An existing position blocks every new AI entry for an auditable exit review. The
AI-independent short-horizon exit policy reviews a 25%-of-risk profit target,
35%-of-risk stop, 15-minute holding cap, session-close flatten, expiry, and
stale-quote conditions. Partial fills, terminal order states, and
assignment/exercise risk are classified by a separate deterministic lifecycle
policy; assignment always becomes manual review rather than an automatic broker
mutation.

## Alpaca infrastructure

Alpaca Trading API supplies account, contract, order, position, and market data
operations. The connected Alpaca Codex plugin has been verified with read-only
option-chain, quote, IV, and Greeks calls on the free indicative feed. The official
Python SDK provides sanitized paper-account diagnostics and the contract master
metadata used by `run_shadow_cycle`. The dedicated account was verified at
$100,000 with zero orders, fills, and positions and Level 3 options.

## Differentiator

The design separates probabilistic AI reasoning from deterministic capital
controls. The shadow bridge recomputes debit and maximum loss from option
evidence instead of trusting AI totals, evaluates every deterministic gate, and
builds an MLeg debit-spread preview with `paper=true` and `sent=false`. The
explicit paper executor adds client-order-id deduplication and remains blocked
until both approval flags are enabled. A non-executing performance ledger can already reconstruct conservative
shadow cohorts from fresh Alpaca indicative quotes for the exact same option legs;
synthetic demos and missing marks are excluded. Two hashed real SPY option
snapshots and an exact-symbol conservative quote-path comparison additionally
prove the market-data/payoff plumbing while remaining explicitly not a backtest.
Every decision produces a
machine-readable trace linking market evidence, AI thesis, rejected alternatives,
risk calculations, and eventual Alpaca request, fill, and broker P&L records once
paper execution is explicitly approved.
