"""Deterministic research replay for normalized option trade observations.

This module deliberately consumes already-materialized entry and exit observations.
It does not fetch data, infer fills, or place orders.  The input contract makes the
assumptions visible so a future historical dataset cannot be mistaken for a live
execution result.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from options_alpha_agent.config import Settings
from options_alpha_agent.models import PortfolioState, TradeProposal
from options_alpha_agent.risk import evaluate_trade


class ReplayInputError(ValueError):
    """Raised when a replay record is incomplete or unsafe to evaluate."""


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ReplayInputError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ReplayInputError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ReplayInputError(f"{field_name} must be finite")
    return parsed


def _integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ReplayInputError(f"{field_name} must be an integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ReplayInputError(f"{field_name} must be an integer") from exc
    if str(value).strip() != str(parsed):
        raise ReplayInputError(f"{field_name} must be an integer")
    return parsed


def _boolean(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ReplayInputError(f"{field_name} must be boolean")


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ReplayInputError("timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayInputError("timestamp must be an ISO-8601 string") from exc
    if parsed.tzinfo is None:
        raise ReplayInputError("timestamp must include a timezone")
    return parsed


def _required_text(record: Mapping[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ReplayInputError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ReplayObservation:
    """One completed, normalized observation for one options position."""

    timestamp: datetime
    underlying: str
    strategy: str
    entry_debit_usd: Decimal
    exit_value_usd: Decimal
    max_loss_usd: Decimal
    days_to_expiry: int
    bid_ask_spread_pct: Decimal
    min_open_interest: int
    defined_risk: bool
    quantity: int = 1
    thesis: str = "historical replay observation"
    entry_quote_age_seconds: int = 0
    exit_quote_age_seconds: int = 0
    entry_quote_fresh: bool = True
    exit_quote_fresh: bool = True

    @classmethod
    def from_mapping(cls, record: Mapping[str, Any]) -> ReplayObservation:
        underlying = _required_text(record, "underlying").upper()
        if not underlying.isascii() or not underlying.isalnum():
            raise ReplayInputError("underlying must be uppercase ASCII alphanumeric")
        entry = _decimal(record.get("entry_debit_usd"), "entry_debit_usd")
        exit_value = _decimal(record.get("exit_value_usd"), "exit_value_usd")
        max_loss = _decimal(record.get("max_loss_usd"), "max_loss_usd")
        spread = _decimal(record.get("bid_ask_spread_pct"), "bid_ask_spread_pct")
        if entry <= 0 or exit_value < 0 or max_loss <= 0:
            raise ReplayInputError("entry, exit, and max loss values are invalid")
        if spread < 0:
            raise ReplayInputError("bid_ask_spread_pct cannot be negative")
        quantity = _integer(record.get("quantity", 1), "quantity")
        if quantity < 1:
            raise ReplayInputError("quantity must be positive")
        entry_quote_age = _integer(
            record.get("entry_quote_age_seconds", 0), "entry_quote_age_seconds"
        )
        exit_quote_age = _integer(record.get("exit_quote_age_seconds", 0), "exit_quote_age_seconds")
        if entry_quote_age < 0 or exit_quote_age < 0:
            raise ReplayInputError("quote age cannot be negative")
        return cls(
            timestamp=_timestamp(record.get("timestamp")),
            underlying=underlying,
            strategy=_required_text(record, "strategy"),
            entry_debit_usd=entry,
            exit_value_usd=exit_value,
            max_loss_usd=max_loss,
            days_to_expiry=_integer(record.get("days_to_expiry"), "days_to_expiry"),
            bid_ask_spread_pct=spread,
            min_open_interest=_integer(record.get("min_open_interest"), "min_open_interest"),
            defined_risk=_boolean(record.get("defined_risk"), "defined_risk"),
            quantity=quantity,
            thesis=str(record.get("thesis", "historical replay observation")),
            entry_quote_age_seconds=entry_quote_age,
            exit_quote_age_seconds=exit_quote_age,
            entry_quote_fresh=_boolean(record.get("entry_quote_fresh", True), "entry_quote_fresh"),
            exit_quote_fresh=_boolean(record.get("exit_quote_fresh", True), "exit_quote_fresh"),
        )

    def public_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        for key in (
            "entry_debit_usd",
            "exit_value_usd",
            "max_loss_usd",
            "bid_ask_spread_pct",
        ):
            result[key] = str(result[key])
        return result


@dataclass(frozen=True, slots=True)
class ReplayTradeResult:
    timestamp: str
    underlying: str
    strategy: str
    accepted: bool
    reasons: tuple[str, ...]
    pnl_usd: Decimal
    equity_after_usd: Decimal
    effective_entry_debit_usd: Decimal
    effective_exit_value_usd: Decimal

    def public_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "underlying": self.underlying,
            "strategy": self.strategy,
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "pnl_usd": str(self.pnl_usd),
            "equity_after_usd": str(self.equity_after_usd),
            "effective_entry_debit_usd": str(self.effective_entry_debit_usd),
            "effective_exit_value_usd": str(self.effective_exit_value_usd),
        }


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    research_only: bool
    initial_equity_usd: Decimal
    final_equity_usd: Decimal
    net_pnl_usd: Decimal
    total_observations: int
    accepted_trades: int
    rejected_trades: int
    win_rate: Decimal
    profit_factor: Decimal | None
    max_drawdown_usd: Decimal
    max_drawdown_pct: Decimal
    rejected_trade_rate: Decimal
    entry_slippage_pct: Decimal
    exit_slippage_pct: Decimal
    max_quote_age_seconds: int
    results: tuple[ReplayTradeResult, ...]

    def public_dict(self) -> dict[str, object]:
        result = asdict(self)
        for key in (
            "initial_equity_usd",
            "final_equity_usd",
            "net_pnl_usd",
            "win_rate",
            "max_drawdown_usd",
            "max_drawdown_pct",
            "rejected_trade_rate",
            "entry_slippage_pct",
            "exit_slippage_pct",
        ):
            result[key] = str(result[key])
        result["profit_factor"] = (
            str(self.profit_factor) if self.profit_factor is not None else None
        )
        result["results"] = [item.public_dict() for item in self.results]
        return result


def load_replay_csv(path: str | Path) -> list[ReplayObservation]:
    """Load a replay CSV without allowing arbitrary files outside the caller's scope."""

    csv_path = Path(path)
    if not csv_path.is_file():
        raise ReplayInputError("replay CSV does not exist")
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ReplayInputError("replay CSV has no header")
        return [ReplayObservation.from_mapping(row) for row in reader]


def replay_observations(
    observations: Iterable[ReplayObservation],
    settings: Settings,
    *,
    initial_equity_usd: Decimal | None = None,
    entry_slippage_pct: Decimal = Decimal("0"),
    exit_slippage_pct: Decimal = Decimal("0"),
    max_quote_age_seconds: int = 300,
) -> ReplaySummary:
    """Apply the same deterministic risk gates to completed research observations."""

    initial = settings.starting_equity_usd if initial_equity_usd is None else initial_equity_usd
    if not initial.is_finite() or initial <= 0:
        raise ReplayInputError("initial equity must be positive and finite")
    for value, field_name in (
        (entry_slippage_pct, "entry_slippage_pct"),
        (exit_slippage_pct, "exit_slippage_pct"),
    ):
        if not value.is_finite() or not Decimal("0") <= value < Decimal("1"):
            raise ReplayInputError(f"{field_name} must be between 0 and 1")
    if max_quote_age_seconds < 0:
        raise ReplayInputError("max_quote_age_seconds cannot be negative")
    ordered = sorted(observations, key=lambda item: item.timestamp)
    equity = initial
    peak_equity = initial
    max_drawdown = Decimal("0")
    start_of_day_equity = initial
    last_day: date | None = None
    accepted = 0
    rejected = 0
    wins = 0
    gross_profit = Decimal("0")
    gross_loss = Decimal("0")
    results: list[ReplayTradeResult] = []

    for observation in ordered:
        current_day = observation.timestamp.date()
        if last_day != current_day:
            start_of_day_equity = equity
            last_day = current_day
        effective_entry = observation.entry_debit_usd * (Decimal("1") + entry_slippage_pct)
        effective_exit = observation.exit_value_usd * (Decimal("1") - exit_slippage_pct)
        effective_max_loss = observation.max_loss_usd * (Decimal("1") + entry_slippage_pct)
        stale_reasons: list[str] = []
        if (
            not observation.entry_quote_fresh
            or observation.entry_quote_age_seconds > max_quote_age_seconds
        ):
            stale_reasons.append("stale_entry_quote")
        if (
            not observation.exit_quote_fresh
            or observation.exit_quote_age_seconds > max_quote_age_seconds
        ):
            stale_reasons.append("stale_exit_quote")
        proposal = TradeProposal(
            proposal_id=f"replay-{len(results) + 1:06d}",
            underlying=observation.underlying,
            strategy=observation.strategy,
            quantity=observation.quantity,
            max_loss_usd=effective_max_loss * observation.quantity,
            net_debit_usd=effective_entry * observation.quantity,
            days_to_expiry=observation.days_to_expiry,
            bid_ask_spread_pct=observation.bid_ask_spread_pct,
            min_open_interest=observation.min_open_interest,
            defined_risk=observation.defined_risk,
            thesis=observation.thesis,
        )
        portfolio = PortfolioState(
            equity_usd=equity,
            start_of_day_equity_usd=start_of_day_equity,
            deployed_risk_usd=Decimal("0"),
            open_positions=0,
        )
        decision = evaluate_trade(proposal, portfolio, settings)
        reasons = (*decision.reasons, *stale_reasons)
        allowed = decision.allowed and not stale_reasons
        pnl = Decimal("0")
        if allowed:
            accepted += 1
            pnl = (effective_exit - effective_entry) * observation.quantity
            equity += pnl
            if pnl > 0:
                wins += 1
                gross_profit += pnl
            elif pnl < 0:
                gross_loss += -pnl
        else:
            rejected += 1
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, peak_equity - equity)
        results.append(
            ReplayTradeResult(
                timestamp=observation.timestamp.isoformat(),
                underlying=observation.underlying,
                strategy=observation.strategy,
                accepted=allowed,
                reasons=reasons,
                pnl_usd=pnl,
                equity_after_usd=equity,
                effective_entry_debit_usd=effective_entry,
                effective_exit_value_usd=effective_exit,
            )
        )

    net_pnl = equity - initial
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    total = len(ordered)
    accepted_decimal = Decimal(accepted)
    return ReplaySummary(
        research_only=True,
        initial_equity_usd=initial,
        final_equity_usd=equity,
        net_pnl_usd=net_pnl,
        total_observations=total,
        accepted_trades=accepted,
        rejected_trades=rejected,
        win_rate=(Decimal(wins) / accepted_decimal if accepted else Decimal("0")),
        profit_factor=profit_factor,
        max_drawdown_usd=max_drawdown,
        max_drawdown_pct=(max_drawdown / initial if initial else Decimal("0")),
        rejected_trade_rate=(Decimal(rejected) / Decimal(total) if total else Decimal("0")),
        entry_slippage_pct=entry_slippage_pct,
        exit_slippage_pct=exit_slippage_pct,
        max_quote_age_seconds=max_quote_age_seconds,
        results=tuple(results),
    )
