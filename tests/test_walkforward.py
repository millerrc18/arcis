"""Tests for the walk-forward harness, trial registry, and boundaries."""

from datetime import date, timedelta

import pytest

from arcis.research import walkforward as wf
from arcis.research.registry import Registry, code_hash, data_hash


def cal(n: int, start: date = date(2020, 1, 6)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def row(sig: date, exit: date | None, pnl: float = 0.0) -> dict:
    return {"signal_date": sig.isoformat(),
            "exit_session": exit.isoformat() if exit else None,
            "filled": exit is not None, "pnl_dollars": pnl}


class TestWalkForward:
    def test_make_folds(self):
        dates = cal(100)
        folds = wf.make_folds(dates, n_splits=5)
        # First fold dropped (no training data) -> 4 folds.
        assert len(folds) == 4
        assert folds[0].valid_start == dates[20]
        assert folds[0].train_end == dates[19]
        # Validation blocks are contiguous and cover the tail.
        assert folds[-1].valid_end == dates[99]

    def test_purge_drops_overlapping_labels(self):
        dates = cal(60)
        folds = wf.make_folds(dates, n_splits=3)
        fold = folds[0]  # valid: dates[20..39], train ends dates[19]
        # A training trade signaled on dates[15] but exited on dates[25]
        # overlaps the validation interval -> purged.
        rows = [row(dates[15], dates[25], 10.0),
                row(dates[10], dates[12], 5.0),   # clean train
                row(dates[25], dates[26], 7.0)]    # validation
        train, valid = wf.apply_purge_embargo(rows, fold, dates)
        assert [r["pnl_dollars"] for r in train] == [5.0]
        assert [r["pnl_dollars"] for r in valid] == [7.0]

    def test_embargo_drops_post_validation_train_rows(self):
        dates = cal(60)
        folds = wf.make_folds(dates, n_splits=3)
        fold = folds[0]  # valid dates[20..39]
        # Signal after the validation block but within the embargo.
        rows = [row(dates[40], dates[41], 3.0),
                row(dates[10], dates[11], 5.0)]
        train, valid = wf.apply_purge_embargo(rows, fold, dates,
                                              embargo_sessions=15)
        assert [r["pnl_dollars"] for r in train] == [5.0]

    def test_unfilled_rows_purge_only_on_signal_day(self):
        dates = cal(60)
        folds = wf.make_folds(dates, n_splits=3)
        fold = folds[0]
        rows = [row(dates[19], None, 0.0),   # signal on train_end, unfilled
                row(dates[20], None, 0.0)]   # signal on valid_start
        train, valid = wf.apply_purge_embargo(rows, fold, dates)
        assert len(train) == 1 and len(valid) == 1

    def test_fold_pnl(self):
        assert wf.fold_pnl([row(cal(10)[0], None, 1.5),
                            row(cal(10)[1], None, -0.5)]) == pytest.approx(1.0)


class TestRegistry:
    def test_log_and_read_back(self, tmp_path):
        reg = Registry(tmp_path / "registry.jsonl")
        rec = reg.log(trial_id="T-001", description="smoke",
                      code_sha="abc", data_sha="def",
                      params={"k": 1}, result_summary={"pnl": 2.0})
        assert rec["trial_id"] == "T-001"
        assert "timestamp_utc" in rec
        assert reg.has("T-001")
        assert not reg.has("T-999")
        trials = reg.trials()
        assert len(trials) == 1 and trials[0]["params"] == {"k": 1}

    def test_hashes(self, tmp_path):
        f = tmp_path / "a.py"
        f.write_text("x = 1\n")
        h1 = code_hash([str(f)])
        h2 = code_hash([str(f)])
        assert h1 == h2 and len(h1) == 64
        assert data_hash(b"data") == data_hash(b"data")
        assert data_hash(b"data") != data_hash(b"other")


class TestBoundaries:
    def test_obf_shape(self):
        pytest.importorskip("scipy")
        from arcis.research.boundaries import lan_demet_obf_bounds
        b = lan_demet_obf_bounds(2, alpha=0.025)
        assert len(b) == 2
        # OBF: very conservative early, near nominal at the end.
        assert b[0] > b[1]
        assert b[0] == pytest.approx(2.80, abs=0.05)
        assert b[1] == pytest.approx(1.98, abs=0.05)

    def test_obf_five_looks_decreasing(self):
        pytest.importorskip("scipy")
        from arcis.research.boundaries import lan_demet_obf_bounds
        b = lan_demet_obf_bounds(5, alpha=0.025)
        assert len(b) == 5
        assert all(x > y for x, y in zip(b, b[1:], strict=False))
        assert b[-1] == pytest.approx(2.04, abs=0.08)

    def test_archive(self, tmp_path):
        pytest.importorskip("scipy")
        from arcis.research.boundaries import archive
        rec = archive(tmp_path / "bounds.json", 2, alpha=0.025)
        assert rec["method"].startswith("Lan-DeMets")
        assert len(rec["z_boundaries"]) == 2
        assert (tmp_path / "bounds.json").exists()
