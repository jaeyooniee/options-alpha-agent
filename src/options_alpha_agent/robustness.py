"""Research-only robustness sweeps for the allowlisted option structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from options_alpha_agent.simulation import SimulationAssumptions, compare_strategies


@dataclass(frozen=True, slots=True)
class RobustnessCase:
    """One deterministic scenario used in a parameter/seed sensitivity sweep."""

    name: str
    annual_drift: float
    annual_volatility: float
    seed: int


@dataclass(frozen=True, slots=True)
class RobustnessAggregate:
    """Aggregate result for one strategy across all non-historical cases."""

    strategy: str
    case_count: int
    positive_mean_cases: int
    mean_return_on_risk: float
    minimum_return_on_risk: float
    mean_win_rate: float
    worst_p05_pnl_usd: float
    average_rank: float

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    """Machine-readable scenario sweep output; never a historical backtest."""

    research_only: bool
    paths_per_case: int
    days_to_expiry: int
    cases: tuple[RobustnessCase, ...]
    aggregates: tuple[RobustnessAggregate, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "research_only": self.research_only,
            "paths_per_case": self.paths_per_case,
            "days_to_expiry": self.days_to_expiry,
            "cases": [asdict(case) for case in self.cases],
            "aggregates": [aggregate.public_dict() for aggregate in self.aggregates],
        }


def default_robustness_cases(seed: int = 20260829) -> tuple[RobustnessCase, ...]:
    """Return a fixed set of directional, neutral, volatility, and seed cases."""

    return (
        RobustnessCase("bullish_base", 0.30, 0.18, seed),
        RobustnessCase("bearish_base", -0.30, 0.18, seed + 1),
        RobustnessCase("neutral_low_vol", 0.00, 0.12, seed + 2),
        RobustnessCase("neutral_high_vol", 0.00, 0.36, seed + 3),
        RobustnessCase("mild_bullish_holdout", 0.12, 0.24, seed + 4),
        RobustnessCase("mild_bearish_holdout", -0.12, 0.24, seed + 5),
    )


def evaluate_robustness(
    *,
    paths: int = 1000,
    seed: int = 20260829,
    days_to_expiry: int = 7,
    cases: tuple[RobustnessCase, ...] | None = None,
) -> RobustnessReport:
    """Compare every strategy over fixed stress cases and identical paths per case."""

    if paths < 100:
        raise ValueError("paths must be at least 100")
    if not 1 <= days_to_expiry <= 45:
        raise ValueError("days_to_expiry must be between 1 and 45")
    resolved_cases = cases or default_robustness_cases(seed)
    if not resolved_cases:
        raise ValueError("at least one robustness case is required")

    per_strategy: dict[str, list[tuple[float, float, float, int]]] = {}
    for case in resolved_cases:
        assumptions = SimulationAssumptions(
            annual_drift=case.annual_drift,
            annual_volatility=case.annual_volatility,
            days_to_expiry=days_to_expiry,
            paths=paths,
            seed=case.seed,
        )
        results = compare_strategies(assumptions)
        ranks = {result.strategy: rank for rank, result in enumerate(results, start=1)}
        for result in results:
            per_strategy.setdefault(result.strategy, []).append(
                (
                    result.mean_return_on_risk,
                    result.win_rate,
                    result.p05_pnl_usd,
                    ranks[result.strategy],
                )
            )

    aggregates = []
    for strategy, values in per_strategy.items():
        aggregates.append(
            RobustnessAggregate(
                strategy=strategy,
                case_count=len(values),
                positive_mean_cases=sum(value[0] > 0 for value in values),
                mean_return_on_risk=round(sum(value[0] for value in values) / len(values), 4),
                minimum_return_on_risk=round(min(value[0] for value in values), 4),
                mean_win_rate=round(sum(value[1] for value in values) / len(values), 4),
                worst_p05_pnl_usd=round(min(value[2] for value in values), 2),
                average_rank=round(sum(value[3] for value in values) / len(values), 4),
            )
        )
    aggregates.sort(key=lambda item: (item.average_rank, -item.mean_return_on_risk))
    return RobustnessReport(
        research_only=True,
        paths_per_case=paths,
        days_to_expiry=days_to_expiry,
        cases=tuple(resolved_cases),
        aggregates=tuple(aggregates),
    )
