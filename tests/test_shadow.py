import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from options_alpha_agent.ai import AIDecision, AuditLog
from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState
from options_alpha_agent.shadow import evaluate_shadow


def settings() -> Settings:
    return Settings(
        alpaca_api_key=None,
        alpaca_secret_key=None,
        openai_api_key=None,
        alpaca_paper=True,
        trade_execution_enabled=False,
        starting_equity_usd=Decimal("100000"),
        max_risk_per_trade_pct=Decimal("0.02"),
        max_portfolio_risk_pct=Decimal("0.10"),
        max_daily_drawdown_pct=Decimal("0.04"),
        max_open_positions=5,
    )


def portfolio() -> PortfolioState:
    return PortfolioState(
        equity_usd=Decimal("100000"),
        start_of_day_equity_usd=Decimal("100000"),
        deployed_risk_usd=Decimal("0"),
        open_positions=0,
    )


def decision(action: str = "PROPOSE_TRADE") -> AIDecision:
    is_trade = action == "PROPOSE_TRADE"
    return AIDecision.from_json(
        json.dumps(
            {
                "action": action,
                "underlying": "SPY",
                "strategy": "call_debit_spread" if is_trade else None,
                "confidence": 0.8,
                "thesis": "Defined-risk directional setup for a shadow preview.",
                "evidence": ["synthetic fixture only"],
                "rejected_alternatives": ["long_call"],
                "invalidation_conditions": ["quote becomes stale"],
                "quantity": 1 if is_trade else 0,
                "max_loss_usd": 750 if is_trade else 0,
                "net_debit_usd": 750 if is_trade else 0,
            }
        )
    )


def evidence() -> dict[str, object]:
    return {
        "underlying": "SPY",
        "source": "synthetic_shadow_fixture",
        "timestamp": "2026-08-29T12:00:00Z",
        "signal": {
            "status": "available",
            "lookahead_safe": True,
            "regime": "bullish",
            "recommended_strategy": "call_debit_spread",
        },
        "intraday_signal": {
            "status": "available",
            "lookahead_safe": True,
            "regime": "bullish",
            "entry_allowed": True,
        },
        "option_candidate": {
            "contract_symbol": "SPY260905C00780000",
            "days_to_expiry": 7,
            "bid_ask_spread_pct": "0.05",
            "min_open_interest": 1000,
            "defined_risk": True,
            "debit_per_share_usd": "7.50",
            "max_loss_per_share_usd": "7.50",
            "legs": [
                {"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1},
                {"symbol": "SPY260905C00800000", "side": "sell", "ratio_qty": 1},
            ],
        },
    }


def test_shadow_pipeline_builds_risk_checked_preview_without_sending(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    result = evaluate_shadow(
        decision(),
        evidence(),
        portfolio(),
        settings(),
        proposal_id="shadow-001",
        audit_log=audit,
    )

    assert result.status == "preview_ready"
    assert result.risk_decision.allowed is True
    assert result.order_preview is not None
    assert result.order_preview["paper"] is True
    assert result.order_preview["sent"] is False
    assert result.order_preview["order_class"] == "mleg"
    assert audit.path.read_text(encoding="utf-8").count("shadow_risk_decision") == 1


def test_shadow_pipeline_rejects_risk_before_preview() -> None:
    result = evaluate_shadow(
        decision(),
        evidence(),
        replace(portfolio(), deployed_risk_usd=Decimal("9500")),
        settings(),
        proposal_id="shadow-002",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.allowed is False
    assert "portfolio_risk_exceeded" in result.risk_decision.reasons
    assert result.order_preview is None


def test_shadow_pipeline_preserves_no_trade_abstention() -> None:
    result = evaluate_shadow(
        decision("NO_TRADE"),
        evidence(),
        portfolio(),
        settings(),
        proposal_id="shadow-003",
    )

    assert result.status == "no_trade"
    assert result.risk_decision.reasons == ("ai_no_trade",)
    assert result.order_preview is None


def test_shadow_pipeline_fails_closed_on_missing_option_evidence() -> None:
    result = evaluate_shadow(
        decision(),
        {
            "underlying": "SPY",
            "signal": {
                "status": "available",
                "lookahead_safe": True,
                "regime": "bullish",
                "recommended_strategy": "call_debit_spread",
            },
            "intraday_signal": {
                "status": "available",
                "lookahead_safe": True,
                "regime": "bullish",
                "entry_allowed": True,
            },
        },
        portfolio(),
        settings(),
        proposal_id="shadow-004",
    )

    assert result.status == "fail_closed"
    assert result.risk_decision.allowed is False
    assert result.order_preview is None


def test_long_option_is_rejected_from_the_production_entry_path() -> None:
    long_decision = AIDecision.from_json(
        json.dumps(
            {
                "action": "PROPOSE_TRADE",
                "underlying": "SPY",
                "strategy": "long_call",
                "confidence": 0.8,
                "thesis": "Single-leg defined-risk shadow preview.",
                "evidence": ["synthetic fixture only"],
                "rejected_alternatives": [],
                "invalidation_conditions": ["quote becomes stale"],
                "quantity": 1,
                "max_loss_usd": 750,
                "net_debit_usd": 750,
            }
        )
    )
    long_evidence = {
        "underlying": "SPY",
        "signal": {
            "status": "available",
            "lookahead_safe": True,
            "regime": "bullish",
            "recommended_strategy": "call_debit_spread",
        },
        "intraday_signal": {
            "status": "available",
            "lookahead_safe": True,
            "regime": "bullish",
            "entry_allowed": True,
        },
        "option_candidate": {
            "contract_symbol": "SPY260905C00780000",
            "days_to_expiry": 7,
            "bid_ask_spread_pct": "0.05",
            "min_open_interest": 1000,
            "defined_risk": True,
            "debit_per_share_usd": "7.50",
            "max_loss_per_share_usd": "7.50",
            "legs": [{"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1}],
        },
    }

    result = evaluate_shadow(
        long_decision,
        long_evidence,
        portfolio(),
        settings(),
        proposal_id="shadow-long-001",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.reasons == ("signal_strategy_mismatch",)
    assert result.order_preview is None


def test_shadow_pipeline_rejects_missing_lookahead_safe_signal() -> None:
    evidence_without_signal = evidence()
    evidence_without_signal.pop("signal")

    result = evaluate_shadow(
        decision(),
        evidence_without_signal,
        portfolio(),
        settings(),
        proposal_id="shadow-005",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.reasons == ("signal_unavailable",)


def test_shadow_pipeline_rejects_directional_signal_mismatch() -> None:
    contradictory = evidence()
    contradictory["signal"] = {
        "status": "available",
        "lookahead_safe": True,
        "regime": "bearish",
        "recommended_strategy": "put_debit_spread",
    }
    contradictory["intraday_signal"] = {
        "status": "available",
        "lookahead_safe": True,
        "regime": "bearish",
        "entry_allowed": True,
    }

    result = evaluate_shadow(
        decision(),
        contradictory,
        portfolio(),
        settings(),
        proposal_id="shadow-006",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.reasons == ("signal_strategy_mismatch",)


def test_shadow_pipeline_rejects_missing_intraday_confirmation() -> None:
    minute_missing = evidence()
    minute_missing.pop("intraday_signal")

    result = evaluate_shadow(
        decision(),
        minute_missing,
        portfolio(),
        settings(),
        proposal_id="shadow-008",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.reasons == ("intraday_signal_unavailable",)


def test_shadow_pipeline_rejects_intraday_entry_outside_window() -> None:
    outside_window = evidence()
    outside_window["intraday_signal"] = {
        "status": "available",
        "lookahead_safe": True,
        "regime": "bullish",
        "entry_allowed": False,
    }

    result = evaluate_shadow(
        decision(),
        outside_window,
        portfolio(),
        settings(),
        proposal_id="shadow-009",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.reasons == ("intraday_entry_not_allowed",)


def test_shadow_pipeline_rejects_low_ai_confidence() -> None:
    low_confidence = replace(decision(), confidence=Decimal("0.64"))

    result = evaluate_shadow(
        low_confidence,
        evidence(),
        portfolio(),
        settings(),
        proposal_id="shadow-007",
    )

    assert result.status == "risk_rejected"
    assert result.risk_decision.reasons == ("ai_confidence_below_threshold",)
