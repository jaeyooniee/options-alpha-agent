"""Small local command surface for validation and demonstrations."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from options_alpha_agent.ai import (
    AIDecision,
    AIDecisionEngine,
    audit_log_for_settings,
    probe_ai_provider,
)
from options_alpha_agent.alpaca_probe import probe_account
from options_alpha_agent.config import Settings
from options_alpha_agent.dashboard import serve_dashboard
from options_alpha_agent.data_capture import capture_underlying_bars
from options_alpha_agent.execution import submit_paper_order
from options_alpha_agent.market_evidence import build_market_evidence
from options_alpha_agent.models import PortfolioState, TradeProposal
from options_alpha_agent.option_data import collect_market_evidence, probe_option_data
from options_alpha_agent.option_snapshot import (
    capture_option_snapshot,
    load_option_snapshot,
    summarize_option_snapshot,
)
from options_alpha_agent.orchestration import run_reconciled_shadow_cycle
from options_alpha_agent.provenance import file_sha256
from options_alpha_agent.reconciliation import (
    append_reconciliation_audit,
    reconcile_paper_account,
)
from options_alpha_agent.replay import load_replay_csv, replay_observations
from options_alpha_agent.risk import evaluate_trade
from options_alpha_agent.robustness import evaluate_robustness
from options_alpha_agent.run_lock import RunLockError, run_lock_for_settings
from options_alpha_agent.shadow import evaluate_shadow
from options_alpha_agent.shadow_performance import summarize_shadow_performance
from options_alpha_agent.short_shadow import summarize_short_horizon_shadow
from options_alpha_agent.signals import analyze_bars, analyze_intraday_bars
from options_alpha_agent.simulation import SimulationAssumptions, compare_strategies
from options_alpha_agent.snapshot_compare import compare_option_snapshots
from options_alpha_agent.submission_check import submission_report
from options_alpha_agent.walk_forward import evaluate_walk_forward, load_bars_csv


def _doctor() -> int:
    settings = Settings.from_env()
    report: dict[str, object] = {
        "status": "ok",
        "config": {
            "paper_mode": settings.alpaca_paper,
            "execution_enabled": settings.trade_execution_enabled,
            "paper_order_approved": settings.paper_order_approved,
            "trading_kill_switch": settings.trading_kill_switch,
            "has_alpaca_credentials": settings.has_alpaca_credentials,
            "worker_lock_path": settings.worker_lock_path,
            "ai_provider": settings.ai_provider,
            "has_ai_credentials": settings.has_ai_credentials,
            "ai_model": (
                settings.openai_model
                if settings.ai_provider == "openai"
                else settings.featherless_model
            ),
            "starting_equity_usd": str(settings.starting_equity_usd),
        },
    }
    if settings.has_alpaca_credentials:
        try:
            report["account"] = probe_account(settings).public_dict()
            report["option_data"] = probe_option_data(settings).public_dict()
        except Exception as exc:  # noqa: BLE001 - CLI boundary intentionally sanitizes errors
            report["status"] = "failed"
            report["error_type"] = type(exc).__name__
            print(json.dumps(report, indent=2))
            return 1
    print(json.dumps(report, indent=2))
    return 0


def _ai_doctor() -> int:
    settings = Settings.from_env()
    report: dict[str, object] = {
        "status": "ok",
        "execution_enabled": settings.trade_execution_enabled,
        "order_sent": False,
    }
    try:
        report["ai"] = probe_ai_provider(settings)
    except Exception as exc:  # noqa: BLE001 - sanitize errors at the CLI boundary
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        print(json.dumps(report, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


def _market_evidence() -> int:
    settings = Settings.from_env()
    report: dict[str, object] = {
        "status": "ok",
        "execution_enabled": settings.trade_execution_enabled,
        "order_sent": False,
    }
    try:
        report["evidence"] = collect_market_evidence(settings)
    except Exception as exc:  # noqa: BLE001 - sanitize errors at the CLI boundary
        report["status"] = "failed"
        report["error_type"] = type(exc).__name__
        print(json.dumps(report, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


def _capture_bars(underlying: str, output_path: str, days: int, limit: int) -> int:
    settings = Settings.from_env()
    try:
        report = capture_underlying_bars(
            settings,
            underlying,
            output_path,
            days=days,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "read_only_underlying_bar_capture",
                "status": "ok",
                "report": report.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _ai_smoke() -> int:
    settings = Settings.from_env()
    evidence = {
        "underlying": "SPY",
        "purpose": "provider_smoke_test",
        "data_kind": "synthetic_non_trading_fixture",
        "market_data_available": False,
        "option_contracts": [],
        "required_safety_posture": "NO_TRADE when evidence is insufficient",
    }
    audit = audit_log_for_settings(settings)
    outcome = AIDecisionEngine(settings, audit_log=audit).decide(evidence)
    shadow = evaluate_shadow(
        outcome.decision,
        evidence,
        PortfolioState(
            equity_usd=settings.starting_equity_usd,
            start_of_day_equity_usd=settings.starting_equity_usd,
            deployed_risk_usd=Decimal("0"),
            open_positions=0,
        ),
        settings,
        proposal_id=outcome.request_id,
        ai_outcome=outcome,
        audit_log=audit,
    )
    passed = outcome.provider_status == "ok" and outcome.decision.action == "NO_TRADE"
    report = {
        "status": "ok" if passed else "failed",
        "smoke_test": outcome.public_dict(),
        "shadow": shadow.public_dict(),
        "execution_enabled": settings.trade_execution_enabled,
        "order_sent": False,
    }
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


def _shadow_demo() -> int:
    """Exercise proposal reconstruction and MLeg preview without a provider or broker."""

    settings = Settings.from_env()
    decision = AIDecision.from_json(
        json.dumps(
            {
                "action": "PROPOSE_TRADE",
                "underlying": "SPY",
                "strategy": "call_debit_spread",
                "confidence": 0.8,
                "thesis": "Offline bounded-risk preview; no market claim is made.",
                "evidence": ["synthetic fixture"],
                "rejected_alternatives": ["long_call"],
                "invalidation_conditions": ["quote becomes stale"],
                "quantity": 1,
                "max_loss_usd": 750,
                "net_debit_usd": 750,
            }
        )
    )
    evidence = {
        "underlying": "SPY",
        "source": "synthetic_shadow_fixture",
        "timestamp": "2026-08-29T12:00:00Z",
        "signal": {"status": "available", "lookahead_safe": True, "regime": "bullish"},
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
    evaluation = evaluate_shadow(
        decision,
        evidence,
        PortfolioState(
            equity_usd=settings.starting_equity_usd,
            start_of_day_equity_usd=settings.starting_equity_usd,
            deployed_risk_usd=Decimal("0"),
            open_positions=0,
        ),
        settings,
        proposal_id="shadow-demo-001",
        audit_log=audit_log_for_settings(settings),
    )
    print(
        json.dumps(
            {
                "kind": "offline_shadow_demo",
                "result": evaluation.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0 if evaluation.status == "preview_ready" else 1


def _offline_demo() -> int:
    """Run the complete deterministic demo path without network or broker access."""

    settings = Settings.from_env()
    as_of = date(2026, 8, 29)
    origin = datetime(2026, 7, 25, tzinfo=UTC)
    bars = [
        {"timestamp": origin + timedelta(days=index), "close": str(740 + index * 2)}
        for index in range(35)
    ]
    signal = analyze_bars(bars)
    minute_origin = datetime(2026, 8, 29, 14, 45, tzinfo=UTC)
    # An intraday pullback followed by a one-minute rebound. This deliberately
    # exercises the same short-horizon entry gate used by the production path.
    minute_closes = [100 + index * 0.2 for index in range(27)] + [
        104.6,
        104.1,
        103.6,
        103.1,
        102.8,
        102.9,
        103.1,
        103.3,
    ]
    minute_bars = [
        {"timestamp": minute_origin + timedelta(minutes=index), "close": str(close)}
        for index, close in enumerate(minute_closes)
    ]
    intraday_signal = analyze_intraday_bars(minute_bars)
    rows = [
        {
            "symbol": "SPY260905C00780000",
            "option_type": "call",
            "strike": "780",
            "expiration": "2026-09-05",
            "bid": "7.00",
            "ask": "7.50",
            "open_interest": 1000,
        },
        {
            "symbol": "SPY260905C00800000",
            "option_type": "call",
            "strike": "800",
            "expiration": "2026-09-05",
            "bid": "2.50",
            "ask": "2.80",
            "open_interest": 1000,
        },
        {
            "symbol": "SPY260905P00780000",
            "option_type": "put",
            "strike": "780",
            "expiration": "2026-09-05",
            "bid": "7.00",
            "ask": "7.50",
            "open_interest": 1000,
        },
        {
            "symbol": "SPY260905P00760000",
            "option_type": "put",
            "strike": "760",
            "expiration": "2026-09-05",
            "bid": "2.50",
            "ask": "2.80",
            "open_interest": 1000,
        },
    ]
    evidence = build_market_evidence(
        "SPY",
        Decimal("780"),
        rows,
        as_of=as_of,
        source="synthetic_end_to_end_fixture",
        signal=signal.public_dict(),
        intraday_signal=intraday_signal.public_dict(),
    )
    strategy = signal.recommended_strategy
    if strategy is None:
        print(json.dumps({"status": "failed", "error_type": "NeutralSyntheticSignal"}))
        return 1
    candidate = evidence["candidate_catalog"][strategy]
    decision = AIDecision.from_json(
        json.dumps(
            {
                "action": "PROPOSE_TRADE",
                "underlying": "SPY",
                "strategy": strategy,
                "confidence": "0.80",
                "thesis": "Synthetic bullish regime fixture for the non-executing demo.",
                "evidence": ["signal.regime=bullish", "candidate passes quote and OI filters"],
                "rejected_alternatives": ["long_call"],
                "invalidation_conditions": ["signal turns neutral", "quote becomes stale"],
                "quantity": 1,
                "max_loss_usd": str(Decimal(candidate["max_loss_per_share_usd"]) * 100),
                "net_debit_usd": str(Decimal(candidate["debit_per_share_usd"]) * 100),
            }
        )
    )
    evaluation = evaluate_shadow(
        decision,
        evidence,
        PortfolioState(
            equity_usd=settings.starting_equity_usd,
            start_of_day_equity_usd=settings.starting_equity_usd,
            deployed_risk_usd=Decimal("0"),
            open_positions=0,
        ),
        settings,
        proposal_id="offline-demo-001",
        audit_log=audit_log_for_settings(settings),
    )
    report = {
        "status": "ok" if evaluation.status == "preview_ready" else "failed",
        "kind": "offline_end_to_end_demo",
        "not_live_data": True,
        "signal": signal.public_dict(),
        "intraday_signal": intraday_signal.public_dict(),
        "candidate_count": len(evidence["candidate_catalog"]),
        "decision": decision.public_dict(),
        "evaluation": evaluation.public_dict(),
        "execution_enabled": settings.trade_execution_enabled,
        "order_sent": False,
    }
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ok" else 1


def _shadow_cycle(underlying: str) -> int:
    """Run one live-data, non-executing cycle suitable for a scheduled worker."""

    settings = Settings.from_env()
    if not settings.has_alpaca_credentials:
        print(json.dumps({"status": "failed", "error_type": "MissingAlpacaCredentials"}))
        return 1
    try:
        with run_lock_for_settings(settings):
            audit = audit_log_for_settings(settings)
            reconciliation, evidence, outcome, evaluation = run_reconciled_shadow_cycle(
                settings,
                underlying=underlying,
                audit_log=audit,
            )
            execution = submit_paper_order(settings, evaluation, audit_log=audit)
    except RunLockError:
        print(json.dumps({"status": "blocked", "error_type": "WorkerAlreadyRunning"}, indent=2))
        return 1
    except Exception as exc:  # noqa: BLE001 - scheduled worker must fail closed
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    report = {
        "status": "ok",
        "kind": "live_read_only_shadow_cycle",
        "underlying": evidence.get("underlying"),
        "reconciliation": reconciliation.public_dict(),
        "data_fresh": evidence.get("data_fresh"),
        "provider_status": outcome.provider_status,
        "decision": outcome.decision.public_dict(),
        "evaluation": evaluation.public_dict(),
        "execution": execution.public_dict(),
        "execution_enabled": settings.trade_execution_enabled,
        "order_sent": False,
    }
    print(json.dumps(report, indent=2))
    return 0 if evaluation.status in {"no_trade", "preview_ready"} else 1


def _dashboard(host: str, port: int) -> int:
    settings = Settings.from_env()
    try:
        serve_dashboard(settings, host=host, port=port)
    except KeyboardInterrupt:
        return 0
    return 0


def _monitor() -> int:
    settings = Settings.from_env()
    audit = audit_log_for_settings(settings)
    try:
        snapshot = reconcile_paper_account(settings)
        append_reconciliation_audit(snapshot, audit_log=audit)
    except Exception as exc:  # noqa: BLE001 - read-only monitor returns safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "kind": "read_only_paper_account_reconciliation",
                "snapshot": snapshot.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _risk_demo() -> int:
    settings = Settings.from_env()
    portfolio = PortfolioState(
        equity_usd=Decimal("100000"),
        start_of_day_equity_usd=Decimal("100000"),
        deployed_risk_usd=Decimal("2000"),
        open_positions=1,
    )
    proposal = TradeProposal(
        proposal_id="demo-001",
        underlying="SPY",
        strategy="call_debit_spread",
        quantity=1,
        max_loss_usd=Decimal("750"),
        net_debit_usd=Decimal("750"),
        days_to_expiry=7,
        bid_ask_spread_pct=Decimal("0.06"),
        min_open_interest=2500,
        defined_risk=True,
        thesis="Demonstration only; no order is sent.",
    )
    decision = evaluate_trade(proposal, portfolio, settings)
    print(
        json.dumps(
            {
                "risk_allowed": decision.allowed,
                "reasons": decision.reasons,
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _simulate(regime: str, paths: int, seed: int) -> int:
    annual_drift = {"bullish": 0.30, "neutral": 0.0, "bearish": -0.30}[regime]
    assumptions = SimulationAssumptions(
        annual_drift=annual_drift,
        paths=paths,
        seed=seed,
    )
    report = {
        "kind": "reproducible_scenario_simulation",
        "not_a_backtest": True,
        "regime": regime,
        "assumptions": asdict(assumptions),
        "results": [result.public_dict() for result in compare_strategies(assumptions)],
    }
    print(json.dumps(report, indent=2))
    return 0


def _robustness(paths: int, seed: int, days_to_expiry: int) -> int:
    settings = Settings.from_env()
    try:
        report = evaluate_robustness(
            paths=paths,
            seed=seed,
            days_to_expiry=days_to_expiry,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    output = report.public_dict()
    output.update(
        {
            "kind": "reproducible_scenario_robustness",
            "status": "ok",
            "not_a_backtest": True,
            "execution_enabled": settings.trade_execution_enabled,
            "order_sent": False,
        }
    )
    print(json.dumps(output, indent=2))
    return 0


def _replay(
    csv_path: str,
    initial_equity: str,
    entry_slippage_pct: str,
    exit_slippage_pct: str,
    max_quote_age_seconds: int,
) -> int:
    settings = Settings.from_env()
    try:
        observations = load_replay_csv(csv_path)
        summary = replay_observations(
            observations,
            settings,
            initial_equity_usd=Decimal(initial_equity),
            entry_slippage_pct=Decimal(entry_slippage_pct),
            exit_slippage_pct=Decimal(exit_slippage_pct),
            max_quote_age_seconds=max_quote_age_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "normalized_option_replay",
                "status": "ok",
                "dataset_sha256": file_sha256(csv_path),
                "summary": summary.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _walk_forward(csv_path: str, horizon_bars: int, holdout_bars: int) -> int:
    settings = Settings.from_env()
    try:
        bars = load_bars_csv(csv_path)
        summary = evaluate_walk_forward(
            bars,
            horizon_bars=horizon_bars,
            holdout_bars=holdout_bars,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "lookahead_safe_underlying_walk_forward",
                "status": "ok",
                "dataset_sha256": file_sha256(csv_path),
                "summary": summary.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _submission_check() -> int:
    report = submission_report()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ready" else 1


def _shadow_performance(horizon_hours: int) -> int:
    settings = Settings.from_env()
    try:
        audit = audit_log_for_settings(settings)
        summary = summarize_shadow_performance(
            audit.events(),
            horizon_hours=horizon_hours,
        )
    except Exception as exc:  # noqa: BLE001 - CLI emits only the safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "non_executing_shadow_performance",
                "status": "ok",
                "summary": summary.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _short_shadow(minimum_cohorts: int) -> int:
    settings = Settings.from_env()
    try:
        audit = audit_log_for_settings(settings)
        summary = summarize_short_horizon_shadow(audit.events(), minimum_cohorts=minimum_cohorts)
    except Exception as exc:  # noqa: BLE001 - CLI emits only the safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "short_horizon_exact_leg_shadow_validation",
                "status": "ok",
                "summary": summary.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _cloud_preflight() -> int:
    """Validate Cloud Run durability and safety configuration without cloud access."""

    settings = Settings.from_env()
    checks = {
        "durable_backend_gcs": settings.durable_state_backend == "gcs",
        "gcs_bucket_configured": bool(settings.gcs_state_bucket),
        "paper_mode": settings.alpaca_paper,
        "execution_disabled": not settings.trade_execution_enabled,
        "paper_order_approval_disabled": not settings.paper_order_approved,
        "kill_switch_enabled": settings.trading_kill_switch,
    }
    status = "ready" if all(checks.values()) else "not_ready"
    print(
        json.dumps(
            {
                "kind": "cloud_run_preflight",
                "status": status,
                "checks": checks,
                "durable_state": {
                    "backend": settings.durable_state_backend,
                    "gcs_audit_object": settings.gcs_audit_object,
                    "gcs_lock_object": settings.gcs_lock_object,
                    "gcs_lock_ttl_seconds": settings.gcs_lock_ttl_seconds,
                },
                "external_calls": False,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0 if status == "ready" else 1


def _option_snapshot_check(csv_path: str) -> int:
    settings = Settings.from_env()
    try:
        rows = load_option_snapshot(csv_path)
        summary = summarize_option_snapshot(rows)
    except Exception as exc:  # noqa: BLE001 - CLI emits only the safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "read_only_option_snapshot",
                "status": "ok",
                "dataset_sha256": file_sha256(csv_path),
                "summary": summary.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def _capture_option_snapshot(
    underlying: str,
    expiration: str,
    output_path: str,
    strike_window_pct: str,
    max_age_seconds: int,
) -> int:
    settings = Settings.from_env()
    try:
        report = capture_option_snapshot(
            settings,
            underlying,
            expiration,
            output_path,
            strike_window_pct=Decimal(strike_window_pct),
            max_age_seconds=max_age_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - CLI emits only the safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(json.dumps({"status": "ok", "report": report.public_dict()}, indent=2))
    return 0


def _compare_option_snapshots(entry_path: str, exit_path: str) -> int:
    settings = Settings.from_env()
    try:
        comparison = compare_option_snapshots(
            load_option_snapshot(entry_path),
            load_option_snapshot(exit_path),
        )
    except Exception as exc:  # noqa: BLE001 - CLI emits only the safe error type
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "kind": "exact_symbol_option_quote_path",
                "status": "ok",
                "entry_sha256": file_sha256(entry_path),
                "exit_sha256": file_sha256(exit_path),
                "comparison": comparison.public_dict(),
                "execution_enabled": settings.trade_execution_enabled,
                "order_sent": False,
            },
            indent=2,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Options Alpha Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Validate configuration and read account metadata")
    subparsers.add_parser("ai-doctor", help="Validate AI credentials and model without inference")
    subparsers.add_parser("market-evidence", help="Collect read-only paper option evidence")
    capture_bars = subparsers.add_parser(
        "capture-bars", help="Capture read-only IEX daily bars for research"
    )
    capture_bars.add_argument("--underlying", default="SPY")
    capture_bars.add_argument("--output", required=True)
    capture_bars.add_argument("--days", type=int, default=90)
    capture_bars.add_argument("--limit", type=int, default=60)
    subparsers.add_parser("monitor", help="Reconcile paper account and P&L without mutation")
    subparsers.add_parser(
        "cloud-preflight", help="Validate Cloud Run durability settings without cloud access"
    )
    subparsers.add_parser("ai-smoke", help="Run one minimal, non-trading AI decision")
    subparsers.add_parser(
        "shadow-demo", help="Build a risk-checked order preview without sending it"
    )
    subparsers.add_parser(
        "demo", help="Run the complete deterministic offline demo without network access"
    )
    shadow_cycle = subparsers.add_parser(
        "shadow-cycle", help="Run one live-data, non-executing shadow cycle"
    )
    shadow_cycle.add_argument("--underlying", default="SPY")
    dashboard = subparsers.add_parser("dashboard", help="Serve the read-only safety dashboard")
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8501)
    subparsers.add_parser("risk-demo", help="Run an offline pre-trade risk demonstration")
    simulate = subparsers.add_parser(
        "simulate", help="Compare defined-risk strategies on reproducible price paths"
    )
    simulate.add_argument("--regime", choices=("bullish", "neutral", "bearish"), default="neutral")
    simulate.add_argument("--paths", type=int, default=5000)
    simulate.add_argument("--seed", type=int, default=20260829)
    robustness = subparsers.add_parser(
        "robustness", help="Sweep allowlisted strategies across reproducible stress cases"
    )
    robustness.add_argument("--paths", type=int, default=1000)
    robustness.add_argument("--seed", type=int, default=20260829)
    robustness.add_argument("--days-to-expiry", type=int, default=7)
    replay = subparsers.add_parser(
        "replay", help="Evaluate normalized option observations without broker access"
    )
    replay.add_argument("--csv", required=True, help="CSV with normalized entry/exit observations")
    replay.add_argument("--initial-equity", default="100000")
    replay.add_argument("--entry-slippage-pct", default="0.03")
    replay.add_argument("--exit-slippage-pct", default="0.03")
    replay.add_argument("--max-quote-age-seconds", type=int, default=300)
    walk_forward = subparsers.add_parser(
        "walk-forward", help="Evaluate a timestamp/close CSV without look-ahead"
    )
    walk_forward.add_argument("--csv", required=True, help="CSV with timestamp and close columns")
    walk_forward.add_argument("--horizon-bars", type=int, default=5)
    walk_forward.add_argument(
        "--holdout-bars",
        type=int,
        default=0,
        help="Reserve the final N bars as an out-of-sample reporting window",
    )
    shadow_performance = subparsers.add_parser(
        "shadow-performance",
        help="Reconstruct conservative virtual P&L from the verified audit log",
    )
    shadow_performance.add_argument("--horizon-hours", type=int, default=24)
    short_shadow = subparsers.add_parser(
        "short-shadow",
        help="Evaluate exact-leg Alpaca shadow marks at 1, 5, and 15 minutes",
    )
    short_shadow.add_argument("--minimum-cohorts", type=int, default=10)
    option_snapshot = subparsers.add_parser(
        "option-snapshot-check",
        help="Validate a versioned read-only option-chain snapshot",
    )
    option_snapshot.add_argument("--csv", required=True)
    capture_option_snapshot_parser = subparsers.add_parser(
        "capture-option-snapshot",
        help="Capture one immutable read-only IEX/indicative option snapshot",
    )
    capture_option_snapshot_parser.add_argument("--underlying", default="SPY")
    capture_option_snapshot_parser.add_argument("--expiration", required=True)
    capture_option_snapshot_parser.add_argument("--output", required=True)
    capture_option_snapshot_parser.add_argument("--strike-window-pct", default="0.02")
    capture_option_snapshot_parser.add_argument("--max-age-seconds", type=int, default=300)
    compare_option_snapshot_parser = subparsers.add_parser(
        "option-snapshot-compare",
        help="Compare two exact-symbol option snapshots with conservative quote sides",
    )
    compare_option_snapshot_parser.add_argument("--entry", required=True)
    compare_option_snapshot_parser.add_argument("--exit", required=True)
    subparsers.add_parser(
        "submission-check", help="Check local submission artifacts without publishing"
    )
    args = parser.parse_args()

    if args.command == "doctor":
        return _doctor()
    if args.command == "ai-doctor":
        return _ai_doctor()
    if args.command == "market-evidence":
        return _market_evidence()
    if args.command == "capture-bars":
        return _capture_bars(args.underlying, args.output, args.days, args.limit)
    if args.command == "monitor":
        return _monitor()
    if args.command == "cloud-preflight":
        return _cloud_preflight()
    if args.command == "ai-smoke":
        return _ai_smoke()
    if args.command == "shadow-demo":
        return _shadow_demo()
    if args.command == "demo":
        return _offline_demo()
    if args.command == "shadow-cycle":
        return _shadow_cycle(args.underlying)
    if args.command == "dashboard":
        return _dashboard(args.host, args.port)
    if args.command == "risk-demo":
        return _risk_demo()
    if args.command == "simulate":
        return _simulate(args.regime, args.paths, args.seed)
    if args.command == "robustness":
        return _robustness(args.paths, args.seed, args.days_to_expiry)
    if args.command == "replay":
        return _replay(
            args.csv,
            args.initial_equity,
            args.entry_slippage_pct,
            args.exit_slippage_pct,
            args.max_quote_age_seconds,
        )
    if args.command == "walk-forward":
        return _walk_forward(args.csv, args.horizon_bars, args.holdout_bars)
    if args.command == "shadow-performance":
        return _shadow_performance(args.horizon_hours)
    if args.command == "short-shadow":
        return _short_shadow(args.minimum_cohorts)
    if args.command == "option-snapshot-check":
        return _option_snapshot_check(args.csv)
    if args.command == "capture-option-snapshot":
        return _capture_option_snapshot(
            args.underlying,
            args.expiration,
            args.output,
            args.strike_window_pct,
            args.max_age_seconds,
        )
    if args.command == "option-snapshot-compare":
        return _compare_option_snapshots(args.entry, args.exit)
    if args.command == "submission-check":
        return _submission_check()
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
