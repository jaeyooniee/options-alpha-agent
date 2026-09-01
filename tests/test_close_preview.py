from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from options_alpha_agent.close_preview import ClosePreviewError, build_close_order_preview

NOW = datetime(2026, 8, 31, 14, 15, tzinfo=UTC)


def entry_preview() -> dict[str, object]:
    return {
        "client_order_id": "entry-001",
        "order_class": "mleg",
        "type": "limit",
        "time_in_force": "day",
        "qty": 1,
        "limit_price": "5.00",
        "legs": [
            {"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1},
            {"symbol": "SPY260905C00800000", "side": "sell", "ratio_qty": 1},
        ],
        "paper": True,
        "sent": False,
    }


def candidate(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "long_bid_per_share_usd": "6.00",
        "short_ask_per_share_usd": "2.50",
        "long_quote_timestamp": NOW.isoformat(),
        "short_quote_timestamp": NOW.isoformat(),
        "legs": [
            {"symbol": "SPY260905C00780000", "side": "buy", "ratio_qty": 1},
            {"symbol": "SPY260905C00800000", "side": "sell", "ratio_qty": 1},
        ],
    }
    result.update(overrides)
    return result


def test_build_close_preview_inverts_exact_legs_and_never_sends() -> None:
    preview = build_close_order_preview(entry_preview(), candidate(), now=NOW)

    assert preview["order_class"] == "mleg"
    assert preview["limit_price"] == "3.50"
    assert preview["expected_liquidation_value_usd"] == "350.00"
    assert [leg["side"] for leg in preview["legs"]] == ["sell", "buy"]
    assert preview["entry_client_order_id"] == "entry-001"
    assert preview["paper"] is True
    assert preview["sent"] is False


def test_close_preview_rejects_wrong_legs() -> None:
    wrong = candidate()
    wrong["legs"][0]["symbol"] = "SPY260905C00770000"

    with pytest.raises(ClosePreviewError, match="exact entry legs"):
        build_close_order_preview(entry_preview(), wrong, now=NOW)


def test_close_preview_rejects_stale_quote_and_non_credit() -> None:
    stale = candidate(
        long_quote_timestamp=(NOW - timedelta(seconds=301)).isoformat(),
        short_quote_timestamp=(NOW - timedelta(seconds=301)).isoformat(),
    )
    with pytest.raises(ClosePreviewError, match="stale"):
        build_close_order_preview(entry_preview(), stale, now=NOW)

    crossed = candidate(long_bid_per_share_usd="2.00", short_ask_per_share_usd="2.50")
    with pytest.raises(ClosePreviewError, match="positive executable credit"):
        build_close_order_preview(entry_preview(), crossed, now=NOW)


def test_close_preview_is_not_a_broker_request() -> None:
    preview = build_close_order_preview(entry_preview(), candidate(), now=NOW)

    assert "alpaca" not in preview
    assert preview["sent"] is False
    assert Decimal(preview["limit_price"]) > 0
