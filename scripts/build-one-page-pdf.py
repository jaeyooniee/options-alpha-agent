"""Build the polished one-page hackathon technical summary PDF."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "options-alpha-one-page.pdf"

INK = HexColor("#111827")
MUTED = HexColor("#526071")
BLUE = HexColor("#4EA7E8")
BLUE_PALE = HexColor("#EAF6FD")
TEAL = HexColor("#20BFA9")
TEAL_PALE = HexColor("#EAFBF7")
AMBER = HexColor("#F4B740")
AMBER_PALE = HexColor("#FFF7E3")
PANEL = HexColor("#F5F7F9")
LINE = HexColor("#DCE3E9")
WHITE = HexColor("#FFFFFF")


def wrap_text(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if stringWidth(candidate, font, size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_bullets(
    pdf: canvas.Canvas,
    bullets: list[str],
    *,
    x: float,
    y: float,
    width: float,
    font_size: float = 8.35,
    leading: float = 11.2,
) -> float:
    cursor = y
    for bullet in bullets:
        lines = wrap_text(bullet, "Helvetica", font_size, width - 14)
        pdf.setFillColor(TEAL)
        pdf.circle(x + 2.7, cursor - 3.0, 1.65, fill=1, stroke=0)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", font_size)
        for line in lines:
            pdf.drawString(x + 11, cursor - 6, line)
            cursor -= leading
        cursor -= 3.5
    return cursor


def draw_panel(
    pdf: canvas.Canvas,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    eyebrow: str,
    title: str,
    bullets: list[str],
    fill: HexColor,
    accent: HexColor,
) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(0.75)
    pdf.roundRect(x, y, width, height, 8, fill=1, stroke=1)
    pdf.setFillColor(accent)
    pdf.roundRect(x, y + height - 8, width, 8, 8, fill=1, stroke=0)
    pdf.rect(x, y + height - 8, width, 4, fill=1, stroke=0)

    pdf.setFillColor(accent)
    pdf.setFont("Helvetica-Bold", 7.1)
    pdf.drawString(x + 14, y + height - 27, eyebrow.upper())
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 13.2)
    pdf.drawString(x + 14, y + height - 47, title)
    draw_bullets(pdf, bullets, x=x + 14, y=y + height - 65, width=width - 28)


def draw_metric(
    pdf: canvas.Canvas, *, x: float, y: float, width: float, value: str, label: str
) -> None:
    pdf.setFillColor(PANEL)
    pdf.setStrokeColor(LINE)
    pdf.roundRect(x, y, width, 42, 6, fill=1, stroke=1)
    pdf.setFillColor(BLUE)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(x + width / 2, y + 22.5, value)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.6)
    pdf.drawCentredString(x + width / 2, y + 9, label.upper())


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    width, height = A4
    pdf = canvas.Canvas(str(OUTPUT), pagesize=A4, pageCompression=1)
    pdf.setTitle("Options Alpha - The Guarded Agent - One-Page Technical Summary")
    pdf.setAuthor("Options Alpha")
    pdf.setSubject("AI logic, deterministic risk gates, and Alpaca infrastructure")

    pdf.setFillColor(WHITE)
    pdf.rect(0, 0, width, height, fill=1, stroke=0)

    margin = 34
    pdf.setFillColor(BLUE)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(margin, height - 34, "OPTIONS ALPHA / ALPACA AI TRADING AGENTS HACKATHON")

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 25)
    pdf.drawString(margin, height - 68, "The Guarded Agent")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9.3)
    pdf.drawString(
        margin,
        height - 86,
        "Autonomous options paper trading where AI proposes and deterministic controls decide.",
    )

    badge_width = 137
    badge_x = width - margin - badge_width
    pdf.setFillColor(AMBER_PALE)
    pdf.setStrokeColor(AMBER)
    pdf.roundRect(badge_x, height - 76, badge_width, 30, 15, fill=1, stroke=1)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawCentredString(badge_x + badge_width / 2, height - 64, "PAPER ONLY / EXECUTION OFF")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.6)
    pdf.drawCentredString(badge_x + badge_width / 2, height - 72, "KILL SWITCH ON")

    metrics_y = height - 142
    metric_gap = 7
    metric_width = (width - 2 * margin - 4 * metric_gap) / 5
    metrics = [
        ("$100K", "verified equity"),
        ("LEVEL 3", "options approval"),
        ("0", "orders and fills"),
        ("2", "production structures"),
        ("128", "tests passing"),
    ]
    for index, (value, label) in enumerate(metrics):
        draw_metric(
            pdf,
            x=margin + index * (metric_width + metric_gap),
            y=metrics_y,
            width=metric_width,
            value=value,
            label=label,
        )

    column_gap = 12
    panel_width = (width - 2 * margin - column_gap) / 2
    panel_height = 235
    top_y = 404
    bottom_y = 157

    draw_panel(
        pdf,
        x=margin,
        y=top_y,
        width=panel_width,
        height=panel_height,
        eyebrow="01 / Probabilistic layer",
        title="AI reasons - it never brokers",
        bullets=[
            "Daily direction plus a one-minute pullback/reversal gate limits AI calls.",
            "Featherless receives only sanitized, timestamped Alpaca evidence.",
            "One strict JSON decision: NO_TRADE or one allowlisted options proposal.",
            "Malformed, stale, missing, or unsupported output fails closed to abstention.",
            (
                "Evidence, model metadata, hashes, token use, cost, and rejected "
                "alternatives are audited."
            ),
            "The AI module has no Alpaca order client and cannot change risk limits.",
        ],
        fill=BLUE_PALE,
        accent=BLUE,
    )
    draw_panel(
        pdf,
        x=margin + panel_width + column_gap,
        y=top_y,
        width=panel_width,
        height=panel_height,
        eyebrow="02 / Deterministic layer",
        title="Capital protection is recomputed",
        bullets=[
            "Production permits only signal-matched call or put debit spreads.",
            "Debit and maximum loss are rebuilt from option legs, never trusted from AI output.",
            (
                "Gates cover confidence, 2--10 DTE, quote freshness, spread, OI, trade risk, "
                "portfolio risk, drawdown, and positions."
            ),
            (
                "Existing positions block new entries for exit review; profit, stop, "
                "15-minute hold, expiry, partial-fill, and assignment states use "
                "AI-independent policies."
            ),
            (
                "Two execution approvals plus an independent kill switch guard the paper "
                "broker boundary."
            ),
        ],
        fill=TEAL_PALE,
        accent=TEAL,
    )
    draw_panel(
        pdf,
        x=margin,
        y=bottom_y,
        width=panel_width,
        height=panel_height,
        eyebrow="03 / Alpaca infrastructure",
        title="Real APIs, read-only proof first",
        bullets=[
            (
                "Official alpaca-py clients reconcile account, clock, orders, positions, "
                "contracts, and market data."
            ),
            (
                "Alpaca MCP evidence covers option chain, quote, IV, and Greeks on the free "
                "indicative feed."
            ),
            (
                "Two immutable 22-contract SPY snapshots include timestamps, Greeks, schema "
                "checks, and SHA-256."
            ),
            (
                "Closed-market live shadow evidence proves NO_TRADE and order_sent=false "
                "without an AI call."
            ),
            (
                "Worker and dashboard images bake in fail-closed paper defaults; CI is "
                "configured to build them."
            ),
        ],
        fill=PANEL,
        accent=INK,
    )
    draw_panel(
        pdf,
        x=margin + panel_width + column_gap,
        y=bottom_y,
        width=panel_width,
        height=panel_height,
        eyebrow="04 / Differentiator and evidence",
        title="Auditable abstention beats bravado",
        bullets=[
            (
                "A hash-chained trace links evidence, AI thesis, recomputed risk, preview, and "
                "broker state."
            ),
            (
                "Real-source shadow P&L uses adverse quote sides and exact legs; missing marks "
                "stay unmarked."
            ),
            (
                "Seeded scenarios and negative underlying holdouts are disclosed without "
                "being called options alpha."
            ),
            (
                "Current limitation: multi-date option history and open-market AI shadow "
                "evidence are still pending."
            ),
            (
                "Target users are small systematic traders and fintech builders; a future "
                "path is a hosted risk-and-audit API."
            ),
            (
                "Every failure mode becomes NO_TRADE, risk rejection, manual review, or "
                "blocked execution."
            ),
        ],
        fill=AMBER_PALE,
        accent=AMBER,
    )

    flow_y = 101
    pdf.setFillColor(INK)
    pdf.roundRect(margin, flow_y, width - 2 * margin, 40, 7, fill=1, stroke=0)
    pdf.setFillColor(WHITE)
    pdf.setFont("Helvetica-Bold", 8.4)
    flow = "EXIT REVIEW  ->  ALPACA EVIDENCE  ->  AI PROPOSAL  ->  RISK GATES  ->  UNSENT PREVIEW"
    pdf.drawCentredString(width / 2, flow_y + 23, flow)
    pdf.setFillColor(HexColor("#B9C5D1"))
    pdf.setFont("Helvetica", 6.8)
    pdf.drawCentredString(
        width / 2,
        flow_y + 10,
        "No provider failure, stale quote, rejected proposal, or audit error can become an order.",
    )

    pdf.setFillColor(AMBER)
    pdf.setFont("Helvetica-Bold", 8.2)
    pdf.drawString(margin, 74, "CURRENT FIRST-ORDER DECISION: NO-GO")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.3)
    pdf.drawString(
        margin,
        61,
        (
            "Execution stays disabled until multi-session validation, image smoke tests, "
            "durable cloud audit,"
        ),
    )
    pdf.drawString(
        margin,
        51,
        (
            "and explicit user approval. Live trading is prohibited by configuration and "
            "project policy."
        ),
    )

    pdf.setStrokeColor(LINE)
    pdf.line(margin, 38, width - margin, 38)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(
        margin, 25, "Options Alpha / Technical one-page / No credentials or paper account ID"
    )
    pdf.drawRightString(width - margin, 25, "Generated from the verified local repository")

    pdf.showPage()
    pdf.save()
    return OUTPUT


if __name__ == "__main__":
    print(build())
