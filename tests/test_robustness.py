import pytest

from options_alpha_agent.robustness import evaluate_robustness


def test_robustness_sweep_is_deterministic_and_covers_all_strategies() -> None:
    first = evaluate_robustness(paths=100, seed=20260829)
    second = evaluate_robustness(paths=100, seed=20260829)

    assert first.public_dict() == second.public_dict()
    assert first.research_only is True
    assert len(first.cases) == 6
    assert {item.strategy for item in first.aggregates} == {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
    }
    assert all(item.case_count == 6 for item in first.aggregates)


@pytest.mark.parametrize("kwargs", [{"paths": 99}, {"days_to_expiry": 0}, {"days_to_expiry": 46}])
def test_robustness_rejects_unsafe_simulation_parameters(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        evaluate_robustness(**kwargs)
