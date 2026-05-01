from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    from src.schema.sqlite import create_all_tables

    db = str(tmp_path / "test.db")
    create_all_tables(db)
    return db


def test_collect_schedule_health_uses_live_metrics(tmp_db):
    from src.scheduler.reports import _collect_schedule_health

    with sqlite3.connect(tmp_db) as conn:
        conn.execute(
            "INSERT INTO scan_metrics "
            "(scan_number, scan_time, universe_count, features_count, scored_count, packet_worthy, "
            "risk_passed, paper_traded, live_traded, llm_success, llm_total, llm_fallback, "
            "avg_conviction, duration_seconds, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, "09:30", 100, 100, 100, 4, 4, 0, 0, 10, 10, 0, 7.5, 12.0, "2026-05-01T09:30:00"),
        )
        conn.execute(
            "INSERT INTO scan_metrics "
            "(scan_number, scan_time, universe_count, features_count, scored_count, packet_worthy, "
            "risk_passed, paper_traded, live_traded, llm_success, llm_total, llm_fallback, "
            "avg_conviction, duration_seconds, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (2, "10:10", 100, 100, 100, 5, 5, 0, 0, 10, 10, 0, 7.8, 11.0, "2026-05-01T10:10:00"),
        )
        conn.execute(
            "INSERT INTO schedule_metrics (metric_date, metric_name, metric_value, details) "
            "VALUES (?, ?, ?, ?)",
            ("2026-05-01", "vram_handoff_training_ok", 1.0, '{"result":"ok"}'),
        )
        conn.commit()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "src.monitoring.system_metrics.collect_system_snapshot",
            lambda db_path: {"gpu_util_pct": 72.3, "gpu_temp_c": 63.6},
        )
        monkeypatch.setattr("src.scheduler.reports._expected_scan_interval_minutes", lambda: 30)
        monkeypatch.setattr(
            "src.scheduler.reports.datetime",
            type(
                "FrozenDateTime",
                (),
                {
                    "now": staticmethod(lambda tz=None: datetime(2026, 5, 1, 16, 0, 0, tzinfo=tz)),
                    "fromisoformat": staticmethod(datetime.fromisoformat),
                    "strptime": staticmethod(datetime.strptime),
                },
            ),
        )
        health = _collect_schedule_health(tmp_db)

    assert health == {
        "gpu_util": 72.3,
        "scan_delay_max": 600.0,
        "handoff_ok": True,
        "temp_max": 64,
    }
