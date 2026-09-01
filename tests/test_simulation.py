from options_alpha_agent.simulation import (
    SimulationAssumptions,
    black_scholes_price,
    compare_strategies,
)


def test_black_scholes_call_and_put_are_positive() -> None:
    common = {
        "spot": 100.0,
        "strike": 100.0,
        "years": 7 / 365,
        "volatility": 0.20,
        "risk_free_rate": 0.04,
    }

    assert black_scholes_price(**common, option_type="call") > 0
    assert black_scholes_price(**common, option_type="put") > 0


def test_strategy_comparison_is_reproducible_and_defined_risk() -> None:
    assumptions = SimulationAssumptions(paths=500, seed=7)

    first = compare_strategies(assumptions)
    second = compare_strategies(assumptions)

    assert first == second
    assert {result.strategy for result in first} == {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
    }
    assert all(result.max_loss_usd == result.entry_debit_usd for result in first)
    assert all(result.max_loss_usd > 0 for result in first)
