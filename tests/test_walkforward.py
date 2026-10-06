"""Tests for the walk-forward harness, trial registry, and boundaries."""

import json
from datetime import date, timedelta

import pytest

from arcis.research import walkforward as wf
from arcis.research.boundaries import archive, lan_demet_obf_bounds
from arcis.research.registry import TrialRegistry, code_hash, data_hash


def cal(n: int, start: date = date(2020, 1, 6)) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def row(sig: date, label_end: date, pnl: float = 0.0) -> dict:
    return {"signal_date": sig.isoformat(),
            "label_end": label_end.isoformat(),
            "filled": True, "pnl_dollars": pnl}


class TestWalkForward:
    def test_make_folds_explicit_embargo_gap(self):
        dates = cal(400)
        folds = wf.make_folds(dates, n_splits=3, val_size=63,
                              embargo_sessions=15)
        assert len(folds) == 3
        for f in folds:
            gap = dates.index(f.valid_start) - dates.index(f.train_end)
            assert gap == 16  # 15-session embargo gap, both-endpoint count
        # Validation blocks walk back from the end without overlap.
        assert folds[-1].valid_end == dates[399]
        assert folds[0].valid_end < folds[1].valid_start

    def test_make_folds_uses_embargo_param(self):
        dates = cal(400)
        f15 = wf.make_folds(dates, n_splits=3, val_size=63,
                            embargo_sessions=15)
        f5 = wf.make_folds(dates, n_splits=3, val_size=63,
                           embargo_sessions=5)
        gap15 = (dates.index(f15[0].valid_start)
                 - dates.index(f15[0].train_end))
        gap5 = (dates.index(f5[0].valid_start)
                - dates.index(f5[0].train_end))
        assert gap15 == 16
        assert gap5 == 6

    def test_make_folds_short_calendar_raises(self):
        with pytest.raises(ValueError, match="need"):
            wf.make_folds(cal(100), n_splits=5)

    def test_purge_and_embargo(self):
        dates = cal(400)
        fold = wf.make_folds(dates, n_splits=3, val_size=63)[0]
        V = dates.index(fold.valid_start)
        r_emb = row(dates[100], dates[V - 10], 1.0)   # in the embargo gap
        r_ov = row(dates[100], dates[V + 5], 2.0)     # overlaps validation
        r_ok = row(dates[100], dates[V - 20], 3.0)    # clean train
        r_v = row(fold.valid_start, fold.valid_start, 4.0)
        train, valid = wf.apply_purge_embargo(
            [r_emb, r_ov, r_ok, r_v], fold, dates)
        assert [r["pnl_dollars"] for r in train] == [3.0]
        assert [r["pnl_dollars"] for r in valid] == [4.0]

    def test_embargo_boundary_exact(self):
        # label_end 16 sessions before V (15-session gap) -> kept;
        # 15 sessions before V -> dropped.
        dates = cal(400)
        fold = wf.make_folds(dates, n_splits=3, val_size=63)[0]
        V = dates.index(fold.valid_start)
        r_keep = row(dates[50], dates[V - 16], 1.0)
        r_drop = row(dates[50], dates[V - 15], 2.0)
        train, _ = wf.apply_purge_embargo([r_keep, r_drop], fold, dates)
        assert [r["pnl_dollars"] for r in train] == [1.0]

    def test_date_grouped(self):
        dates = cal(400)
        fold = wf.make_folds(dates, n_splits=3, val_size=63)[0]
        sig = fold.valid_start
        rows = [row(sig, sig, float(i)) for i in range(5)]
        train, valid = wf.apply_purge_embargo(rows, fold, dates)
        assert len(valid) == 5 and not train

    def test_fold_pnl(self):
        assert wf.fold_pnl([row(cal(10)[0], cal(10)[0], 1.5),
                            row(cal(10)[1], cal(10)[1], -0.5)]
                           ) == pytest.approx(1.0)


class TestRegistry:
    def test_log_and_read_back(self, tmp_path):
        reg = TrialRegistry(tmp_path / "registry.jsonl")
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
    def test_two_look_matches_ld_of(self):
        # Lan-DeMets OBF one-sided 2.5%: spending
        # α(t) = 2 − 2Φ(z_{1−α/2}/√t)  (gsDesign sfLDOF).
        # Reference: gsDesign sfLDOF 2-look ≈ [2.9626, 1.9686].
        b = lan_demet_obf_bounds(2, alpha=0.025)
        assert b[0] == pytest.approx(2.9626, abs=5e-4)
        assert b[1] == pytest.approx(1.9686, abs=5e-4)

    def test_three_look(self):
        # Reference: gsDesign sfLDOF 3-look ≈ [3.7103, 2.5114, 1.9931].
        b = lan_demet_obf_bounds(3, alpha=0.025)
        assert b[0] == pytest.approx(3.7103, abs=5e-4)
        assert b[1] == pytest.approx(2.5114, abs=5e-4)
        assert b[2] == pytest.approx(1.9931, abs=5e-4)

    def test_spending_function_shape(self):
        from arcis.research.boundaries import spending_ld_of
        assert spending_ld_of(0.0) == 0.0
        assert spending_ld_of(1.0) == pytest.approx(0.025)
        assert spending_ld_of(0.5) < spending_ld_of(1.0)
        assert spending_ld_of(0.5) == pytest.approx(0.00153, abs=1e-4)

    def test_five_looks_decreasing(self):
        b = lan_demet_obf_bounds(5, alpha=0.025)
        assert len(b) == 5
        assert all(x > y for x, y in zip(b, b[1:], strict=False))
        assert b[-1] == pytest.approx(2.03, abs=0.08)

    def test_bad_inputs_raise(self):
        with pytest.raises(ValueError):
            lan_demet_obf_bounds(0)
        with pytest.raises(ValueError):
            lan_demet_obf_bounds(2, alpha=1.5)

    def test_norm_helpers_roundtrip(self):
        from arcis.research.boundaries import norm_cdf, norm_ppf
        for p in (0.025, 0.5, 0.975):
            assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-9)

    def test_archive(self, tmp_path):
        out = tmp_path / "bounds.json"
        rec = archive(out, 2, alpha=0.025)
        assert rec["method"] == "lan_demet_obf"
        assert len(rec["bounds"]) == 2
        assert out.exists()
        back = json.loads(out.read_text())
        assert back["bounds"] == rec["bounds"]
        assert back["implementation"] == "pure-python stdlib (math.bisect)"
        assert "2 - 2*Phi" in back["spending_function"]


class TestLoggedRun:
    def test_complete_run_logged(self, tmp_path):
        reg = TrialRegistry(tmp_path / "r.jsonl")
        with reg.logged_run("T-1", "desc", "abc", "def",
                            {"k": 1}) as rec:
            rec["pnl"] = 5.0
        trials = reg.trials()
        assert len(trials) == 1
        assert trials[0]["result_summary"]["status"] == "complete"
        assert trials[0]["result_summary"]["pnl"] == 5.0
        assert trials[0]["code_sha256"] == "abc"

    def test_failed_run_logged_and_reraised(self, tmp_path):
        reg = TrialRegistry(tmp_path / "r.jsonl")
        with pytest.raises(RuntimeError, match="boom"), \
                reg.logged_run("T-2", "desc", "abc", "def", {}) as rec:
            rec["partial"] = True
            raise RuntimeError("boom")
        trials = reg.trials()
        assert len(trials) == 1
        assert trials[0]["result_summary"]["status"] == "failed"
        assert "boom" in trials[0]["result_summary"]["error"]
        assert trials[0]["result_summary"]["partial"] is True

    def test_data_hash_of_panel(self, tmp_path):
        from arcis.research.panel import Bar, Panel
        b = [Bar(date(2020, 1, 6) + timedelta(days=i), 100, 101, 99, 100, 1)
             for i in range(5)]
        p = Panel({"AAA": b, "SPY": b})
        reg = TrialRegistry(tmp_path / "r.jsonl")
        h1 = reg.data_hash_of_panel(p)
        b2 = [Bar(date(2020, 1, 6) + timedelta(days=i), 100, 101, 99, 101, 1)
              for i in range(5)]
        p2 = Panel({"AAA": b2, "SPY": b2})
        assert reg.data_hash_of_panel(p2) != h1
