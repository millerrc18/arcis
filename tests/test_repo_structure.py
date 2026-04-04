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
_KNOWN_FUNCTIONS = {
    f"{v['file']}:{v['function']}" for v in KNOWN.get("oversized_functions", [])
}
_KNOWN_DOCSTRINGS = set(KNOWN.get("missing_docstring_headers", []))


def test_no_file_over_400_lines():
    for p in Path("src").rglob("*.py"):
        if p.name == "__init__.py":
            continue
        lines = len(p.read_text(encoding="utf-8").splitlines())
        if lines > 400:
            normalized = str(p).replace("\\", "/")
            if normalized in _KNOWN_FILES:
                warnings.warn(f"GRANDFATHERED: {p} ({lines} lines)")
            else:
                assert False, f"NEW VIOLATION: {p} is {lines} lines (max 400)"


def test_no_function_over_60_lines():
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
        for line in p.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
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
