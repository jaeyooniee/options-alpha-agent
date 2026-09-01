from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from options_alpha_agent.walk_forward import (
    WalkForwardInputError,
    evaluate_walk_forward,
    load_bars_csv,
)


def rising_bars(count: int = 40) -> list[dict[str, object]]:
    origin = datetime(2026, 1, 2, 21, 0, tzinfo=UTC)
    return [
        {
            "timestamp": origin + timedelta(days=index),
            "close": str(100 + index),
        }
        for index in range(count)
    ]


def test_walk_forward_uses_past_history_and_future_only_as_target() -> None:
    baseline = evaluate_walk_forward(rising_bars(35), horizon_bars=3, holdout_bars=6)
    extended = evaluate_walk_forward(rising_bars(40), horizon_bars=3, holdout_bars=6)

    assert baseline.lookahead_safe is True
    assert baseline.directional_points > 0
    assert baseline.directional_hit_rate == 1
    assert extended.points[: len(baseline.points)] == baseline.points
    assert baseline.points[0].target_timestamp > baseline.points[0].as_of
    assert baseline.points[0].forward_close_usd > baseline.points[0].close_usd
    assert baseline.holdout_bars == 6
    assert baseline.holdout_points > 0
    assert baseline.holdout_directional_hit_rate == 1
    assert baseline.holdout_mean_signed_return > 0


def test_walk_forward_rejects_insufficient_history() -> None:
    with pytest.raises(WalkForwardInputError, match="not enough bars"):
        evaluate_walk_forward(rising_bars(32), horizon_bars=3)


def test_walk_forward_rejects_holdout_shorter_than_horizon() -> None:
    with pytest.raises(WalkForwardInputError, match="holdout_bars"):
        evaluate_walk_forward(rising_bars(40), horizon_bars=3, holdout_bars=2)


def test_walk_forward_csv_loader_requires_timezone_and_columns(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    path.write_text(
        "timestamp,close\n2026-01-02T21:00:00+00:00,100\n2026-01-03T21:00:00+00:00,101\n",
        encoding="utf-8",
    )

    assert len(load_bars_csv(path)) == 2

    path.write_text("timestamp,close\n2026-01-02T21:00:00,100\n", encoding="utf-8")
    with pytest.raises(WalkForwardInputError, match="timezone"):
        load_bars_csv(path)
