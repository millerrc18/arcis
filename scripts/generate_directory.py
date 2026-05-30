#!/usr/bin/env python3
"""Generate DIRECTORY.md — annotated repo tree with file counts and descriptions.

When to run:
    After every sprint, or when the module structure changes significantly.
    The output helps new contributors orient in the codebase.

What it reads:
    - Filesystem tree under the repo root (skipping .git, __pycache__, etc.)
    - src/schema/registry.py for table count
    - ANNOTATIONS dict in this file for directory/file descriptions

What it writes:
    - DIRECTORY.md in the repo root

Prerequisites:
    - git on PATH. The tree is intersected with `git ls-files` so only TRACKED
      repo structure is emitted — untracked scratch (tmp/, audit dumps, stray
      report files, the mojibake root file) never leaks into DIRECTORY.md even
      though we still walk the live filesystem for ordering/annotations. git is
      always present in a repo, so this is robust against ALL future debris;
      the SKIP set below is now only a perf shortcut for bulk/vendored dirs.

Usage:
    python scripts/generate_directory.py
"""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def _tracked_paths() -> set[Path]:
    """Absolute paths of every git-tracked file, plus all their parent dirs.

    Walking the filesystem (rglob / iterdir) sees untracked scratch; intersecting
    with this set keeps DIRECTORY.md a faithful index of the COMMITTED repo. Parent
    dirs are included so a tracked file keeps its enclosing directories visible.
    """
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    tracked: set[Path] = set()
    for rel in out.split("\0"):
        if not rel:
            continue
        f = (ROOT / rel).resolve()
        tracked.add(f)
        for parent in f.parents:
            tracked.add(parent)
            if parent == ROOT:
                break
    return tracked


TRACKED = _tracked_paths()

# Directories to skip
SKIP = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".pytest_cache", "dist", ".cache", ".idea", ".vscode",
    "unsloth_compiled_cache", ".claude",
    # Bulk data / vendored / runtime dirs — excluded so DIRECTORY.md stays a
    # code-structure index (these deep-walk to 10k+ leaf files otherwise).
    "data", "training_data", "logs", "llama.cpp", "models", "pg-data",
}

# Annotations for key directories and files
ANNOTATIONS = {
    # Root
    "MASTER.md": "Single source of truth — system state, architecture, decisions",
    "CLAUDE.md": "CC agent instructions — rules, schema, startup sequence",
    "README.md": "Public-facing project overview",
    "RELEASES.md": "Version history and release process",
    "CHANGELOG.md": "Detailed change log (all PRs)",
    "LICENSE": "BSL 1.1 — source-visible, Apache 2.0 in 2030",
    "render.yaml": "Render deployment configuration",
    "pyrightconfig.json": "Python type-checking config",
    "requirements.txt": "Core Python dependencies",
    "training/requirements.txt": "Training-specific deps (PEFT, TRL, BitsAndBytes) — relocated from repo root in v0.36.55 (#101) so GitHub's auto dependency-submission stops choking on the unsloth git+URL pin",
    "requirements-cloud.txt": "Render cloud deployment deps",
    # Top-level dirs
    "config/": "YAML settings, known violations, guardrail baselines",
    "data/": "Runtime data (gitignored) + reference data",
    "docs/": "Research, sprints, architecture, decisions, guides",
    "frontend/": "React 19 dashboard (Vite 8, Tailwind 4)",
    "scripts/": "Utility scripts (audit, stress test, migration, verification)",
    "src/": "Python backend (FastAPI, scheduler, trading, training, schema registry)",
    "tests/": "pytest suite (SQLite floor 5,467; live counts in Quick Stats)",
    # src/ modules
    "src/api/": "FastAPI routes (local + cloud), 120+ endpoints",
    "src/api/routes/": "Local API routes (14 files)",
    "src/api/cloud_routes/": "Render cloud API routes (6 files)",
    "src/attribution/": "Alpha attribution — LLM vs ranker-only comparison",
    "src/cli/": "CLI commands (scan, watch, shadow-status, etc.)",
    "src/commands/": "Command queue executor (11 command types)",
    "src/config/": "YAML config loader + environment detection",
    "src/council/": "5-agent AI Council — Modified Delphi protocol",
    "src/data_collection/": "12 overnight collectors (options, VIX, FRED, EDGAR, etc.)",
    "src/data_enrichment/": "7-dimension feature enrichment (Finnhub, news, insider)",
    "src/data_ingestion/": "Market data fetching (yfinance, Alpaca)",
    "src/email/": "SMTP email sender (digest, full-stream modes)",
    "src/evaluation/": "Build score, HSHS health, backtester, system validator",
    "src/features/": "Feature engine (regime, setup classifier, indicators, MR)",
    "src/journal/": "Trade journal — CRUD for shadow_trades (PostgreSQL runtime)",
    "src/llm/": "Ollama client, packet writer, conviction parser, validator",
    "src/logging/": "Structured logging configuration",
    "src/notifications/": "Telegram bot (32 notification functions)",
    "src/packets/": "Trade packet builder + renderer + EOD recap",
    "src/ranking/": "Deterministic ranker (score 0-100)",
    "src/risk/": "Risk governor (8 hard checks + kill switch)",
    "src/scheduler/": "Watch loop + 4-tier multi-cadence scanners",
    "src/schema/": "Schema registry — single source of truth for all DB tables + validator + Postgres sync",
    "src/services/": "Business logic services (scan, shadow, system)",
    "src/shadow_trading/": "Trade execution (Alpaca adapter, bracket orders, reconcile)",
    "src/strategy/": "Strategy configuration and dispatching",
    "src/sync/": "Render Postgres sync (incremental, per-table reconnect)",
    "src/training/": "Training pipeline (data collector, versioning, backfill, leakage)",
    "src/universe/": "S&P 100 universe management",
    "src/utils/": "Activity logger, helpers",
    # docs/ subdirs
    "docs/research/": "70+ research documents covering all system domains",
    "docs/research/deep-research/": "Deep research results (highest authority)",
    "docs/sprints/": "Sprint prompts and implementation plans",
    "docs/decisions/": "Architecture Decision Records (ADRs, 12 decisions)",
    "docs/archive/": "Archived docs (49 old sprints, audits, governance)",
    "docs/diagrams/": "13 SVG architecture diagrams (light/dark mode)",
    "docs/guides/": "Setup guides (email, audit plugin, daily audit)",
    "docs/blueprint/": "Original project blueprint",
    "docs/charter/": "Project charter (.docx)",
    # frontend/
    "frontend/src/": "React source code",
    "frontend/src/pages/": "Dashboard pages (count in Quick Stats)",
    "frontend/src/components/": "Shared UI components",
    "frontend/public/": "Static assets (icons, manifest, service worker)",
    # scripts/
    "scripts/stress_test.py": "Historical stress testing (2008/2020/2022)",
    "scripts/verify_docs.py": "Documentation count drift checker",
    "scripts/daily_repo_audit.py": "Automated CI audit (GitHub Actions)",
    "scripts/render_migrate.py": "Postgres schema migration from registry",
    "scripts/alpha_attribution_backtest.py": "Attribution backtest on historical data",
}


def count_files(path: Path, ext: str = ".py") -> int:
    # Match SKIP against path COMPONENTS, not substrings: a substring test wrongly
    # excludes legitimate dirs like src/data_collection (contains "data") and zeroes
    # the count when the repo lives under a skipped dir (e.g. a .claude worktree).
    # Also intersect with TRACKED so untracked scratch .py files don't inflate counts.
    return len([f for f in path.rglob(f"*{ext}") if f.name != "__init__.py"
                and not any(part in SKIP for part in f.parts)
                and f.resolve() in TRACKED])


def build_tree(root: Path, prefix: str = "", max_depth: int = 3, current_depth: int = 0) -> list[str]:
    lines = []
    if current_depth >= max_depth:
        return lines

    items = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    # Filter: drop SKIP dirs, dotfiles, and anything not git-tracked. TRACKED holds
    # tracked files AND their parent dirs, so a directory survives iff it contains
    # at least one tracked file — untracked scratch dirs/files are excluded.
    items = [i for i in items if i.name not in SKIP and not i.name.startswith(".")
             and i.resolve() in TRACKED]

    dirs = [i for i in items if i.is_dir()]
    files = [i for i in items if i.is_file()]

    for i, d in enumerate(dirs):
        is_last_dir = (i == len(dirs) - 1 and not files)
        connector = "└── " if is_last_dir else "├── "
        # .as_posix() not str() — Path.relative_to() returns backslash on
        # Windows ('training\\requirements.txt') which fails the ANNOTATIONS
        # lookup (keys are forward-slash, canonical POSIX). Bug surfaced on
        # the v0.36.55 (#101) training-reqs relocation, but the fix
        # generalizes to ALL future nested-path annotations.
        rel = d.relative_to(ROOT).as_posix() + "/"
        annotation = ANNOTATIONS.get(rel, "")

        # Add file count for src/ modules
        if "src/" in rel and current_depth >= 1:
            py_count = count_files(d)
            if py_count > 0:
                annotation = f"({py_count} files) {annotation}" if annotation else f"({py_count} files)"

        suffix = f"  ← {annotation}" if annotation else ""
        lines.append(f"{prefix}{connector}{d.name}/{suffix}")

        child_prefix = prefix + ("    " if is_last_dir else "│   ")
        lines.extend(build_tree(d, child_prefix, max_depth, current_depth + 1))

    for i, f in enumerate(files):
        is_last = (i == len(files) - 1)
        connector = "└── " if is_last else "├── "
        # See dir-loop comment above re: as_posix() vs str().
        rel = f.relative_to(ROOT).as_posix()
        annotation = ANNOTATIONS.get(rel, "")
        suffix = f"  ← {annotation}" if annotation else ""
        lines.append(f"{prefix}{connector}{f.name}{suffix}")

    return lines


def main():
    py_count = count_files(ROOT / "src")
    test_count = count_files(ROOT / "tests")
    page_count = len(list((ROOT / "frontend" / "src" / "pages").glob("*.jsx")))
    research_count = len(list((ROOT / "docs" / "research").rglob("*.md")))
    # Authoritative table count: import the registry's TABLES dict directly rather
    # than regex-counting `_register` calls (the regex is brittle — it silently
    # drifts if a helper is renamed or a call is reformatted off column 0).
    import sys
    sys.path.insert(0, str(ROOT))
    from src.schema.registry import TABLES
    table_count = len(TABLES)

    header = f"""# Arcis Repository Directory

> **Auto-generated** by `scripts/generate_directory.py` — run after every sprint.
> Last updated: {__import__('datetime').date.today().isoformat()}

## Quick Stats

| Metric | Count |
|---|---|
| Python source files | {py_count} |
| Test files | {test_count} |
| Dashboard pages | {page_count} |
| Research documents | {research_count} |
| Schema tables | {table_count} |

## Directory Tree

```
arcis/
"""

    tree_lines = build_tree(ROOT, max_depth=3)
    tree = "\n".join(tree_lines)

    footer = """```

## Key Files (start here)

| File | Purpose |
|---|---|
| `MASTER.md` | **Read this first.** System state, architecture, all 24 strategy decisions, phase gates. |
| `CLAUDE.md` | Agent instructions — mandatory rules for CC sprints. |
| `RELEASES.md` | Version history, release process, path to v1.0.0. |
| `src/schema/registry.py` | Single source of truth for all 49 database tables. |
| `src/scheduler/watch.py` | The main loop — scans, monitors, collects, trains. |
| `config/settings.example.yaml` | All configuration keys with descriptions. |
| `docs/sprints/` | Sprint prompts ready to fire in CC. |

## Module Map (src/)

Each module has a standard 5-field docstring header:
```
Called by: ...
Calls: ...
Owns tables: ...
Config keys: ...
Tests: ...
```

Use `grep -n "Called by:" src/**/*.py` to trace the dependency graph.
"""

    output = ROOT / "DIRECTORY.md"
    output.write_text(header + tree + "\n" + footer, encoding="utf-8")
    print(f"Generated {output} ({len(tree_lines)} tree lines)")


if __name__ == "__main__":
    main()
