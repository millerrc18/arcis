"""Main-flow tests (#95, T12): gating, dry-run, TRUNCATE, re-check, broker,
already-clean, config-pending, CLI smoke.

Verify-by-mutation throughout. Drives the assembled decorated entry point against
a FRESH EPHEMERAL scratch DB on the 5434 server (TEST_DATABASE_URL). NEVER prod
5433; NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1. The backup module + watch-loop +
broker checks are mocked where the test is not exercising them.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid

import psycopg2
import pytest

import scripts.clean_slate_wipe as cs
from scripts._clean_slate import backup as backup_mod
from scripts._clean_slate import config_verify as config_verify_mod
from scripts._clean_slate import live_schema as live_schema_mod
from scripts._clean_slate._errors import BackupVerifyError, CleanSlateAbort
from scripts._clean_slate.classification import KEEP_TABLES, WIPE_TABLES
from src.schema.postgres import create_all_tables
from src.tools._safety import DryRunResult, ProdGuardError

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="integration(authoritative-coverage:pg-tests): needs TEST_DATABASE_URL 5434 server",
)

_PROD_SIGNATURE_DSN = "postgresql://halcyon_app:secret@127.0.0.1:5433/halcyon"


def _maintenance_dsn() -> str:
    base = os.environ["TEST_DATABASE_URL"]
    head, _, _db = base.rpartition("/")
    return f"{head}/postgres"


def _dsn_for(db: str) -> str:
    head, _, _db = os.environ["TEST_DATABASE_URL"].rpartition("/")
    return f"{head}/{db}"


@pytest.fixture
def scratch_dsn():
    """A fresh registry-provisioned ephemeral DB (non-prod); dropped on teardown."""
    db_name = f"cs_wipe_{uuid.uuid4().hex[:12]}"
    admin = psycopg2.connect(_maintenance_dsn(), connect_timeout=10)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    dsn = _dsn_for(db_name)
    try:
        create_all_tables(dsn)
        yield dsn
    finally:
        with admin.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        admin.close()


def _seed_wipe_and_keep(dsn: str):
    """Seed a WIPE FK chain (recommendations<-shadow_trades) + a KEEP row."""
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, created_at) "
            "VALUES ('cs-rec-1', 'AAA', NOW()::text)"
        )
        cur.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, recommendation_id, status, created_at, updated_at) "
            "VALUES ('cs-st-1', 'AAA', 'cs-rec-1', 'open', NOW()::text, NOW()::text)"
        )
        cur.execute(
            "INSERT INTO macro_snapshots "
            "(series_id, series_name, value, collected_at, collected_date) "
            "VALUES ('DGS10', 'ten-yr', 4.5, NOW()::text, CURRENT_DATE::text)"
        )
    conn.close()


def _count(dsn: str, table: str) -> int:
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            return int(cur.fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def no_external_gates(monkeypatch):
    """Default: watch loop stopped, broker flat, NSSM confirms stopped."""
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: True)


@pytest.fixture
def mock_backup(monkeypatch):
    """Stub the backup module so TRUNCATE tests don't need docker pg_dump."""
    def fake_backup(dsn, scratch_server_dsn, out_dir):
        return {"result": "BACKUP_VERIFIED", "dump_path": str(out_dir) + "/prod.sql",
                "create_table_count": 80, "restored_table_count": 80}
    monkeypatch.setattr(backup_mod, "run_backup_and_verify", fake_backup)


# ── Dry-run default (no confirm) ────────────────────────────────────────────


def test_dry_run_default_no_mutation_but_dumps_prod(
    scratch_dsn, no_external_gates, monkeypatch, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)

    backup_calls: list = []
    def tracking_backup(dsn, scratch_server_dsn, out_dir):
        backup_calls.append(dsn)
        return {"result": "BACKUP_VERIFIED", "dump_path": str(out_dir) + "/prod.sql"}
    monkeypatch.setattr(backup_mod, "run_backup_and_verify", tracking_backup)

    log_path = tmp_path / "audit.log"
    entry = cs._make_entry_point(log_path=log_path)
    result = entry(dsn=scratch_dsn, out_dir=tmp_path)

    # No confirm → DryRunResult, NO mutation.
    assert isinstance(result, DryRunResult)
    assert _count(scratch_dsn, "shadow_trades") == 1  # untouched
    assert _count(scratch_dsn, "recommendations") == 1
    # The dry run STILL performed the read-path dump (spec §2.2).
    assert backup_calls == [scratch_dsn]
    # dry_run event logged.
    assert "dry_run" in log_path.read_text(encoding="utf-8")


# ── ProdGuard block ─────────────────────────────────────────────────────────


def test_prod_guard_blocks_prod_dsn_without_env_and_confirm(monkeypatch, tmp_path):
    # Ensure env opt-in is NOT set.
    monkeypatch.delenv("ARCIS_ALLOW_PROD_PG", raising=False)
    log_path = tmp_path / "audit.log"
    entry = cs._make_entry_point(log_path=log_path)
    with pytest.raises(ProdGuardError):
        entry(dsn=_PROD_SIGNATURE_DSN, confirm=True, out_dir=tmp_path)
    assert "prod_guard_block" in log_path.read_text(encoding="utf-8")


def test_prod_guard_blocks_prod_dsn_with_confirm_but_no_env(monkeypatch, tmp_path):
    # confirm=True alone is insufficient; env is also required.
    monkeypatch.delenv("ARCIS_ALLOW_PROD_PG", raising=False)
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(ProdGuardError):
        entry(dsn=_PROD_SIGNATURE_DSN, confirm=True, out_dir=tmp_path)


def test_kwarg_dsn_is_required_for_prod_guard_to_fire(monkeypatch, tmp_path):
    # The footgun (memory: feedback_cli_decorated_public_api): prod_guard reads
    # kwargs.get('dsn'). The entry point declares dsn as keyword-only (*, dsn),
    # so a POSITIONAL call is a TypeError at the wrapped fn — the safe failure
    # mode that forces callers to use dsn=. Prove a positional call cannot reach
    # the DB (it raises TypeError inside the wrapper's fn invocation).
    monkeypatch.setenv("ARCIS_ALLOW_PROD_PG", "1")
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    # safe_op/prod_guard wrappers accept *args; the keyword-only fn signature
    # rejects a positional dsn → TypeError (no DB touch, no silent prod write).
    with pytest.raises(TypeError):
        entry(_PROD_SIGNATURE_DSN, confirm=True)


# ── TRUNCATE-by-mutation (confirmed run on scratch) ─────────────────────────


def test_confirmed_truncate_wipes_and_preserves_keep(
    scratch_dsn, no_external_gates, mock_backup, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    assert _count(scratch_dsn, "shadow_trades") == 1
    assert _count(scratch_dsn, "macro_snapshots") == 1

    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(
        dsn=scratch_dsn, confirm=True, skip_sqlite=True, out_dir=tmp_path,
    )

    assert manifest["result"] == "WIPE_COMPLETE"
    # WIPE → 0 (CASCADE-safe FK chain).
    assert _count(scratch_dsn, "shadow_trades") == 0
    assert _count(scratch_dsn, "recommendations") == 0
    # KEEP unchanged.
    assert _count(scratch_dsn, "macro_snapshots") == 1
    assert manifest["post_verify_db"]["result"] == "POST_VERIFY_PASSED"
    # Delta report present.
    deltas = manifest["truncate"]["deltas"]
    assert deltas["shadow_trades"] == (1, 0)
    assert deltas["recommendations"] == (1, 0)


def test_truncate_could_have_failed_guard(scratch_dsn, no_external_gates, mock_backup, tmp_path):
    # Verify-by-mutation control: if we DON'T run the wipe, the rows persist.
    _seed_wipe_and_keep(scratch_dsn)
    assert _count(scratch_dsn, "shadow_trades") == 1  # pre-wipe state is real


# ── Watch-loop Phase-0 abort ────────────────────────────────────────────────


def test_watchloop_running_phase0_aborts(scratch_dsn, monkeypatch, mock_backup, tmp_path):
    _seed_wipe_and_keep(scratch_dsn)
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: "watch.lock present")
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(CleanSlateAbort) as exc:
        entry(dsn=scratch_dsn, confirm=True, out_dir=tmp_path)
    assert exc.value.code == "ABORT_WATCHLOOP"
    # Nothing committed.
    assert _count(scratch_dsn, "shadow_trades") == 1


# ── Watch-loop Phase-3.0 RE-CHECK abort (None at Phase 0, running at re-check) ──


def test_watchloop_recheck_aborts_nothing_committed(
    scratch_dsn, monkeypatch, mock_backup, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: True)

    calls = {"n": 0}
    def flaky_watchloop():
        calls["n"] += 1
        # None at Phase 0 (first call), running at the Phase-3.0 re-check (2nd).
        return None if calls["n"] == 1 else "watch.lock reappeared"
    monkeypatch.setattr(cs, "_check_watch_loop_running", flaky_watchloop)

    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(CleanSlateAbort) as exc:
        entry(dsn=scratch_dsn, confirm=True, skip_sqlite=True, out_dir=tmp_path)
    assert exc.value.code == "ABORT_WATCHLOOP_RECHECK"
    # Nothing committed — the TRUNCATE never ran.
    assert _count(scratch_dsn, "shadow_trades") == 1


def test_watchloop_unverified_nssm_aborts(scratch_dsn, monkeypatch, mock_backup, tmp_path):
    _seed_wipe_and_keep(scratch_dsn)
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: False)  # UNVERIFIED
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(CleanSlateAbort) as exc:
        entry(dsn=scratch_dsn, confirm=True, skip_sqlite=True, out_dir=tmp_path)
    assert exc.value.code == "ABORT_WATCHLOOP_UNVERIFIED"
    assert _count(scratch_dsn, "shadow_trades") == 1


def test_watchloop_unverified_overridden_by_attestation(
    scratch_dsn, monkeypatch, mock_backup, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: [])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: False)
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(
        dsn=scratch_dsn, confirm=True, skip_sqlite=True,
        i_have_stopped_nssm=True, out_dir=tmp_path,
    )
    assert manifest["result"] == "WIPE_COMPLETE"
    assert _count(scratch_dsn, "shadow_trades") == 0


# ── Broker HARD gate ────────────────────────────────────────────────────────


def test_broker_open_positions_aborts_before_backup(
    scratch_dsn, monkeypatch, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: ["AAPL", "MSFT"])
    backup_calls: list = []
    monkeypatch.setattr(
        backup_mod, "run_backup_and_verify",
        lambda *a, **k: backup_calls.append(1) or {"result": "BACKUP_VERIFIED"},
    )
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(CleanSlateAbort) as exc:
        entry(dsn=scratch_dsn, confirm=True, out_dir=tmp_path)
    assert exc.value.code == "ABORT_BROKER_NOT_FLAT"
    assert backup_calls == []  # aborted BEFORE backup
    assert _count(scratch_dsn, "shadow_trades") == 1


def test_broker_override_proceeds_with_warn(
    scratch_dsn, monkeypatch, mock_backup, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    monkeypatch.setattr(cs, "_check_watch_loop_running", lambda: None)
    monkeypatch.setattr(cs, "_check_alpaca_positions", lambda: ["AAPL"])
    monkeypatch.setattr(cs, "_nssm_confirms_stopped", lambda: True)
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(
        dsn=scratch_dsn, confirm=True, skip_sqlite=True,
        i_have_flattened_broker=True, out_dir=tmp_path,
    )
    assert manifest["result"] == "WIPE_COMPLETE"
    assert any("BROKER_NOT_FLAT_OVERRIDE" in w for w in manifest["warnings"])
    assert _count(scratch_dsn, "shadow_trades") == 0


# ── Already-clean short-circuit (no backup) ─────────────────────────────────


def test_already_clean_short_circuits_no_backup(
    scratch_dsn, no_external_gates, monkeypatch, tmp_path
):
    # Do NOT seed → all WIPE tables empty.
    backup_calls: list = []
    monkeypatch.setattr(
        backup_mod, "run_backup_and_verify",
        lambda *a, **k: backup_calls.append(1) or {"result": "BACKUP_VERIFIED"},
    )
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(dsn=scratch_dsn, confirm=True, skip_sqlite=True, out_dir=tmp_path)
    assert manifest["result"] == "ALREADY_CLEAN"
    assert backup_calls == []  # NO backup of empty state


# ── Config-verify (MAJOR-3) ─────────────────────────────────────────────────


def test_config_verify_fails_on_stale_config(tmp_path):
    cfg = tmp_path / "settings.local.yaml"
    cfg.write_text(
        "llm:\n  model: my-finetune:latest\n"
        "live_trading:\n  post_bootcamp: true\n"
        "risk:\n  starting_capital: 250000\n",
        encoding="utf-8",
    )
    verdict = config_verify_mod.verify_post_reset_config(
        cfg, base_tag="qwen2.5:7b", check_ollama=False
    )
    assert verdict["result"] == "POST_VERIFY_CONFIG_FAILED"
    assert len(verdict["failures"]) == 3  # model + post_bootcamp + capital


def test_config_verify_passes_on_reset_config(tmp_path):
    cfg = tmp_path / "settings.local.yaml"
    cfg.write_text(
        "llm:\n  model: qwen2.5:7b\n"
        "live_trading:\n  post_bootcamp: false\n"
        "risk:\n  starting_capital: 100000\n",
        encoding="utf-8",
    )
    verdict = config_verify_mod.verify_post_reset_config(
        cfg, base_tag="qwen2.5:7b", check_ollama=False
    )
    assert verdict["result"] == "POST_VERIFY_CONFIG_PASSED"
    assert verdict["failures"] == []


def test_normal_run_records_config_pending(
    scratch_dsn, no_external_gates, mock_backup, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(dsn=scratch_dsn, confirm=True, skip_sqlite=True, out_dir=tmp_path)
    assert manifest["post_verify_config"]["result"] == "POST_VERIFY_CONFIG_PENDING"


def test_verify_config_run_asserts_config(
    scratch_dsn, no_external_gates, mock_backup, monkeypatch, tmp_path
):
    _seed_wipe_and_keep(scratch_dsn)
    cfg = tmp_path / "settings.local.yaml"
    cfg.write_text(
        "llm:\n  model: qwen2.5:7b\n"
        "live_trading:\n  post_bootcamp: false\n"
        "risk:\n  starting_capital: 100000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_verify_mod, "_ollama_loaded_models", lambda: ["qwen2.5:7b"])
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    manifest = entry(
        dsn=scratch_dsn, confirm=True, skip_sqlite=True, verify_config=True,
        config_path=cfg, base_tag="qwen2.5:7b", out_dir=tmp_path,
    )
    assert manifest["post_verify_config"]["result"] == "POST_VERIFY_CONFIG_PASSED"


# ── Backup REFUSE blocks TRUNCATE ───────────────────────────────────────────


def test_backup_refuse_blocks_truncate(scratch_dsn, no_external_gates, monkeypatch, tmp_path):
    _seed_wipe_and_keep(scratch_dsn)
    def refusing_backup(dsn, scratch_server_dsn, out_dir):
        raise BackupVerifyError("REFUSE_BACKUP", "CREATE TABLE shortfall: 79 < 80")
    monkeypatch.setattr(backup_mod, "run_backup_and_verify", refusing_backup)
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    with pytest.raises(BackupVerifyError) as exc:
        entry(dsn=scratch_dsn, confirm=True, out_dir=tmp_path)
    assert exc.value.code == "REFUSE_BACKUP"
    # TRUNCATE never ran.
    assert _count(scratch_dsn, "shadow_trades") == 1


# ── emergency is inert ──────────────────────────────────────────────────────


def test_emergency_flag_is_inert(scratch_dsn, no_external_gates, mock_backup, tmp_path):
    # --emergency does NOT bypass --confirm. Without confirm, still a dry run.
    entry = cs._make_entry_point(log_path=tmp_path / "audit.log")
    _seed_wipe_and_keep(scratch_dsn)
    result = entry(dsn=scratch_dsn, emergency=True, out_dir=tmp_path)
    assert isinstance(result, DryRunResult)  # emergency did NOT execute the wipe
    assert _count(scratch_dsn, "shadow_trades") == 1


# ── CLI subprocess smoke (Task 11) ──────────────────────────────────────────


def test_cli_dry_run_smoke_no_mutation(scratch_dsn, tmp_path):
    # Invoke the CLI with no --confirm against the scratch DSN. Mock the external
    # gates + backup via env-free monkeypatching is not possible in a subprocess,
    # so we patch nothing and rely on: watch loop not running locally + backup
    # being exercised. To keep the subprocess hermetic + fast, point --dsn at the
    # scratch DSN and pass --skip-sqlite; the dry run prints the preview.
    env = dict(os.environ)
    env["DATABASE_URL"] = ""
    env["PYTHONPATH"] = os.getcwd()
    # The subprocess dry-run will attempt the read-path backup (docker pg_dump),
    # which is unavailable for the scratch DSN — so assert the process runs and
    # the preview/abort path is reached deterministically by checking it does NOT
    # mutate. We seed first and assert the row survives.
    _seed_wipe_and_keep(scratch_dsn)
    proc = subprocess.run(
        [sys.executable, "scripts/clean_slate_wipe.py", "--dsn", scratch_dsn],
        capture_output=True, text=True, env=env, timeout=120,
    )
    # Either the dry-run preview printed, or a read-path abort/refuse fired
    # (e.g. docker pg_dump unavailable) — in BOTH cases NO mutation occurred.
    assert _count(scratch_dsn, "shadow_trades") == 1
    combined = proc.stdout + proc.stderr
    assert "CLEAN-SLATE WIPE" in combined or "ABORT" in combined or "REFUSE" in combined
