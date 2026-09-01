"""Static regression tests for the project's paper-only trading invariant."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "options_alpha_agent"


def _trading_client_calls() -> list[tuple[Path, ast.Call]]:
    calls: list[tuple[Path, ast.Call]] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "TradingClient"
            ):
                calls.append((path, node))
    return calls


def test_every_real_trading_client_is_hard_coded_to_paper_mode() -> None:
    calls = _trading_client_calls()

    assert calls, "Expected at least one Alpaca TradingClient construction to audit"
    for path, call in calls:
        paper_keyword = next((item for item in call.keywords if item.arg == "paper"), None)
        assert paper_keyword is not None, f"{path} must set TradingClient paper=True explicitly"
        assert isinstance(paper_keyword.value, ast.Constant), (
            f"{path} must use a literal paper flag"
        )
        assert paper_keyword.value.value is True, (
            f"{path} must never construct a live TradingClient"
        )
