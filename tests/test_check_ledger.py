"""T3: the ledger check fails on bad examples and passes on good ones."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_ledger

REPO = Path(__file__).resolve().parent.parent

MINIMAL_SCOPE = """# SCOPE.md

### 3.1 CORE — research lane

| Component | Package | Step | Active | Simplest form |
|---|---|---|---|---|
| Forward news recorder | `recorder` | 1 | yes | Capture-only polling |

### 3.2 CORE — live lane

| Component | Package | Active | Simplest form |
|---|---|---|---|
| Sizer | `sizing` | no | Volatility-targeted |

### 3.3 DEFERRED
"""


def make_repo(tmp_path: Path, scope_text: str, packages: list[str]) -> Path:
    (tmp_path / "SCOPE.md").write_text(scope_text)
    for pkg in packages:
        (tmp_path / "src" / "arcis" / pkg).mkdir(parents=True)
    return tmp_path


def test_fails_when_subpackage_has_no_ledger_row(tmp_path):
    repo = make_repo(tmp_path, MINIMAL_SCOPE, ["recorder", "ghost"])
    errors = check_ledger.check(repo)
    assert any("ghost" in e and "no ledger row" in e for e in errors)


def test_fails_when_subpackage_is_not_active(tmp_path):
    repo = make_repo(tmp_path, MINIMAL_SCOPE, ["sizing"])
    errors = check_ledger.check(repo)
    assert any("sizing" in e and "Active" in e for e in errors)


def test_passes_when_every_subpackage_is_active(tmp_path):
    repo = make_repo(tmp_path, MINIMAL_SCOPE, ["recorder"])
    assert check_ledger.check(repo) == []


def test_passes_on_the_real_repo():
    # Vacuous until the first package lands; meaningful from T5 on.
    assert check_ledger.check(REPO) == []


def test_fails_without_scope_md(tmp_path):
    assert check_ledger.check(tmp_path) != []


def test_parses_both_tables():
    rows = check_ledger.find_ledger_rows(REPO / "SCOPE.md")
    assert rows["recorder"] == "yes"
    assert rows["sizing"] == "no"
    assert rows["strategy"] == "no"
