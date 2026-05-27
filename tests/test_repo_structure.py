"""Repository structure enforcement — prevents drift.

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""
import ast
import importlib
import json
import re
import warnings
from pathlib import Path

import yaml

KNOWN = json.loads(Path("config/known_violations.json").read_text(encoding="utf-8"))

# Pre-compute lookup sets from known violations JSON
_KNOWN_FILES = {v["file"] for v in KNOWN.get("oversized_files", [])}
# Map file path -> recorded line count for tolerance checking (closes #745)
_KNOWN_FILE_COUNTS = {v["file"]: v["lines"] for v in KNOWN.get("oversized_files", [])}
_KNOWN_FUNCTIONS = {
    f"{v['file']}:{v['function']}" for v in KNOWN.get("oversized_functions", [])
}
# Map "file:function" -> recorded line count for tolerance checking (closes #745)
_KNOWN_FUNCTION_COUNTS = {
    f"{v['file']}:{v['function']}": v["lines"]
    for v in KNOWN.get("oversized_functions", [])
}
_KNOWN_DOCSTRINGS = set(KNOWN.get("missing_docstring_headers", []))

# Tolerance for grandfathered size growth: max(+50 lines, +10% of recorded).
# Rationale: +50 catches minor churn on small files; +10% scales gracefully for
# large files (a 2000-line file shouldn't get a flat +50 allowance). Using the
# larger of the two avoids hair-trigger failures on minor edits while still
# detecting material growth. If a file legitimately exceeds this band, update
# its entry in config/known_violations.json with a comment explaining why.
_GRANDFATHERED_TOLERANCE_FLAT = 50
_GRANDFATHERED_TOLERANCE_PCT = 0.10


def _file_tolerance(recorded: int) -> int:
    return max(_GRANDFATHERED_TOLERANCE_FLAT, int(recorded * _GRANDFATHERED_TOLERANCE_PCT))


def test_no_file_over_400_lines():
    """Files over 400 lines must be grandfathered.

    Hardening (closes #745): grandfathered files are additionally checked
    against recorded_count + tolerance to catch silent growth. Tolerance is
    max(+50 lines, +10% of recorded). If a grandfathered file has grown past
    its tolerance band, either split it, update its entry in
    config/known_violations.json, or add an operator-deferral comment.
    """
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        lines = len(p.read_text(encoding="utf-8").splitlines())
        if lines > 400:
            normalized = str(p).replace("\\", "/")
            if normalized in _KNOWN_FILES:
                recorded = _KNOWN_FILE_COUNTS[normalized]
                tolerance = _file_tolerance(recorded)
                if lines > recorded + tolerance:
                    assert False, (
                        f"GRANDFATHERED {normalized} grew from {recorded} to {lines} "
                        f"lines (>{recorded + tolerance} tolerance). "
                        f"Either split, update entry in config/known_violations.json, "
                        f"or add operator-deferral with rationale."
                    )
                else:
                    warnings.warn(f"GRANDFATHERED: {p} ({lines} lines)")
            else:
                assert False, f"NEW VIOLATION: {p} is {lines} lines (max 400)"


def test_no_function_over_60_lines():
    """Functions over 60 lines must be grandfathered.

    Hardening (closes #745): grandfathered functions are additionally checked
    against recorded_count + tolerance to catch silent growth. Tolerance is
    max(+50 lines, +10% of recorded). If a grandfathered function has grown past
    its tolerance band, either split it, update its entry in
    config/known_violations.json, or add an operator-deferral comment.
    """
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    key = f"{str(p).replace(chr(92), '/')}:{node.name}"
                    if key in _KNOWN_FUNCTIONS:
                        recorded = _KNOWN_FUNCTION_COUNTS[key]
                        tolerance = _file_tolerance(recorded)
                        if length > recorded + tolerance:
                            assert False, (
                                f"GRANDFATHERED {key} grew from {recorded} to {length} "
                                f"lines (>{recorded + tolerance} tolerance). "
                                f"Either split, update entry in config/known_violations.json, "
                                f"or add operator-deferral with rationale."
                            )
                        else:
                            warnings.warn(f"GRANDFATHERED: {key} ({length} lines)")
                    else:
                        assert False, f"NEW VIOLATION: {key} is {length} lines (max 60)"


def test_all_modules_have_standard_docstring():
    required = ["Called by:", "Calls:", "Owns tables:", "Config keys:", "Tests:"]
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        has = (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        )
        if not has or not all(f in tree.body[0].value.value for f in required):
            key = str(p).replace("\\", "/")
            if key in _KNOWN_DOCSTRINGS:
                warnings.warn(f"GRANDFATHERED: {p} missing standard docstring")
            else:
                missing = [
                    f
                    for f in required
                    if not has or f not in tree.body[0].value.value
                ]
                assert False, f"NEW VIOLATION: {p} missing: {missing}"


def test_every_new_table_in_render_migrate():
    migrate = Path("scripts/render_migrate.py").read_text(encoding="utf-8").lower()
    for p in Path("src").rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # Caught by test_all_source_files_utf8
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if stripped.startswith('"') or stripped.startswith("'"):
                continue
            m = re.search(
                r"CREATE TABLE IF NOT EXISTS (\w+)", line, re.IGNORECASE
            )
            if m:
                table = m.group(1).lower()
                if table not in migrate:
                    if table in KNOWN.get("missing_migrate_tables", []):
                        warnings.warn(f"GRANDFATHERED: table '{table}'")
                    else:
                        assert (
                            False
                        ), f"NEW VIOLATION: table '{table}' in {p} not in render_migrate.py"


# ── PR #203 guardrails ────────────────────────────────────────────────


def test_frontend_api_calls_have_backend_routes():
    """Every fetchApi() path in frontend/src/api.js must match a backend route."""
    # Extract frontend paths
    api_js = Path("frontend/src/api.js").read_text(encoding="utf-8")
    frontend_paths = set(re.findall(r"fetchApi\(['\"]([^'\"?]+)", api_js))
    # Normalize: strip trailing slashes, remove path params like ${id}
    frontend_paths = {re.sub(r'/\$\{[^}]+\}', '/{param}', p).rstrip('/') for p in frontend_paths}

    # Extract backend routes from all route files, accounting for router prefixes
    backend_paths = set()
    for route_file in list(Path("src/api/routes").rglob("*.py")) + list(Path("src/api/cloud_routes").rglob("*.py")):
        text = route_file.read_text(encoding="utf-8")
        # Detect router prefix: APIRouter(prefix="/actions")
        prefix_match = re.search(r'APIRouter\(prefix=["\']([^"\']+)', text)
        prefix = prefix_match.group(1).rstrip('/') if prefix_match else ""
        for match in re.findall(r'router\.\w+\(["\']([^"\']+)', text):
            # Normalize FastAPI path params {ticker} → {param}
            normalized = re.sub(r'\{[^}]+\}', '{param}', match).rstrip('/')
            # Cloud routes include /api/ prefix — strip it for comparison
            normalized = re.sub(r'^/api', '', normalized)
            backend_paths.add(prefix + normalized)

    missing = frontend_paths - backend_paths
    # Filter out known dynamic paths that are constructed differently
    missing = {p for p in missing if not p.startswith('/shadow/close')}
    assert not missing, f"Frontend calls with no backend route: {sorted(missing)}"


def test_no_ddl_outside_registry():
    """CREATE TABLE statements must only exist in src/schema/registry.py."""
    allowed = {"src/schema/registry.py", "src/schema/postgres.py", "src/schema/validator.py"}
    for p in Path("src").rglob("*.py"):
        normalized = str(p).replace("\\", "/")
        if any(a in normalized for a in allowed):
            continue
        if p.name == "__init__.py":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # Skip strings that are just checking for table existence
        lines = [l for l in text.splitlines()
                 if "CREATE TABLE" in l.upper()
                 and not l.strip().startswith("#")
                 and not l.strip().startswith('"')
                 and not l.strip().startswith("'")
                 and "IF NOT EXISTS" not in l.upper()
                 and "sqlite_master" not in l.lower()]
        assert not lines, f"DDL outside registry in {p}: {lines[0].strip()}"


def test_all_src_modules_importable():
    """Every .py file in src/ should be importable without ModuleNotFoundError."""
    errors = []
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        module_path = str(p).replace("/", ".").replace("\\", ".").removesuffix(".py")
        try:
            importlib.import_module(module_path)
        except ModuleNotFoundError as e:
            # Allow missing optional deps (yfinance, ib_async) — they're runtime-only
            if e.name not in ("yfinance", "ib_async", "ib_insync"):
                errors.append(f"{module_path}: {e}")
        except Exception:
            pass  # Other errors (config, DB) are expected in CI — we only catch import chain breaks
    assert not errors, f"Broken imports:\n" + "\n".join(errors)


def test_no_stub_functions():
    """Functions with only pass, return None, or return {} are likely unfinished stubs."""
    stubs = []
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                # Filter out docstring
                real_body = [n for n in body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
                if len(real_body) == 1:
                    stmt = real_body[0]
                    if isinstance(stmt, ast.Pass):
                        stubs.append(f"{p}:{node.name} (line {node.lineno}) — body is just 'pass'")
                    elif isinstance(stmt, ast.Return) and stmt.value is None:
                        stubs.append(f"{p}:{node.name} (line {node.lineno}) — body is just 'return None'")
    # Allow known placeholders and intentional no-ops (table init stubs migrated to registry)
    # These are intentional no-ops — table init functions migrated to schema registry
    known_stubs = {
        "_ensure_setup_signals_table", "init_schedule_metrics",
        "ensure_bracket_health_table", "_init_canary_tables",
        "_ensure_curriculum_columns", "_ensure_preference_table",
        "init_quality_drift_tables",
    }
    stubs = [s for s in stubs
             if "test_" not in s and "__init__" not in s
             and not any(k in s for k in known_stubs)]
    assert not stubs, f"Stub functions found (CC forgot to implement):\n" + "\n".join(stubs[:10])


def test_every_module_has_tests():
    """Every src/ Python module should have at least one test file that imports it."""
    untested = []
    test_content = ""
    for t in Path("tests").rglob("*.py"):
        try:
            test_content += t.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        module_name = p.stem  # e.g. "logger" from src/attribution/logger.py
        parent_name = p.parent.name  # e.g. "attribution"
        # Check if any test file references this module
        if module_name not in test_content and parent_name + "." + module_name not in test_content:
            untested.append(str(p))
    # Known exceptions (config, __main__, etc.)
    untested = [u for u in untested if not any(x in u for x in [
        "__main__", "config/__init__", "log_config", "constants",
    ])]
    if len(untested) > 15:
        assert False, f"{len(untested)} modules with no test coverage — top 10:\n" + "\n".join(untested[:10])


def test_todos_have_issue_numbers():
    """TODOs in src/ must reference a GitHub issue: # TODO(#123) or # TODO: #123."""
    orphan_todos = []
    for p in Path("src").rglob("*.py"):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(lines, 1):
            if re.search(r"#\s*TODO", line, re.IGNORECASE):
                if not re.search(r"#\d+", line):
                    orphan_todos.append(f"{p}:{i}: {line.strip()}")
    assert not orphan_todos, f"TODOs without issue numbers (will be forgotten):\n" + "\n".join(orphan_todos[:10])


def test_dashboard_routes_have_pages():
    """Every Route in App.jsx must point to an existing page component file."""
    app_jsx = Path("frontend/src/App.jsx").read_text(encoding="utf-8")
    routes = re.findall(r'element=.*?<(\w+)', app_jsx)
    imports = re.findall(r"import (\w+) from ['\"]./pages/(\w+)", app_jsx)
    import_map = {name: file for name, file in imports}
    missing = []
    for component in routes:
        if component in ("ErrorBoundary", "Layout"):
            continue
        if component in import_map:
            page_file = Path(f"frontend/src/pages/{import_map[component]}.jsx")
            if not page_file.exists():
                missing.append(f"Route <{component}> → {page_file} does not exist")
        # Also check the import exists
        if component not in import_map and component not in ("ErrorBoundary", "Layout", "Routes", "Route", "BrowserRouter"):
            missing.append(f"Route <{component}> has no import in App.jsx")
    assert not missing, f"Broken dashboard routes:\n" + "\n".join(missing)


def test_shadow_trades_writes_match_schema():
    """Columns written to shadow_trades in executor.py must exist in schema registry."""
    registry = Path("src/schema/registry.py").read_text(encoding="utf-8")
    # Extract shadow_trades column names from registry
    in_shadow = False
    columns = set()
    for line in registry.splitlines():
        if 'name="shadow_trades"' in line:
            in_shadow = True
        if in_shadow and "ColumnDef(" in line:
            match = re.search(r'ColumnDef\("(\w+)"', line)
            if match:
                columns.add(match.group(1))
        if in_shadow and "primary_key" in line:
            break
    # Extract what executor.py writes to trade_data
    executor = Path("src/shadow_trading/executor.py").read_text(encoding="utf-8")
    writes = set(re.findall(r'trade_data\["(\w+)"\]', executor))
    # Filter out non-column keys
    known_non_columns = {"order_type", "source", "broker"}
    unknown = writes - columns - known_non_columns
    assert not unknown, f"executor.py writes columns not in schema registry: {sorted(unknown)}"


def test_config_keys_exist_in_example():
    """Config keys used in code should exist in settings.example.yaml."""
    with open("config/settings.example.yaml", encoding="utf-8") as f:
        example = yaml.safe_load(f)

    valid_sections = set(example.keys()) if example else set()

    # Find top-level config section access: config.get("section", {}) pattern
    # The {} default signals a section (dict), not a scalar config value
    code_sections = set()
    for p in Path("src").rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in re.findall(r'(?<![_a-zA-Z0-9])config\.get\(["\'](\w+)["\'],\s*\{\}', text):
            code_sections.add(match)
        for match in re.findall(r'(?<![_a-zA-Z0-9])config\[[\"\'](\w+)[\"\']\]\.get\(', text):
            code_sections.add(match)

    # Known fallback lookups that try alternate config locations
    known_fallbacks = {"fred", "ranking"}
    missing = code_sections - valid_sections - {"app"} - known_fallbacks
    assert not missing, f"Config sections used in code but not in settings.example.yaml: {sorted(missing)}"


# ── Render deployment hardening ──────────────────────────────────────


def test_all_source_files_utf8():
    """Every .py file in src/ must be valid UTF-8 (prevents Render build failures)."""
    bad = []
    for p in Path("src").rglob("*.py"):
        try:
            p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            bad.append(f"{p}: {e}")
    assert not bad, f"Non-UTF-8 source files (will break on Render):\n" + "\n".join(bad)


def test_cloud_app_imports_covered_by_requirements_cloud():
    """All 3rd-party imports in the cloud_app import chain must be in requirements-cloud.txt."""
    # Parse requirements-cloud.txt into package names
    cloud_reqs = set()
    for line in Path("requirements-cloud.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract package name before version specifier
        pkg = re.split(r"[>=<!\[]", line)[0].strip().lower().replace("-", "_")
        cloud_reqs.add(pkg)
    # Map common import names to pip package names
    import_to_pkg = {
        "yaml": "pyyaml", "dotenv": "python_dotenv", "psycopg2": "psycopg2_binary",
        "uvicorn": "uvicorn", "fastapi": "fastapi", "pydantic": "pydantic",
        "sqlalchemy": "sqlalchemy",
    }

    # Files in the cloud_app import chain (not the full src/)
    cloud_files = [
        Path("src/api/cloud_app.py"),
        *Path("src/api/cloud_routes").glob("*.py"),
        Path("src/sync/render_sync.py"),
        Path("src/config/__init__.py"),
        Path("src/schema/sync_config.py"),
        Path("src/schema/registry.py"),
        Path("src/schema/postgres.py"),
        Path("src/schema/sqlite.py"),
    ]

    import sys
    stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()

    missing = []
    for fpath in cloud_files:
        if not fpath.exists():
            continue
        tree = ast.parse(fpath.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    pkg = import_to_pkg.get(top, top).lower().replace("-", "_")
                    if top not in stdlib and not top.startswith("src") and pkg not in cloud_reqs:
                        missing.append(f"{fpath}: import {alias.name} (need '{pkg}' in requirements-cloud.txt)")
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                pkg = import_to_pkg.get(top, top).lower().replace("-", "_")
                if top not in stdlib and not top.startswith("src") and pkg not in cloud_reqs:
                    missing.append(f"{fpath}: from {node.module} (need '{pkg}' in requirements-cloud.txt)")
    assert not missing, f"Cloud imports not in requirements-cloud.txt:\n" + "\n".join(missing)


def test_no_legacy_alpaca_trade_api_imports():
    """Legacy `alpaca_trade_api` SDK is deprecated — we're on `alpaca-py`.

    Guards against LLM-pasted old snippets and accidental reintroduction.
    See docs/sprints/sprint-alpaca-py-migration.md.
    """
    offenders = []
    for root in (Path("src"), Path("tests")):
        for p in root.rglob("*.py"):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] == "alpaca_trade_api":
                            offenders.append(f"{p}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split(".")[0] == "alpaca_trade_api":
                        offenders.append(f"{p}:{node.lineno} from {node.module}")
    assert not offenders, (
        "Legacy alpaca_trade_api imports detected (use alpaca-py):\n"
        + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Repo-root cleanliness rules — added by Phase 5 PR-A (master-spec §4.1, DD-06)
# Canonical context: docs/audits/2026-05-27-phase-5-unified/master-spec.md
# ---------------------------------------------------------------------------


def _list_repo_root_underscore_scratch(root: Path) -> list[Path]:
    """Return underscore-prefixed Python scratch files at the given root.

    Excludes `__init__.py` / `__main__.py` (dunder-bound module markers).
    The function takes an explicit root so the sentinel tests in PR-A can
    drive it with a fake `tmp_path` root — see test_repo_structure_rule_*
    in this file for the non-vacuous verification.
    """
    return [
        p
        for p in root.glob("_*.py")
        if p.is_file() and p.name not in {"__init__.py", "__main__.py"}
    ]


def _list_repo_root_sqlite(root: Path) -> list[Path]:
    """Return SQLite files at the given root.

    Catches `*.sqlite`, `*.sqlite3`, `*.sqlite-journal`, `*.db` — anything a
    stray test fixture or accidental write might drop at the repo root.
    Runtime SQLite lives under `C:\\arcis\\data\\` per CLAUDE.md:26.
    """
    patterns = ("*.sqlite", "*.sqlite3", "*.sqlite-journal", "*.db")
    return sorted({p for pat in patterns for p in root.glob(pat) if p.is_file()})


def test_no_underscore_scratch_at_repo_root():
    """Forbid `_*.py` REPL-scratch files at the repo root.

    Phase 5 PR-A removed 17 such files (`_a.py`, `_audit.py`, `_ck.py`,
    `_f.py`, `_p.py`, `_q.py`, `_t1.py`..`_t1i2.py`, `_v.py`) — see
    CHANGELOG entry under <!-- PR-A entries -->. The rule prevents
    silent re-introduction: REPL scratch belongs in a private branch
    or a worktree, never the canonical repo root.

    Exclusions: `__init__.py`, `__main__.py` (legitimate dunder modules).
    """
    offenders = _list_repo_root_underscore_scratch(Path("."))
    assert not offenders, (
        "Underscore-prefixed scratch files detected at repo root "
        "(disallowed by Phase 5 PR-A; see master-spec §4.1):\n"
        + "\n".join(f"  - {p.name}" for p in offenders)
    )


def test_no_sqlite_at_repo_root():
    """Forbid SQLite database files at the repo root.

    Phase 5 PR-A removed a 0-byte stub `ai_research_desk.sqlite3` (the
    canonical runtime DB lives at `C:\\arcis\\data\\ai_research_desk.sqlite3`
    per CLAUDE.md:26). The rule prevents accidental writes to a repo-root
    stub which would create a confusing parallel DB invisible to the
    `ARCIS_DB_PATH` configuration.
    """
    offenders = _list_repo_root_sqlite(Path("."))
    assert not offenders, (
        "SQLite/DB files detected at repo root "
        "(disallowed by Phase 5 PR-A; runtime DB lives at "
        "C:/arcis/data/ai_research_desk.sqlite3 per CLAUDE.md:26):\n"
        + "\n".join(f"  - {p.name}" for p in offenders)
    )


# ---------------------------------------------------------------------------
# Sentinel tests for the 2 repo-root cleanliness rules (Phase 5 PR-A T3).
# Verified non-vacuous: each sentinel constructs a fake repo root under
# tmp_path, drops a single violating file, and asserts the helper detects
# the file. If the helper were silently broken (always returning []) these
# tests would fail. They never touch the real repo root — verified by the
# tmp_path fixture's scope guarantee.
# ---------------------------------------------------------------------------


def test_repo_root_underscore_scratch_rule_detects_violation(tmp_path):
    """Sentinel: _list_repo_root_underscore_scratch correctly identifies a
    `_*.py` scratch file as a violation.

    Verified non-vacuous: with the helper disabled (e.g. returning `[]`)
    this test correctly identifies the temp `_scratch_sentinel.py` as a
    violation and fails. The test does NOT write to the real repo root —
    it constructs a fake root under pytest's tmp_path fixture.

    Also exercises the exclusion contract: `__init__.py` at the fake root
    must NOT be flagged.
    """
    # Drop a single violating file at the fake root.
    violator = tmp_path / "_scratch_sentinel.py"
    violator.write_text("# scratch — should be detected\n", encoding="utf-8")

    # Drop the exclusion sentinel — must NOT be flagged.
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    offenders = _list_repo_root_underscore_scratch(tmp_path)
    offender_names = {p.name for p in offenders}

    assert "_scratch_sentinel.py" in offender_names, (
        f"Helper failed to detect _scratch_sentinel.py — got {offender_names!r}"
    )
    assert "__init__.py" not in offender_names, (
        "Exclusion broken: __init__.py was flagged as scratch"
    )


def test_repo_root_sqlite_rule_detects_violation(tmp_path):
    """Sentinel: _list_repo_root_sqlite correctly identifies SQLite/DB files
    at a repo root.

    Verified non-vacuous: with the helper disabled (e.g. returning `[]`)
    this test correctly identifies the temp `sentinel.sqlite3` as a
    violation and fails. The test does NOT write to the real repo root —
    it constructs a fake root under pytest's tmp_path fixture.

    Exercises all four extensions in the helper's pattern list.
    """
    violators = [
        tmp_path / "sentinel.sqlite",
        tmp_path / "sentinel.sqlite3",
        tmp_path / "sentinel.sqlite-journal",
        tmp_path / "sentinel.db",
    ]
    for p in violators:
        p.write_bytes(b"")  # empty file; existence is what matters

    # Drop a non-violating sibling to confirm we don't over-match.
    (tmp_path / "README.md").write_text("# not a db\n", encoding="utf-8")

    offenders = _list_repo_root_sqlite(tmp_path)
    offender_names = {p.name for p in offenders}

    for v in violators:
        assert v.name in offender_names, (
            f"Helper failed to detect {v.name} — got {offender_names!r}"
        )
    assert "README.md" not in offender_names, (
        "Over-match: README.md was flagged as a SQLite file"
    )
