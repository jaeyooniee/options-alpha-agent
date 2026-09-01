"""Short-horizon, exact-leg shadow validation.

This module evaluates one-minute live shadow audit events at 1, 5, and 15
minutes after a preview-ready decision. It is research-only: it never imports
an Alpaca trading client, never sends an order, and only accepts the verified
Alpaca shadow source. Entry uses the recorded debit; liquidation uses the
adverse executable quote sides for the exact same option legs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from options_alpha_agent.market_evidence import MAX_CLOCK_SKEW_SECONDS
from options_alpha_agent.shadow_performance import (
    ALPACA_SHADOW_SOURCE,
    ShadowCohort,
    _candidate_for_strategy,
    _leg_symbols,
    _liquidation_value,
    _opening_from_event,
    _timestamp,
)

DEFAULT_HORIZONS_MINUTES = (1, 5, 15)
DEFAULT_MINIMUM_COHORTS = 10
MAX_MARK_LAG_MINUTES = 2


@dataclass(frozen=True, slots=True)
class ShortHorizonMetric:
    horizon_minutes: int
    opened_cohorts: int
    closed_cohorts: int
    unmarked_cohorts: int
    positive_cohorts: int
    win_rate: Decimal
    mean_pnl_usd: Decimal
    total_pnl_usd: Decimal
    mean_return_on_max_loss: Decimal | None
    mark_coverage: Decimal
    sufficient_sample: bool
    positive_mean: bool

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "win_rate",
            "mean_pnl_usd",
            "total_pnl_usd",
            "mean_return_on_max_loss",
            "mark_coverage",
        ):
            result[key] = str(result[key]) if result[key] is not None else None
        return result


@dataclass(frozen=True, slots=True)
class ShortHorizonValidationSummary:
    research_only: bool
    source: str
    observed_events: int
    preview_openings: int
    minimum_cohorts: int
    max_mark_lag_minutes: int
    horizons: tuple[ShortHorizonMetric, ...]
    recommended_action: str
    order_sent: bool

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["horizons"] = [metric.public_dict() for metric in self.horizons]
        return result


def _valid_mark(
    event: Mapping[str, Any],
    cohort: ShadowCohort,
    *,
    target_time: datetime,
) -> tuple[datetime, Decimal] | None:
    event_time = _timestamp(event.get("timestamp"))
    evidence = event.get("evidence")
    if (
        event_time is None
        or event_time < target_time
        or event_time > target_time + timedelta(minutes=MAX_MARK_LAG_MINUTES)
        or not isinstance(evidence, Mapping)
        or evidence.get("source") != ALPACA_SHADOW_SOURCE
        or evidence.get("data_fresh") is not True
    ):
        return None
    candidate = _candidate_for_strategy(evidence, cohort.strategy)
    if candidate is None or _leg_symbols(candidate) != cohort.leg_symbols:
        return None
    quote_times = [
        _timestamp(candidate.get("long_quote_timestamp")),
        _timestamp(candidate.get("short_quote_timestamp")),
    ]
    if any(
        quote_time is None
        or quote_time < target_time - timedelta(minutes=MAX_MARK_LAG_MINUTES)
        or quote_time > target_time + timedelta(minutes=MAX_MARK_LAG_MINUTES)
        or quote_time > event_time + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
        for quote_time in quote_times
    ):
        return None
    liquidation = _liquidation_value(candidate, quantity=cohort.quantity)
    if liquidation is None:
        return None
    return event_time, max(-cohort.max_loss_usd, liquidation - cohort.entry_debit_usd)


def _metric_for_horizon(
    cohorts: list[ShadowCohort],
    events: list[Mapping[str, Any]],
    horizon_minutes: int,
    *,
    minimum_cohorts: int,
) -> ShortHorizonMetric:
    pnls: list[Decimal] = []
    for cohort in cohorts:
        opened_at = _timestamp(cohort.opened_at)
        if opened_at is None:
            continue
        target = opened_at + timedelta(minutes=horizon_minutes)
        marks = (
            mark
            for event in events
            if (mark := _valid_mark(event, cohort, target_time=target)) is not None
        )
        first_mark = next(iter(marks), None)
        if first_mark is not None:
            pnls.append(first_mark[1])
    closed = len(pnls)
    opened = len(cohorts)
    positive = sum(pnl > 0 for pnl in pnls)
    total = sum(pnls, Decimal("0"))
    max_loss = sum((cohort.max_loss_usd for cohort in cohorts), Decimal("0"))
    return ShortHorizonMetric(
        horizon_minutes=horizon_minutes,
        opened_cohorts=opened,
        closed_cohorts=closed,
        unmarked_cohorts=opened - closed,
        positive_cohorts=positive,
        win_rate=Decimal(positive) / Decimal(closed) if closed else Decimal("0"),
        mean_pnl_usd=total / Decimal(closed) if closed else Decimal("0"),
        total_pnl_usd=total,
        mean_return_on_max_loss=(total / max_loss if max_loss > 0 else None),
        mark_coverage=Decimal(closed) / Decimal(opened) if opened else Decimal("0"),
        sufficient_sample=closed >= minimum_cohorts,
        positive_mean=bool(closed and total > 0),
    )


def summarize_short_horizon_shadow(
    events: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    horizons_minutes: tuple[int, ...] = DEFAULT_HORIZONS_MINUTES,
    minimum_cohorts: int = DEFAULT_MINIMUM_COHORTS,
) -> ShortHorizonValidationSummary:
    """Summarize real-source exact-leg shadow cohorts at short horizons."""

    if not horizons_minutes or any(minutes < 1 or minutes > 60 for minutes in horizons_minutes):
        raise ValueError("horizons_minutes must contain values between 1 and 60")
    if len(set(horizons_minutes)) != len(horizons_minutes):
        raise ValueError("horizons_minutes must be unique")
    if minimum_cohorts < 1 or minimum_cohorts > 10_000:
        raise ValueError("minimum_cohorts must be between 1 and 10000")
    ordered = sorted(
        (event for event in events if isinstance(event, Mapping)),
        key=lambda event: _timestamp(event.get("timestamp")) or datetime.min.replace(tzinfo=UTC),
    )
    cohorts: list[ShadowCohort] = []
    seen: set[str] = set()
    for event in ordered:
        opening = _opening_from_event(event)
        if opening is None:
            continue
        cohort, _ = opening
        if cohort.proposal_id not in seen:
            cohorts.append(cohort)
            seen.add(cohort.proposal_id)
    metrics = tuple(
        _metric_for_horizon(
            cohorts,
            ordered,
            horizon,
            minimum_cohorts=minimum_cohorts,
        )
        for horizon in horizons_minutes
    )
    fifteen = next((metric for metric in metrics if metric.horizon_minutes == 15), metrics[-1])
    all_gates_pass = (
        fifteen.sufficient_sample
        and fifteen.mark_coverage >= Decimal("0.90")
        and fifteen.positive_mean
    )
    return ShortHorizonValidationSummary(
        research_only=True,
        source=ALPACA_SHADOW_SOURCE,
        observed_events=len(ordered),
        preview_openings=len(cohorts),
        minimum_cohorts=minimum_cohorts,
        max_mark_lag_minutes=MAX_MARK_LAG_MINUTES,
        horizons=metrics,
        recommended_action="REVIEW_FOR_NEXT_GATE" if all_gates_pass else "CONTINUE_SHADOW",
        order_sent=False,
    )
