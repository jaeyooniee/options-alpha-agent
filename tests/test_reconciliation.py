from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from options_alpha_agent.ai import AuditLog
from options_alpha_agent.config import Settings
from options_alpha_agent.reconciliation import (
    append_reconciliation_audit,
    reconcile_paper_account,
)


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


class FakeClient:
    def get_account(self) -> SimpleNamespace:
        return SimpleNamespace(
            equity="100250",
            last_equity="100000",
            cash="99500",
            buying_power="399500",
        )

    def get_orders(self, request: object) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id="private-broker-order-id-filled",
                client_order_id="shadow-order-001",
                status="filled",
                qty="1",
                filled_qty="1",
                filled_avg_price="7.50",
                submitted_at="2026-08-29T14:30:00Z",
                filled_at="2026-08-29T14:30:01Z",
            ),
            SimpleNamespace(
                id="private-broker-order-id-new",
                client_order_id="shadow-order-002",
                status="new",
                qty="2",
                filled_qty="0",
                filled_avg_price=None,
            ),
            SimpleNamespace(
                id="private-broker-order-id-canceled",
                client_order_id="shadow-order-003",
                status="canceled",
            ),
        ]

    def get_all_positions(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                symbol="SPY260905C00780000",
                qty="1",
                side="long",
                avg_entry_price="7.50",
                market_value="800",
                unrealized_pl="50",
                unrealized_plpc="0.0667",
            )
        ]

    def get_clock(self) -> SimpleNamespace:
        return SimpleNamespace(
            is_open=True,
            next_open="2026-08-30T13:30:00+00:00",
            next_close="2026-08-29T20:00:00+00:00",
        )


def test_reconciliation_returns_safe_account_pnl_and_market_clock(tmp_path: Path) -> None:
    snapshot = reconcile_paper_account(
        replace(settings(), alpaca_api_key="paper-key", alpaca_secret_key="paper-secret"),
        client=FakeClient(),
    )

    assert snapshot.public_dict()["day_pnl_usd"] == "250"
    assert snapshot.filled_order_count == 1
    assert snapshot.open_order_count == 1
    assert snapshot.position_count == 1
    assert snapshot.market_open is True
    assert snapshot.order_lifecycle_counts == {
        "MANAGE_FILLED_POSITION": 1,
        "WAIT_FOR_FILL": 1,
        "NO_ACTION": 1,
    }
    assert snapshot.orders[0].client_order_id == "shadow-order-001"
    assert snapshot.orders[0].filled_avg_price_usd == "7.50"
    assert snapshot.orders[0].lifecycle_action == "MANAGE_FILLED_POSITION"
    assert snapshot.orders[0].broker_order_ref is not None
    assert snapshot.orders[0].broker_order_ref.startswith("sha256:")
    assert snapshot.orders[0].pnl_attribution == "position_level_only"
    assert snapshot.public_dict()["market_open"] is True
    assert "account-id" not in str(snapshot.public_dict())
    assert "private-broker-order-id-filled" not in str(snapshot.public_dict())

    audit = AuditLog(tmp_path / "audit.jsonl")
    append_reconciliation_audit(snapshot, audit_log=audit)
    assert audit.verify() != "GENESIS"
    assert [event["event_type"] for event in audit.events()] == [
        "paper_order_reconciliation",
        "paper_order_reconciliation",
        "paper_order_reconciliation",
        "account_reconciliation",
    ]
    assert "private-broker-order-id-filled" not in audit.path.read_text(encoding="utf-8")


def test_reconciliation_marks_filled_order_without_valid_price_for_manual_review() -> None:
    class MissingPriceClient(FakeClient):
        def get_orders(self, request: object) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    id="private-broker-order-id-filled",
                    client_order_id="shadow-order-001",
                    status="filled",
                    qty="1",
                    filled_qty="1",
                    filled_avg_price="not-a-price",
                )
            ]

    snapshot = reconcile_paper_account(
        replace(settings(), alpaca_api_key="paper-key", alpaca_secret_key="paper-secret"),
        client=MissingPriceClient(),
    )

    assert snapshot.orders[0].lifecycle_action == "MANUAL_REVIEW"
    assert "filled_average_price_missing_or_invalid" in snapshot.orders[0].lifecycle_reasons
