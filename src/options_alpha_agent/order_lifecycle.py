"""Deterministic order-fill lifecycle classification without broker mutation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class LifecycleError(ValueError):
    """Raised when an order fill snapshot is inconsistent."""


@dataclass(frozen=True, slots=True)
class FillState:
    status: str
    requested_qty: int
    filled_qty: int
    remaining_qty: int

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    action: str
    reasons: tuple[str, ...]
    fill_state: FillState
    assignment_manual_review: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reasons": list(self.reasons),
            "fill_state": self.fill_state.public_dict(),
            "assignment_manual_review": self.assignment_manual_review,
        }


def classify_fill_state(status: Any, requested_qty: Any, filled_qty: Any) -> FillState:
    """Normalize broker fill quantities while rejecting impossible states."""

    normalized_status = str(getattr(status, "value", status)).lower()
    try:
        requested = int(str(requested_qty))
        filled = int(str(filled_qty))
    except (TypeError, ValueError) as exc:
        raise LifecycleError("order quantities must be integers") from exc
    if not normalized_status or requested < 1 or filled < 0 or filled > requested:
        raise LifecycleError("order fill quantities are inconsistent")
    return FillState(normalized_status, requested, filled, requested - filled)


def evaluate_lifecycle(
    state: FillState,
    *,
    assignment_risk: bool = False,
) -> LifecycleDecision:
    """Choose a safe next action for a fill snapshot; never contacts Alpaca."""

    terminal_no_fill = {"canceled", "cancelled", "expired", "rejected", "stopped"}
    terminal_filled = {"filled", "done_for_day"}
    pending = {"new", "accepted", "pending_new", "pending_cancel", "held"}
    if assignment_risk:
        return LifecycleDecision(
            "MANUAL_REVIEW",
            ("assignment_or_exercise_risk",),
            state,
            True,
        )
    if state.status in terminal_no_fill:
        if state.filled_qty:
            return LifecycleDecision(
                "MANAGE_FILLED_AND_REVIEW_REMAINDER",
                ("terminal_status_with_partial_fill",),
                state,
                False,
            )
        return LifecycleDecision("NO_ACTION", ("terminal_without_fill",), state, False)
    if state.status in terminal_filled:
        if state.filled_qty != state.requested_qty:
            raise LifecycleError("filled terminal status must fill the requested quantity")
        return LifecycleDecision("MANAGE_FILLED_POSITION", ("fully_filled",), state, False)
    if state.filled_qty and state.remaining_qty:
        return LifecycleDecision(
            "CANCEL_REMAINDER_AND_MANAGE_FILLED",
            ("partial_fill",),
            state,
            False,
        )
    if state.status in pending:
        return LifecycleDecision("WAIT_FOR_FILL", ("order_pending",), state, False)
    return LifecycleDecision("MANUAL_REVIEW", ("unknown_order_status",), state, False)
