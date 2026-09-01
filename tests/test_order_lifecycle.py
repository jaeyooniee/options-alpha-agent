from types import SimpleNamespace

import pytest

from options_alpha_agent.order_lifecycle import (
    LifecycleError,
    classify_fill_state,
    evaluate_lifecycle,
)


def test_partial_fill_cancels_remainder_and_manages_filled_quantity() -> None:
    state = classify_fill_state("partially_filled", 3, 1)
    decision = evaluate_lifecycle(state)

    assert decision.action == "CANCEL_REMAINDER_AND_MANAGE_FILLED"
    assert decision.fill_state.remaining_qty == 2


def test_assignment_risk_always_requires_manual_review() -> None:
    state = classify_fill_state(SimpleNamespace(value="filled"), 1, 1)

    decision = evaluate_lifecycle(state, assignment_risk=True)

    assert decision.action == "MANUAL_REVIEW"
    assert decision.assignment_manual_review is True


def test_terminal_status_and_impossible_fill_are_safe() -> None:
    rejected = evaluate_lifecycle(classify_fill_state("rejected", 1, 0))
    assert rejected.action == "NO_ACTION"

    with pytest.raises(LifecycleError):
        classify_fill_state("filled", 1, 2)
