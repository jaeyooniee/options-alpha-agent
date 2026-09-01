"""Non-executing bridge from an AI proposal to deterministic risk and order preview."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from options_alpha_agent.ai import AIDecision, AIOutcome, AuditLog, sanitize_evidence
from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState, RiskDecision, TradeProposal
from options_alpha_agent.risk import evaluate_trade

CONTRACT_MULTIPLIER = Decimal("100")


class ShadowPipelineError(ValueError):
    """Raised when evidence cannot safely become a trade proposal or preview."""


@dataclass(frozen=True, slots=True)
class ShadowEvaluation:
    """Complete non-executing result of proposal construction and risk evaluation."""

    status: str
    proposal: TradeProposal | None
    risk_decision: RiskDecision
    order_preview: dict[str, Any] | None
    error_type: str | None

    def public_dict(self) -> dict[str, Any]:
        proposal = None
        if self.proposal is not None:
            proposal = {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in asdict(self.proposal).items()
            }
        return {
            "status": self.status,
            "proposal": proposal,
            "risk_allowed": self.risk_decision.allowed,
            "risk_reasons": list(self.risk_decision.reasons),
            "order_preview": self.order_preview,
            "error_type": self.error_type,
            "order_sent": False,
        }


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ShadowPipelineError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ShadowPipelineError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ShadowPipelineError(f"{field_name} must be finite")
    return parsed


def _candidate(evidence: Mapping[str, Any], strategy: str | None = None) -> Mapping[str, Any]:
    candidate = evidence.get("option_candidate")
    if candidate is None and strategy is not None:
        catalog = evidence.get("candidate_catalog")
        if isinstance(catalog, Mapping):
            candidate = catalog.get(strategy)
    if not isinstance(candidate, Mapping):
        raise ShadowPipelineError("option_candidate evidence is required")
    return candidate


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ShadowPipelineError(f"{field_name} must be a positive integer")
    return value


def _contract_symbol(value: Any, field_name: str = "contract_symbol") -> str:
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isalnum()
        or not 1 <= len(value) <= 32
    ):
        raise ShadowPipelineError(f"{field_name} must be an uppercase Alpaca option symbol")
    if value != value.upper():
        raise ShadowPipelineError(f"{field_name} must be uppercase")
    return value


def build_trade_proposal(
    decision: AIDecision,
    evidence: Mapping[str, Any],
    *,
    proposal_id: str,
) -> TradeProposal | None:
    """Recalculate monetary risk from option evidence; never trust AI risk totals."""

    if decision.action == "NO_TRADE":
        return None
    symbol = evidence.get("underlying")
    if symbol != decision.underlying:
        raise ShadowPipelineError("AI underlying does not match market evidence")

    candidate = _candidate(evidence, decision.strategy)
    contract_symbol = _contract_symbol(candidate.get("contract_symbol"))
    if not contract_symbol.startswith(decision.underlying):
        raise ShadowPipelineError("option contract does not match the AI underlying")
    days_to_expiry = candidate.get("days_to_expiry")
    if isinstance(days_to_expiry, bool) or not isinstance(days_to_expiry, int):
        raise ShadowPipelineError("days_to_expiry must be an integer")
    min_open_interest = candidate.get("min_open_interest")
    if isinstance(min_open_interest, bool) or not isinstance(min_open_interest, int):
        raise ShadowPipelineError("min_open_interest must be an integer")
    defined_risk = candidate.get("defined_risk")
    if not isinstance(defined_risk, bool):
        raise ShadowPipelineError("defined_risk must be boolean")
    spread_pct = _decimal(candidate.get("bid_ask_spread_pct"), "bid_ask_spread_pct")
    debit_per_share = _decimal(candidate.get("debit_per_share_usd"), "debit_per_share_usd")
    max_loss_per_share = _decimal(candidate.get("max_loss_per_share_usd"), "max_loss_per_share_usd")
    if debit_per_share <= 0 or max_loss_per_share <= 0:
        raise ShadowPipelineError("option debit and max loss must be positive")
    if spread_pct < 0:
        raise ShadowPipelineError("bid_ask_spread_pct cannot be negative")
    if max_loss_per_share < debit_per_share:
        raise ShadowPipelineError("max loss cannot be below the debit")

    quantity = decision.quantity
    computed_debit = debit_per_share * CONTRACT_MULTIPLIER * quantity
    computed_max_loss = max_loss_per_share * CONTRACT_MULTIPLIER * quantity
    return TradeProposal(
        proposal_id=proposal_id,
        underlying=decision.underlying,
        strategy=decision.strategy or "",
        quantity=quantity,
        max_loss_usd=computed_max_loss,
        net_debit_usd=computed_debit,
        days_to_expiry=days_to_expiry,
        bid_ask_spread_pct=spread_pct,
        min_open_interest=min_open_interest,
        defined_risk=defined_risk,
        thesis=decision.thesis,
    )


def build_order_preview(
    proposal: TradeProposal,
    evidence: Mapping[str, Any],
    risk_decision: RiskDecision,
) -> dict[str, Any]:
    """Build a sanitized MLeg-like payload without importing or calling a broker client."""

    if not risk_decision.allowed:
        raise ShadowPipelineError("cannot preview an order that failed risk gates")
    candidate = _candidate(evidence, proposal.strategy)
    raw_legs = candidate.get("legs")
    expected_legs = 2 if proposal.strategy.endswith("debit_spread") else 1
    if not isinstance(raw_legs, list) or len(raw_legs) != expected_legs:
        raise ShadowPipelineError(f"{proposal.strategy} requires {expected_legs} option legs")

    legs: list[dict[str, Any]] = []
    for raw_leg in raw_legs:
        if not isinstance(raw_leg, Mapping):
            raise ShadowPipelineError("each option leg must be an object")
        side = raw_leg.get("side")
        if side not in {"buy", "sell"}:
            raise ShadowPipelineError("option leg side must be buy or sell")
        ratio = _positive_int(raw_leg.get("ratio_qty"), "ratio_qty")
        legs.append(
            {
                "symbol": _contract_symbol(raw_leg.get("symbol"), "leg symbol"),
                "side": side,
                "ratio_qty": ratio,
            }
        )

    sides = [leg["side"] for leg in legs]
    if expected_legs == 1 and sides != ["buy"]:
        raise ShadowPipelineError("a long option preview requires one buy leg")
    if expected_legs == 2 and sorted(sides) != ["buy", "sell"]:
        raise ShadowPipelineError("a debit spread preview requires one buy and one sell leg")
    if any(not leg["symbol"].startswith(proposal.underlying) for leg in legs):
        raise ShadowPipelineError("all option legs must match the proposal underlying")

    limit_price = proposal.net_debit_usd / CONTRACT_MULTIPLIER / proposal.quantity
    preview = {
        "client_order_id": proposal.proposal_id,
        "order_class": "mleg" if expected_legs == 2 else "simple",
        "type": "limit",
        "time_in_force": "day",
        "side": "buy",
        "qty": proposal.quantity,
        "limit_price": str(limit_price.quantize(Decimal("0.01"))),
        "legs": legs,
        "paper": True,
        "sent": False,
    }
    if expected_legs == 1:
        preview["symbol"] = legs[0]["symbol"]
    return preview


def _signal_allows_strategy(signal: Mapping[str, Any], strategy: str | None) -> bool:
    """Allow only the predeclared production structure for a directional signal.

    Long options remain in the research/payoff catalog, but they are not a
    production entry choice: the available validation does not establish when
    their additional convexity improves risk-adjusted results.  A live model
    must therefore either abstain or select the deterministic debit-spread
    recommendation attached to the daily signal.
    """

    return strategy == signal.get("recommended_strategy") and strategy in {
        "call_debit_spread",
        "put_debit_spread",
    }


def evaluate_shadow(
    decision: AIDecision,
    evidence: Mapping[str, Any],
    portfolio: PortfolioState,
    settings: Settings,
    *,
    proposal_id: str,
    ai_outcome: AIOutcome | None = None,
    audit_log: AuditLog | None = None,
    now: datetime | None = None,
) -> ShadowEvaluation:
    """Run AI output through evidence reconstruction and all deterministic gates."""

    try:
        safe_evidence = sanitize_evidence(evidence)
        if not isinstance(safe_evidence, Mapping):
            raise ShadowPipelineError("evidence must be an object")
    except Exception as exc:  # noqa: BLE001 - no untrusted evidence may escape
        safe_evidence = {"sanitization": "rejected"}
        evaluation = ShadowEvaluation(
            status="fail_closed",
            proposal=None,
            risk_decision=RiskDecision(False, ("unsafe_evidence",)),
            order_preview=None,
            error_type=type(exc).__name__,
        )
    else:
        if decision.action == "NO_TRADE":
            evaluation = ShadowEvaluation(
                status="no_trade",
                proposal=None,
                risk_decision=RiskDecision(False, ("ai_no_trade",)),
                order_preview=None,
                error_type=None,
            )
        elif safe_evidence.get("data_fresh") is False:
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("stale_market_data",)),
                order_preview=None,
                error_type=None,
            )
        elif not (
            isinstance(safe_evidence.get("signal"), Mapping)
            and safe_evidence["signal"].get("status") == "available"
            and safe_evidence["signal"].get("lookahead_safe") is True
        ):
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("signal_unavailable",)),
                order_preview=None,
                error_type=None,
            )
        elif not (
            isinstance(safe_evidence.get("intraday_signal"), Mapping)
            and safe_evidence["intraday_signal"].get("status") == "available"
            and safe_evidence["intraday_signal"].get("lookahead_safe") is True
        ):
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("intraday_signal_unavailable",)),
                order_preview=None,
                error_type=None,
            )
        elif safe_evidence["intraday_signal"].get("entry_allowed") is not True:
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("intraday_entry_not_allowed",)),
                order_preview=None,
                error_type=None,
            )
        elif safe_evidence["intraday_signal"].get("regime") != safe_evidence["signal"].get(
            "regime"
        ):
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("timeframe_regime_mismatch",)),
                order_preview=None,
                error_type=None,
            )
        elif not _signal_allows_strategy(safe_evidence["signal"], decision.strategy):
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("signal_strategy_mismatch",)),
                order_preview=None,
                error_type=None,
            )
        elif decision.confidence < settings.min_ai_confidence:
            evaluation = ShadowEvaluation(
                status="risk_rejected",
                proposal=None,
                risk_decision=RiskDecision(False, ("ai_confidence_below_threshold",)),
                order_preview=None,
                error_type=None,
            )
        else:
            try:
                proposal = build_trade_proposal(decision, safe_evidence, proposal_id=proposal_id)
                if proposal is None:
                    raise ShadowPipelineError("trade proposal unexpectedly absent")
                risk_decision = evaluate_trade(proposal, portfolio, settings)
                preview = (
                    build_order_preview(proposal, safe_evidence, risk_decision)
                    if risk_decision.allowed
                    else None
                )
                evaluation = ShadowEvaluation(
                    status="preview_ready" if risk_decision.allowed else "risk_rejected",
                    proposal=proposal,
                    risk_decision=risk_decision,
                    order_preview=preview,
                    error_type=None,
                )
            except Exception as exc:  # noqa: BLE001 - shadow boundary must fail closed
                evaluation = ShadowEvaluation(
                    status="fail_closed",
                    proposal=None,
                    risk_decision=RiskDecision(False, ("shadow_pipeline_error",)),
                    order_preview=None,
                    error_type=type(exc).__name__,
                )

    if audit_log is not None:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        event = {
            "timestamp": timestamp.isoformat(),
            "event_type": "shadow_risk_decision",
            "request_id": ai_outcome.request_id if ai_outcome else None,
            "evidence": safe_evidence,
            "decision": decision.public_dict(),
            "evaluation": evaluation.public_dict(),
            "risk_decision": {
                "allowed": evaluation.risk_decision.allowed,
                "reasons": list(evaluation.risk_decision.reasons),
            },
            "trade_execution_enabled": settings.trade_execution_enabled,
            "order_sent": False,
        }
        audit_log.append(event)
    return evaluation


def public_json(evaluation: ShadowEvaluation) -> str:
    """Render a stable JSON preview for CLI/demo artifacts."""

    return json.dumps(evaluation.public_dict(), indent=2, sort_keys=True)
