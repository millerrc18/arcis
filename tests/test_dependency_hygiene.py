"""Regression tests for the Area B dependency hygiene PR.

Covers:
- #461: three circular import cycles, broken by extracting shared primitives
- #463: sqlalchemy phantom dependency removed from requirements-cloud.txt
- #464: FastAPI on_event("startup") migrated to lifespan context manager
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


# ── #461: Circular imports — shared primitives live in neutral modules ───

def test_cycle1_price_helper_in_neutral_module():
    """#461 Cycle 1: _get_current_price_safe must live outside the
    risk.governor ↔ shadow_trading.executor cycle."""
    from src.risk.price_utils import _get_current_price_safe
    assert callable(_get_current_price_safe)


def test_cycle2_slope_direction_in_indicators():
    """#461 Cycle 2: _slope_direction must live in features.indicators,
    not features.engine (engine.py ↔ regime.py cycle)."""
    from src.features.indicators import _slope_direction
    assert callable(_slope_direction)


def test_cycle3_structured_formatter_in_formatters():
    """#461 Cycle 3: StructuredFormatter must live in observability.formatters,
    not log_config (log_config ↔ loki_handler cycle)."""
    from src.observability.formatters import StructuredFormatter
    import logging
    assert issubclass(StructuredFormatter, logging.Formatter)


def _module_name_for_file(path: Path) -> str:
    """Convert a src/... path to its dotted module name."""
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    return ".".join(rel.parts)


def _top_level_import_sources(path: Path) -> set[str]:
    """Return {module name} for every top-level `from X import ...` in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in tree.body:  # only top-level
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_no_top_level_bidirectional_import_between_cycle_pairs():
    """#461: each previously-cycling pair must not have BOTH sides doing
    top-level imports of each other. Guards against a future refactor
    lifting a deferred import to module scope on both ends simultaneously."""
    pairs = [
        (REPO_ROOT / "src/risk/governor.py",
         REPO_ROOT / "src/shadow_trading/executor.py"),
        (REPO_ROOT / "src/features/regime.py",
         REPO_ROOT / "src/features/engine.py"),
        (REPO_ROOT / "src/log_config.py",
         REPO_ROOT / "src/observability/loki_handler.py"),
    ]
    failures: list[str] = []
    for a, b in pairs:
        a_mod = _module_name_for_file(a)
        b_mod = _module_name_for_file(b)
        a_imports = _top_level_import_sources(a)
        b_imports = _top_level_import_sources(b)
        a_imports_b = b_mod in a_imports
        b_imports_a = a_mod in b_imports
        if a_imports_b and b_imports_a:
            failures.append(f"Top-level cycle: {a_mod} ↔ {b_mod}")
    assert not failures, "Top-level circular imports detected:\n  " + "\n  ".join(failures)


# ── #463: sqlalchemy phantom dependency ──────────────────────────────────

def test_sqlalchemy_not_in_requirements_cloud():
    """#463: sqlalchemy is not imported anywhere in production code — must not
    appear in requirements.txt (formerly requirements-cloud.txt which was
    consolidated; the cloud-specific file no longer exists)."""
    req_file = REPO_ROOT / "requirements.txt"
    if not req_file.exists():
        import pytest
        pytest.skip("requirements.txt not found — skipping sqlalchemy check")
    content = req_file.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        # Match "sqlalchemy" as a package name (allow -binary, version suffixes)
        pkg = stripped.split(";")[0].split("==")[0].split(">")[0].split("<")[0].split("[")[0].strip().lower()
        assert pkg != "sqlalchemy", (
            f"sqlalchemy is phantom — no imports anywhere in src/. "
            f"Found in requirements-cloud.txt: {stripped!r}"
        )


# ── #464: FastAPI lifespan migration ─────────────────────────────────────

def test_api_app_uses_lifespan_not_on_event():
    """#464: @app.on_event() was deprecated in FastAPI 0.93 — src/api/app.py
    must use the lifespan context manager pattern instead. Checks the AST
    for a decorator call rather than string-matching to avoid false matches
    on docstrings that reference the old API."""
    tree = ast.parse((REPO_ROOT / "src/api/app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            # Match `@app.on_event(...)` — Attribute + Call
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "on_event"
            ):
                raise AssertionError(
                    f"src/api/app.py still decorates {node.name}() with @*.on_event"
                )

    source = (REPO_ROOT / "src/api/app.py").read_text(encoding="utf-8")
    assert "lifespan=" in source, (
        "src/api/app.py must pass lifespan= to FastAPI(...)"
    )


def test_api_app_lifespan_is_asynccontextmanager():
    """#464: the lifespan function must be decorated with @asynccontextmanager
    and be async — synchronous lifespan definitions will raise at startup."""
    tree = ast.parse((REPO_ROOT / "src/api/app.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            decorator_names = [
                d.id if isinstance(d, ast.Name) else
                d.attr if isinstance(d, ast.Attribute) else None
                for d in node.decorator_list
            ]
            assert "asynccontextmanager" in decorator_names, (
                "lifespan() must be @asynccontextmanager-decorated"
            )
            return
    raise AssertionError("src/api/app.py has no `async def lifespan(...)`")
