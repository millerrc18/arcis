"""Tests for the Russell reconstitution monitor."""

from arcis.reconstitution.monitor import (
    DEC_2026_SCHEDULE,
    ReconCandidate,
    classify_migration,
    get_checklist_status,
    is_long_side_candidate,
)


class TestMigrationClassification:
    def test_r1000_to_r2000_is_downward(self):
        assert classify_migration("Russell 1000", "Russell 2000") == "downward_migration"

    def test_sp500_to_sp400_is_downward(self):
        assert classify_migration("S&P 500", "S&P 400") == "downward_migration"

    def test_deletion_is_rebound(self):
        assert classify_migration("Russell 2000", "") == "deletion_rebound"
        assert classify_migration("Russell 2000", "none") == "deletion_rebound"

    def test_upward_not_classified(self):
        assert classify_migration("Russell 2000", "Russell 1000") is None

    def test_addition_not_classified(self):
        assert classify_migration("", "Russell 3000") is None


class TestLongSideFilter:
    def test_downward_migration_passes(self):
        c = ReconCandidate(
            ticker="TEST",
            company="Test",
            from_index="Russell 1000",
            to_index="Russell 2000",
            event_type="downward_migration",
        )
        assert is_long_side_candidate(c)

    def test_deletion_rebound_passes(self):
        c = ReconCandidate(
            ticker="TEST",
            company="Test",
            from_index="Russell 2000",
            to_index="",
            event_type="deletion_rebound",
        )
        assert is_long_side_candidate(c)

    def test_addition_fails(self):
        c = ReconCandidate(
            ticker="TEST",
            company="Test",
            from_index="",
            to_index="Russell 3000",
            event_type="addition",
        )
        assert not is_long_side_candidate(c)


class TestSchedule:
    def test_dec_2026_dates(self):
        assert DEC_2026_SCHEDULE["effective_date"] == "2026-12-11"
        assert len(DEC_2026_SCHEDULE["preliminary_dates"]) == 5
        assert DEC_2026_SCHEDULE["preliminary_dates"][0] == "2026-11-13"

    def test_checklist_exists(self):
        status = get_checklist_status()
        assert len(status) > 0
        assert all(v is False for v in status.values())
