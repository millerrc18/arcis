"""Tests for GET /api/preflight/latest — S4 preflight echo endpoint.

Called by: pytest (CI)
Calls: src.api.cloud_routes.preflight
Owns tables: none
Config keys: none
Tests: Track 1.5 / Round 8.D (S4)
"""
from __future__ import annotations

import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src.api.cloud_routes.preflight import (
    _find_latest_transcript,
    _parse_transcript,
    get_preflight_latest,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_TRANSCRIPT = textwrap.dedent("""\
    Pre-flight Monday Checklist (audit-spec §9)
    Generated: 2026-04-25T08:00:00-04:00
    ========================================================================

    Summary: 9 PASS / 1 FAIL (10 total)

    [ 1] [2026-04-25T08:00:01-04:00] PASS (required) pre_651_quarantine_clean
         evidence: unquarantined live pre-cutoff rows = 0 (cutoff=2026-04-22T00:00:00-04:00)

    [ 2] [2026-04-25T08:00:02-04:00] PASS (required) quarantine_column_extended
         evidence: present=['attribution_trades', 'walkforward_trades'] missing=[]

    [ 3] [2026-04-25T08:00:03-04:00] PASS (required) canonical_sharpe_module_exists
         evidence: path=/repo/src/analytics/canonical_sharpe.py exists=True

    [ 4] [2026-04-25T08:00:04-04:00] PASS (required) governor_enabled
         evidence: risk_governor.enabled=True

    [ 5] [2026-04-25T08:00:05-04:00] PASS (required) capital_cap
         evidence: live_trading.starting_capital=100 (expected 100)

    [ 6] [2026-04-25T08:00:06-04:00] PASS (required) effective_position_cap
         evidence: effective_position_cap=5

    [ 7] [2026-04-25T08:00:07-04:00] PASS (required) mr_bracket_config
         evidence: stop_atr_multiple=2.0 template-importable

    [ 8] [2026-04-25T08:00:08-04:00] FAIL (required) alpaca_connectivity
         error: skipped

    [ 9] [2026-04-25T08:00:09-04:00] PASS (required) baseline_memo_signed_off
         evidence: commit abc1234 signed-off-by=millerrc18@gmail.com

    [10] [2026-04-25T08:00:10-04:00] PASS (required) transcript_saved
         evidence: path=/repo/audits/2026-04-27/preflight_transcript.txt

""")


# ── _find_latest_transcript tests ─────────────────────────────────────────────

class TestFindLatestTranscript:
    def test_returns_none_when_no_transcripts_exist(self, tmp_path):
        result = _find_latest_transcript(tmp_path)
        assert result is None

    def test_returns_path_when_transcript_exists(self, tmp_path):
        transcript = tmp_path / "preflight_transcript.txt"
        transcript.write_text("content", encoding="utf-8")
        result = _find_latest_transcript(tmp_path)
        assert result == transcript

    def test_returns_most_recent_when_multiple_exist(self, tmp_path):
        dir1 = tmp_path / "2026-04-25"
        dir1.mkdir()
        dir2 = tmp_path / "2026-04-26"
        dir2.mkdir()
        t1 = dir1 / "preflight_transcript.txt"
        t2 = dir2 / "preflight_transcript.txt"
        t1.write_text("older", encoding="utf-8")
        t2.write_text("newer", encoding="utf-8")
        # Selection is by mtime (PR #690 O6), so set explicit mtimes rather
        # than relying on filesystem write-order timing (Windows FS can
        # return identical mtimes for back-to-back writes).
        os.utime(t1, (1_700_000_000, 1_700_000_000))
        os.utime(t2, (1_700_000_100, 1_700_000_100))
        result = _find_latest_transcript(tmp_path)
        assert result == t2

    def test_returns_none_when_dirs_exist_but_no_transcript(self, tmp_path):
        subdir = tmp_path / "2026-04-25"
        subdir.mkdir()
        (subdir / "other_file.txt").write_text("not a transcript", encoding="utf-8")
        result = _find_latest_transcript(tmp_path)
        assert result is None

    def test_returns_most_recently_modified_regardless_of_name(self, tmp_path):
        """Ordering must be by mtime, not lexicographic name (PR #690 O6).

        Three transcripts in name-ordered dirs but touched in a different order:
        the latest mtime must win even when its name sorts first lexically.
        Guards against the ``2026-5-1`` non-padded-month bug where lex sort
        would pick the wrong (older) directory.
        """
        # Create three audit dirs whose names sort A < B < C lexically.
        dir_a = tmp_path / "2026-04-27"  # newest by name
        dir_b = tmp_path / "2026-04-26"
        dir_c = tmp_path / "2026-04-25"  # oldest by name
        for d in (dir_a, dir_b, dir_c):
            d.mkdir()
        ta = dir_a / "preflight_transcript.txt"
        tb = dir_b / "preflight_transcript.txt"
        tc = dir_c / "preflight_transcript.txt"
        # Write in name-sort order so default mtimes match name order.
        ta.write_text("a", encoding="utf-8")
        tb.write_text("b", encoding="utf-8")
        tc.write_text("c", encoding="utf-8")
        # Now touch mtimes so the lex-smallest name (dir_c) is the most recent.
        # Pick widely-spaced timestamps so flaky filesystem resolution can't blur them.
        os.utime(ta, (1_700_000_000, 1_700_000_000))  # oldest by mtime, newest by name
        os.utime(tb, (1_700_000_100, 1_700_000_100))
        os.utime(tc, (1_700_000_200, 1_700_000_200))  # newest by mtime, oldest by name

        result = _find_latest_transcript(tmp_path)
        assert result == tc, (
            f"expected mtime-newest ({tc.name}'s parent), got {result}"
        )


# ── _parse_transcript tests ───────────────────────────────────────────────────

class TestParseTranscript:
    def test_parses_last_run_at(self):
        result = _parse_transcript(SAMPLE_TRANSCRIPT)
        assert result["last_run_at"] == "2026-04-25T08:00:00-04:00"

    def test_parses_overall_status_yellow_when_any_fail(self):
        result = _parse_transcript(SAMPLE_TRANSCRIPT)
        assert result["overall_status"] == "yellow"

    def test_parses_overall_status_green_when_all_pass(self):
        all_pass = SAMPLE_TRANSCRIPT.replace(
            "9 PASS / 1 FAIL (10 total)", "10 PASS / 0 FAIL (10 total)"
        ).replace(
            "FAIL (required) alpaca_connectivity", "PASS (required) alpaca_connectivity"
        ).replace("error: skipped", "evidence: connected")
        result = _parse_transcript(all_pass)
        assert result["overall_status"] == "green"

    def test_parses_overall_status_red_when_multiple_required_fail(self):
        multi_fail = SAMPLE_TRANSCRIPT.replace(
            "9 PASS / 1 FAIL (10 total)", "7 PASS / 3 FAIL (10 total)"
        )
        result = _parse_transcript(multi_fail)
        assert result["overall_status"] == "red"

    def test_parses_items_list(self):
        result = _parse_transcript(SAMPLE_TRANSCRIPT)
        assert "items" in result
        assert isinstance(result["items"], list)
        assert len(result["items"]) == 10

    def test_items_have_required_fields(self):
        result = _parse_transcript(SAMPLE_TRANSCRIPT)
        first = result["items"][0]
        assert "name" in first
        assert "status" in first
        assert first["name"] == "pre_651_quarantine_clean"
        assert first["status"] == "pass"

    def test_items_capture_fail_status(self):
        result = _parse_transcript(SAMPLE_TRANSCRIPT)
        failed = [i for i in result["items"] if i["status"] == "fail"]
        assert len(failed) == 1
        assert failed[0]["name"] == "alpaca_connectivity"

    def test_returns_n_pass_n_fail(self):
        result = _parse_transcript(SAMPLE_TRANSCRIPT)
        assert result["n_pass"] == 9
        assert result["n_fail"] == 1


# ── get_preflight_latest endpoint tests ───────────────────────────────────────

class TestGetPreflightLatest:
    def test_returns_empty_state_when_no_transcript_found(self, tmp_path):
        with patch(
            "src.api.cloud_routes.preflight._find_latest_transcript",
            return_value=None,
        ):
            result = get_preflight_latest()
        assert result["last_run_at"] is None
        assert result["overall_status"] == "unknown"
        assert result["items"] == []
        assert result["transcript_path"] is None

    def test_returns_populated_state_when_transcript_found(self, tmp_path):
        transcript_file = tmp_path / "preflight_transcript.txt"
        transcript_file.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")
        with patch(
            "src.api.cloud_routes.preflight._find_latest_transcript",
            return_value=transcript_file,
        ):
            result = get_preflight_latest()
        assert result["last_run_at"] == "2026-04-25T08:00:00-04:00"
        assert result["overall_status"] == "yellow"
        assert len(result["items"]) == 10
        assert result["transcript_path"] == str(transcript_file)

    def test_response_shape_has_all_keys(self, tmp_path):
        transcript_file = tmp_path / "preflight_transcript.txt"
        transcript_file.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")
        with patch(
            "src.api.cloud_routes.preflight._find_latest_transcript",
            return_value=transcript_file,
        ):
            result = get_preflight_latest()
        assert set(result.keys()) >= {
            "last_run_at", "overall_status", "items", "transcript_path", "n_pass", "n_fail"
        }

    def test_empty_state_all_required_keys_present(self):
        with patch(
            "src.api.cloud_routes.preflight._find_latest_transcript",
            return_value=None,
        ):
            result = get_preflight_latest()
        assert set(result.keys()) >= {
            "last_run_at", "overall_status", "items", "transcript_path", "n_pass", "n_fail"
        }


# ── T7: SQLite-only routing verification (replaces TestPostgresRouting) ───────
# Phase 5 §3.2 strip: DATABASE_URL branch removed from get_preflight_latest.
# All 4 original TestPostgresRouting tests are replaced below.
# Verify-by-mutation: if the `if database_url:` branch were re-introduced,
# test_sqlite_is_sole_path_regardless_of_database_url_env would fail because
# the patch on _find_latest_transcript would be bypassed and psycopg2 (not
# patched) would be invoked instead.

class TestSQLiteOnlyRouting:
    def test_sqlite_is_sole_path_regardless_of_database_url_env(self, monkeypatch, tmp_path):
        """get_preflight_latest reads the filesystem even when DATABASE_URL is
        set in the environment. The PG branch was removed in T7 (Phase 5 §3.2);
        DATABASE_URL is now irrelevant to this route.

        Verify-by-mutation: if the removed `if database_url:` branch were
        re-introduced, this test would fail — the monkeypatched DATABASE_URL
        would cause the PG path to run, psycopg2 is not mocked here, so an
        ImportError or AttributeError would surface rather than the expected
        transcript data.
        """
        from src.api.cloud_routes import preflight as pf
        monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@host/db")
        transcript_file = tmp_path / "preflight_transcript.txt"
        transcript_file.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")
        with patch(
            "src.api.cloud_routes.preflight._find_latest_transcript",
            return_value=transcript_file,
        ):
            result = pf.get_preflight_latest()
        assert result["last_run_at"] == "2026-04-25T08:00:00-04:00"
        assert result["overall_status"] == "yellow"
        assert len(result["items"]) == 10

    def test_empty_state_when_no_transcript(self, monkeypatch, tmp_path):
        """When audits/ has no transcript, returns empty-state regardless of
        DATABASE_URL — the dashboard surfaces its 'not run yet' message."""
        from src.api.cloud_routes import preflight as pf
        monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@host/db")
        with patch(
            "src.api.cloud_routes.preflight._find_latest_transcript",
            return_value=None,
        ):
            result = pf.get_preflight_latest()
        assert result["last_run_at"] is None
        assert result["overall_status"] == "unknown"
        assert result["items"] == []


class TestPreflightRunsTableRegistered:
    """Lock that the preflight_runs table exists in the schema registry."""

    def test_preflight_runs_in_registry(self):
        from src.schema.registry import TABLES
        assert "preflight_runs" in TABLES

    def test_preflight_runs_has_required_columns(self):
        from src.schema.registry import TABLES
        cols = {c.name for c in TABLES["preflight_runs"].columns}
        required = {
            "run_id", "last_run_at", "overall_status", "n_pass", "n_fail",
            "items_json", "transcript_path", "created_at",
        }
        missing = required - cols
        assert not missing, f"preflight_runs missing columns: {missing}"
