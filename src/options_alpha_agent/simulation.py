"""Reproducible option-strategy scenario simulation for research, not execution."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from statistics import fmean, median


@dataclass(frozen=True, slots=True)
class SimulationAssumptions:
    spot: float = 780.0
    annual_drift: float = 0.0
    annual_volatility: float = 0.18
    risk_free_rate: float = 0.04
    days_to_expiry: int = 7
    paths: int = 5000
    seed: int = 20260829
    entry_slippage_pct: float = 0.03


@dataclass(frozen=True, slots=True)
class StrategySimulation:
    strategy: str
    long_strike: float
    short_strike: float | None
    entry_debit_usd: float
    max_loss_usd: float
    mean_pnl_usd: float
    median_pnl_usd: float
    win_rate: float
    p05_pnl_usd: float
    cvar05_pnl_usd: float
    mean_return_on_risk: float

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def black_scholes_price(
    *,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    risk_free_rate: float,
    option_type: str,
) -> float:
    """Return a European option estimate used only for controlled simulations."""

    if years <= 0:
        if option_type == "call":
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)
    if spot <= 0 or strike <= 0 or volatility <= 0:
        raise ValueError("spot, strike, and volatility must be positive")
    if option_type not in {"call", "put"}:
        raise ValueError("option_type must be call or put")

    vol_time = volatility * math.sqrt(years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * years) / vol_time
    d2 = d1 - vol_time
    discounted_strike = strike * math.exp(-risk_free_rate * years)
    if option_type == "call":
        return spot * _normal_cdf(d1) - discounted_strike * _normal_cdf(d2)
    return discounted_strike * _normal_cdf(-d2) - spot * _normal_cdf(-d1)


def _terminal_spots(assumptions: SimulationAssumptions) -> list[float]:
    if assumptions.paths < 100:
        raise ValueError("paths must be at least 100")
    if not 1 <= assumptions.days_to_expiry <= 45:
        raise ValueError("days_to_expiry must be between 1 and 45")
    rng = random.Random(assumptions.seed)
    years = assumptions.days_to_expiry / 365.0
    drift = (assumptions.annual_drift - 0.5 * assumptions.annual_volatility**2) * years
    diffusion = assumptions.annual_volatility * math.sqrt(years)
    return [
        assumptions.spot * math.exp(drift + diffusion * rng.gauss(0.0, 1.0))
        for _ in range(assumptions.paths)
    ]


def _strategy_definition(strategy: str, spot: float) -> tuple[str, float, float | None]:
    definitions = {
        "long_call": ("call", round(spot), None),
        "long_put": ("put", round(spot), None),
        "call_debit_spread": ("call", round(spot * 0.995), round(spot * 1.02)),
        "put_debit_spread": ("put", round(spot * 1.005), round(spot * 0.98)),
    }
    try:
        return definitions[strategy]
    except KeyError as exc:
        raise ValueError(f"Unsupported strategy: {strategy}") from exc


def _entry_debit(
    strategy: str,
    option_type: str,
    long_strike: float,
    short_strike: float | None,
    assumptions: SimulationAssumptions,
) -> float:
    years = assumptions.days_to_expiry / 365.0
    long_premium = black_scholes_price(
        spot=assumptions.spot,
        strike=long_strike,
        years=years,
        volatility=assumptions.annual_volatility,
        risk_free_rate=assumptions.risk_free_rate,
        option_type=option_type,
    )
    debit = long_premium * (1.0 + assumptions.entry_slippage_pct)
    if short_strike is not None:
        short_premium = black_scholes_price(
            spot=assumptions.spot,
            strike=short_strike,
            years=years,
            volatility=assumptions.annual_volatility,
            risk_free_rate=assumptions.risk_free_rate,
            option_type=option_type,
        )
        debit -= short_premium * (1.0 - assumptions.entry_slippage_pct)
    if debit <= 0:
        raise ValueError(f"{strategy} did not produce a positive defined-risk debit")
    return debit * 100.0


def _payoff(
    terminal_spot: float,
    option_type: str,
    long_strike: float,
    short_strike: float | None,
) -> float:
    if option_type == "call":
        long_value = max(terminal_spot - long_strike, 0.0)
        short_value = max(terminal_spot - short_strike, 0.0) if short_strike else 0.0
    else:
        long_value = max(long_strike - terminal_spot, 0.0)
        short_value = max(short_strike - terminal_spot, 0.0) if short_strike else 0.0
    return (long_value - short_value) * 100.0


def simulate_strategy(
    strategy: str,
    assumptions: SimulationAssumptions,
    terminal_spots: list[float] | None = None,
) -> StrategySimulation:
    option_type, long_strike, short_strike = _strategy_definition(strategy, assumptions.spot)
    entry_debit = _entry_debit(strategy, option_type, long_strike, short_strike, assumptions)
    scenarios = terminal_spots or _terminal_spots(assumptions)
    pnl = sorted(
        _payoff(terminal, option_type, long_strike, short_strike) - entry_debit
        for terminal in scenarios
    )
    tail_count = max(1, math.ceil(len(pnl) * 0.05))
    p05 = pnl[tail_count - 1]
    cvar05 = fmean(pnl[:tail_count])
    return StrategySimulation(
        strategy=strategy,
        long_strike=long_strike,
        short_strike=short_strike,
        entry_debit_usd=round(entry_debit, 2),
        max_loss_usd=round(entry_debit, 2),
        mean_pnl_usd=round(fmean(pnl), 2),
        median_pnl_usd=round(median(pnl), 2),
        win_rate=round(sum(value > 0 for value in pnl) / len(pnl), 4),
        p05_pnl_usd=round(p05, 2),
        cvar05_pnl_usd=round(cvar05, 2),
        mean_return_on_risk=round(fmean(pnl) / entry_debit, 4),
    )


def compare_strategies(
    assumptions: SimulationAssumptions,
) -> list[StrategySimulation]:
    """Compare every allowlisted strategy over identical terminal-price paths."""

    terminal_spots = _terminal_spots(assumptions)
    strategies = (
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
    )
    results = [simulate_strategy(strategy, assumptions, terminal_spots) for strategy in strategies]
    return sorted(results, key=lambda result: result.mean_return_on_risk, reverse=True)
