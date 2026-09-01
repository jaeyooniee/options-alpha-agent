from datetime import UTC, datetime, timedelta

from options_alpha_agent.signals import SignalError, analyze_bars, analyze_intraday_bars


def bars(start: str, closes: list[str]) -> list[dict[str, object]]:
    origin = datetime.fromisoformat(start).replace(tzinfo=UTC)
    return [
        {"timestamp": origin + timedelta(days=index), "close": close}
        for index, close in enumerate(closes)
    ]


def test_bullish_signal_is_deterministic_and_lookahead_safe() -> None:
    close_values = [str(100 + index) for index in range(35)]

    first = analyze_bars(bars("2026-08-01T00:00:00", close_values))
    second = analyze_bars(bars("2026-08-01T00:00:00", close_values))

    assert first == second
    assert first.regime == "bullish"
    assert first.recommended_strategy == "call_debit_spread"
    assert first.lookahead_safe is True


def test_bearish_signal_recommends_put_spread() -> None:
    close_values = [str(200 - index) for index in range(35)]

    result = analyze_bars(bars("2026-08-01T00:00:00", close_values))

    assert result.regime == "bearish"
    assert result.recommended_strategy == "put_debit_spread"


def test_signal_filters_future_bars() -> None:
    close_values = [str(100 + index) for index in range(35)]
    series = bars("2026-08-01T00:00:00", close_values)

    result = analyze_bars(
        series,
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        minimum_bars=21,
    )

    assert result.bar_count == 32
    assert result.as_of.startswith("2026-09-01")


def test_signal_requires_enough_history() -> None:
    try:
        analyze_bars(bars("2026-08-01T00:00:00", ["100"] * 20))
    except SignalError as exc:
        assert "at least" in str(exc)
    else:
        raise AssertionError("short history must fail closed")


def test_minute_signal_requires_alignment_and_entry_window() -> None:
    origin = datetime(2026, 8, 29, 14, 45, tzinfo=UTC)  # 10:45 in New York.
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
    minute_bars = [
        {"timestamp": origin + timedelta(minutes=index), "close": str(close)}
        for index, close in enumerate(closes)
    ]

    result = analyze_intraday_bars(minute_bars)

    assert result.regime == "bullish"
    assert result.recommended_strategy == "call_debit_spread"
    assert result.entry_allowed is True
    assert result.z_score_20 <= -0.5
    assert result.momentum_1 > 0
    assert result.lookahead_safe is True
