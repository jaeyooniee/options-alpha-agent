"""Fail-closed AI decision boundary with strict validation and audit logging."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4

from options_alpha_agent.config import Settings

ALLOWED_AI_STRATEGIES = frozenset(
    {"long_call", "long_put", "call_debit_spread", "put_debit_spread"}
)
DECISION_KEYS = frozenset(
    {
        "action",
        "underlying",
        "strategy",
        "confidence",
        "thesis",
        "evidence",
        "rejected_alternatives",
        "invalidation_conditions",
        "quantity",
        "max_loss_usd",
        "net_debit_usd",
    }
)
SENSITIVE_EVIDENCE_KEY_PARTS = (
    "api_key",
    "secret",
    "password",
    "authorization",
    "access_token",
    "account_id",
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(?:"
    r"sk-[a-z0-9_-]{20,}|"
    r"(?:api[_ -]?key|secret|password|authorization|access[_ -]?token)\s*[:=]\s*\S+|"
    r"bearer\s+[a-z0-9._-]{12,}"
    r")"
)


class AISchemaError(ValueError):
    """Raised when a model response violates the decision contract."""


class AIBudgetError(RuntimeError):
    """Raised before a call that would exceed a configured AI budget."""


class EvidenceValidationError(ValueError):
    """Raised when evidence is unsafe or too large to transmit."""


class AuditLogError(RuntimeError):
    """Raised when the audit trail cannot be read safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _decimal_field(payload: Mapping[str, Any], name: str) -> Decimal:
    value = payload[name]
    if isinstance(value, bool):
        raise AISchemaError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AISchemaError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise AISchemaError(f"{name} must be finite")
    return parsed


def _contains_sensitive_text(value: str) -> bool:
    """Reject common credential formats before they reach a provider or audit log."""

    return SENSITIVE_TEXT_RE.search(value) is not None


def _safe_error_detail(exc: Exception) -> str | None:
    """Return bounded validation detail without persisting provider output."""

    if not isinstance(exc, (AISchemaError, EvidenceValidationError, AIBudgetError)):
        return None
    detail = str(exc).strip()
    if not detail or len(detail) > 240 or _contains_sensitive_text(detail):
        return None
    return detail


def _string_list(payload: Mapping[str, Any], name: str, *, required: bool) -> tuple[str, ...]:
    value = payload[name]
    if not isinstance(value, list) or len(value) > 8:
        raise AISchemaError(f"{name} must be an array with at most 8 items")
    if required and not value:
        raise AISchemaError(f"{name} cannot be empty")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in value):
        raise AISchemaError(f"{name} must contain short non-empty strings")
    if any(_contains_sensitive_text(item) for item in value):
        raise AISchemaError(f"{name} must not contain credential-like text")
    return tuple(item.strip() for item in value)


@dataclass(frozen=True, slots=True)
class AIDecision:
    """Validated model output. It is a proposal, never an executable order."""

    action: str
    underlying: str
    strategy: str | None
    confidence: Decimal
    thesis: str
    evidence: tuple[str, ...]
    rejected_alternatives: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    quantity: int
    max_loss_usd: Decimal
    net_debit_usd: Decimal

    @classmethod
    def from_json(cls, raw: str) -> AIDecision:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AISchemaError("AI response is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise AISchemaError("AI response must be one JSON object")
        if set(payload) != DECISION_KEYS:
            missing = sorted(DECISION_KEYS - set(payload))
            extra = sorted(set(payload) - DECISION_KEYS)
            raise AISchemaError(f"AI response keys mismatch; missing={missing}, extra={extra}")

        action = payload["action"]
        if action not in {"NO_TRADE", "PROPOSE_TRADE"}:
            raise AISchemaError("action must be NO_TRADE or PROPOSE_TRADE")
        underlying = payload["underlying"]
        if (
            not isinstance(underlying, str)
            or not underlying.isascii()
            or not underlying.isalnum()
            or underlying != underlying.upper()
            or not 1 <= len(underlying) <= 8
        ):
            raise AISchemaError("underlying must be a short uppercase symbol")
        strategy = payload["strategy"]
        if strategy is not None and strategy not in ALLOWED_AI_STRATEGIES:
            raise AISchemaError("strategy is not in the options-only allowlist")
        confidence = _decimal_field(payload, "confidence")
        if not Decimal("0") <= confidence <= Decimal("1"):
            raise AISchemaError("confidence must be between 0 and 1")
        thesis = payload["thesis"]
        if not isinstance(thesis, str) or not thesis.strip() or len(thesis) > 1_000:
            raise AISchemaError("thesis must be a non-empty string of at most 1000 characters")
        if _contains_sensitive_text(thesis):
            raise AISchemaError("thesis must not contain credential-like text")
        quantity = payload["quantity"]
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise AISchemaError("quantity must be an integer")
        max_loss_usd = _decimal_field(payload, "max_loss_usd")
        net_debit_usd = _decimal_field(payload, "net_debit_usd")

        if action == "NO_TRADE":
            if strategy is not None or quantity != 0:
                raise AISchemaError("NO_TRADE must have null strategy and zero quantity")
            if max_loss_usd != 0 or net_debit_usd != 0:
                raise AISchemaError("NO_TRADE must have zero loss and debit")
        else:
            if strategy is None or quantity < 1:
                raise AISchemaError("PROPOSE_TRADE requires an allowlisted strategy and quantity")
            if max_loss_usd <= 0 or net_debit_usd <= 0:
                raise AISchemaError("PROPOSE_TRADE requires positive bounded loss and debit")

        return cls(
            action=action,
            underlying=underlying,
            strategy=strategy,
            confidence=confidence,
            thesis=thesis.strip(),
            evidence=_string_list(payload, "evidence", required=True),
            rejected_alternatives=_string_list(payload, "rejected_alternatives", required=False),
            invalidation_conditions=_string_list(
                payload, "invalidation_conditions", required=False
            ),
            quantity=quantity,
            max_loss_usd=max_loss_usd,
            net_debit_usd=net_debit_usd,
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "underlying": self.underlying,
            "strategy": self.strategy,
            "confidence": str(self.confidence),
            "thesis": self.thesis,
            "evidence": list(self.evidence),
            "rejected_alternatives": list(self.rejected_alternatives),
            "invalidation_conditions": list(self.invalidation_conditions),
            "quantity": self.quantity,
            "max_loss_usd": str(self.max_loss_usd),
            "net_debit_usd": str(self.net_debit_usd),
        }


@dataclass(frozen=True, slots=True)
class AIOutcome:
    request_id: str
    provider_status: str
    model: str
    decision: AIDecision
    error_type: str | None
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Decimal

    def public_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "provider_status": self.provider_status,
            "model": self.model,
            "decision": self.decision.public_dict(),
            "error_type": self.error_type,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost_usd": str(self.estimated_cost_usd),
        }


def sanitize_evidence(value: Any, *, path: str = "$", depth: int = 0) -> Any:
    """Validate and copy JSON evidence while rejecting credential-like fields."""

    if depth > 8:
        raise EvidenceValidationError(f"evidence nesting is too deep at {path}")
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        if len(value) > 100:
            raise EvidenceValidationError(f"too many evidence fields at {path}")
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise EvidenceValidationError(f"evidence keys must be strings at {path}")
            normalized = key.lower()
            if any(part in normalized for part in SENSITIVE_EVIDENCE_KEY_PARTS):
                raise EvidenceValidationError(f"sensitive evidence field rejected at {path}.{key}")
            sanitized[key] = sanitize_evidence(item, path=f"{path}.{key}", depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        if len(value) > 500:
            raise EvidenceValidationError(f"too many evidence items at {path}")
        return [
            sanitize_evidence(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise EvidenceValidationError(f"non-finite evidence value at {path}")
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise EvidenceValidationError(f"non-finite evidence value at {path}")
    if isinstance(value, str):
        if _contains_sensitive_text(value):
            raise EvidenceValidationError(f"credential-like evidence text rejected at {path}")
        return value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    raise EvidenceValidationError(f"unsupported evidence type at {path}")


class AuditLog:
    """Append-only, hash-chained JSONL audit trail."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def daily_usage(self, now: datetime) -> tuple[int, Decimal]:
        if not self.path.exists():
            return 0, Decimal("0")
        calls = 0
        cost = Decimal("0")
        prefix = now.astimezone(UTC).date().isoformat()
        try:
            self.verify()
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if str(event.get("timestamp", "")).startswith(prefix) and event.get(
                    "provider_called"
                ):
                    calls += 1
                    cost += Decimal(str(event.get("estimated_cost_usd", "0")))
        except (OSError, json.JSONDecodeError, InvalidOperation) as exc:
            raise AuditLogError("AI audit log is unreadable; refusing new calls") from exc
        return calls, cost

    def verify(self) -> str:
        """Verify every link and return the current tail hash."""

        if not self.path.exists():
            return "GENESIS"
        previous_hash = "GENESIS"
        try:
            for line_number, line in enumerate(
                self.path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise AuditLogError(f"AI audit record is not an object at line {line_number}")
                stored_hash = record.pop("event_sha256")
                if record.get("previous_event_sha256") != previous_hash:
                    raise AuditLogError(f"AI audit chain link mismatch at line {line_number}")
                calculated_hash = _sha256_text(_canonical_json(record))
                if calculated_hash != stored_hash:
                    raise AuditLogError(f"AI audit event hash mismatch at line {line_number}")
                previous_hash = stored_hash
        except AuditLogError:
            raise
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AuditLogError("AI audit chain is invalid; refusing access") from exc
        return previous_hash

    def append(self, event: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous_hash = self.verify()
        try:
            record = sanitize_evidence(event)
        except EvidenceValidationError as exc:
            raise AuditLogError("AI audit event contains unsafe data") from exc
        if not isinstance(record, dict):  # Defensive guard for alternative Mapping implementations.
            raise AuditLogError("AI audit event must be an object")
        record["previous_event_sha256"] = previous_hash
        record["event_sha256"] = _sha256_text(_canonical_json(record))
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(_canonical_json(record) + "\n")

    def events(self) -> list[dict[str, Any]]:
        """Return verified audit events for local idempotency checks."""

        if not self.path.exists():
            return []
        self.verify()
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise AuditLogError("AI audit record is not an object")
                events.append(event)
        return events


def audit_log_for_settings(settings: Settings) -> Any:
    """Build the configured fail-closed audit log without importing cloud SDKs locally."""

    if settings.durable_state_backend == "gcs":
        from options_alpha_agent.durable_audit import GCSAuditLog

        if not settings.gcs_state_bucket:  # Settings validation normally prevents this.
            raise AuditLogError("GCS audit bucket is not configured")
        return GCSAuditLog(settings.gcs_state_bucket, settings.gcs_audit_object)
    return AuditLog(settings.ai_audit_log_path)


SYSTEM_PROMPT = """You are the probabilistic research layer of an options-only paper-trading agent.
You may only return a proposed decision. You cannot place orders or override deterministic risk
gates. Use only the supplied timestamped evidence. If evidence is missing, stale, synthetic,
contradictory, or does not establish an edge, choose NO_TRADE. If the deterministic signal is not
available or is not marked lookahead_safe, choose NO_TRADE. Return exactly one JSON object and no
markdown.

Production directional consistency is mandatory: use the supplied signal's
recommended_strategy exactly, which is either call_debit_spread or
put_debit_spread. A neutral, missing, stale, or contradictory signal must use
NO_TRADE. Long options exist only in the research catalog and must not be proposed.

Required keys and types:
- action: \"NO_TRADE\" or \"PROPOSE_TRADE\"
- underlying: uppercase symbol
- strategy: null, or one of long_call, long_put, call_debit_spread, put_debit_spread
- confidence: number from 0 to 1
- thesis: concise decision rationale, not hidden chain-of-thought
- evidence: 1 to 8 concise strings tied to supplied data
- rejected_alternatives: 0 to 8 concise strings
- invalidation_conditions: 0 to 8 concise strings
- quantity: integer
- max_loss_usd: number
- net_debit_usd: number

Use JSON numbers, not quoted strings, for confidence, quantity, max_loss_usd, and
net_debit_usd. Always include every required key, including the three arrays. Do
not return a markdown fence, explanation, or any key outside this contract.

For NO_TRADE, strategy must be null and quantity, max_loss_usd, and net_debit_usd must all be zero.
For PROPOSE_TRADE, use only an allowlisted strategy, positive quantity, and positive bounded
loss/debit.
Do not add keys."""


def _fail_closed_decision(underlying: str, error_type: str) -> AIDecision:
    symbol = (
        underlying
        if underlying.isascii() and underlying.isalnum() and underlying == underlying.upper()
        else "SPY"
    )
    return AIDecision(
        action="NO_TRADE",
        underlying=symbol,
        strategy=None,
        confidence=Decimal("0"),
        thesis="AI unavailable or invalid; deterministic fail-closed policy applied.",
        evidence=(f"provider_failure:{error_type}",),
        rejected_alternatives=(),
        invalidation_conditions=(),
        quantity=0,
        max_loss_usd=Decimal("0"),
        net_debit_usd=Decimal("0"),
    )


class AIDecisionEngine:
    """Call the configured model, validate output, and fail closed on every error."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None = None,
        audit_log: AuditLog | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self._client = client
        self.audit_log = audit_log or audit_log_for_settings(settings)
        self.now = now or (lambda: datetime.now(UTC))

    @property
    def model(self) -> str:
        if self.settings.ai_provider == "openai":
            return self.settings.openai_model
        return self.settings.featherless_model

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.has_ai_credentials:
            raise RuntimeError("configured AI provider credential is missing")
        from openai import OpenAI

        if self.settings.ai_provider == "featherless":
            self._client = OpenAI(
                api_key=self.settings.featherless_api_key,
                base_url=self.settings.featherless_base_url,
                timeout=self.settings.ai_timeout_seconds,
                default_headers={
                    "HTTP-Referer": (
                        "https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon"
                    ),
                    "X-Title": "Options Alpha Agent",
                },
            )
        elif self.settings.ai_provider == "openai":
            self._client = OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.ai_timeout_seconds,
            )
        else:
            raise RuntimeError("AI provider is disabled")
        return self._client

    def decide(self, evidence: Mapping[str, Any]) -> AIOutcome:
        request_id = str(uuid4())
        started = time.perf_counter()
        timestamp = self.now()
        sanitized: Any = {}
        evidence_json = "{}"
        prompt = ""
        raw_response = ""
        prompt_tokens = 0
        completion_tokens = 0
        provider_called = False
        estimated_cost = Decimal("0")
        error_detail: str | None = None
        underlying = str(evidence.get("underlying", "SPY"))

        try:
            if self.settings.ai_provider == "disabled":
                raise RuntimeError("AI provider is disabled")
            sanitized = sanitize_evidence(evidence)
            evidence_json = _canonical_json(sanitized)
            if len(evidence_json) > self.settings.ai_max_input_chars:
                raise EvidenceValidationError("evidence exceeds AI_MAX_INPUT_CHARS")
            calls, spent = self.audit_log.daily_usage(timestamp)
            if calls >= self.settings.ai_max_daily_calls:
                raise AIBudgetError("AI_MAX_DAILY_CALLS reached")
            prompt = "Evaluate this evidence pack:\n" + evidence_json
            estimated_input_tokens = math.ceil((len(SYSTEM_PROMPT) + len(prompt)) / 4)
            predicted_cost = (
                Decimal(estimated_input_tokens) * self.settings.ai_input_cost_per_million_usd
                + Decimal(self.settings.ai_max_output_tokens)
                * self.settings.ai_output_cost_per_million_usd
            ) / Decimal("1000000")
            if spent + predicted_cost > self.settings.ai_max_daily_cost_usd:
                raise AIBudgetError("AI_MAX_DAILY_COST_USD would be exceeded")

            client = self._get_client()
            provider_called = True
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=self.settings.ai_max_output_tokens,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise AISchemaError("AI returned empty content")
            raw_response = content
            usage = getattr(response, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            estimated_cost = (
                Decimal(prompt_tokens) * self.settings.ai_input_cost_per_million_usd
                + Decimal(completion_tokens) * self.settings.ai_output_cost_per_million_usd
            ) / Decimal("1000000")
            decision = AIDecision.from_json(raw_response)
            status = "ok"
            error_type = None
        except Exception as exc:  # noqa: BLE001 - this is the fail-closed boundary
            status = "fail_closed"
            error_type = type(exc).__name__
            error_detail = _safe_error_detail(exc)
            decision = _fail_closed_decision(underlying.upper(), error_type)

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        event = {
            "timestamp": timestamp.astimezone(UTC).isoformat(),
            "event_type": "ai_decision",
            "request_id": request_id,
            "provider": self.settings.ai_provider,
            "model": self.model,
            "provider_called": provider_called,
            "status": status,
            "error_type": error_type,
            "error_detail": error_detail,
            "latency_ms": latency_ms,
            "prompt_sha256": _sha256_text(SYSTEM_PROMPT + "\n" + prompt),
            "evidence_sha256": _sha256_text(evidence_json),
            "response_sha256": _sha256_text(raw_response) if raw_response else None,
            "evidence": sanitized,
            "decision": decision.public_dict(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": str(estimated_cost),
            "trade_execution_enabled": self.settings.trade_execution_enabled,
            "order_sent": False,
        }
        try:
            self.audit_log.append(event)
        except Exception as exc:  # noqa: BLE001 - an unwritable audit log must fail closed
            status = "fail_closed"
            error_type = type(exc).__name__
            decision = _fail_closed_decision(underlying.upper(), error_type)

        return AIOutcome(
            request_id=request_id,
            provider_status=status,
            model=self.model,
            decision=decision,
            error_type=error_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost,
        )


def probe_ai_provider(settings: Settings) -> dict[str, Any]:
    """Verify the configured provider and model without running inference."""

    if settings.ai_provider != "featherless":
        return {
            "provider": settings.ai_provider,
            "configured": settings.has_ai_credentials,
            "inference_called": False,
        }
    if not settings.featherless_api_key:
        raise RuntimeError("FEATHERLESS_API_KEY is required")
    headers = {
        "Authorization": f"Bearer {settings.featherless_api_key}",
        "Accept": "application/json",
        "User-Agent": "OptionsAlphaAgent/0.1",
        "X-Title": "Options Alpha Agent",
    }
    plan_request = urllib.request.Request(f"{settings.featherless_base_url}/plan", headers=headers)
    encoded_model = urllib.parse.quote(settings.featherless_model, safe="")
    model_request = urllib.request.Request(
        f"{settings.featherless_base_url}/models/{encoded_model}", headers=headers
    )
    with urllib.request.urlopen(plan_request, timeout=settings.ai_timeout_seconds) as response:
        plan = json.load(response)
    with urllib.request.urlopen(model_request, timeout=settings.ai_timeout_seconds) as response:
        model = json.load(response)
    pricing = model.get("pricing") or {}
    availability = model.get("availability") or {}
    return {
        "provider": "featherless",
        "configured": True,
        "plan_id": plan.get("id"),
        "plan_name": plan.get("name"),
        "model": model.get("id"),
        "model_status": model.get("status"),
        "availability_tier": availability.get("tier"),
        "context_length": model.get("context_length"),
        "input_cost_per_million_usd": pricing.get("input"),
        "output_cost_per_million_usd": pricing.get("output"),
        "inference_called": False,
    }
