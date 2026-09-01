"""Look-ahead-safe underlying-bar walk-forward evaluation for research."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from options_alpha_agent.signals import SignalBar, SignalError, analyze_bars, normalize_bars


class WalkForwardInputError(ValueError):
    """Raised when a walk-forward input cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class WalkForwardPoint:
    as_of: str
    target_timestamp: str
    regime: str
    recommended_strategy: str | None
    close_usd: Decimal
    forward_close_usd: Decimal
    forward_return: Decimal
    signed_signal_return: Decimal
    directional_hit: bool | None
    lookahead_safe: bool

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "close_usd",
            "forward_close_usd",
            "forward_return",
            "signed_signal_return",
        ):
            result[key] = str(result[key])
        return result


@dataclass(frozen=True, slots=True)
class WalkForwardSummary:
    research_only: bool
    horizon_bars: int
    minimum_bars: int
    holdout_bars: int
    total_points: int
    directional_points: int
    neutral_points: int
    directional_hit_rate: Decimal
    mean_forward_return: Decimal
    mean_signed_signal_return: Decimal
    cumulative_signed_signal_return: Decimal
    max_signed_return_drawdown: Decimal
    holdout_points: int
    holdout_directional_hit_rate: Decimal
    holdout_mean_signed_return: Decimal
    lookahead_safe: bool
    points: tuple[WalkForwardPoint, ...]

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "directional_hit_rate",
            "mean_forward_return",
            "mean_signed_signal_return",
            "cumulative_signed_signal_return",
            "max_signed_return_drawdown",
            "holdout_directional_hit_rate",
            "holdout_mean_signed_return",
        ):
            result[key] = str(result[key])
        result["points"] = [point.public_dict() for point in self.points]
        return result


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise WalkForwardInputError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise WalkForwardInputError(f"{field_name} must be positive and finite")
    return parsed


def load_bars_csv(path: str | Path) -> list[SignalBar]:
    """Load a timestamp/close CSV into normalized, sorted bars."""

    csv_path = Path(path)
    if not csv_path.is_file():
        raise WalkForwardInputError("underlying bars CSV does not exist")
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not {"timestamp", "close"}.issubset(reader.fieldnames):
                raise WalkForwardInputError("underlying bars CSV requires timestamp and close")
            rows = []
            for row in reader:
                timestamp = row.get("timestamp")
                if not isinstance(timestamp, str) or not timestamp.strip():
                    raise WalkForwardInputError("timestamp must be an ISO-8601 string")
                try:
                    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise WalkForwardInputError("timestamp must be an ISO-8601 string") from exc
                if parsed_timestamp.tzinfo is None:
                    raise WalkForwardInputError("timestamp must include a timezone")
                rows.append(
                    {
                        "timestamp": timestamp,
                        "close": _decimal(row.get("close"), "close"),
                    }
                )
    except OSError as exc:
        raise WalkForwardInputError("underlying bars CSV could not be read") from exc
    try:
        return normalize_bars(rows)
    except SignalError as exc:
        raise WalkForwardInputError(str(exc)) from exc


def evaluate_walk_forward(
    bars: Iterable[Any],
    *,
    horizon_bars: int = 5,
    minimum_bars: int = 30,
    holdout_bars: int = 0,
) -> WalkForwardSummary:
    """Evaluate each signal using only history available at that signal timestamp."""

    if not 1 <= horizon_bars <= 45:
        raise WalkForwardInputError("horizon_bars must be between 1 and 45")
    if minimum_bars < 21:
        raise WalkForwardInputError("minimum_bars must support the signal windows")
    if holdout_bars < 0:
        raise WalkForwardInputError("holdout_bars cannot be negative")
    try:
        normalized = normalize_bars(bars)
    except SignalError as exc:
        raise WalkForwardInputError(str(exc)) from exc
    if len(normalized) < minimum_bars + horizon_bars:
        raise WalkForwardInputError("not enough bars for walk-forward evaluation")
    if holdout_bars and holdout_bars < horizon_bars:
        raise WalkForwardInputError("holdout_bars must be at least horizon_bars")
    if holdout_bars >= len(normalized):
        raise WalkForwardInputError("holdout_bars must leave an in-sample history")

    points: list[WalkForwardPoint] = []
    for index in range(minimum_bars - 1, len(normalized) - horizon_bars):
        history = normalized[: index + 1]
        current = history[-1]
        future = normalized[index + horizon_bars]
        signal = analyze_bars(history, as_of=current.timestamp, minimum_bars=minimum_bars)
        forward_return = future.close / current.close - Decimal("1")
        if signal.regime == "bullish":
            signed_return = forward_return
        elif signal.regime == "bearish":
            signed_return = -forward_return
        else:
            signed_return = Decimal("0")
        directional_hit = None if signal.regime == "neutral" else signed_return > 0
        points.append(
            WalkForwardPoint(
                as_of=current.timestamp.isoformat(),
                target_timestamp=future.timestamp.isoformat(),
                regime=signal.regime,
                recommended_strategy=signal.recommended_strategy,
                close_usd=current.close,
                forward_close_usd=future.close,
                forward_return=forward_return,
                signed_signal_return=signed_return,
                directional_hit=directional_hit,
                lookahead_safe=True,
            )
        )

    directional = [point for point in points if point.directional_hit is not None]
    neutral = len(points) - len(directional)
    signed_returns = [point.signed_signal_return for point in points]
    forward_returns = [point.forward_return for point in points]
    holdout_start_index = len(normalized) - holdout_bars if holdout_bars else len(normalized)
    holdout_points = [
        point
        for index, point in enumerate(points, start=minimum_bars - 1)
        if index >= holdout_start_index
    ]
    holdout_directional = [point for point in holdout_points if point.directional_hit is not None]
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for value in signed_returns:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return WalkForwardSummary(
        research_only=True,
        horizon_bars=horizon_bars,
        minimum_bars=minimum_bars,
        holdout_bars=holdout_bars,
        total_points=len(points),
        directional_points=len(directional),
        neutral_points=neutral,
        directional_hit_rate=(
            Decimal(sum(point.directional_hit is True for point in directional))
            / Decimal(len(directional))
            if directional
            else Decimal("0")
        ),
        mean_forward_return=sum(forward_returns, Decimal("0")) / Decimal(len(points)),
        mean_signed_signal_return=sum(signed_returns, Decimal("0")) / Decimal(len(points)),
        cumulative_signed_signal_return=cumulative,
        max_signed_return_drawdown=max_drawdown,
        holdout_points=len(holdout_points),
        holdout_directional_hit_rate=(
            Decimal(sum(point.directional_hit is True for point in holdout_directional))
            / Decimal(len(holdout_directional))
            if holdout_directional
            else Decimal("0")
        ),
        holdout_mean_signed_return=(
            sum((point.signed_signal_return for point in holdout_points), Decimal("0"))
            / Decimal(len(holdout_points))
            if holdout_points
            else Decimal("0")
        ),
        lookahead_safe=all(point.lookahead_safe for point in points),
        points=tuple(points),
    )
