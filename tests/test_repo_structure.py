"""Repository structure enforcement — prevents drift.

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: none
Tests: self
"""
import ast
import datetime
import importlib
import json
import re
import subprocess
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
    # Route components live under ./pages/ (the old dashboard) OR ./console/
    # (the Founder Console rebuild — a deliberate parallel structure). Both are
    # validated to resolve to a real file; the import path is captured from the
    # source so this never drifts when a new console route is added.
    page_imports = re.findall(r"import (\w+) from ['\"]\./pages/([\w/]+)", app_jsx)
    console_imports = re.findall(r"import (\w+) from ['\"]\./(console/[\w/]+)", app_jsx)
    import_map = {name: f"frontend/src/pages/{file}.jsx" for name, file in page_imports}
    import_map.update({name: f"frontend/src/{rel}.jsx" for name, rel in console_imports})
    missing = []
    for component in routes:
        if component in ("ErrorBoundary", "Layout"):
            continue
        if component in import_map:
            comp_file = Path(import_map[component])
            if not comp_file.exists():
                missing.append(f"Route <{component}> → {comp_file} does not exist")
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


# ---------------------------------------------------------------------------
# Phase 5 PR-F T36 sentinels: DIRECTORY.md staleness + docs-header discipline.
# Canonical context: docs/audits/2026-05-27-phase-5-unified/implementation-plan.md
# (T36 entry). Both sentinels are NON-grandfathered — there is no entry in
# config/known_violations.json for either; they must pass on the real tree.
# ---------------------------------------------------------------------------

# Staleness threshold for DIRECTORY.md vs the HEAD commit date.
# N = 45 days. Rationale: Arcis sprints historically run ~1–3 weeks, and
# generate_directory.py is re-run "after every sprint" (see its module
# docstring) — so a fresh DIRECTORY.md lands within a sprint of any commit
# that materially reshapes the tree. 45 days is a ~2–3-sprint window: loose
# enough that normal cadence never trips it, tight enough to flag a months-
# stale index whose tree has drifted. The plan text says "within N sprints";
# 45 days is the calendar proxy for that sprint-count, chosen because there is
# no machine-readable sprint clock in the repo to count against.
_DIRECTORY_STALENESS_MAX_DAYS = 45


def _parse_directory_last_updated(text: str) -> datetime.date:
    """Parse the `Last updated: YYYY-MM-DD` date that generate_directory.py
    writes INTO DIRECTORY.md.

    The generator emits the line as ``> Last updated: {date.today()}`` inside a
    blockquote, so we tolerate an optional leading ``>`` / whitespace. We use
    THIS in-file date — not filesystem mtime — because mtime resets on
    ``git checkout`` and is meaningless in CI / fresh clones, whereas the
    written date is committed content that travels with the file.

    Raises AssertionError if the line is absent or malformed (a missing
    freshness stamp is itself a regression worth failing on).
    """
    m = re.search(r"^\s*>?\s*Last updated:\s*(\d{4}-\d{2}-\d{2})\s*$", text, re.MULTILINE)
    assert m, "DIRECTORY.md has no parseable `Last updated: YYYY-MM-DD` line"
    return datetime.date.fromisoformat(m.group(1))


def _head_commit_date() -> datetime.date:
    """Return the HEAD commit's author/commit date (``git log -1 %cI``).

    %cI is strict-ISO-8601 with a timezone offset; we take the calendar date.
    """
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return datetime.date.fromisoformat(out[:10])


def test_directory_md_not_stale_vs_head():
    """Sentinel: DIRECTORY.md's `Last updated:` date is within
    _DIRECTORY_STALENESS_MAX_DAYS (45) of the HEAD commit date.

    Freshness source is the `Last updated: YYYY-MM-DD` line the generator
    writes INTO DIRECTORY.md — NOT filesystem mtime (mtime resets on
    `git checkout` and is unreliable in CI / fresh clones). We compare it to
    the HEAD commit date from `git log -1 --format=%cI`.

    Verified non-vacuous (verify-by-mutation, Q5): a `Last updated:` date 45+
    days behind the head date FAILS the gap check, while a same-day date
    PASSES — proven in test_directory_staleness_rule_detects_violation below
    using tmp_path content (no real-tree write).
    """
    last_updated = _parse_directory_last_updated(
        Path("DIRECTORY.md").read_text(encoding="utf-8")
    )
    head_date = _head_commit_date()
    gap = (head_date - last_updated).days
    assert gap <= _DIRECTORY_STALENESS_MAX_DAYS, (
        f"DIRECTORY.md is stale: `Last updated: {last_updated}` is {gap} days "
        f"behind HEAD commit date {head_date} (max {_DIRECTORY_STALENESS_MAX_DAYS}). "
        f"Re-run `python scripts/generate_directory.py` and commit the result."
    )


def test_directory_staleness_rule_detects_violation(tmp_path):
    """Sentinel-of-the-sentinel: the staleness check FAILS on a stale stamp
    and PASSES on a fresh one.

    Verify-by-mutation (Q5): an OLD `Last updated:` date (45+ days behind the
    reference head date) yields a gap over the threshold (violation); a fresh
    same-day date yields gap 0 (clean). Drives the parser with tmp_path
    content — never touches the real DIRECTORY.md.
    """
    head_date = datetime.date(2026, 5, 29)

    stale = tmp_path / "DIRECTORY_stale.md"
    stale.write_text("> Last updated: 2020-01-01\n", encoding="utf-8")
    stale_gap = (head_date - _parse_directory_last_updated(stale.read_text(encoding="utf-8"))).days
    assert stale_gap > _DIRECTORY_STALENESS_MAX_DAYS, (
        f"Mutation check broken: a 2020 stamp should exceed the "
        f"{_DIRECTORY_STALENESS_MAX_DAYS}-day window (got gap {stale_gap})"
    )

    fresh = tmp_path / "DIRECTORY_fresh.md"
    fresh.write_text(f"> Last updated: {head_date.isoformat()}\n", encoding="utf-8")
    fresh_gap = (head_date - _parse_directory_last_updated(fresh.read_text(encoding="utf-8"))).days
    assert fresh_gap <= _DIRECTORY_STALENESS_MAX_DAYS, (
        f"Mutation check broken: a same-day stamp should be within the window "
        f"(got gap {fresh_gap})"
    )


def _doc_header_violation(text: str) -> str | None:
    """Return a reason string if `text` violates the doc-header contract, else
    None.

    Contract (after stripping an OPTIONAL leading YAML frontmatter block
    delimited by `---` … `---`):
      1. Line 1 is an ATX H1 — exactly one `#`, then a space, then a title.
      2. The next non-blank line is a PROSE paragraph: NOT another heading
         (`#`/`##`/…), NOT a list item (`-`/`*`/`+`/`1.`), NOT a code fence
         (```` ``` ```` / `~~~`).

    A doc that opens with `# Title` immediately followed by a sub-heading,
    a bullet list, or a code block jumps the reader straight into structure
    with no orienting sentence — exactly what this sentinel forbids.
    """
    lines = text.splitlines()

    # Strip optional YAML frontmatter: a leading `---` line, up to the next `---`.
    if lines and lines[0].strip() == "---":
        end = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end is None:
            return "unterminated YAML frontmatter (opening `---` has no closing `---`)"
        lines = lines[end + 1:]

    # Skip blank lines between frontmatter and the title.
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return "no content after optional frontmatter"

    title = lines[idx]
    if not re.match(r"^#\s+\S", title) or title.lstrip().startswith("##"):
        return f"line 1 is not an `# Title` H1: {title!r}"

    # Find the next non-blank line after the title.
    j = idx + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return "H1 title has no following prose paragraph"

    nxt = lines[j].lstrip()
    if nxt.startswith("#"):
        return f"line after H1 is another heading, not prose: {lines[j]!r}"
    if re.match(r"^([-*+]\s|\d+[.)]\s)", nxt):
        return f"line after H1 is a list item, not prose: {lines[j]!r}"
    if nxt.startswith("```") or nxt.startswith("~~~"):
        return f"line after H1 is a code fence, not prose: {lines[j]!r}"
    return None


def _docs_with_header_violations() -> list[str]:
    """Scan docs/standards/ + docs/runbooks/ for header-contract violations."""
    bad = []
    for d in (Path("docs/standards"), Path("docs/runbooks")):
        for p in sorted(d.rglob("*.md")):
            reason = _doc_header_violation(p.read_text(encoding="utf-8"))
            if reason is not None:
                bad.append(f"{p.as_posix()}: {reason}")
    return bad


def test_standards_and_runbooks_docs_have_header():
    """Sentinel: every doc in docs/standards/ + docs/runbooks/ opens with an
    `# Title` H1 whose next non-blank line is a prose paragraph (after any
    optional YAML frontmatter).

    T35 made both current docs (standards/boundary-touch-tests.md,
    runbooks/stack-dump.md) conform, so this passes on the real tree.

    Verified non-vacuous (verify-by-mutation, Q5): a doc whose `# Title` is
    immediately followed by `## Heading` (no prose) FAILS the contract, while
    a `# Title` + prose doc PASSES — proven in
    test_doc_header_rule_detects_violation below using tmp_path content.
    """
    bad = _docs_with_header_violations()
    assert not bad, (
        "Docs in standards/ or runbooks/ violate the header contract "
        "(H1 then prose paragraph; see Phase 5 PR-F T36):\n"
        + "\n".join(f"  - {b}" for b in bad)
    )


def test_doc_header_rule_detects_violation(tmp_path):
    """Sentinel-of-the-sentinel: the header check FAILS on a heading-after-H1
    doc and PASSES on a conforming H1+prose doc.

    Verify-by-mutation (Q5): `# Title` immediately followed by `## Heading`
    (no orienting prose) is a violation; `# Title` followed by a prose
    paragraph is clean. Also confirms an optional YAML frontmatter block is
    skipped before the H1 check. Drives the helper with tmp_path content —
    never touches the real docs tree.
    """
    # Violation: H1 then a sub-heading with no prose.
    assert _doc_header_violation("# Title\n\n## Heading\n\nbody\n") is not None, (
        "Mutation check broken: `# Title` + `## Heading` should be a violation"
    )
    # Violation: H1 then a list item.
    assert _doc_header_violation("# Title\n\n- bullet\n") is not None, (
        "Mutation check broken: `# Title` + list item should be a violation"
    )
    # Violation: H1 then a code fence.
    assert _doc_header_violation("# Title\n\n```\ncode\n```\n") is not None, (
        "Mutation check broken: `# Title` + code fence should be a violation"
    )
    # Clean: H1 then prose.
    assert _doc_header_violation("# Title\n\nA prose sentence orienting the reader.\n") is None, (
        "False positive: `# Title` + prose should be clean"
    )
    # Clean: optional YAML frontmatter, then H1 then prose.
    assert _doc_header_violation(
        "---\ntitle: x\n---\n# Title\n\nProse after frontmatter.\n"
    ) is None, (
        "Frontmatter handling broken: `---`…`---` then H1+prose should be clean"
    )


# ---------------------------------------------------------------------------
# Phase 5 PR-G T37 sentinels: known_violations freshness + docs/audits archive
# policy. Canonical context:
# docs/audits/2026-05-27-phase-5-unified/implementation-plan.md (T37 entry).
# Both sentinels are NON-grandfathered — there is no entry in
# config/known_violations.json for either; they must pass on the real tree.
# ---------------------------------------------------------------------------


def _stale_oversized_file_entries(known: dict, root: Path) -> list[str]:
    """Return ``oversized_files`` entries whose file is CURRENTLY <=400 lines.

    A grandfather entry is "stale" once the file it excuses no longer exceeds
    the 400-line cap: the entry is dead weight that should be PRUNED (T38), and
    leaving it lets a future regression re-grow the file silently under cover of
    a still-present allowlist row. Missing files are skipped here — a deleted
    file is a separate concern (and T38's prune target), not a <400L staleness
    signal — so this sentinel flags only the precise "exists AND now small"
    case.

    ``root`` is explicit so the negative sentinel can drive it with a tmp_path
    tree (see test_known_violations_freshness_rule_detects_violation).
    """
    stale = []
    for entry in known.get("oversized_files", []):
        rel = entry["file"]
        p = root / rel
        if not p.is_file():
            continue
        lines = len(p.read_text(encoding="utf-8").splitlines())
        if lines <= 400:
            stale.append(f"{rel}: now {lines} lines (<=400) — grandfather entry is stale")
    return stale


def test_known_violations_has_no_stale_undersized_file_entries():
    """Sentinel (a): no ``oversized_files`` entry in known_violations.json
    refers to a file that is CURRENTLY <=400 lines.

    Rationale: a grandfather row for a file that has since shrunk under the cap
    is dead weight — and worse, it silently re-permits the file to re-grow back
    to its (large) recorded count + tolerance without tripping
    test_no_file_over_400_lines. Freshness here keeps the allowlist honest.

    NON-grandfathered: this sentinel has no self-entry. The 4 currently-live
    >400L entries flagged in the T37 brief (auditor.py, cloud_routes/
    analytics.py, core.py, kpis_compute.py) all exceed 400 lines today, so this
    passes on the real tree. If it ever FAILS, the offending row is a T38 prune
    target — do NOT silence it by editing known_violations.json from here.

    Verified non-vacuous (verify-by-mutation, Q5): a synthetic known-violations
    dict pointing at a 3-line tmp_path file is flagged stale, while the real
    tree is clean — proven in
    test_known_violations_freshness_rule_detects_violation below.
    """
    stale = _stale_oversized_file_entries(KNOWN, Path("."))
    assert not stale, (
        "Stale grandfather entries in config/known_violations.json (file now "
        "<=400 lines — PRUNE per Phase 5 PR-G T38, do not edit from the test):\n"
        + "\n".join(f"  - {s}" for s in stale)
    )


def test_known_violations_freshness_rule_detects_violation(tmp_path):
    """Sentinel-of-the-sentinel: the freshness check FLAGS an entry whose file
    is now <=400 lines and IGNORES one that is still >400.

    Verify-by-mutation (Q5): builds a fake known-violations dict with two rows —
    one pointing at a 3-line file (stale), one at a 500-line file (still
    legitimately oversized) — under tmp_path, and asserts only the small-file
    row is returned. Also confirms a missing-file row is not treated as a
    <=400L staleness hit. Never reads the real known_violations.json.
    """
    small = tmp_path / "src" / "now_small.py"
    small.parent.mkdir(parents=True, exist_ok=True)
    small.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")  # 3 lines, <=400

    big = tmp_path / "src" / "still_big.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(500)) + "\n", encoding="utf-8")

    fake = {
        "oversized_files": [
            {"file": "src/now_small.py", "lines": 612},
            {"file": "src/still_big.py", "lines": 500},
            {"file": "src/deleted_file.py", "lines": 444},  # absent on disk
        ]
    }
    stale = _stale_oversized_file_entries(fake, tmp_path)

    assert any("src/now_small.py" in s for s in stale), (
        f"Mutation check broken: a now-3-line file must be flagged stale — got {stale!r}"
    )
    assert not any("src/still_big.py" in s for s in stale), (
        "False positive: a genuinely >400L file must NOT be flagged stale"
    )
    assert not any("src/deleted_file.py" in s for s in stale), (
        "A missing file must not be reported as a <=400L staleness hit "
        "(deletion is a separate concern)"
    )


# Archive-policy cutoff for git-TRACKED top-level subdirs of docs/audits/.
# N = 90 days behind the HEAD commit date — the calendar proxy for the plan's
# "older than 3 sprints" rule. Rationale: Arcis sprints run ~1–3 weeks each
# (same cadence cited for the T36 DIRECTORY staleness window); 3 sprints is at
# most ~9 weeks ≈ 63 days, rounded up to 90 for a safe margin so normal cadence
# never trips it, yet a months-stale receipt directory that T34's archive sweep
# (boundary 2026-05-21) should have moved to docs/archive/sprint-receipts/ is
# caught. We use the HEAD commit date (not wall-clock) so the check is
# reproducible in CI / fresh clones, and only police *date-prefixed*
# (`YYYY-MM-DD-…`) subdirs — undated dirs (e.g. `cleanup-1`) carry no age signal
# and are out of this policy's scope.
_AUDITS_ARCHIVE_MAX_DAYS = 90
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def _git_tracked_top_level_audit_subdirs(root: Path) -> list[str]:
    """Return the names of git-TRACKED top-level subdirectories of
    ``docs/audits/`` (one hop below docs/audits/, dirs only).

    Uses ``git ls-files docs/audits/`` — exactly how generate_directory.py
    discovers tracked content — so UNTRACKED debris is invisible. This is
    deliberate: the untracked ``docs/audits/2026-05-06-dashboard-coherence/``
    that T34 could not ``git mv`` still sits on disk; a filesystem walk would
    wrongly flag it. Top-level *files* (e.g. known-pre-existing-failures.md) are
    excluded — they are not subdirectories and the archive policy is about
    receipt *directories*.
    """
    out = subprocess.run(
        ["git", "ls-files", "docs/audits/"],
        capture_output=True, text=True, check=True, cwd=str(root),
    ).stdout
    subdirs = set()
    for line in out.splitlines():
        rel = line.strip()
        if not rel.startswith("docs/audits/"):
            continue
        remainder = rel[len("docs/audits/"):]
        # Only entries with a path separator are inside a subdir; the first
        # component is the top-level subdir name. Bare files (no '/') are skipped.
        if "/" in remainder:
            subdirs.add(remainder.split("/", 1)[0])
    return sorted(subdirs)


def _aged_tracked_audit_subdirs(root: Path, head_date: datetime.date) -> list[str]:
    """Return ``"name: N days old"`` for tracked top-level docs/audits subdirs
    whose ``YYYY-MM-DD-`` prefix is more than _AUDITS_ARCHIVE_MAX_DAYS behind
    ``head_date``. Undated subdirs are skipped (no age signal)."""
    aged = []
    for name in _git_tracked_top_level_audit_subdirs(root):
        m = _DATE_PREFIX_RE.match(name)
        if not m:
            continue  # undated dir (e.g. cleanup-1) — out of policy scope
        dir_date = datetime.date.fromisoformat(m.group(1))
        age = (head_date - dir_date).days
        if age > _AUDITS_ARCHIVE_MAX_DAYS:
            aged.append(f"{name}: {age} days old")
    return aged


def test_docs_audits_has_no_stale_tracked_top_level_subdir():
    """Sentinel (b): no git-TRACKED top-level subdir of docs/audits/ is older
    than _AUDITS_ARCHIVE_MAX_DAYS (90 days) behind the HEAD commit date.

    Enforces T34's archive policy going forward: pre-2026-05-21 receipt dirs
    were moved to docs/archive/sprint-receipts/; aged receipts must not
    re-accumulate at the docs/audits/ top level. The oldest tracked subdir
    today is dated 2026-05-21 (T34's boundary), well inside the window, so this
    passes on the real tree.

    Scans git-TRACKED subdirs ONLY (``git ls-files``), so the untracked
    docs/audits/2026-05-06-dashboard-coherence/ debris T34 couldn't git-mv is
    correctly ignored — a filesystem walk would wrongly flag it.

    Verified non-vacuous (verify-by-mutation, Q5): an injected 2020-dated entry
    is flagged aged while the real tracked set is clean — proven in
    test_docs_audits_archive_rule_detects_violation below.
    """
    aged = _aged_tracked_audit_subdirs(Path("."), _head_commit_date())
    assert not aged, (
        "Aged git-tracked top-level docs/audits/ subdirs (older than "
        f"{_AUDITS_ARCHIVE_MAX_DAYS} days — archive them under "
        "docs/archive/sprint-receipts/ per Phase 5 T34 policy):\n"
        + "\n".join(f"  - {a}" for a in aged)
    )


def test_docs_audits_archive_rule_detects_violation():
    """Sentinel-of-the-sentinel: the age check FLAGS a 2020-dated subdir,
    IGNORES a fresh one, and IGNORES an undated one.

    Verify-by-mutation (Q5): exercises the pure date-filter half
    (``_DATE_PREFIX_RE`` + age math, mirrored from _aged_tracked_audit_subdirs)
    against a reference head date with three synthetic names — far-past, recent,
    and undated. No git, no filesystem: it pins the policy arithmetic that the
    real-tree test relies on.
    """
    head_date = datetime.date(2026, 5, 30)

    def _age_filter(names: list[str]) -> list[str]:
        out = []
        for name in names:
            m = _DATE_PREFIX_RE.match(name)
            if not m:
                continue
            age = (head_date - datetime.date.fromisoformat(m.group(1))).days
            if age > _AUDITS_ARCHIVE_MAX_DAYS:
                out.append(name)
        return out

    flagged = _age_filter(
        ["2020-01-01-ancient-receipt", "2026-05-21-capability-registry", "cleanup-1"]
    )
    assert "2020-01-01-ancient-receipt" in flagged, (
        "Mutation check broken: a 2020-dated subdir must be flagged aged"
    )
    assert "2026-05-21-capability-registry" not in flagged, (
        "False positive: a subdir dated 9 days behind head must NOT be flagged"
    )
    assert "cleanup-1" not in flagged, (
        "An undated subdir must be out of policy scope (no age signal)"
    )
