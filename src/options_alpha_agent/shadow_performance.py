"""Reconstruct non-executing shadow cohorts and P&L from verified audit events.

Every preview-ready decision can open one virtual cohort. Later audit events may
mark that cohort only when they contain fresh quotes for the exact same option
legs. The module never imports a broker client and never infers a fill from a
midpoint: entry uses the recorded debit and liquidation uses long bid minus
short ask, floored at zero.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any

CONTRACT_MULTIPLIER = Decimal("100")
ALPACA_SHADOW_SOURCE = "alpaca_paper_contracts+indicative_options"


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _leg_symbols(candidate: Mapping[str, Any]) -> tuple[str, ...] | None:
    raw_legs = candidate.get("legs")
    if not isinstance(raw_legs, list) or len(raw_legs) not in {1, 2}:
        return None
    symbols: list[str] = []
    for leg in raw_legs:
        if not isinstance(leg, Mapping):
            return None
        symbol = leg.get("symbol")
        if (
            not isinstance(symbol, str)
            or not symbol.isascii()
            or not symbol.isalnum()
            or symbol != symbol.upper()
        ):
            return None
        symbols.append(symbol)
    return tuple(symbols)


def _candidate_for_strategy(evidence: Mapping[str, Any], strategy: str) -> Mapping[str, Any] | None:
    catalog = evidence.get("candidate_catalog")
    if isinstance(catalog, Mapping):
        candidate = catalog.get(strategy)
        if isinstance(candidate, Mapping):
            return candidate
    candidate = evidence.get("option_candidate")
    if isinstance(candidate, Mapping) and candidate.get("strategy") in {None, strategy}:
        return candidate
    return None


def _liquidation_value(candidate: Mapping[str, Any], *, quantity: int) -> Decimal | None:
    long_bid = _decimal(candidate.get("long_bid_per_share_usd"))
    if long_bid is None or long_bid < 0:
        return None
    symbols = _leg_symbols(candidate)
    if symbols is None:
        return None
    per_share = long_bid
    if len(symbols) == 2:
        short_ask = _decimal(candidate.get("short_ask_per_share_usd"))
        if short_ask is None or short_ask < 0:
            return None
        per_share = max(Decimal("0"), long_bid - short_ask)
    return per_share * CONTRACT_MULTIPLIER * quantity


@dataclass(frozen=True, slots=True)
class ShadowCohort:
    proposal_id: str
    opened_at: str
    underlying: str
    strategy: str
    quantity: int
    leg_symbols: tuple[str, ...]
    entry_debit_usd: Decimal
    max_loss_usd: Decimal
    latest_mark_at: str | None = None
    latest_liquidation_value_usd: Decimal | None = None
    pnl_usd: Decimal | None = None
    closed_at: str | None = None

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["leg_symbols"] = list(self.leg_symbols)
        for key in (
            "entry_debit_usd",
            "max_loss_usd",
            "latest_liquidation_value_usd",
            "pnl_usd",
        ):
            value = result[key]
            result[key] = str(value) if value is not None else None
        result["status"] = "closed" if self.closed_at else "open"
        return result


@dataclass(frozen=True, slots=True)
class ShadowPerformanceSummary:
    research_only: bool
    horizon_hours: int
    opened_cohorts: int
    closed_cohorts: int
    open_cohorts: int
    marked_cohorts: int
    unmarked_cohorts: int
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    total_marked_pnl_usd: Decimal
    closed_win_rate: Decimal
    marked_return_on_max_loss: Decimal | None
    closed_cohort_max_drawdown_usd: Decimal | None
    closed_cohort_expected_shortfall_5pct_usd: Decimal | None
    closed_cohort_sample_size: int
    risk_metrics_status: str
    order_sent: bool
    cohorts: tuple[ShadowCohort, ...]

    def public_dict(self, *, include_cohorts: bool = True) -> dict[str, Any]:
        result = asdict(self)
        for key in (
            "realized_pnl_usd",
            "unrealized_pnl_usd",
            "total_marked_pnl_usd",
            "closed_win_rate",
            "marked_return_on_max_loss",
            "closed_cohort_max_drawdown_usd",
            "closed_cohort_expected_shortfall_5pct_usd",
        ):
            result[key] = str(result[key]) if result[key] is not None else None
        result["cohorts"] = (
            [cohort.public_dict() for cohort in self.cohorts] if include_cohorts else []
        )
        return result


def _opening_from_event(event: Mapping[str, Any]) -> tuple[ShadowCohort, Mapping[str, Any]] | None:
    if event.get("event_type") != "shadow_risk_decision":
        return None
    evaluation = event.get("evaluation")
    evidence = event.get("evidence")
    decision = event.get("decision")
    if not all(isinstance(value, Mapping) for value in (evaluation, evidence, decision)):
        return None
    if evidence.get("source") != ALPACA_SHADOW_SOURCE or evidence.get("data_fresh") is not True:
        return None
    if evaluation.get("status") != "preview_ready" or event.get("order_sent") is True:
        return None
    proposal = evaluation.get("proposal")
    if not isinstance(proposal, Mapping):
        return None
    timestamp = _timestamp(event.get("timestamp"))
    proposal_id = proposal.get("proposal_id")
    underlying = proposal.get("underlying")
    strategy = proposal.get("strategy")
    quantity = proposal.get("quantity")
    entry = _decimal(proposal.get("net_debit_usd"))
    max_loss = _decimal(proposal.get("max_loss_usd"))
    if (
        timestamp is None
        or not isinstance(proposal_id, str)
        or not proposal_id
        or not isinstance(underlying, str)
        or not isinstance(strategy, str)
        or isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 1
        or entry is None
        or entry <= 0
        or max_loss is None
        or max_loss <= 0
    ):
        return None
    candidate = _candidate_for_strategy(evidence, strategy)
    if candidate is None:
        return None
    symbols = _leg_symbols(candidate)
    if symbols is None:
        return None
    return (
        ShadowCohort(
            proposal_id=proposal_id,
            opened_at=timestamp.isoformat(),
            underlying=underlying,
            strategy=strategy,
            quantity=quantity,
            leg_symbols=symbols,
            entry_debit_usd=entry,
            max_loss_usd=max_loss,
        ),
        evidence,
    )


def summarize_shadow_performance(
    events: Iterable[Mapping[str, Any]], *, horizon_hours: int = 24
) -> ShadowPerformanceSummary:
    """Build conservative cohort P&L from append-only shadow audit events."""

    if not 1 <= horizon_hours <= 24 * 45:
        raise ValueError("horizon_hours must be between 1 and 1080")
    horizon = timedelta(hours=horizon_hours)
    ordered = sorted(
        (event for event in events if isinstance(event, Mapping)),
        key=lambda event: _timestamp(event.get("timestamp")) or datetime.min.replace(tzinfo=UTC),
    )
    cohorts: list[ShadowCohort] = []
    seen_proposal_ids: set[str] = set()

    for event in ordered:
        event_time = _timestamp(event.get("timestamp"))
        evidence = event.get("evidence")
        if (
            event_time is not None
            and isinstance(evidence, Mapping)
            and evidence.get("source") == ALPACA_SHADOW_SOURCE
            and evidence.get("data_fresh") is True
        ):
            for index, cohort in enumerate(cohorts):
                if cohort.closed_at is not None or event_time <= _timestamp(cohort.opened_at):
                    continue
                candidate = _candidate_for_strategy(evidence, cohort.strategy)
                if candidate is None or _leg_symbols(candidate) != cohort.leg_symbols:
                    continue
                liquidation = _liquidation_value(candidate, quantity=cohort.quantity)
                if liquidation is None:
                    continue
                pnl = max(-cohort.max_loss_usd, liquidation - cohort.entry_debit_usd)
                close_now = event_time - _timestamp(cohort.opened_at) >= horizon
                cohorts[index] = ShadowCohort(
                    proposal_id=cohort.proposal_id,
                    opened_at=cohort.opened_at,
                    underlying=cohort.underlying,
                    strategy=cohort.strategy,
                    quantity=cohort.quantity,
                    leg_symbols=cohort.leg_symbols,
                    entry_debit_usd=cohort.entry_debit_usd,
                    max_loss_usd=cohort.max_loss_usd,
                    latest_mark_at=event_time.isoformat(),
                    latest_liquidation_value_usd=liquidation,
                    pnl_usd=pnl,
                    closed_at=event_time.isoformat() if close_now else None,
                )

        opening = _opening_from_event(event)
        if opening is None:
            continue
        cohort, _ = opening
        if cohort.proposal_id not in seen_proposal_ids:
            cohorts.append(cohort)
            seen_proposal_ids.add(cohort.proposal_id)

    closed = [cohort for cohort in cohorts if cohort.closed_at is not None]
    open_cohorts = [cohort for cohort in cohorts if cohort.closed_at is None]
    marked = [cohort for cohort in cohorts if cohort.pnl_usd is not None]
    realized = sum((cohort.pnl_usd or Decimal("0") for cohort in closed), Decimal("0"))
    unrealized = sum(
        (cohort.pnl_usd or Decimal("0") for cohort in open_cohorts if cohort.pnl_usd is not None),
        Decimal("0"),
    )
    wins = sum((cohort.pnl_usd or Decimal("0")) > 0 for cohort in closed)
    marked_max_loss = sum((cohort.max_loss_usd for cohort in marked), Decimal("0"))
    marked_return_on_max_loss = (
        (realized + unrealized) / marked_max_loss if marked_max_loss > 0 else None
    )
    closed_pnls = [cohort.pnl_usd for cohort in closed if cohort.pnl_usd is not None]
    if len(closed_pnls) < 2:
        closed_drawdown = None
    else:
        cumulative = Decimal("0")
        peak = Decimal("0")
        closed_drawdown = Decimal("0")
        for cohort in sorted(closed, key=lambda item: item.closed_at or item.opened_at):
            cumulative += cohort.pnl_usd or Decimal("0")
            peak = max(peak, cumulative)
            closed_drawdown = max(closed_drawdown, peak - cumulative)
    if len(closed_pnls) < 20:
        closed_expected_shortfall = None
        risk_metrics_status = "insufficient_closed_sample"
    else:
        tail_size = max(1, ceil(len(closed_pnls) * 0.05))
        closed_expected_shortfall = sum(sorted(closed_pnls)[:tail_size], Decimal("0")) / Decimal(
            tail_size
        )
        risk_metrics_status = "available"
    return ShadowPerformanceSummary(
        research_only=True,
        horizon_hours=horizon_hours,
        opened_cohorts=len(cohorts),
        closed_cohorts=len(closed),
        open_cohorts=len(open_cohorts),
        marked_cohorts=len(marked),
        unmarked_cohorts=len(cohorts) - len(marked),
        realized_pnl_usd=realized,
        unrealized_pnl_usd=unrealized,
        total_marked_pnl_usd=realized + unrealized,
        closed_win_rate=(Decimal(wins) / Decimal(len(closed)) if closed else Decimal("0")),
        marked_return_on_max_loss=marked_return_on_max_loss,
        closed_cohort_max_drawdown_usd=closed_drawdown,
        closed_cohort_expected_shortfall_5pct_usd=closed_expected_shortfall,
        closed_cohort_sample_size=len(closed_pnls),
        risk_metrics_status=risk_metrics_status,
        order_sent=False,
        cohorts=tuple(cohorts),
    )
