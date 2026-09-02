"""Environment-driven configuration with fail-closed trading defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv

from options_alpha_agent.provenance import is_unsafe_workspace_path


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _decimal_env(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number") from exc


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    alpaca_api_key: str | None
    alpaca_secret_key: str | None
    openai_api_key: str | None
    alpaca_paper: bool
    trade_execution_enabled: bool
    starting_equity_usd: Decimal
    max_risk_per_trade_pct: Decimal
    max_portfolio_risk_pct: Decimal
    max_daily_drawdown_pct: Decimal
    max_open_positions: int
    ai_provider: str = "featherless"
    featherless_api_key: str | None = None
    featherless_base_url: str = "https://api.featherless.ai/v1"
    featherless_model: str = "mistralai/Mistral-Large-Instruct-2411"
    openai_model: str = "gpt-5-mini"
    paper_order_approved: bool = False
    trading_kill_switch: bool = True
    ai_timeout_seconds: float = 30.0
    ai_max_input_chars: int = 20_000
    ai_max_output_tokens: int = 600
    ai_max_daily_calls: int = 200
    ai_max_daily_cost_usd: Decimal = Decimal("2.50")
    ai_input_cost_per_million_usd: Decimal = Decimal("0.125")
    ai_output_cost_per_million_usd: Decimal = Decimal("1.15")
    ai_audit_log_path: str = "logs/ai-decisions.jsonl"
    worker_lock_path: str = "logs/shadow-cycle.lock"
    durable_state_backend: str = "local"
    gcs_state_bucket: str | None = None
    gcs_audit_object: str = "options-alpha/audit/ai-decisions.jsonl"
    gcs_lock_object: str = "options-alpha/locks/shadow-cycle.json"
    gcs_lock_ttl_seconds: int = 900
    min_ai_confidence: Decimal = Decimal("0.65")

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        settings = cls(
            alpaca_api_key=os.getenv("ALPACA_API_KEY") or None,
            alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY") or None,
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            alpaca_paper=_bool_env("ALPACA_PAPER", True),
            trade_execution_enabled=_bool_env("TRADE_EXECUTION_ENABLED", False),
            starting_equity_usd=_decimal_env("STARTING_EQUITY_USD", "100000"),
            max_risk_per_trade_pct=_decimal_env("MAX_RISK_PER_TRADE_PCT", "0.02"),
            max_portfolio_risk_pct=_decimal_env("MAX_PORTFOLIO_RISK_PCT", "0.10"),
            max_daily_drawdown_pct=_decimal_env("MAX_DAILY_DRAWDOWN_PCT", "0.04"),
            max_open_positions=_int_env("MAX_OPEN_POSITIONS", 5),
            ai_provider=os.getenv("AI_PROVIDER", "featherless").strip().lower(),
            featherless_api_key=os.getenv("FEATHERLESS_API_KEY") or None,
            featherless_base_url=os.getenv(
                "FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1"
            ).rstrip("/"),
            featherless_model=os.getenv(
                "FEATHERLESS_MODEL", "mistralai/Mistral-Large-Instruct-2411"
            ).strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            paper_order_approved=_bool_env("PAPER_ORDER_APPROVED", False),
            trading_kill_switch=_bool_env("TRADING_KILL_SWITCH", True),
            ai_timeout_seconds=_float_env("AI_TIMEOUT_SECONDS", 30.0),
            ai_max_input_chars=_int_env("AI_MAX_INPUT_CHARS", 20_000),
            ai_max_output_tokens=_int_env("AI_MAX_OUTPUT_TOKENS", 600),
            ai_max_daily_calls=_int_env("AI_MAX_DAILY_CALLS", 200),
            ai_max_daily_cost_usd=_decimal_env("AI_MAX_DAILY_COST_USD", "2.50"),
            ai_input_cost_per_million_usd=_decimal_env("AI_INPUT_COST_PER_MILLION_USD", "0.125"),
            ai_output_cost_per_million_usd=_decimal_env("AI_OUTPUT_COST_PER_MILLION_USD", "1.15"),
            ai_audit_log_path=os.getenv("AI_AUDIT_LOG_PATH", "logs/ai-decisions.jsonl").strip(),
            worker_lock_path=os.getenv("WORKER_LOCK_PATH", "logs/shadow-cycle.lock").strip(),
            durable_state_backend=os.getenv("DURABLE_STATE_BACKEND", "local").strip().lower(),
            gcs_state_bucket=os.getenv("GCS_STATE_BUCKET") or None,
            gcs_audit_object=os.getenv(
                "GCS_AUDIT_OBJECT", "options-alpha/audit/ai-decisions.jsonl"
            ).strip(),
            gcs_lock_object=os.getenv(
                "GCS_LOCK_OBJECT", "options-alpha/locks/shadow-cycle.json"
            ).strip(),
            gcs_lock_ttl_seconds=_int_env("GCS_LOCK_TTL_SECONDS", 900),
            min_ai_confidence=_decimal_env("MIN_AI_CONFIDENCE", "0.65"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.alpaca_paper:
            raise ValueError("Live trading is prohibited for this project")
        if self.trade_execution_enabled and not self.paper_order_approved:
            raise ValueError(
                "PAPER_ORDER_APPROVED must be true before paper execution can be enabled"
            )
        if self.starting_equity_usd != Decimal("100000"):
            raise ValueError("Competition account must start with exactly $100,000")
        for field_name in (
            "max_risk_per_trade_pct",
            "max_portfolio_risk_pct",
            "max_daily_drawdown_pct",
        ):
            value = getattr(self, field_name)
            if not Decimal("0") < value < Decimal("1"):
                raise ValueError(f"{field_name} must be between 0 and 1")
        if self.max_risk_per_trade_pct > self.max_portfolio_risk_pct:
            raise ValueError("Per-trade risk cannot exceed total portfolio risk")
        if self.max_open_positions < 1:
            raise ValueError("MAX_OPEN_POSITIONS must be positive")
        if self.ai_provider not in {"disabled", "featherless", "openai"}:
            raise ValueError("AI_PROVIDER must be disabled, featherless, or openai")
        if self.ai_provider == "featherless":
            if self.featherless_base_url != "https://api.featherless.ai/v1":
                raise ValueError("FEATHERLESS_BASE_URL must use the official HTTPS API")
            if not self.featherless_model:
                raise ValueError("FEATHERLESS_MODEL must not be empty")
        if self.ai_provider == "openai" and not self.openai_model:
            raise ValueError("OPENAI_MODEL must not be empty")
        if self.ai_timeout_seconds <= 0:
            raise ValueError("AI_TIMEOUT_SECONDS must be positive")
        if not 1_000 <= self.ai_max_input_chars <= 100_000:
            raise ValueError("AI_MAX_INPUT_CHARS must be between 1000 and 100000")
        if not 50 <= self.ai_max_output_tokens <= 4_000:
            raise ValueError("AI_MAX_OUTPUT_TOKENS must be between 50 and 4000")
        if not 1 <= self.ai_max_daily_calls <= 10_000:
            raise ValueError("AI_MAX_DAILY_CALLS must be between 1 and 10000")
        for field_name in (
            "ai_max_daily_cost_usd",
            "ai_input_cost_per_million_usd",
            "ai_output_cost_per_million_usd",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if not Decimal("0") <= self.min_ai_confidence <= Decimal("1"):
            raise ValueError("MIN_AI_CONFIDENCE must be between 0 and 1")
        if is_unsafe_workspace_path(self.ai_audit_log_path):
            raise ValueError("AI_AUDIT_LOG_PATH must be a workspace-relative path")
        if is_unsafe_workspace_path(self.worker_lock_path):
            raise ValueError("WORKER_LOCK_PATH must be a workspace-relative path")
        if self.durable_state_backend not in {"local", "gcs"}:
            raise ValueError("DURABLE_STATE_BACKEND must be local or gcs")
        if self.durable_state_backend == "gcs" and not self.gcs_state_bucket:
            raise ValueError("GCS_STATE_BUCKET is required when DURABLE_STATE_BACKEND=gcs")
        for field_name in ("gcs_audit_object", "gcs_lock_object"):
            object_name = getattr(self, field_name)
            if not object_name or is_unsafe_workspace_path(object_name):
                raise ValueError(f"{field_name.upper()} must be a safe bucket-relative object name")
        if not 60 <= self.gcs_lock_ttl_seconds <= 3_600:
            raise ValueError("GCS_LOCK_TTL_SECONDS must be between 60 and 3600")

    @property
    def has_alpaca_credentials(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def has_ai_credentials(self) -> bool:
        if self.ai_provider == "featherless":
            return bool(self.featherless_api_key)
        if self.ai_provider == "openai":
            return bool(self.openai_api_key)
        return False
