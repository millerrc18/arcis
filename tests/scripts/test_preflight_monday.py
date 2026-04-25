"""T1.07 — Monday morning go/no-go gate script tests.

Tests scripts/preflight_monday.py per audit-spec §9 (10-item checklist):
  (1) check_pre_651_quarantine_clean: zero unquarantined pre-cutoff rows
  (2) check_quarantine_column_extended: attribution_trades + walkforward_trades
  (3) check_canonical_sharpe_module_exists: src/analytics/canonical_sharpe.py
  (4) check_governor_enabled: config.risk_governor.enabled == True
  (5) check_capital_cap: config.live_trading.starting_capital == 100
  (6) check_effective_position_cap: helper returns > 0
  (7) check_mr_bracket_config: stop_atr_multiple set + template importable
  (8) check_alpaca_connectivity: get_account returns non-None (skippable)
  (9) check_baseline_memo_signed_off: memo file with Signed-off-by trailer
  (10) Transcript writer + main() orchestration + exit codes
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.preflight_monday import (
    CheckResult,
    check_alpaca_connectivity,
    check_baseline_memo_signed_off,
    check_canonical_sharpe_module_exists,
    check_capital_cap,
    check_effective_position_cap,
    check_governor_enabled,
    check_mr_bracket_config,
    check_pre_651_quarantine_clean,
    check_quarantine_column_extended,
    main,
    write_transcript,
)


# --- 1. check_pre_651_quarantine_clean ---------------------------------------

def _seed_shadow_trade(conn, **kwargs):
    cols = ",".join(kwargs)
    qm = ",".join("?" * len(kwargs))
    conn.execute(f"INSERT INTO shadow_trades ({cols}) VALUES ({qm})", tuple(kwargs.values()))


@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            source TEXT,
            quarantined INTEGER DEFAULT 0,
            created_at TEXT
        )
        """
    )
    yield conn
    conn.close()


def test_pre_651_quarantine_clean_zero_rows(in_memory_db):
    """No live pre-cutoff unquarantined rows -> PASS."""
    _seed_shadow_trade(
        in_memory_db,
        trade_id="t1",
        source="live",
        quarantined=1,
        created_at="2026-04-15T00:00:00-04:00",
    )
    _seed_shadow_trade(
        in_memory_db,
        trade_id="t2",
        source="live",
        quarantined=0,
        created_at="2026-04-23T00:00:00-04:00",
    )
    result = check_pre_651_quarantine_clean(conn=in_memory_db)
    assert result.passed is True
    assert result.required is True
    assert "0" in result.evidence


def test_pre_651_quarantine_clean_dirty(in_memory_db):
    """Live pre-cutoff unquarantined row -> FAIL."""
    _seed_shadow_trade(
        in_memory_db,
        trade_id="dirty",
        source="live",
        quarantined=0,
        created_at="2026-04-15T00:00:00-04:00",
    )
    result = check_pre_651_quarantine_clean(conn=in_memory_db)
    assert result.passed is False
    assert result.required is True


# --- 2. check_quarantine_column_extended -------------------------------------

def test_quarantine_column_extended_pass():
    """Real schema registry has quarantined on attribution + walkforward -> PASS."""
    result = check_quarantine_column_extended()
    assert result.passed is True
    assert result.required is True
    assert "attribution_trades" in result.evidence
    assert "walkforward_trades" in result.evidence


def test_quarantine_column_extended_missing(monkeypatch):
    """If walkforward_trades is missing the column -> FAIL."""
    from src.schema.registry import ColumnDef, TABLES, TableDef

    fake_table = TableDef(
        name="walkforward_trades",
        description="test",
        columns=[ColumnDef("trade_id", "TEXT", nullable=False)],
        primary_key="trade_id",
    )
    fake_tables = dict(TABLES)
    fake_tables["walkforward_trades"] = fake_table
    monkeypatch.setattr("src.schema.registry.TABLES", fake_tables)
    result = check_quarantine_column_extended()
    assert result.passed is False


# --- 3. check_canonical_sharpe_module_exists ---------------------------------

def test_canonical_sharpe_module_exists_real_repo():
    """Real repo has the module -> PASS."""
    repo_root = Path(__file__).resolve().parents[2]
    result = check_canonical_sharpe_module_exists(repo_root)
    assert result.passed is True


def test_canonical_sharpe_module_missing(tmp_path):
    """Missing module file -> FAIL."""
    result = check_canonical_sharpe_module_exists(tmp_path)
    assert result.passed is False


# --- 4. check_governor_enabled -----------------------------------------------

def test_governor_enabled_pass():
    cfg = {"risk_governor": {"enabled": True}}
    result = check_governor_enabled(cfg)
    assert result.passed is True


def test_governor_disabled_fail():
    cfg = {"risk_governor": {"enabled": False}}
    result = check_governor_enabled(cfg)
    assert result.passed is False


def test_governor_missing_section_fail():
    result = check_governor_enabled({})
    assert result.passed is False


# --- 5. check_capital_cap ----------------------------------------------------

def test_capital_cap_pass():
    cfg = {"live_trading": {"starting_capital": 100}}
    result = check_capital_cap(cfg)
    assert result.passed is True


def test_capital_cap_wrong_value():
    cfg = {"live_trading": {"starting_capital": 1000}}
    result = check_capital_cap(cfg)
    assert result.passed is False


# --- 6. check_effective_position_cap -----------------------------------------

def test_effective_position_cap_positive():
    cfg = {"risk": {"max_open_positions": 5}}
    result = check_effective_position_cap(cfg)
    assert result.passed is True
    assert "5" in result.evidence


def test_effective_position_cap_default_when_unset():
    """Helper returns default 10 -> still > 0 -> PASS."""
    result = check_effective_position_cap({})
    assert result.passed is True


# --- 7. check_mr_bracket_config ----------------------------------------------

def test_mr_bracket_config_pass():
    cfg = {"strategies": {"mean_reversion": {"stop_atr_multiple": 2.5}}}
    result = check_mr_bracket_config(cfg)
    assert result.passed is True
    assert "2.5" in result.evidence


def test_mr_bracket_config_missing_key():
    cfg = {"strategies": {"mean_reversion": {}}}
    result = check_mr_bracket_config(cfg)
    assert result.passed is False


def test_mr_bracket_config_template_unimportable(monkeypatch):
    cfg = {"strategies": {"mean_reversion": {"stop_atr_multiple": 2.5}}}
    monkeypatch.setitem(sys.modules, "src.packets.template", None)
    result = check_mr_bracket_config(cfg)
    assert result.passed is False


# --- 8. check_alpaca_connectivity --------------------------------------------

class _FakeAccount:
    equity = 100.0


class _FakeBroker:
    def get_account(self):
        return _FakeAccount()


def test_alpaca_connectivity_pass(monkeypatch):
    monkeypatch.setattr(
        "src.trading.broker_factory.get_live_broker",
        lambda cfg: _FakeBroker(),
    )
    result = check_alpaca_connectivity({}, skip=False)
    assert result.passed is True


def test_alpaca_connectivity_returns_none(monkeypatch):
    class NoneBroker:
        def get_account(self):
            return None

    monkeypatch.setattr(
        "src.trading.broker_factory.get_live_broker",
        lambda cfg: NoneBroker(),
    )
    result = check_alpaca_connectivity({}, skip=False)
    assert result.passed is False


def test_alpaca_connectivity_raises(monkeypatch):
    def boom(cfg):
        raise RuntimeError("network down")

    monkeypatch.setattr("src.trading.broker_factory.get_live_broker", boom)
    result = check_alpaca_connectivity({}, skip=False)
    assert result.passed is False
    assert "network down" in (result.error or "")


def test_alpaca_connectivity_skipped():
    """--skip-alpaca-probe records a FAIL with skip reason."""
    result = check_alpaca_connectivity({}, skip=True)
    assert result.passed is False
    assert "skip" in (result.evidence + (result.error or "")).lower()


# --- 9. check_baseline_memo_signed_off ---------------------------------------

def _git(repo, *args, env=None):
    """Run a git command in the repo. Returns (stdout, returncode)."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )
    return result.stdout, result.returncode


@pytest.fixture
def temp_git_repo(tmp_path):
    """Initialize a tiny git repo with config so commits succeed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "operator@example.com")
    _git(repo, "config", "user.name", "Operator")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def test_memo_signed_off_pass(temp_git_repo):
    """Memo file committed with -s flag has Signed-off-by trailer."""
    repo = temp_git_repo
    memo = repo / "audits" / "2026-04-27" / "stage1_baseline_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# Stage 1 baseline\n")
    _git(repo, "add", "audits/2026-04-27/stage1_baseline_memo.md")
    _git(
        repo,
        "commit",
        "-s",
        "-m",
        "memo: stage1 baseline",
    )
    result = check_baseline_memo_signed_off(
        repo,
        "audits/2026-04-27/stage1_baseline_memo.md",
        operator_email="operator@example.com",
    )
    assert result.passed is True


def test_memo_signed_off_missing_file(temp_git_repo):
    """No memo file at all -> FAIL."""
    result = check_baseline_memo_signed_off(
        temp_git_repo,
        "audits/2026-04-27/stage1_baseline_memo.md",
        operator_email="operator@example.com",
    )
    assert result.passed is False


def test_memo_signed_off_no_trailer(temp_git_repo):
    """Memo committed WITHOUT -s flag -> FAIL."""
    repo = temp_git_repo
    memo = repo / "audits" / "2026-04-27" / "stage1_baseline_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# Stage 1 baseline\n")
    _git(repo, "add", "audits/2026-04-27/stage1_baseline_memo.md")
    _git(repo, "commit", "-m", "memo: stage1 baseline (unsigned)")
    result = check_baseline_memo_signed_off(
        repo,
        "audits/2026-04-27/stage1_baseline_memo.md",
        operator_email="operator@example.com",
    )
    assert result.passed is False


def test_memo_signed_off_email_mismatch(temp_git_repo):
    """Trailer email != operator email -> FAIL."""
    repo = temp_git_repo
    memo = repo / "audits" / "2026-04-27" / "stage1_baseline_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# Stage 1 baseline\n")
    _git(repo, "add", "audits/2026-04-27/stage1_baseline_memo.md")
    _git(repo, "commit", "-s", "-m", "memo: stage1 baseline")
    result = check_baseline_memo_signed_off(
        repo,
        "audits/2026-04-27/stage1_baseline_memo.md",
        operator_email="someone-else@example.com",
    )
    assert result.passed is False


def test_memo_signed_off_empty_email_accepts_any_trailer(temp_git_repo):
    """operator_email='' -> any Signed-off-by trailer is accepted."""
    repo = temp_git_repo
    memo = repo / "audits" / "2026-04-27" / "stage1_baseline_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# Stage 1 baseline\n")
    _git(repo, "add", "audits/2026-04-27/stage1_baseline_memo.md")
    _git(repo, "commit", "-s", "-m", "memo: stage1 baseline")
    result = check_baseline_memo_signed_off(
        repo,
        "audits/2026-04-27/stage1_baseline_memo.md",
        operator_email="",
    )
    assert result.passed is True


# --- 10. write_transcript + main() orchestration -----------------------------

def test_write_transcript_creates_file(tmp_path):
    """Transcript file is created with timestamps + per-check status."""
    results = [
        CheckResult(name="check_a", required=True, passed=True, evidence="ok"),
        CheckResult(name="check_b", required=True, passed=False, evidence="", error="boom"),
    ]
    out_path = tmp_path / "transcript.txt"
    write_transcript(out_path, results)
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "check_a" in content
    assert "check_b" in content
    assert "PASS" in content
    assert "FAIL" in content
    assert "boom" in content


def test_main_all_pass_exit_zero(tmp_path, monkeypatch, temp_git_repo):
    """All checks pass -> exit 0."""
    repo = temp_git_repo
    # Set up the repo: memo committed with -s
    memo = repo / "audits" / "2026-04-27" / "stage1_baseline_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# memo\n")
    # Also place the canonical_sharpe.py to make T1.03 check pass.
    sharpe = repo / "src" / "analytics" / "canonical_sharpe.py"
    sharpe.parent.mkdir(parents=True)
    sharpe.write_text("# stub\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-s", "-m", "memo: stage1 baseline")

    transcript_path = tmp_path / "preflight_transcript.txt"

    # Patch DB call to return clean.
    import scripts.preflight_monday as pm

    def fake_open_db():
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute(
            "CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, source TEXT, quarantined INTEGER, created_at TEXT)"
        )
        return c

    monkeypatch.setattr(pm, "_open_db", fake_open_db)
    monkeypatch.setattr(
        "src.trading.broker_factory.get_live_broker",
        lambda cfg: _FakeBroker(),
    )

    fake_cfg = {
        "risk_governor": {"enabled": True},
        "live_trading": {"starting_capital": 100},
        "risk": {"max_open_positions": 5},
        "strategies": {"mean_reversion": {"stop_atr_multiple": 2.5}},
    }

    exit_code = main(
        argv=[
            "--repo-root", str(repo),
            "--memo", "audits/2026-04-27/stage1_baseline_memo.md",
            "--transcript", str(transcript_path),
            "--operator-email", "operator@example.com",
        ],
        config=fake_cfg,
    )
    assert exit_code == 0
    assert transcript_path.exists()


def test_main_one_fail_exit_nonzero(tmp_path, monkeypatch, temp_git_repo):
    """One required check fails -> exit non-zero."""
    repo = temp_git_repo
    transcript_path = tmp_path / "transcript.txt"

    import scripts.preflight_monday as pm

    def fake_open_db():
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute(
            "CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, source TEXT, quarantined INTEGER, created_at TEXT)"
        )
        # Seed a dirty row.
        c.execute(
            "INSERT INTO shadow_trades (trade_id, source, quarantined, created_at) VALUES (?, ?, ?, ?)",
            ("t1", "live", 0, "2026-04-15T00:00:00-04:00"),
        )
        return c

    monkeypatch.setattr(pm, "_open_db", fake_open_db)
    monkeypatch.setattr(
        "src.trading.broker_factory.get_live_broker",
        lambda cfg: _FakeBroker(),
    )

    fake_cfg = {
        "risk_governor": {"enabled": True},
        "live_trading": {"starting_capital": 100},
        "risk": {"max_open_positions": 5},
        "strategies": {"mean_reversion": {"stop_atr_multiple": 2.5}},
    }

    exit_code = main(
        argv=[
            "--repo-root", str(repo),
            "--memo", "audits/2026-04-27/stage1_baseline_memo.md",
            "--transcript", str(transcript_path),
            "--operator-email", "operator@example.com",
        ],
        config=fake_cfg,
    )
    assert exit_code != 0
    assert transcript_path.exists()


def test_main_skip_alpaca_records_fail(tmp_path, monkeypatch, temp_git_repo):
    """--skip-alpaca-probe records FAILED alpaca connectivity result."""
    repo = temp_git_repo
    memo = repo / "audits" / "2026-04-27" / "stage1_baseline_memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text("# memo\n")
    sharpe = repo / "src" / "analytics" / "canonical_sharpe.py"
    sharpe.parent.mkdir(parents=True)
    sharpe.write_text("# stub\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-s", "-m", "memo: stage1 baseline")

    transcript_path = tmp_path / "transcript.txt"

    import scripts.preflight_monday as pm

    def fake_open_db():
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute(
            "CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, source TEXT, quarantined INTEGER, created_at TEXT)"
        )
        return c

    monkeypatch.setattr(pm, "_open_db", fake_open_db)

    fake_cfg = {
        "risk_governor": {"enabled": True},
        "live_trading": {"starting_capital": 100},
        "risk": {"max_open_positions": 5},
        "strategies": {"mean_reversion": {"stop_atr_multiple": 2.5}},
    }

    exit_code = main(
        argv=[
            "--repo-root", str(repo),
            "--memo", "audits/2026-04-27/stage1_baseline_memo.md",
            "--transcript", str(transcript_path),
            "--operator-email", "operator@example.com",
            "--skip-alpaca-probe",
        ],
        config=fake_cfg,
    )
    assert exit_code != 0
    content = transcript_path.read_text(encoding="utf-8")
    # Even on early failure, ALL 10 items must appear.
    assert "alpaca" in content.lower()
    assert "skip" in content.lower()


def test_main_all_ten_items_in_transcript(tmp_path, monkeypatch, temp_git_repo):
    """Even on early failure, ALL 10 items must appear in transcript."""
    repo = temp_git_repo
    transcript_path = tmp_path / "transcript.txt"

    import scripts.preflight_monday as pm

    def fake_open_db():
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.execute(
            "CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, source TEXT, quarantined INTEGER, created_at TEXT)"
        )
        return c

    monkeypatch.setattr(pm, "_open_db", fake_open_db)
    monkeypatch.setattr(
        "src.trading.broker_factory.get_live_broker",
        lambda cfg: _FakeBroker(),
    )

    fake_cfg = {
        "risk_governor": {"enabled": False},  # one fail
        "live_trading": {"starting_capital": 100},
        "risk": {"max_open_positions": 5},
        "strategies": {"mean_reversion": {"stop_atr_multiple": 2.5}},
    }

    main(
        argv=[
            "--repo-root", str(repo),
            "--memo", "audits/2026-04-27/stage1_baseline_memo.md",
            "--transcript", str(transcript_path),
            "--operator-email", "operator@example.com",
        ],
        config=fake_cfg,
    )

    content = transcript_path.read_text(encoding="utf-8")
    # All 10 §9 items should be referenced — by the function names of the checks.
    expected_names = [
        "pre_651_quarantine_clean",
        "quarantine_column_extended",
        "canonical_sharpe_module_exists",
        "governor_enabled",
        "capital_cap",
        "effective_position_cap",
        "mr_bracket_config",
        "alpaca_connectivity",
        "baseline_memo_signed_off",
        "transcript_saved",
    ]
    for n in expected_names:
        assert n in content, f"missing check name {n!r} in transcript"
