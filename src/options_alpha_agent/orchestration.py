"""One read-only market-to-AI-to-risk cycle; broker execution is intentionally absent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from options_alpha_agent.ai import (
    AIDecision,
    AIDecisionEngine,
    AIOutcome,
    AuditLog,
    audit_log_for_settings,
)
from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState
from options_alpha_agent.option_data import collect_market_evidence
from options_alpha_agent.reconciliation import (
    ReconciliationSnapshot,
    append_reconciliation_audit,
    reconcile_paper_account,
)
from options_alpha_agent.shadow import ShadowEvaluation, evaluate_shadow


def _no_trade_decision(underlying: str, error_type: str) -> AIDecision:
    symbol = (
        underlying.upper()
        if isinstance(underlying, str) and underlying.isascii() and underlying.isalnum()
        else "SPY"
    )
    return AIDecision.from_json(
        json.dumps(
            {
                "action": "NO_TRADE",
                "underlying": symbol,
                "strategy": None,
                "confidence": 0,
                "thesis": "Market evidence was unavailable; cycle failed closed.",
                "evidence": [f"market_evidence_failure:{error_type}"],
                "rejected_alternatives": [],
                "invalidation_conditions": [],
                "quantity": 0,
                "max_loss_usd": 0,
                "net_debit_usd": 0,
            }
        )
    )


def _no_trade_outcome(settings: Settings, underlying: str, error_type: str) -> AIOutcome:
    return AIOutcome(
        request_id=str(uuid4()),
        provider_status="fail_closed",
        model=(
            settings.openai_model
            if settings.ai_provider == "openai"
            else settings.featherless_model
        ),
        decision=_no_trade_decision(underlying, error_type),
        error_type=error_type,
        prompt_tokens=0,
        completion_tokens=0,
        estimated_cost_usd=Decimal("0"),
    )


def _minute_entry_eligible(evidence: dict[str, Any]) -> bool:
    """Permit an AI call only when daily and minute direction agree in-window."""

    daily = evidence.get("signal")
    minute = evidence.get("intraday_signal")
    if not isinstance(daily, dict) or not isinstance(minute, dict):
        return False
    if daily.get("status") != "available" or minute.get("status") != "available":
        return False
    if daily.get("lookahead_safe") is not True or minute.get("lookahead_safe") is not True:
        return False
    regime = daily.get("regime")
    return (
        minute.get("entry_allowed") is True
        and regime in {"bullish", "bearish"}
        and minute.get("regime") == regime
    )


def run_shadow_cycle(
    settings: Settings,
    portfolio: PortfolioState,
    *,
    underlying: str = "SPY",
    now: datetime | None = None,
    audit_log: AuditLog | None = None,
    ai_client: Any | None = None,
    trading_client: Any | None = None,
    stock_client: Any | None = None,
    option_client: Any | None = None,
    market_open: bool | None = None,
) -> tuple[dict[str, Any], AIOutcome, ShadowEvaluation]:
    """Run one complete non-executing cycle with fail-closed recovery."""

    audit = audit_log or audit_log_for_settings(settings)
    cycle_time = now or datetime.now(UTC)
    if cycle_time.tzinfo is None:
        cycle_time = cycle_time.replace(tzinfo=UTC)
    else:
        cycle_time = cycle_time.astimezone(UTC)
    if market_open is False:
        symbol = (
            underlying.upper()
            if isinstance(underlying, str) and underlying.isascii() and underlying.isalnum()
            else "SPY"
        )
        evidence = {
            "underlying": symbol,
            "source": "alpaca_market_clock",
            "as_of": cycle_time.astimezone(UTC).isoformat(),
            "data_fresh": False,
            "market_data_available": False,
            "candidate_catalog": {},
            "candidate_failures": {"market_clock": "MarketClosed"},
            "market_open": False,
        }
        outcome = _no_trade_outcome(settings, symbol, "MarketClosed")
        audit.append(
            {
                "timestamp": cycle_time.astimezone(UTC).isoformat(),
                "event_type": "market_closed",
                "provider_called": False,
                "market_open": False,
                "error_type": "MarketClosed",
                "order_sent": False,
            }
        )
    else:
        try:
            evidence = collect_market_evidence(
                settings,
                underlying,
                now=cycle_time,
                trading_client=trading_client,
                stock_client=stock_client,
                option_client=option_client,
            )
        except Exception as exc:  # noqa: BLE001 - unavailable market data means no trade
            error_type = type(exc).__name__
            symbol = (
                underlying.upper()
                if isinstance(underlying, str) and underlying.isascii() and underlying.isalnum()
                else "SPY"
            )
            evidence = {
                "underlying": symbol,
                "source": "alpaca_read_only_collection_failed",
                "as_of": cycle_time.astimezone(UTC).isoformat(),
                "data_fresh": False,
                "market_data_available": False,
                "candidate_catalog": {},
                "candidate_failures": {"collection": error_type},
                "market_open": True if market_open is True else None,
            }
            outcome = _no_trade_outcome(settings, symbol, error_type)
            audit.append(
                {
                    "timestamp": cycle_time.astimezone(UTC).isoformat(),
                    "event_type": "market_evidence_failure",
                    "provider_called": False,
                    "error_type": error_type,
                    "evidence": evidence,
                    "order_sent": False,
                }
            )
        else:
            if market_open is not None:
                evidence["market_open"] = market_open
            if _minute_entry_eligible(evidence):
                outcome = AIDecisionEngine(settings, client=ai_client, audit_log=audit).decide(
                    evidence
                )
            else:
                outcome = _no_trade_outcome(settings, underlying, "MinuteEntryNotEligible")
                audit.append(
                    {
                        "timestamp": cycle_time.astimezone(UTC).isoformat(),
                        "event_type": "minute_scan_abstention",
                        "provider_called": False,
                        "error_type": "MinuteEntryNotEligible",
                        "daily_regime": evidence.get("signal", {}).get("regime"),
                        "minute_regime": evidence.get("intraday_signal", {}).get("regime"),
                        "minute_entry_allowed": evidence.get("intraday_signal", {}).get(
                            "entry_allowed"
                        ),
                        "order_sent": False,
                    }
                )

    evaluation = evaluate_shadow(
        outcome.decision,
        evidence,
        portfolio,
        settings,
        proposal_id=outcome.request_id,
        ai_outcome=outcome,
        audit_log=audit,
        now=cycle_time,
    )
    return evidence, outcome, evaluation


def run_reconciled_shadow_cycle(
    settings: Settings,
    *,
    underlying: str = "SPY",
    now: datetime | None = None,
    audit_log: AuditLog | None = None,
    ai_client: Any | None = None,
    trading_client: Any | None = None,
    stock_client: Any | None = None,
    option_client: Any | None = None,
) -> tuple[ReconciliationSnapshot, dict[str, Any], AIOutcome, ShadowEvaluation]:
    """Reconcile the paper account before one non-executing shadow decision.

    The shared ``trading_client`` is read-only here. It supplies account/order/
    position/clock state to reconciliation and option-contract metadata to market
    evidence. Order submission remains outside this function and independently
    approval-gated.
    """

    audit = audit_log or audit_log_for_settings(settings)
    reconciliation = reconcile_paper_account(settings, client=trading_client, now=now)
    append_reconciliation_audit(reconciliation, audit_log=audit)
    # Career26's useful operational rule is "review exits before entries".  We
    # do not yet have a fresh exact-leg close adapter, so any broker-reconciled
    # position blocks a new AI entry and becomes an auditable manual exit review
    # instead of allowing a second exposure to accumulate.
    if reconciliation.position_count:
        symbol = underlying.upper() if underlying.isascii() and underlying.isalnum() else "SPY"
        cycle_time = now or datetime.now(UTC)
        if cycle_time.tzinfo is None:
            cycle_time = cycle_time.replace(tzinfo=UTC)
        else:
            cycle_time = cycle_time.astimezone(UTC)
        evidence = {
            "underlying": symbol,
            "source": "alpaca_paper_reconciliation_exit_first_gate",
            "as_of": cycle_time.isoformat(),
            "data_fresh": False,
            "market_data_available": False,
            "market_open": reconciliation.market_open,
            "position_count": reconciliation.position_count,
            "candidate_catalog": {},
            "candidate_failures": {"entry": "ExistingPositionRequiresExitReview"},
        }
        outcome = _no_trade_outcome(settings, symbol, "ExistingPositionRequiresExitReview")
        audit.append(
            {
                "timestamp": cycle_time.isoformat(),
                "event_type": "exit_first_entry_blocked",
                "position_count": reconciliation.position_count,
                "provider_called": False,
                "error_type": "ExistingPositionRequiresExitReview",
                "order_sent": False,
            }
        )
        evaluation = evaluate_shadow(
            outcome.decision,
            evidence,
            reconciliation.portfolio_state(settings),
            settings,
            proposal_id=outcome.request_id,
            ai_outcome=outcome,
            audit_log=audit,
            now=cycle_time,
        )
        return reconciliation, evidence, outcome, evaluation
    evidence, outcome, evaluation = run_shadow_cycle(
        settings,
        reconciliation.portfolio_state(settings),
        underlying=underlying,
        now=now,
        audit_log=audit,
        ai_client=ai_client,
        trading_client=trading_client,
        stock_client=stock_client,
        option_client=option_client,
        market_open=reconciliation.market_open,
    )
    return reconciliation, evidence, outcome, evaluation
