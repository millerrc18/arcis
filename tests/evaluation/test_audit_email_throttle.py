"""v0.36.47 — audit-alert email throttle.

check_escalation() emailed the operator for EVERY flag on EVERY audit run, with
no dedup. The daily auditor re-runs on each watch-loop restart, so a persistent
flag (e.g. a false-positive drawdown) re-spammed the operator every cycle
(2026-05-21 flood). Throttle: email each flag CATEGORY at most once per 24h via
the restart-safe notifications_dedup table.
"""

from unittest.mock import patch

import pytest

from src.evaluation.auditor import check_escalation
from src.journal.store import initialize_database


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    initialize_database(path)
    return path


def _audit(category="drawdown", severity="critical"):
    return {"flags": [{
        "severity": severity, "category": category,
        "description": f"{category} issue", "recommendation": "review",
    }]}


def test_same_category_emailed_once_within_window(db_path):
    with patch("src.email.notifier.send_email", return_value=True) as send:
        check_escalation(_audit(), db_path=db_path)   # 1st → sends
        check_escalation(_audit(), db_path=db_path)   # 2nd (same category) → throttled
        check_escalation(_audit(), db_path=db_path)   # 3rd → still throttled
    assert send.call_count == 1


def test_distinct_categories_each_emailed(db_path):
    with patch("src.email.notifier.send_email", return_value=True) as send:
        check_escalation(_audit(category="drawdown"), db_path=db_path)
        check_escalation(_audit(category="model_quality"), db_path=db_path)
        check_escalation(_audit(category="rubric_drift"), db_path=db_path)
    # three different categories → three emails (no cross-category suppression)
    assert send.call_count == 3
