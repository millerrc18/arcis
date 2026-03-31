"""Render docs/architecture.md from the live Arcis codebase."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DOC_PATH = ROOT / "docs" / "architecture.md"
OVERRIDES = {
    "src/models.py": "Backward-compatible schema re-exports for packet construction and older imports.",
    "src/evaluation/metrics.py": "Lightweight evaluation metrics helpers used by reporting and tests.",
    "src/packets/template.py": "Template packet builder and demo renderer for non-LLM packet generation.",
}

sys.path.insert(0, str(ROOT))

from scripts.schema_report import render_schema


def clean_text(text: str) -> str:
    replacements = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2192": "->",
        "\u2248": "~",
        "\u03c1": "rho",
        "\u2265": ">=",
        "\u2264": "<=",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\ufffd": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def module_description(path: Path) -> str:
    rel_path = path.relative_to(ROOT).as_posix()
    if rel_path in OVERRIDES:
        return OVERRIDES[rel_path]

    if path.name == "__init__.py":
        package_name = path.parent.name if path.parent != SRC else "src"
        return f"Package marker for {package_name}."

    text = path.read_text(encoding="utf-8")
    try:
        module = ast.parse(text)
        doc = ast.get_docstring(module)
    except SyntaxError:
        doc = None

    if doc:
        line = doc.splitlines()[0].strip().rstrip(".")
    else:
        line = path.stem.replace("_", " ")
    return clean_text(line) + "."


def render_module_inventory() -> str:
    directories = sorted(
        {
            path.parent
            for path in SRC.rglob("*.py")
            if "__pycache__" not in path.parts and not path.name.endswith("_backup.py")
        },
        key=lambda p: p.as_posix(),
    )
    lines: list[str] = []
    for directory in directories:
        files = sorted(
            path for path in directory.glob("*.py") if not path.name.endswith("_backup.py")
        )
        if not files:
            continue
        rel_dir = directory.relative_to(SRC).as_posix() or "root"
        lines.append(f"### `{rel_dir}/`")
        for path in files:
            rel_path = path.relative_to(ROOT).as_posix()
            lines.append(f"- `{rel_path}`: {module_description(path)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def route_description(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    if doc:
        return clean_text(doc.splitlines()[0].strip().rstrip(".")) + "."
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return clean_text(node.name.replace("_", " ")) + "."
    return "Route."


def render_api_inventory() -> str:
    route_files = [ROOT / "src" / "api" / "cloud_app.py", *sorted((ROOT / "src" / "api" / "routes").glob("*.py"))]
    lines: list[str] = []
    for path in route_files:
        if path.name == "__init__.py":
            continue
        rel_path = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lines.append(f"### `{rel_path}`")
        found = False
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                owner = getattr(dec.func.value, "id", None)
                if owner not in {"app", "router"}:
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                method = dec.func.attr.upper()
                route = dec.args[0].value
                lines.append(f"- `{method} {route}`: {route_description(node)}")
                found = True
        if not found:
            lines.append("- No HTTP routes declared in this file.")
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> None:
    module_inventory = render_module_inventory()
    api_inventory = render_api_inventory()
    schema_report = render_schema(ROOT / "ai_research_desk.sqlite3")

    content = f"""# Architecture

## System Overview
Arcis is an autonomous equity trading system for the S&P 100 that combines deterministic technical ranking, event-aware risk overlays, LLM-generated trade commentary, bracket-order execution through Alpaca, and a self-improving training loop. The live runtime is centered on the watch loop and scan service: market data and enrichment flow into feature computation, regime and event risk size the opportunity set, the ranker surfaces candidates, the packet writer produces structured commentary, the governor enforces hard limits, and the executor journals and manages trades end to end.

## Module Inventory
{module_inventory}

## API Endpoints
{api_inventory}

## Data Flow
1. Universe loading starts with `src/universe/sp100.py`, then `src/data_ingestion/market_data.py` and `src/features/engine.py` build the technical feature set.
2. Enrichment layers add fundamentals, insiders, news, macro context, and PEAD-style earnings signals via `src/data_enrichment/`.
3. `src/features/traffic_light.py` computes the regime overlay, and `src/features/event_risk_score.py` adds the 0-10 continuous calendar risk score plus sizing multiplier.
4. `src/ranking/ranker.py` filters and sorts the candidate set, while `src/services/scan_service.py` coordinates alerts, feature packaging, and packet generation.
5. `src/llm/packet_writer.py` writes XML commentary through Ollama by default, with optional GBNF-constrained generation through `src/llm/grammar_client.py`.
6. `src/risk/governor.py` applies hard portfolio rules, combining traffic-light and event-risk sizing with daily-loss, concentration, volatility, and duplicate-position checks.
7. `src/shadow_trading/executor.py` submits or simulates orders, journals outcomes through `src/journal/store.py`, and maintains bracket-backed open-position management.
8. `src/scheduler/watch.py` orchestrates the day: scans, premarket workflows, bracket monitoring, council sessions, overnight collection, scoring, reporting, and retraining triggers.

## Council Flow
1. `src/council/agents.py` gathers five analytical lenses: Tactical, Strategic, Red Team, Innovation, and Macro.
2. `src/council/protocol.py` runs independent Round 1 votes first, aggregates conviction-weighted outputs, and only escalates to Round 2 when consensus is weak.
3. `src/council/engine.py` persists sessions, votes, debug traces, parameter adjustments, and calibration records into the council tables.
4. `src/council/value_tracker.py` records counterfactual value attribution so the council can earn or lose authority based on realized outcomes.
5. The dashboard surfaces this through `frontend/src/pages/Council.jsx`, including vote cards, consensus labels, strategic prompts, and parameter-adjustment history.

## New Since Last Update
- Traffic Light regime overlay and live state tracking.
- PEAD enrichment features and earnings/event-aware risk handling.
- Implementation shortfall and council value-tracking infrastructure.
- HSHS live scoring and dashboard radar visualization.
- Council v2 vote-first protocol and updated Council dashboard page.
- Event calendar risk scoring with Telegram alerts and multiplicative sizing.
- Bracket health monitoring across intraday, premarket, and post-close checks.
- Optional GBNF grammar enforcement path for XML commentary generation.
- Training data ingestion gates with duplicate detection and compliance halts.
- Notes CRUD API and cloud dashboard Notes page.

## Deleted or Retired Runtime Modules
- `src/scheduler/overnight.py`: retired in favor of the consolidated `src/scheduler/watch.py` loop.
- `src/shadow_trading/broker.py`: no longer active in the runtime path.
- `*_backup.py` council v1 files: retained only as archival references and excluded from active imports, tests, and route generation.

## Database Schema
The following report is generated directly from `python scripts/schema_report.py` against the working SQLite database.

{schema_report}
"""

    DOC_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote architecture doc to {DOC_PATH}")


if __name__ == "__main__":
    main()
