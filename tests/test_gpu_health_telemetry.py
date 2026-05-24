"""Tests for T13: GPU health telemetry rename + 30-day dual-read.

Verifies:
1. _latest_gpu_health_ok reads BOTH old and new metric keys within 30-day window
2. notify_gpu_health is callable and registered under 'gpu_health' dispatch key
3. GPU_HEALTH constant == "gpu_health"

Note: the vram_handoff compat shims (notify_vram_handoff, the 'vram_handoff'
dispatch key, and the VRAM_HANDOFF constant) were contracted in #94 T15 after
T11/T14 removed their callers. The 30-day dual-read over the old
vram_handoff_* metric-key STRINGS (reports.py) is the only intentional bridge
that remains, exercised by the dual-read tests below.
"""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn_with_rows(rows: list[tuple[str, str, float]]) -> sqlite3.Connection:
    """Create an in-memory SQLite connection seeded with schedule_metrics rows.

    rows: list of (metric_name, metric_date, metric_value) tuples.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE schedule_metrics ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  metric_name TEXT,"
        "  metric_value TEXT,"
        "  metric_date TEXT"
        ")"
    )
    for metric_name, metric_date, metric_value in rows:
        conn.execute(
            "INSERT INTO schedule_metrics (metric_name, metric_date, metric_value) VALUES (?,?,?)",
            (metric_name, metric_date, str(metric_value)),
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. GPU_HEALTH constant
# ---------------------------------------------------------------------------

def test_gpu_health_constant():
    from src.utils.activity_logger import GPU_HEALTH
    assert GPU_HEALTH == "gpu_health"


# ---------------------------------------------------------------------------
# 2. _latest_gpu_health_ok — function exists and is callable
# ---------------------------------------------------------------------------

def test_latest_gpu_health_ok_exists():
    from src.scheduler.reports import _latest_gpu_health_ok
    assert callable(_latest_gpu_health_ok)


# ---------------------------------------------------------------------------
# 3. _latest_gpu_health_ok — reads NEW keys (gpu_health_*)
# ---------------------------------------------------------------------------

def test_latest_gpu_health_ok_reads_new_keys():
    """Rows under new key family gpu_health_* are read and returned True."""
    from src.scheduler.reports import _latest_gpu_health_ok

    today = datetime.now(ET).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("gpu_health_training_ok", today, 1.0),
        ("gpu_health_ollama_ok", today, 1.0),
    ])
    assert _latest_gpu_health_ok(conn) is True


def test_latest_gpu_health_ok_returns_false_when_new_key_fails():
    """Returns False when a new key row has value 0."""
    from src.scheduler.reports import _latest_gpu_health_ok

    today = datetime.now(ET).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("gpu_health_training_ok", today, 1.0),
        ("gpu_health_ollama_ok", today, 0.0),
    ])
    assert _latest_gpu_health_ok(conn) is False


# ---------------------------------------------------------------------------
# 4. _latest_gpu_health_ok — reads OLD keys (vram_handoff_*) within 30 days
# ---------------------------------------------------------------------------

def test_latest_gpu_health_ok_reads_old_keys():
    """Rows under old key family vram_handoff_* are read within 30-day window."""
    from src.scheduler.reports import _latest_gpu_health_ok

    # Use a date 15 days ago — within 30-day window
    date_15d_ago = (datetime.now(ET) - timedelta(days=15)).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("vram_handoff_training_ok", date_15d_ago, 1.0),
        ("vram_handoff_inference_ok", date_15d_ago, 1.0),
    ])
    assert _latest_gpu_health_ok(conn) is True


def test_latest_gpu_health_ok_returns_false_for_old_key_failure():
    """Returns False when an old vram_handoff row has value 0."""
    from src.scheduler.reports import _latest_gpu_health_ok

    date_15d_ago = (datetime.now(ET) - timedelta(days=15)).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("vram_handoff_training_ok", date_15d_ago, 0.0),
        ("vram_handoff_inference_ok", date_15d_ago, 1.0),
    ])
    assert _latest_gpu_health_ok(conn) is False


# ---------------------------------------------------------------------------
# 5. _latest_gpu_health_ok — 30-day window (old keys beyond window are ignored)
# ---------------------------------------------------------------------------

def test_latest_gpu_health_ok_ignores_old_keys_beyond_30_days():
    """Rows older than 30 days are excluded; empty result → True (grace behavior)."""
    from src.scheduler.reports import _latest_gpu_health_ok

    date_31d_ago = (datetime.now(ET) - timedelta(days=31)).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("vram_handoff_training_ok", date_31d_ago, 0.0),
        ("vram_handoff_inference_ok", date_31d_ago, 0.0),
    ])
    # Beyond window → no rows returned → grace True
    assert _latest_gpu_health_ok(conn) is True


# ---------------------------------------------------------------------------
# 6. _latest_gpu_health_ok — dual-read: both old and new keys in same window
# ---------------------------------------------------------------------------

def test_latest_gpu_health_ok_dual_read_all_ok():
    """With both old and new key rows present, all must be True."""
    from src.scheduler.reports import _latest_gpu_health_ok

    today = datetime.now(ET).strftime("%Y-%m-%d")
    date_5d_ago = (datetime.now(ET) - timedelta(days=5)).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("gpu_health_training_ok", today, 1.0),
        ("gpu_health_ollama_ok", today, 1.0),
        ("vram_handoff_training_ok", date_5d_ago, 1.0),
        ("vram_handoff_inference_ok", date_5d_ago, 1.0),
    ])
    assert _latest_gpu_health_ok(conn) is True


def test_latest_gpu_health_ok_dual_read_old_key_fails():
    """If old key shows failure, returns False even if new key is ok."""
    from src.scheduler.reports import _latest_gpu_health_ok

    today = datetime.now(ET).strftime("%Y-%m-%d")
    date_5d_ago = (datetime.now(ET) - timedelta(days=5)).strftime("%Y-%m-%d")
    conn = _make_conn_with_rows([
        ("gpu_health_training_ok", today, 1.0),
        ("gpu_health_ollama_ok", today, 1.0),
        ("vram_handoff_training_ok", date_5d_ago, 0.0),
        ("vram_handoff_inference_ok", date_5d_ago, 1.0),
    ])
    assert _latest_gpu_health_ok(conn) is False


# ---------------------------------------------------------------------------
# 7. _latest_gpu_health_ok — empty table returns True (grace behavior)
# ---------------------------------------------------------------------------

def test_latest_gpu_health_ok_empty_returns_true():
    """No rows → returns True (new-deploy grace)."""
    from src.scheduler.reports import _latest_gpu_health_ok

    conn = _make_conn_with_rows([])
    assert _latest_gpu_health_ok(conn) is True


# ---------------------------------------------------------------------------
# 8. notify_gpu_health registered under 'gpu_health' dispatch key
# ---------------------------------------------------------------------------

def test_notify_gpu_health_registered_in_event_map():
    from src.notifications.telegram import _EVENT_MAP, notify_gpu_health
    assert "gpu_health" in _EVENT_MAP
    assert _EVENT_MAP["gpu_health"] is notify_gpu_health


def test_notify_gpu_health_callable():
    from src.notifications.telegram import notify_gpu_health
    assert callable(notify_gpu_health)


def test_notify_gpu_health_sends_message():
    """notify_gpu_health calls send_telegram with appropriate args."""
    from src.notifications.telegram import notify_gpu_health
    with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
        result = notify_gpu_health(direction="training", success=True)
    assert mock_send.called
    assert result is True


def test_notify_gpu_health_failure_message():
    """notify_gpu_health passes success=False to send_telegram."""
    from src.notifications.telegram import notify_gpu_health
    with patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
        result = notify_gpu_health(direction="ollama", success=False, detail="OOM")
    assert mock_send.called
    call_args = mock_send.call_args[0][0]
    assert "OOM" in call_args


# ---------------------------------------------------------------------------
# 9. reports.py uses _latest_gpu_health_ok (not old name) at the call site
# ---------------------------------------------------------------------------

def test_reports_calls_gpu_health_not_vram_handoff():
    """_collect_schedule_health uses _latest_gpu_health_ok, not _latest_vram_handoff_ok."""
    import inspect
    import src.scheduler.reports as reports_mod
    src_text = inspect.getsource(reports_mod._collect_schedule_health)
    assert "_latest_gpu_health_ok" in src_text
    # Old name must NOT be called from this function
    assert "_latest_vram_handoff_ok" not in src_text


# ---------------------------------------------------------------------------
# 10. Writer-side regression locks — restored from T8 (commit 27ddc305) after
#     dropped during v0.36.50 squash. See project_w21_attack_order #117/#94.
# ---------------------------------------------------------------------------

def test_emit_training_health_writes_metric():
    """_emit_training_health upserts gpu_health_training_ok=1.0 with detail."""
    from src.scheduler.watch import WatchLoop
    instance = WatchLoop.__new__(WatchLoop)
    with patch("src.scheduler.watch.upsert_daily_metric") as m_upsert, \
         patch("src.scheduler.watch.safe_send") as m_safe:
        instance._emit_training_health("unit-test detail")
    m_upsert.assert_called_once()
    args, kwargs = m_upsert.call_args
    assert args[0] == "gpu_health_training_ok"
    assert args[1] == 1.0
    assert "unit-test detail" in args[2]
    m_safe.assert_called_once_with(
        "gpu_health", direction="training", success=True, detail="unit-test detail"
    )


def test_emit_training_health_metric_exception_swallowed():
    """A metrics-backend error must NOT crash the training-lifecycle handler."""
    from src.scheduler.watch import WatchLoop
    instance = WatchLoop.__new__(WatchLoop)
    with patch("src.scheduler.watch.upsert_daily_metric",
               side_effect=RuntimeError("PG offline")), \
         patch("src.scheduler.watch.safe_send"):
        instance._emit_training_health("detail")  # must not raise


def test_emit_training_health_safe_send_exception_swallowed():
    """A Telegram-dispatch error must NOT crash the training-lifecycle handler."""
    from src.scheduler.watch import WatchLoop
    instance = WatchLoop.__new__(WatchLoop)
    with patch("src.scheduler.watch.upsert_daily_metric"), \
         patch("src.scheduler.watch.safe_send",
               side_effect=RuntimeError("telegram offline")):
        instance._emit_training_health("detail")  # must not raise


@pytest.mark.parametrize("method_name,expected_detail", [
    ("_run_evening_training_launch", "evening training launched"),
    ("_run_morning_training_stop", "morning training stop"),
    ("_run_market_open_training_stop", "market-open training stop"),
])
def test_training_lifecycle_runner_emits_health(method_name, expected_detail):
    """Each of the 3 training-lifecycle runners must call _emit_training_health."""
    from src.scheduler.watch import WatchLoop
    instance = WatchLoop.__new__(WatchLoop)
    with patch("src.training.trainer.run_fine_tune"), \
         patch("src.training.training_control.stop_training_bounded"), \
         patch.object(WatchLoop, "_emit_training_health") as m_emit:
        getattr(instance, method_name)()
    m_emit.assert_called_once_with(expected_detail)
