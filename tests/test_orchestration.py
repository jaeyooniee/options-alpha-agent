from decimal import Decimal
from pathlib import Path

from options_alpha_agent.ai import AuditLog
from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState
from options_alpha_agent.orchestration import run_reconciled_shadow_cycle, run_shadow_cycle


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


def test_missing_market_credentials_fail_closed_without_ai_or_broker_call(
    tmp_path: Path,
) -> None:
    audit = AuditLog(tmp_path / "cycle.jsonl")
    evidence, outcome, evaluation = run_shadow_cycle(
        settings(),
        portfolio(),
        audit_log=audit,
    )

    assert evidence["market_data_available"] is False
    assert outcome.provider_status == "fail_closed"
    assert evaluation.status == "no_trade"
    assert evaluation.order_preview is None
    assert audit.verify() != "GENESIS"
    assert [event["event_type"] for event in audit.events()] == [
        "market_evidence_failure",
        "shadow_risk_decision",
    ]


def test_closed_market_skips_market_data_and_ai(tmp_path: Path) -> None:
    class ExplodingClient:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"closed market must not call {name}")

    audit = AuditLog(tmp_path / "closed.jsonl")
    evidence, outcome, evaluation = run_shadow_cycle(
        settings(),
        portfolio(),
        audit_log=audit,
        market_open=False,
        ai_client=ExplodingClient(),
        stock_client=ExplodingClient(),
        option_client=ExplodingClient(),
        trading_client=ExplodingClient(),
    )

    assert evidence["market_open"] is False
    assert outcome.provider_status == "fail_closed"
    assert outcome.error_type == "MarketClosed"
    assert evaluation.status == "no_trade"
    assert [event["event_type"] for event in audit.events()] == [
        "market_closed",
        "shadow_risk_decision",
    ]


def test_reconciled_cycle_records_account_before_closed_market_abstention(tmp_path: Path) -> None:
    class ClosedPaperClient:
        def get_account(self) -> object:
            return type(
                "Account",
                (),
                {
                    "equity": "100000",
                    "last_equity": "100000",
                    "cash": "100000",
                    "buying_power": "100000",
                },
            )()

        def get_orders(self, request: object) -> list[object]:
            return []

        def get_all_positions(self) -> list[object]:
            return []

        def get_clock(self) -> object:
            return type("Clock", (), {"is_open": False, "next_open": None, "next_close": None})()

    class ExplodingAI:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("closed reconciled cycle must not call AI")

    audit = AuditLog(tmp_path / "reconciled-closed.jsonl")
    reconciliation, evidence, outcome, evaluation = run_reconciled_shadow_cycle(
        settings(),
        audit_log=audit,
        now=None,
        trading_client=ClosedPaperClient(),
        ai_client=ExplodingAI(),
    )

    assert reconciliation.market_open is False
    assert evidence["market_open"] is False
    assert outcome.error_type == "MarketClosed"
    assert evaluation.status == "no_trade"
    assert [event["event_type"] for event in audit.events()] == [
        "account_reconciliation",
        "market_closed",
        "shadow_risk_decision",
    ]


def test_existing_position_blocks_new_ai_entry_for_exit_first_review(tmp_path: Path) -> None:
    class OpenPositionPaperClient:
        def get_account(self) -> object:
            return type(
                "Account",
                (),
                {
                    "equity": "100000",
                    "last_equity": "100000",
                    "cash": "99000",
                    "buying_power": "100000",
                },
            )()

        def get_orders(self, request: object) -> list[object]:
            return []

        def get_all_positions(self) -> list[object]:
            return [
                type(
                    "Position",
                    (),
                    {
                        "symbol": "SPY260904C00765000",
                        "qty": "1",
                        "side": "long",
                        "avg_entry_price": "5.00",
                        "market_value": "500",
                        "unrealized_pl": "0",
                        "unrealized_plpc": "0",
                    },
                )()
            ]

        def get_clock(self) -> object:
            return type("Clock", (), {"is_open": True, "next_open": None, "next_close": None})()

    class ExplodingAI:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("existing position must block the AI entry call")

    audit = AuditLog(tmp_path / "exit-first.jsonl")
    reconciliation, evidence, outcome, evaluation = run_reconciled_shadow_cycle(
        settings(),
        audit_log=audit,
        trading_client=OpenPositionPaperClient(),
        ai_client=ExplodingAI(),
    )

    assert reconciliation.position_count == 1
    assert evidence["source"] == "alpaca_paper_reconciliation_exit_first_gate"
    assert outcome.error_type == "ExistingPositionRequiresExitReview"
    assert evaluation.status == "no_trade"
    assert [event["event_type"] for event in audit.events()] == [
        "account_reconciliation",
        "exit_first_entry_blocked",
        "shadow_risk_decision",
    ]
