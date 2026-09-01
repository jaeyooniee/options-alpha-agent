import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from options_alpha_agent.ai import AuditLog
from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState
from options_alpha_agent.orchestration import run_shadow_cycle

NOW = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)


def settings(tmp_path: Path) -> Settings:
    return Settings(
        alpaca_api_key="paper-key",
        alpaca_secret_key="paper-secret",
        openai_api_key=None,
        alpaca_paper=True,
        trade_execution_enabled=False,
        starting_equity_usd=Decimal("100000"),
        max_risk_per_trade_pct=Decimal("0.02"),
        max_portfolio_risk_pct=Decimal("0.10"),
        max_daily_drawdown_pct=Decimal("0.04"),
        max_open_positions=5,
        ai_audit_log_path=str(tmp_path / "cycle.jsonl"),
    )


def bars() -> list[SimpleNamespace]:
    origin = datetime(2026, 7, 25, tzinfo=UTC)
    return [
        SimpleNamespace(timestamp=origin + timedelta(days=index), close=740 + index * 2)
        for index in range(35)
    ]


def minute_bars() -> list[SimpleNamespace]:
    origin = NOW - timedelta(minutes=34)
    closes = [100 + index * 0.2 for index in range(27)] + [
        104.6,
        104.1,
        103.6,
        103.1,
        102.8,
        102.9,
        103.1,
        103.3,
    ]
    return [
        SimpleNamespace(timestamp=origin + timedelta(minutes=index), close=close)
        for index, close in enumerate(closes)
    ]


def contracts() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            symbol=symbol,
            type=option_type,
            strike_price=strike,
            expiration_date=date(2026, 9, 5),
            open_interest=1000,
        )
        for symbol, option_type, strike in (
            ("SPY260905C00780000", "call", "780"),
            ("SPY260905C00800000", "call", "800"),
            ("SPY260905P00780000", "put", "780"),
            ("SPY260905P00760000", "put", "760"),
        )
    ]


def snapshots() -> dict[str, SimpleNamespace]:
    quotes = {
        "SPY260905C00780000": ("7.00", "7.50"),
        "SPY260905C00800000": ("2.50", "2.80"),
        "SPY260905P00780000": ("7.00", "7.50"),
        "SPY260905P00760000": ("2.50", "2.80"),
    }
    return {
        symbol: SimpleNamespace(
            latest_quote=SimpleNamespace(
                bid_price=bid,
                ask_price=ask,
                timestamp=NOW - timedelta(seconds=30),
            )
        )
        for symbol, (bid, ask) in quotes.items()
    }


class FakeStockClient:
    def get_stock_latest_quote(self, request: object) -> dict[str, SimpleNamespace]:
        return {
            "SPY": SimpleNamespace(
                bid_price="779",
                ask_price="781",
                timestamp=NOW - timedelta(seconds=30),
            )
        }

    def get_stock_bars(self, request: object) -> SimpleNamespace:
        return SimpleNamespace(
            data={"SPY": minute_bars() if request.timeframe == "minute" else bars()}
        )


class NeutralMinuteStockClient(FakeStockClient):
    def get_stock_bars(self, request: object) -> SimpleNamespace:
        if request.timeframe != "minute":
            return super().get_stock_bars(request)
        origin = NOW - timedelta(minutes=34)
        flat_bars = [
            SimpleNamespace(timestamp=origin + timedelta(minutes=index), close=780)
            for index in range(35)
        ]
        return SimpleNamespace(data={"SPY": flat_bars})


class FakeOptionClient:
    def get_option_chain(self, request: object) -> dict[str, SimpleNamespace]:
        return snapshots()


class FakeTradingClient:
    def get_option_contracts(self, request: object) -> SimpleNamespace:
        return SimpleNamespace(option_contracts=contracts(), next_page_token=None)


class FakeAIClient:
    def __init__(self) -> None:
        self.calls = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "action": "PROPOSE_TRADE",
                                "underlying": "SPY",
                                "strategy": "call_debit_spread",
                                "confidence": 0.8,
                                "thesis": "Bullish synthetic fixture.",
                                "evidence": ["bullish regime", "liquid candidates"],
                                "rejected_alternatives": ["long_call"],
                                "invalidation_conditions": ["stale quote"],
                                "quantity": 1,
                                "max_loss_usd": 500,
                                "net_debit_usd": 500,
                            }
                        )
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )


def test_live_shaped_shadow_cycle_reaches_preview_without_broker_call(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "cycle.jsonl")
    ai_client = FakeAIClient()
    evidence, outcome, evaluation = run_shadow_cycle(
        settings(tmp_path),
        PortfolioState(
            equity_usd=Decimal("100000"),
            start_of_day_equity_usd=Decimal("100000"),
            deployed_risk_usd=Decimal("0"),
            open_positions=0,
        ),
        now=NOW,
        market_open=True,
        audit_log=audit,
        ai_client=ai_client,
        trading_client=FakeTradingClient(),
        stock_client=FakeStockClient(),
        option_client=FakeOptionClient(),
    )

    assert evidence["market_data_available"] is True
    assert evidence["signal"]["regime"] == "bullish"
    assert evidence["intraday_signal"]["regime"] == "bullish"
    assert evidence["intraday_signal"]["entry_allowed"] is True
    assert len(evidence["candidate_catalog"]) == 4
    assert ai_client.calls == 1
    assert outcome.provider_status == "ok"
    assert evaluation.status == "preview_ready"
    assert evaluation.order_preview["order_class"] == "mleg"
    assert evaluation.order_preview["sent"] is False
    assert [event["event_type"] for event in audit.events()] == [
        "ai_decision",
        "shadow_risk_decision",
    ]


def test_minute_scan_abstains_without_calling_ai_when_confirmation_is_neutral(
    tmp_path: Path,
) -> None:
    audit = AuditLog(tmp_path / "minute-abstention.jsonl")
    ai_client = FakeAIClient()
    evidence, outcome, evaluation = run_shadow_cycle(
        settings(tmp_path),
        PortfolioState(
            equity_usd=Decimal("100000"),
            start_of_day_equity_usd=Decimal("100000"),
            deployed_risk_usd=Decimal("0"),
            open_positions=0,
        ),
        now=NOW,
        market_open=True,
        audit_log=audit,
        ai_client=ai_client,
        trading_client=FakeTradingClient(),
        stock_client=NeutralMinuteStockClient(),
        option_client=FakeOptionClient(),
    )

    assert evidence["intraday_signal"]["entry_allowed"] is False
    assert ai_client.calls == 0
    assert outcome.error_type == "MinuteEntryNotEligible"
    assert evaluation.status == "no_trade"
    assert [event["event_type"] for event in audit.events()] == [
        "minute_scan_abstention",
        "shadow_risk_decision",
    ]
