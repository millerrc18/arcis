"""TradingState markdown renderer — pure formatter, no DB access.

Called by: src/tools/tradingstate/__main__.py (Task 7)
Calls: nothing (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/tools/test_tradingstate_cli.py
"""

from __future__ import annotations


def _render_positions(open_positions: list) -> str:
    """Render the open positions as a markdown table, or '(none)' if empty."""
    if not open_positions:
        return "(none)"

    cols = ["ticker", "trade_id", "source", "status", "entry_price", "entry_time", "thesis_text"]

    widths = {c: len(c) for c in cols}
    for row in open_positions:
        for c in cols:
            val = str(row.get(c, ""))
            widths[c] = max(widths[c], len(val))

    header = " | ".join(c.ljust(widths[c]) for c in cols)
    sep = "-|-".join("-" * widths[c] for c in cols)
    data_lines = [
        " | ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols)
        for row in open_positions
    ]
    return "\n".join([header, sep] + data_lines)


def _render_audit(most_recent_audit: dict | None) -> str:
    """Render the most recent audit details with stale flag, or '(no audit found)'."""
    if most_recent_audit is None:
        return "(no audit found)"

    audit_id = most_recent_audit.get("audit_id", "")
    created_at = most_recent_audit.get("created_at", "")
    assessment = most_recent_audit.get("overall_assessment", "")
    stale = most_recent_audit.get("stale", False)
    stale_label = " [STALE]" if stale else ""

    lines = [
        f"- Assessment: {assessment}{stale_label}",
        f"- Audit ID: {audit_id}",
        f"- Created at: {created_at}",
    ]
    return "\n".join(lines)


def _render_gpu_health(gpu_health: dict) -> str:
    """Render GPU health metrics as a markdown list."""
    def _fmt_status(val) -> str:
        if val is None:
            return "not measured"
        return "ok" if val else "failing"

    ollama_status = _fmt_status(gpu_health.get("ollama_ok"))
    training_status = _fmt_status(gpu_health.get("training_ok"))
    metric_date = gpu_health.get("metric_date", "")

    lines = [
        f"- Ollama: {ollama_status}",
        f"- Training: {training_status}",
        f"- Metric date: {metric_date}",
    ]
    return "\n".join(lines)


def render_markdown(snapshot: dict) -> str:
    """Render a TradingState snapshot dict as a 3-section markdown document.

    Sections: Positions, Audit, GPU Health.
    Pure formatter — does not call any DB or config code.
    """
    as_of_et = snapshot.get("as_of_et", "")

    positions_block = _render_positions(snapshot.get("open_positions", []))
    audit_block = _render_audit(snapshot.get("most_recent_audit"))
    gpu_block = _render_gpu_health(snapshot.get("gpu_health", {}))

    parts = [
        f"# Trading State (as of {as_of_et})",
        "",
        "## Positions",
        "",
        positions_block,
        "",
        "## Audit",
        "",
        audit_block,
        "",
        "## GPU Health",
        "",
        gpu_block,
    ]
    return "\n".join(parts)
