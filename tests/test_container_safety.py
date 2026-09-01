from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAFETY_DEFAULTS = (
    "ALPACA_PAPER=true",
    "TRADE_EXECUTION_ENABLED=false",
    "PAPER_ORDER_APPROVED=false",
    "TRADING_KILL_SWITCH=true",
)


@pytest.mark.parametrize("dockerfile", ["Dockerfile.worker", "Dockerfile.dashboard"])
def test_container_images_bake_in_fail_closed_defaults(dockerfile: str) -> None:
    contents = (ROOT / dockerfile).read_text(encoding="utf-8")

    for setting in SAFETY_DEFAULTS:
        assert setting in contents


def test_dashboard_image_declares_read_only_health_check() -> None:
    contents = (ROOT / "Dockerfile.dashboard").read_text(encoding="utf-8")

    assert "HEALTHCHECK" in contents
    assert "/api/healthz" in contents
