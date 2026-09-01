"""Read-only local dashboard for safety and AI audit health."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from options_alpha_agent.ai import AuditLog, audit_log_for_settings
from options_alpha_agent.config import Settings
from options_alpha_agent.shadow_performance import summarize_shadow_performance
from options_alpha_agent.short_shadow import summarize_short_horizon_shadow


def dashboard_snapshot(
    settings: Settings,
    *,
    audit_log: AuditLog | None = None,
) -> dict[str, Any]:
    """Return safe dashboard state without account IDs, credentials, or raw evidence."""

    audit = audit_log or audit_log_for_settings(settings)
    event_count = 0
    latest: dict[str, Any] | None = None
    latest_account: dict[str, Any] | None = None
    latest_cycle: dict[str, Any] | None = None
    latest_ai: dict[str, Any] | None = None
    verified_events: list[dict[str, Any]] = []
    try:
        audit.verify()
        for record in audit.events():
            verified_events.append(record)
            event_count += 1
            evaluation = record.get("evaluation")
            risk_decision = record.get("risk_decision")
            latest = {
                "timestamp": record.get("timestamp"),
                "event_type": record.get("event_type"),
                "status": record.get("status")
                or (evaluation.get("status") if isinstance(evaluation, Mapping) else None),
                "risk_allowed": (
                    risk_decision.get("allowed") if isinstance(risk_decision, Mapping) else None
                ),
                "order_sent": record.get("order_sent") is True,
            }
            if record.get("event_type") == "account_reconciliation":
                snapshot = record.get("snapshot")
                if isinstance(snapshot, Mapping):
                    latest_account = {
                        "timestamp": snapshot.get("timestamp"),
                        "equity_usd": snapshot.get("equity_usd"),
                        "day_pnl_usd": snapshot.get("day_pnl_usd"),
                        "position_count": snapshot.get("position_count"),
                        "open_order_count": snapshot.get("open_order_count"),
                        "market_open": snapshot.get("market_open"),
                        "order_lifecycle_counts": snapshot.get("order_lifecycle_counts"),
                    }
            if record.get("event_type") == "shadow_risk_decision":
                evidence = record.get("evidence")
                signal = evidence.get("signal") if isinstance(evidence, Mapping) else None
                decision = record.get("decision")
                evaluation = record.get("evaluation")
                latest_cycle = {
                    "timestamp": record.get("timestamp"),
                    "underlying": evidence.get("underlying")
                    if isinstance(evidence, Mapping)
                    else None,
                    "market_source": evidence.get("source")
                    if isinstance(evidence, Mapping)
                    else None,
                    "market_open": evidence.get("market_open")
                    if isinstance(evidence, Mapping)
                    else None,
                    "data_fresh": evidence.get("data_fresh")
                    if isinstance(evidence, Mapping)
                    else None,
                    "regime": signal.get("regime") if isinstance(signal, Mapping) else None,
                    "action": decision.get("action") if isinstance(decision, Mapping) else None,
                    "strategy": decision.get("strategy") if isinstance(decision, Mapping) else None,
                    "confidence": decision.get("confidence")
                    if isinstance(decision, Mapping)
                    else None,
                    "risk_allowed": risk_decision.get("allowed")
                    if isinstance(risk_decision, Mapping)
                    else None,
                    "risk_reasons": risk_decision.get("reasons")
                    if isinstance(risk_decision, Mapping)
                    else None,
                    "status": evaluation.get("status") if isinstance(evaluation, Mapping) else None,
                }
            if record.get("event_type") == "ai_decision":
                decision = record.get("decision")
                latest_ai = {
                    "timestamp": record.get("timestamp"),
                    "provider_status": record.get("status"),
                    "provider_called": record.get("provider_called") is True,
                    "error_type": record.get("error_type"),
                    "action": decision.get("action") if isinstance(decision, Mapping) else None,
                    "strategy": decision.get("strategy") if isinstance(decision, Mapping) else None,
                }
        audit_status = "ok" if event_count else "not_initialized"
    except Exception as exc:  # noqa: BLE001 - dashboard must expose health, not raw errors
        audit_status = f"invalid:{type(exc).__name__}"

    try:
        shadow_performance = summarize_shadow_performance(verified_events).public_dict(
            include_cohorts=False
        )
    except Exception:  # noqa: BLE001 - health response must stay safe and available
        shadow_performance = None
    try:
        short_shadow = summarize_short_horizon_shadow(verified_events).public_dict()
    except Exception:  # noqa: BLE001 - health response must stay safe and available
        short_shadow = None

    return {
        "paper_mode": settings.alpaca_paper,
        "execution_enabled": settings.trade_execution_enabled,
        "paper_order_approved": settings.paper_order_approved,
        "trading_kill_switch": settings.trading_kill_switch,
        "order_sent": False,
        "ai_provider": settings.ai_provider,
        "ai_model": (
            settings.openai_model
            if settings.ai_provider == "openai"
            else settings.featherless_model
        ),
        "audit_chain": audit_status,
        "audit_event_count": event_count,
        "latest_event": latest,
        "latest_account": latest_account,
        "latest_cycle": latest_cycle,
        "latest_ai": latest_ai,
        "shadow_performance": shadow_performance,
        "short_shadow": short_shadow,
    }


HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Options Alpha Safety Console</title>
<style>
:root { color-scheme: dark; font-family: Inter, system-ui, sans-serif; }
body { margin: 0; background: #09111f; color: #edf4ff; }
main { max-width: 1160px; margin: 0 auto; padding: 42px 22px 56px; }
.eyebrow { color: #7dd3fc; letter-spacing: .14em; text-transform: uppercase; font-size: 12px; }
h1 { font-size: clamp(32px, 6vw, 62px); margin: 10px 0; }
.muted { color: #9db0c9; }
.grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(190px,1fr));
  gap: 14px; margin: 30px 0; }
.card { background: #101e33; border: 1px solid #223a5c; border-radius: 16px; padding: 20px; }
.label { color: #9db0c9; font-size: 13px; }
.value { font-size: 25px; font-weight: 700; margin-top: 8px; }
.safe { color: #86efac; } .warn { color: #fcd34d; } .bad { color: #fca5a5; }
code { color: #bae6fd; word-break: break-word; }
.flow { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 14px; }
.step { background: #0d1930; border-left: 3px solid #38bdf8; border-radius: 10px; padding: 16px; }
.step strong { display:block; margin: 6px 0; font-size: 18px; }
.pill { display: inline-block; border: 1px solid #365881; border-radius: 999px; color: #bae6fd;
  font-size: 12px; padding: 4px 8px; margin: 3px 3px 0 0; }
.notice { border-color: #2f7757; background: linear-gradient(120deg,#102d29,#101e33); }
summary { cursor: pointer; color: #bae6fd; } details[open] summary { margin-bottom: 14px; }
</style></head>
<body><main>
<div class="eyebrow">Alpaca AI Trading Agents Hackathon</div>
<h1>Options Alpha<br><span class="muted">Safety Console</span></h1>
<p class="muted">AI proposes. Deterministic gates decide. This paper-only health view has no
broker order endpoint.</p>
<section class="grid" id="cards"></section>
<section class="card notice"><div class="label">Why this exists</div>
<p>For systematic traders and fintech builders who need autonomous research without giving an
LLM unrestricted broker authority.</p>
<p class="muted">The agent can propose only defined-risk options structures. It abstains when
data, model output, market hours, or risk limits fail validation.</p></section>
<h2>Latest decision trace</h2>
<section class="flow" id="trace"><div class="step muted">Loading verified audit
summary…</div></section>
<section class="card"><details><summary>Verified public audit summary</summary>
<pre id="latest" class="muted">Loading…</pre></details></section>
<p class="muted">Refreshes every 10 seconds · <code>/api/healthz</code></p>
</main>
<script>
const esc = value => String(value ?? "—").replace(
  /[&<>"']/g,
  char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])
);
const label = value => value === true ? 'YES' : value === false ? 'NO' : (value ?? '—');
const pills = values => Array.isArray(values) && values.length
  ? values.map(value => `<span class="pill">${esc(value)}</span>`).join('')
  : '<span class="muted">—</span>';
async function load() {
  const state = await fetch('/api/state', {cache:'no-store'}).then(r => r.json());
  const items = [
    ['Paper mode', state.paper_mode ? 'ENABLED' : 'BLOCKED', state.paper_mode ? 'safe' : 'bad'],
    ['Execution', state.execution_enabled ? 'REVIEW REQUIRED' : 'DISABLED',
      state.execution_enabled ? 'warn' : 'safe'],
    ['Paper approval', state.paper_order_approved ? 'ENABLED' : 'REQUIRED',
      state.paper_order_approved ? 'warn' : 'safe'],
    ['Kill switch', state.trading_kill_switch ? 'STOPPED' : 'ARMED',
      state.trading_kill_switch ? 'safe' : 'warn'],
    ['Order sent', state.order_sent ? 'YES' : 'NO', state.order_sent ? 'bad' : 'safe'],
    ['AI provider', state.ai_provider, ''],
    ['Audit chain', state.audit_chain, state.audit_chain === 'ok' ? 'safe' : 'warn'],
    ['Audit events', state.audit_event_count, ''],
    ['Day P&L', state.latest_account?.day_pnl_usd ?? '—', ''],
    ['Positions', state.latest_account?.position_count ?? '—', ''],
    ['Shadow cohorts', state.shadow_performance?.opened_cohorts ?? 0, ''],
    ['Shadow marked P&L', state.shadow_performance?.total_marked_pnl_usd ?? '—', ''],
    ['Marked return / max loss', state.shadow_performance?.marked_return_on_max_loss ?? '—', ''],
    ['Closed-cohort risk metrics', state.shadow_performance?.risk_metrics_status ?? '—',
      state.shadow_performance?.risk_metrics_status === 'available' ? 'safe' : 'warn'],
    ['15m shadow cohorts', state.short_shadow?.horizons?.find(
      item => item.horizon_minutes === 15)?.closed_cohorts ?? 0, ''],
    ['15m shadow action', state.short_shadow?.recommended_action ?? '—',
      state.short_shadow?.recommended_action === 'REVIEW_FOR_NEXT_GATE' ? 'safe' : 'warn']
  ];
  document.querySelector('#cards').innerHTML = items.map(([label,value,klass]) =>
    `<article class="card"><div class="label">${label}</div>
      <div class="value ${klass}">${esc(value)}</div></article>`
  ).join('');
  const cycle = state.latest_cycle || {};
  const ai = state.latest_ai || {};
  const marketText = cycle.market_source
    ? `${label(cycle.market_open)} market · fresh ${label(cycle.data_fresh)}`
    : 'No completed market evidence cycle';
  const riskText = cycle.status
    ? `${cycle.status} · allowed ${label(cycle.risk_allowed)}`
    : 'No completed risk evaluation';
  document.querySelector('#trace').innerHTML = [
    ['1 · Market evidence', marketText, cycle.underlying || '—', esc(cycle.regime || 'No regime')],
    ['2 · AI proposal', ai.provider_status || 'Not called', ai.action || cycle.action || '—',
      esc(ai.provider_called ? 'Provider called' : 'No provider call')],
    ['3 · Deterministic risk', riskText, cycle.strategy || 'No strategy',
      pills(cycle.risk_reasons)],
    ['4 · Broker behavior', state.order_sent ? 'BLOCKER: order reported' : 'NO ORDER SENT',
      state.execution_enabled ? 'Execution review required' : 'Execution disabled',
      esc(state.trading_kill_switch ? 'Kill switch stopped' : 'Kill switch not set')]
  ].map(([title,body,detail,extra], index) =>
    `<article class="step"><div class="label">${esc(title)}</div>
      <strong class="${index === 3 && !state.order_sent ? 'safe' : ''}">${esc(body)}</strong>
      <div class="muted">${esc(detail)}</div><div>${extra}</div></article>`
  ).join('');
  document.querySelector('#latest').textContent = JSON.stringify({
    event: state.latest_event,
    account: state.latest_account,
    cycle: state.latest_cycle,
    ai: state.latest_ai,
    shadow_performance: state.shadow_performance,
    short_shadow: state.short_shadow
  }, null, 2);
}
load().catch(() => {
  document.querySelector('#latest').textContent = 'Dashboard health request failed';
});
setInterval(() => load().catch(() => {}), 10000);
</script></body></html>"""


DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Options Alpha — Guarded AI Options Research</title>
<meta name="description" content="Paper-only AI options research with deterministic risk gates.">
<style>
:root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #07111f; color: #edf4ff; }
main { max-width: 1120px; margin: 0 auto; padding: 30px 22px 68px; }
.nav { display:flex; align-items:center; justify-content:space-between; gap:18px; }
.brand { color:#7dd3fc; font-size:13px; letter-spacing:.12em; text-transform:uppercase; }
a { color:#bae6fd; }
.nav a { text-decoration:none; border:1px solid #35577e; border-radius:999px; padding:9px 13px; }
.hero { padding:70px 0 50px; max-width:850px; }
h1 { font-size:clamp(42px,8vw,86px); margin:0; line-height:.98; letter-spacing:-.055em; }
.hero p { color:#b5c6db; font-size:clamp(18px,2.3vw,25px); line-height:1.45; max-width:720px; }
.pill { display:inline-block; margin:5px 6px 0 0; padding:6px 10px; border:1px solid #31577f; }
.pill { border-radius:999px; color:#9edbff; font-size:13px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:14px; }
.grid { margin:20px 0 44px; }
.card { background:#0d1c31; border:1px solid #203a5b; border-radius:18px; padding:22px; }
.card h2 { margin:0 0 10px; font-size:20px; }
.card p, .card li { color:#adbed3; line-height:1.5; }
.accent { background:linear-gradient(120deg,#0d2b2a,#101d38); border-color:#2b6d62; }
.kicker { color:#86efac; font-size:12px; letter-spacing:.12em; text-transform:uppercase; }
.flow { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:20px 0 44px; }
.step { border-left:3px solid #38bdf8; background:#0d1c31; padding:17px; min-height:145px; }
.step strong { display:block; margin:9px 0; }
.muted { color:#9db0c9; }
.fine { color:#8094ac; font-size:14px; line-height:1.5; max-width:850px; }
@media (max-width:700px) { .hero { padding-top:48px; } .flow { grid-template-columns:1fr 1fr; } }
</style>
</head>
<body><main>
<nav class="nav">
<div class="brand">Alpaca AI Trading Agents Hackathon</div>
<a href="/">Open safety console →</a>
</nav>
<section class="hero">
<div class="kicker">Paper-only autonomous options research</div>
<h1>AI proposes.<br>Deterministic gates decide.</h1>
<p>Options Alpha gives systematic traders and fintech builders an autonomous research workflow
without granting an LLM unrestricted broker authority.</p>
<span class="pill">Alpaca paper account only</span>
<span class="pill">Options-only, defined risk</span>
<span class="pill">No live endpoint</span>
<span class="pill">Every decision audited</span>
</section>
<section class="flow">
<article class="step"><div class="muted">01 · Evidence</div><strong>Fresh market facts</strong>
<div class="muted">Alpaca IEX quotes, option chain, IV, Greeks, and a look-ahead-safe
signal.</div></article>
<article class="step"><div class="muted">02 · AI</div><strong>Strict proposal only</strong>
<div class="muted">A constrained JSON decision can propose an allowlisted structure or abstain.
It cannot reach the broker.</div></article>
<article class="step"><div class="muted">03 · Risk</div><strong>Independent veto</strong>
<div class="muted">Loss, DTE, liquidity, exposure, drawdown, and position limits are
recomputed.</div></article>
<article class="step"><div class="muted">04 · Audit</div><strong>Fail closed</strong>
<div class="muted">Stale evidence, malformed output, a closed market, or a failed control
becomes NO_TRADE.</div></article>
</section>
<section class="grid">
<article class="card accent"><div class="kicker">Application of technology</div>
<h2>Autonomy with a hard boundary</h2><p>Model output is schema-validated and separated from
Alpaca execution. Evidence and risk decisions are hash-chained for review.</p></article>
<article class="card"><div class="kicker">Business value</div>
<h2>A control layer before capital is exposed</h2><p>The target user is a systematic trader,
research team, or fintech builder who needs traceable AI research before broker
action.</p></article>
<article class="card"><div class="kicker">Originality</div>
<h2>Abstention is a feature</h2><p>AI loses authority whenever evidence or controls are
weak.</p></article>
</section>
<section class="card"><div class="kicker">Evidence and limits</div>
<h2>What this build proves today</h2><ul>
<li>A fresh $100,000 Alpaca paper account, Level 3 options approval, and zero order/fill/position
history were verified without exposing the account ID.</li>
<li>Alpaca Trading API and MCP reads for option contracts, quotes, IV, and Greeks were exercised.
Real option snapshots are versioned and validated.</li>
<li>Shadow P&amp;L uses exact-leg, conservative bid/ask marks and reports missing marks or
insufficient samples instead of inventing performance.</li></ul>
<p class="fine">This is a paper-only research prototype, not investment advice or a historical-alpha
claim. Execution remains disabled behind two approvals and an independent kill switch.</p></section>
<p class="fine">The live safety console exposes aggregate health only. It contains no credential,
paper account ID, raw option symbols, or broker order route.</p>
</main></body></html>"""


def dashboard_response(
    path: str,
    snapshot: Callable[[], Mapping[str, Any]],
) -> tuple[HTTPStatus, str, bytes]:
    """Build a read-only dashboard response without binding a network socket."""

    if path == "/":
        return HTTPStatus.OK, "text/html; charset=utf-8", HTML.encode("utf-8")
    if path == "/demo":
        return HTTPStatus.OK, "text/html; charset=utf-8", DEMO_HTML.encode("utf-8")
    if path in {"/api/state", "/api/healthz"}:
        body = json.dumps(snapshot(), sort_keys=True).encode("utf-8")
        return HTTPStatus.OK, "application/json", body
    return HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"Not found"


def serve_dashboard(settings: Settings, host: str = "127.0.0.1", port: int = 8501) -> None:
    """Serve the dashboard locally; all routes are read-only."""

    snapshot = lambda: dashboard_snapshot(settings)  # noqa: E731 - tiny request-local factory

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            status, content_type, body = dashboard_response(self.path, snapshot)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        print(f"Dashboard listening on http://{host}:{port}")
        server.serve_forever()
    finally:
        server.server_close()
