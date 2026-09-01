from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from options_alpha_agent.market_evidence import (
    alpaca_contract_rows,
    build_market_evidence,
    select_option_candidate,
)

AS_OF = date(2026, 8, 29)


def rows() -> list[dict[str, object]]:
    return [
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


def test_select_option_candidate_reconstructs_defined_risk_debit_spread() -> None:
    candidate = select_option_candidate(
        rows(),
        "call_debit_spread",
        spot=Decimal("780"),
        as_of=AS_OF,
    )

    assert candidate["days_to_expiry"] == 7
    assert candidate["debit_per_share_usd"] == "5.00"
    assert candidate["max_loss_per_share_usd"] == "5.00"
    assert candidate["long_bid_per_share_usd"] == "7.00"
    assert candidate["long_ask_per_share_usd"] == "7.50"
    assert candidate["short_bid_per_share_usd"] == "2.50"
    assert candidate["short_ask_per_share_usd"] == "2.80"
    assert len(candidate["legs"]) == 2


def test_build_market_evidence_exposes_all_allowlisted_candidates() -> None:
    evidence = build_market_evidence("SPY", Decimal("780"), rows(), as_of=AS_OF)

    assert evidence["market_data_available"] is True
    assert set(evidence["candidate_catalog"]) == {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
    }
    assert evidence["candidate_failures"] == {}


def test_wide_or_illiquid_contracts_are_excluded() -> None:
    bad_rows = [
        {
            "symbol": "SPY260905C00780000",
            "option_type": "call",
            "strike": "780",
            "expiration": "2026-09-05",
            "bid": "7.00",
            "ask": "10.00",
            "open_interest": 10,
        }
    ]

    evidence = build_market_evidence("SPY", Decimal("780"), bad_rows, as_of=AS_OF)

    assert evidence["market_data_available"] is False
    assert len(evidence["candidate_failures"]) == 4


def test_alpaca_contract_rows_filters_stale_quotes_and_normalizes_models() -> None:
    now = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
    contracts = [
        SimpleNamespace(
            symbol="SPY260905C00780000",
            type="call",
            strike_price="780",
            expiration_date=date(2026, 9, 5),
            open_interest="1000",
        ),
        SimpleNamespace(
            symbol="SPY260905C00800000",
            type="call",
            strike_price="800",
            expiration_date=date(2026, 9, 5),
            open_interest="1000",
        ),
    ]
    snapshots = {
        "SPY260905C00780000": SimpleNamespace(
            latest_quote=SimpleNamespace(
                bid_price="7.00",
                ask_price="7.50",
                timestamp=now - timedelta(seconds=30),
            ),
            implied_volatility="0.22",
            greeks=SimpleNamespace(delta="0.55", gamma="0.02", vega="0.31"),
        ),
        "SPY260905C00800000": SimpleNamespace(
            latest_quote=SimpleNamespace(
                bid_price="2.50",
                ask_price="3.00",
                timestamp=now - timedelta(seconds=301),
            )
        ),
    }

    rows = alpaca_contract_rows(contracts, snapshots, now=now)

    assert len(rows) == 1
    assert rows[0]["option_type"] == "call"
    assert rows[0]["open_interest"] == 1000
    assert rows[0]["implied_volatility"] == "0.22"
    assert rows[0]["greeks"] == {"delta": "0.55", "gamma": "0.02", "vega": "0.31"}
    assert rows[0]["quote_timestamp"] == (now - timedelta(seconds=30)).isoformat()


def test_alpaca_contract_rows_rejects_future_quotes() -> None:
    now = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
    contract = SimpleNamespace(
        symbol="SPY260905C00780000",
        type="call",
        strike_price="780",
        expiration_date=date(2026, 9, 5),
        open_interest="1000",
    )
    snapshot = SimpleNamespace(
        latest_quote=SimpleNamespace(
            bid_price="7.00",
            ask_price="7.50",
            timestamp=now + timedelta(seconds=61),
        )
    )

    assert alpaca_contract_rows([contract], {contract.symbol: snapshot}, now=now) == []


def test_candidate_carries_optional_iv_and_greeks_evidence() -> None:
    enriched = rows()
    enriched[0]["implied_volatility"] = "0.22"
    enriched[0]["greeks"] = {"delta": "0.55", "theta": "-0.20"}

    candidate = select_option_candidate(
        enriched,
        "long_call",
        spot=Decimal("780"),
        as_of=AS_OF,
    )

    assert candidate["long_implied_volatility"] == "0.22"
    assert candidate["long_greeks"] == {"delta": "0.55", "theta": "-0.20"}
