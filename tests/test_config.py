from decimal import Decimal

import pytest

from options_alpha_agent.config import Settings


def test_defaults_are_paper_and_execution_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALPACA_PAPER",
        "TRADE_EXECUTION_ENABLED",
        "STARTING_EQUITY_USD",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.alpaca_paper is True
    assert settings.trade_execution_enabled is False
    assert settings.trading_kill_switch is True
    assert settings.starting_equity_usd == Decimal("100000")


def test_live_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_PAPER", "false")

    with pytest.raises(ValueError, match="Live trading is prohibited"):
        Settings.from_env()


def test_featherless_provider_reads_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "featherless")
    monkeypatch.setenv("FEATHERLESS_API_KEY", "test-featherless-key")

    settings = Settings.from_env()

    assert settings.has_ai_credentials is True
    assert settings.featherless_model == "mistralai/Mistral-Large-Instruct-2411"


def test_unofficial_featherless_base_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDER", "featherless")
    monkeypatch.setenv("FEATHERLESS_BASE_URL", "https://example.invalid/v1")

    with pytest.raises(ValueError, match="official HTTPS API"):
        Settings.from_env()


def test_execution_requires_explicit_paper_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADE_EXECUTION_ENABLED", "true")
    monkeypatch.delenv("PAPER_ORDER_APPROVED", raising=False)

    with pytest.raises(ValueError, match="PAPER_ORDER_APPROVED"):
        Settings.from_env()


def test_gcs_durability_requires_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DURABLE_STATE_BACKEND", "gcs")
    monkeypatch.delenv("GCS_STATE_BUCKET", raising=False)

    with pytest.raises(ValueError, match="GCS_STATE_BUCKET"):
        Settings.from_env()


def test_gcs_durability_accepts_safe_bucket_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DURABLE_STATE_BACKEND", "gcs")
    monkeypatch.setenv("GCS_STATE_BUCKET", "options-alpha-private-audit")

    settings = Settings.from_env()

    assert settings.durable_state_backend == "gcs"
    assert settings.gcs_state_bucket == "options-alpha-private-audit"
