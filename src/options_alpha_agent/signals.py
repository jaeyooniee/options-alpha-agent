"""Deterministic, look-ahead-safe underlying regime signal layer."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


class SignalError(ValueError):
    """Raised when an underlying bar series cannot support a signal."""


@dataclass(frozen=True, slots=True)
class SignalBar:
    timestamp: datetime
    close: Decimal


@dataclass(frozen=True, slots=True)
class RegimeSignal:
    status: str
    as_of: str
    bar_count: int
    regime: str
    recommended_strategy: str | None
    close: Decimal
    ema_fast: Decimal
    ema_slow: Decimal
    momentum_5: Decimal
    momentum_20: Decimal
    realized_volatility_annualized: Decimal
    score: Decimal
    lookahead_safe: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "bar_count": self.bar_count,
            "regime": self.regime,
            "recommended_strategy": self.recommended_strategy,
            "close": str(self.close),
            "ema_fast": str(self.ema_fast),
            "ema_slow": str(self.ema_slow),
            "momentum_5": str(self.momentum_5),
            "momentum_20": str(self.momentum_20),
            "realized_volatility_annualized": str(self.realized_volatility_annualized),
            "score": str(self.score),
            "lookahead_safe": self.lookahead_safe,
        }


@dataclass(frozen=True, slots=True)
class IntradaySignal:
    """One-minute pullback/reversal signal used to gate short-horizon entries."""

    status: str
    as_of: str
    bar_count: int
    regime: str
    recommended_strategy: str | None
    entry_allowed: bool
    close: Decimal
    ema_fast: Decimal
    ema_slow: Decimal
    momentum_3: Decimal
    momentum_10: Decimal
    momentum_1: Decimal
    z_score_20: Decimal
    score: Decimal
    lookahead_safe: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "bar_count": self.bar_count,
            "regime": self.regime,
            "recommended_strategy": self.recommended_strategy,
            "entry_allowed": self.entry_allowed,
            "close": str(self.close),
            "ema_fast": str(self.ema_fast),
            "ema_slow": str(self.ema_slow),
            "momentum_3": str(self.momentum_3),
            "momentum_10": str(self.momentum_10),
            "momentum_1": str(self.momentum_1),
            "z_score_20": str(self.z_score_20),
            "score": str(self.score),
            "lookahead_safe": self.lookahead_safe,
        }


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SignalError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise SignalError(f"{field_name} must be finite")
    return parsed


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SignalError("bar timestamp must be ISO-8601") from exc
    else:
        raise SignalError("bar timestamp is missing")
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_bars(bars: Iterable[Any], *, as_of: datetime | None = None) -> list[SignalBar]:
    """Normalize and sort bars, discarding bars after the evaluation timestamp."""

    cutoff = None
    if as_of is not None:
        cutoff = as_of.astimezone(UTC) if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    normalized: list[SignalBar] = []
    for raw in bars:
        raw_timestamp = _field(raw, "timestamp")
        if raw_timestamp is None:
            raw_timestamp = _field(raw, "t")
        timestamp = _timestamp(raw_timestamp)
        if cutoff is not None and timestamp > cutoff:
            continue
        raw_close = _field(raw, "close")
        if raw_close is None:
            raw_close = _field(raw, "c")
        close = _decimal(raw_close, "close")
        if close <= 0:
            raise SignalError("bar close must be positive")
        normalized.append(SignalBar(timestamp, close))
    normalized.sort(key=lambda bar: bar.timestamp)
    deduped: list[SignalBar] = []
    for bar in normalized:
        if deduped and bar.timestamp == deduped[-1].timestamp:
            deduped[-1] = bar
        else:
            deduped.append(bar)
    return deduped


def _ema(values: list[Decimal], period: int) -> Decimal:
    alpha = Decimal("2") / Decimal(period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = alpha * value + (Decimal("1") - alpha) * ema
    return ema


def analyze_bars(
    bars: Iterable[Any],
    *,
    as_of: datetime | None = None,
    minimum_bars: int = 30,
) -> RegimeSignal:
    """Compute a regime using only bars at or before ``as_of``."""

    if minimum_bars < 21:
        raise SignalError("minimum_bars must support the slow EMA and momentum window")
    normalized = normalize_bars(bars, as_of=as_of)
    if len(normalized) < minimum_bars:
        raise SignalError(f"at least {minimum_bars} bars are required")
    closes = [bar.close for bar in normalized]
    current = closes[-1]
    ema_fast = _ema(closes, 8)
    ema_slow = _ema(closes, 21)
    momentum_5 = current / closes[-6] - Decimal("1")
    momentum_20 = current / closes[-21] - Decimal("1")
    returns = [closes[index] / closes[index - 1] - Decimal("1") for index in range(1, len(closes))]
    recent_returns = returns[-20:]
    mean_return = sum(recent_returns, Decimal("0")) / Decimal(len(recent_returns))
    variance = sum((item - mean_return) ** 2 for item in recent_returns) / Decimal(
        len(recent_returns) - 1
    )
    annualized_vol = (variance * Decimal("252")).sqrt()
    trend_gap = (ema_fast - ema_slow) / current
    score = trend_gap * Decimal("10") + momentum_5 * Decimal("2") + momentum_20
    if current > ema_fast > ema_slow and momentum_5 > 0 and momentum_20 > 0:
        regime = "bullish"
        recommended = "call_debit_spread"
    elif current < ema_fast < ema_slow and momentum_5 < 0 and momentum_20 < 0:
        regime = "bearish"
        recommended = "put_debit_spread"
    else:
        regime = "neutral"
        recommended = None
    timestamp = normalized[-1].timestamp
    return RegimeSignal(
        status="available",
        as_of=timestamp.isoformat(),
        bar_count=len(normalized),
        regime=regime,
        recommended_strategy=recommended,
        close=current,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        momentum_5=momentum_5,
        momentum_20=momentum_20,
        realized_volatility_annualized=annualized_vol,
        score=score,
        lookahead_safe=True,
    )


def analyze_intraday_bars(
    bars: Iterable[Any],
    *,
    as_of: datetime | None = None,
    minimum_bars: int = 30,
) -> IntradaySignal:
    """Find a short-horizon pullback/reversal setup without using future bars.

    This mirrors the useful part of the Career26 fast loop without pretending a
    free indicative option feed can sustain sub-second chain scans. A bullish
    setup requires a statistically discounted current minute and a one-minute
    rebound; a bearish setup is symmetric. The 5/20-minute EMA context is
    recorded for audit, while the daily signal is the separate directional veto
    in orchestration. This avoids waiting for a completed EMA crossover after a
    short pullback has already started to rebound.

    The minute layer is an entry gate, not an alpha claim. It permits a new
    entry only from 09:45 through 15:30 New York time; the worker must abstain
    outside that window or when no completed pullback/reversal exists.
    """

    if minimum_bars < 21:
        raise SignalError("minimum_bars must support the slow EMA and momentum window")
    normalized = normalize_bars(bars, as_of=as_of)
    if len(normalized) < minimum_bars:
        raise SignalError(f"at least {minimum_bars} minute bars are required")
    closes = [bar.close for bar in normalized]
    current = closes[-1]
    ema_fast = _ema(closes, 5)
    ema_slow = _ema(closes, 20)
    recent_closes = closes[-20:]
    mean_close = sum(recent_closes, Decimal("0")) / Decimal(len(recent_closes))
    variance = sum((value - mean_close) ** 2 for value in recent_closes) / Decimal(
        len(recent_closes) - 1
    )
    standard_deviation = variance.sqrt()
    momentum_3 = current / closes[-4] - Decimal("1")
    momentum_10 = current / closes[-11] - Decimal("1")
    momentum_1 = current / closes[-2] - Decimal("1")
    z_score_20 = (
        (current - mean_close) / standard_deviation if standard_deviation > 0 else Decimal("0")
    )
    trend_gap = (ema_fast - ema_slow) / current
    score = trend_gap * Decimal("100") - z_score_20 + momentum_1 * Decimal("100")
    if z_score_20 <= Decimal("-0.50") and momentum_1 > 0:
        regime = "bullish"
        recommended = "call_debit_spread"
    elif z_score_20 >= Decimal("0.50") and momentum_1 < 0:
        regime = "bearish"
        recommended = "put_debit_spread"
    else:
        regime = "neutral"
        recommended = None
    timestamp = normalized[-1].timestamp
    eastern_time = timestamp.astimezone(ZoneInfo("America/New_York")).time()
    entry_window = time(9, 45) <= eastern_time < time(15, 30)
    return IntradaySignal(
        status="available",
        as_of=timestamp.isoformat(),
        bar_count=len(normalized),
        regime=regime,
        recommended_strategy=recommended,
        entry_allowed=entry_window and regime != "neutral",
        close=current,
        ema_fast=ema_fast,
        ema_slow=ema_slow,
        momentum_3=momentum_3,
        momentum_10=momentum_10,
        momentum_1=momentum_1,
        z_score_20=z_score_20,
        score=score,
        lookahead_safe=True,
    )
