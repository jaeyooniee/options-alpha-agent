from pathlib import Path

import pytest

from options_alpha_agent.option_snapshot import OptionSnapshotError, load_option_snapshot
from options_alpha_agent.snapshot_compare import compare_option_snapshots

ENTRY = Path("data/options/spy.indicative.2026-08-28T1948Z.csv")
EXIT = Path("data/options/spy.indicative.2026-08-28T1957Z.csv")


def test_real_snapshot_pair_is_exact_symbol_and_explicitly_not_backtest() -> None:
    comparison = compare_option_snapshots(
        load_option_snapshot(ENTRY),
        load_option_snapshot(EXIT),
    )

    assert comparison.research_only is True
    assert comparison.not_backtest is True
    assert comparison.selection_edge_claimed is False
    assert comparison.open_interest_available is False
    assert comparison.matched_contracts == 22
    assert comparison.unmatched_entry_contracts == 0
    assert comparison.unmatched_exit_contracts == 0
    assert comparison.elapsed_seconds > 500
    assert comparison.underlying_return > 0
    assert {item.strategy for item in comparison.structures} == {
        "long_call",
        "long_put",
        "call_debit_spread",
        "put_debit_spread",
    }
    assert all(item.observation_count > 0 for item in comparison.structures)
    assert comparison.order_sent is False


def test_snapshot_comparison_rejects_reverse_time_order() -> None:
    with pytest.raises(OptionSnapshotError, match="later"):
        compare_option_snapshots(
            load_option_snapshot(EXIT),
            load_option_snapshot(ENTRY),
        )
