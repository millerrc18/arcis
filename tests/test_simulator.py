"""Known-answer tests for the S07 bracket simulator (SCOPE §5 done-means).

Every R05/D-020/PREREG §1.1 fill rule fires on hand-constructed bars with
hand-computed expectations. The harness must reproduce them exactly.
"""

from datetime import date, timedelta

import pytest

from arcis.research.ledger import Candidate, ambiguity_report, build_ledger
from arcis.research.panel import Bar, Panel, PanelError
from arcis.research.simulator import BracketSpec, simulate_trade

BUF = 0.05
SPREAD = 0.001


def make_panel(ohlc: list[tuple[float, float, float, float]],
               start: date = date(2020, 1, 6),
               symbol: str = "AAA") -> Panel:
    """Build a Panel from (o, h, l, c) tuples, one session apart.

    Appends one spare flat session: the SEC charge date (T+1) must exist
    past any exit.
    """
    ohlc = list(ohlc)
    last_c = ohlc[-1][3]
    # Spare flat sessions: an exit can land on the last data day, and the
    # SEC charge date (T+1/T+2/T+3 by settlement regime) must exist past
    # any exit.
    for _ in range(4):
        ohlc.append((last_c, last_c + 0.5, last_c - 0.5, last_c))
    bars = [Bar(start + timedelta(days=i), o, h, lo, c, 1_000_000)
            for i, (o, h, lo, c) in enumerate(ohlc)]
    return Panel({symbol: bars, "SPY": bars})


def spec_for(panel: Panel, entry_idx: int = 1, **kw) -> BracketSpec:
    cal = panel.calendar
    args = dict(symbol="AAA", signal_date=cal[0], entry_session=cal[entry_idx],
                limit=100.0, stop=95.0, target=105.0, shares=100)
    args.update(kw)
    return BracketSpec(**args)


def run(panel: Panel, spec: BracketSpec):
    return simulate_trade(panel, spec, buffer=BUF, spread_frac=SPREAD)


class TestEntry:
    def test_strict_trade_through_fills_at_limit(self):
        # Day 1: O=101 > 100, L=99 < 100 -> fill at 100. Day 2 hits target.
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100),
                            (100, 106, 100, 105)])
        r = run(panel, spec_for(panel))
        assert r.entry is not None and r.entry.price == 100.0
        assert r.entry.kind == "entry" and not r.entry.gap
        assert r.exit is not None and r.exit.kind == "target"
        assert r.exit.price == 105.0
        assert r.unfilled_reason is None

    def test_touch_only_is_no_fill(self):
        # Low exactly equals the limit: no fill in the conservative model.
        panel = make_panel([(100, 101, 99, 100), (101, 102, 100, 101)])
        r = run(panel, spec_for(panel))
        assert r.entry is None
        assert r.unfilled_reason == "touch_only"

    def test_no_trade_through(self):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 100.5, 101)])
        r = run(panel, spec_for(panel))
        assert r.entry is None
        assert r.unfilled_reason == "no_trade_through"

    def test_d020_gap_entry_fills_at_open_plus_buffer(self):
        # Open 98 <= limit 100 -> fill at 98 + 0.05, never above the limit.
        panel = make_panel([(100, 101, 99, 100), (98, 99, 97, 98.5),
                            (98.5, 107, 98, 106)])
        r = run(panel, spec_for(panel))
        assert r.entry is not None
        assert r.entry.price == pytest.approx(98.05)
        assert r.entry.gap
        assert r.exit is not None and r.exit.kind == "target"

    def test_d020_cap_at_limit(self):
        # Open 99.98 <= 100, buffer would push above the limit -> cap.
        panel = make_panel([(100, 101, 99, 100), (99.98, 100.5, 99.5, 100)])
        r = run(panel, spec_for(panel, target=100.4))
        assert r.entry is not None
        assert r.entry.price == 100.0  # min(99.98 + 0.05, 100)
        assert r.exit is not None and r.exit.kind == "target"

    def test_corporate_action_suppresses_entry(self):
        panel = make_panel([(100, 101, 99, 100), (98, 99, 97, 98.5)])
        cal = panel.calendar
        spec = BracketSpec(symbol="AAA", signal_date=cal[0],
                           entry_session=cal[1], limit=100.0, stop=95.0,
                           target=105.0, shares=100,
                           events={cal[1]: "halt"})
        r = run(panel, spec)
        assert r.entry is None
        assert r.unfilled_reason == "corporate_action"
        assert r.corporate_action


class TestExits:
    def _entered(self, day2: tuple[float, float, float, float]):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100), day2])
        return run(panel, spec_for(panel)), panel

    def test_stop_fill_no_gap(self):
        r, _ = self._entered((100, 101, 94, 96))
        assert r.exit is not None and r.exit.kind == "stop"
        assert r.exit.price == pytest.approx(94.95)  # 95 - 0.05
        assert not r.exit.gap

    def test_gap_stop_fills_at_open_minus_buffer(self):
        r, _ = self._entered((93, 94, 92, 93))
        assert r.exit is not None and r.exit.kind == "stop"
        assert r.exit.price == pytest.approx(92.95)  # 93 - 0.05
        assert r.exit.gap

    def test_stop_first_on_ambiguous_bar(self):
        # Both stop and target reachable: stop fills first (lower bound).
        r, _ = self._entered((100, 107, 93, 100))
        assert r.exit is not None and r.exit.kind == "stop"
        assert r.ambiguous_bar

    def test_target_fill_at_target_despite_gap_up(self):
        # Open gaps above the target: still filled at the target (R05-13).
        r, _ = self._entered((106, 108, 105.5, 107))
        assert r.exit is not None and r.exit.kind == "target"
        assert r.exit.price == 105.0

    def test_entry_day_stop_out(self):
        # Entry fills (low 94 < 100) then low <= stop 95 -> same-day stop.
        panel = make_panel([(100, 101, 99, 100), (101, 102, 94, 96)])
        r = run(panel, spec_for(panel))
        assert r.entry is not None and r.entry.price == 100.0
        assert r.exit is not None and r.exit.kind == "stop"
        assert r.exit.session == r.entry.session

    def test_entry_day_no_target_fill(self):
        # High reaches the target on the entry day: no fill (needs proof
        # the target came after the fill; daily bars can't show it).
        # The target fills the next session instead.
        panel = make_panel([(100, 101, 99, 100), (101, 108, 99, 107),
                            (107, 108, 106, 107)])
        r = run(panel, spec_for(panel))
        assert r.entry is not None
        assert r.exit is not None and r.exit.kind == "target"
        assert r.exit.session == panel.calendar[2]

    def test_fifteen_session_time_exit(self):
        bars = [(100, 101, 99, 100), (101, 102, 99, 100)]
        bars += [(100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1,
                  100 + i * 0.1) for i in range(16)]
        panel = make_panel(bars)
        r = run(panel, spec_for(panel))
        assert r.entry is not None
        assert r.exit is not None and r.exit.kind == "time"
        # Entry session + 14 = 15th session.
        assert r.exit.session == panel.calendar[15]


class TestCosts:
    def test_no_double_count_and_t1_charge_date(self):
        # Entry 100, target 105, 100 shares. Hand-check the ledger math.
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100),
                            (100, 106, 100, 105)])
        r = run(panel, spec_for(panel))
        assert r.entry_cost["commission"] == 0.0  # modern
        assert r.exit_cost["commission"] == 0.0
        # SEC on the sale notional 105*100 = 10500 at the T+1 charge date.
        # Charge date 2020-01-09 -> $20.70/M (2019-04-16 row; $22.10
        # starts 2020-02-18).
        assert r.exit_cost["sec_fee"] == pytest.approx(
            10500 * 20.70 / 1e6, abs=1e-9)
        # TAF by trade date (exit session): 100 sh * 0.000119 (2012-07-01
        # row covers 2020) capped at 5.95.
        assert r.exit_cost["finra_taf"] == pytest.approx(
            min(100 * 0.000119, 5.95), abs=1e-9)
        # Execution add-on: target exit is passive -> 0.
        assert r.execution_addon_dollars == 0.0
        gross = (105.0 - 100.0) * 100
        assert r.pnl_dollars == pytest.approx(
            gross - r.exit_cost["total_dollars"], abs=1e-6)

    def test_stop_exit_addon(self):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100),
                            (100, 101, 94, 96)])
        r = run(panel, spec_for(panel))
        assert r.exit is not None and r.exit.kind == "stop"
        # R06 conservative: +1.0 bp on the exit notional, beyond the buffer.
        assert r.execution_addon_dollars == pytest.approx(
            0.00010 * r.exit.price * 100, abs=1e-9)

    def test_time_exit_addon(self):
        bars = [(100, 101, 99, 100), (101, 102, 99, 100)]
        bars += [(100, 101, 99, 100)] * 16
        panel = make_panel(bars)
        r = run(panel, spec_for(panel))
        assert r.exit is not None and r.exit.kind == "time"
        # R06 conservative: 0.5 × spread × close-TOD-mult (2.0) + 1.0 bp.
        assert r.execution_addon_dollars == pytest.approx(
            (0.5 * SPREAD * 2.0 + 0.00010) * r.exit.price * 100, abs=1e-9)


class TestFailClosed:
    def test_bad_bracket_raises(self):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100)])
        cal = panel.calendar
        with pytest.raises(PanelError):
            run(panel, BracketSpec(symbol="AAA", signal_date=cal[0],
                                   entry_session=cal[1], limit=100.0,
                                   stop=100.0, target=105.0, shares=100))

    def test_unknown_symbol_raises(self):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100)])
        cal = panel.calendar
        with pytest.raises(PanelError):
            run(panel, BracketSpec(symbol="ZZZ", signal_date=cal[0],
                                   entry_session=cal[1], limit=100.0,
                                   stop=95.0, target=105.0, shares=100))

    def test_determinism(self):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100),
                            (100, 106, 100, 105)])
        r1 = run(panel, spec_for(panel))
        r2 = run(panel, spec_for(panel))
        assert r1.pnl_dollars == r2.pnl_dollars
        assert r1.entry == r2.entry and r1.exit == r2.exit


class TestLedger:
    def test_row_fields_and_ambiguity_report(self):
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100),
                            (100, 106, 100, 105),
                            (101, 102, 100.5, 101)])
        cal = panel.calendar
        cands = [
            Candidate(symbol="AAA", signal_date=cal[0], limit=100.0,
                      stop=95.0, target=105.0, shares=100),
            Candidate(symbol="AAA", signal_date=cal[2], limit=100.0,
                      stop=95.0, target=105.0, shares=100),
        ]
        rows = build_ledger(panel, cands, BUF, SPREAD)
        assert len(rows) == 2
        assert rows[0]["filled"] is True
        assert rows[0]["counterfactual_next_open_pct"] == pytest.approx(1.0)
        assert rows[0]["mae_pct"] is not None
        assert rows[0]["label_end"] == rows[0]["exit_session"]
        assert rows[1]["filled"] is False  # low 100.5 > limit
        assert rows[1]["label_end"] == cal[3].isoformat()  # t+1
        rep = ambiguity_report(rows)
        assert rep["n_candidates"] == 2
        assert rep["fill_rate"] == 0.5
        assert rep["touch_only_rate"] == 0.0


class TestLedgerMetrics:
    def test_metrics_from_ledger(self):
        from arcis.research.ledger import ledger_metrics
        panel = make_panel([(100, 101, 99, 100), (101, 102, 99, 100),
                            (100, 106, 100, 105),
                            (101, 102, 99, 100), (100, 94, 93, 93.5)])
        cal = panel.calendar
        cands = [
            Candidate(symbol="AAA", signal_date=cal[0], limit=100.0,
                      stop=95.0, target=105.0, shares=100),
            Candidate(symbol="AAA", signal_date=cal[3], limit=100.0,
                      stop=95.0, target=105.0, shares=100),
        ]
        rows = build_ledger(panel, cands, BUF, SPREAD)
        met = ledger_metrics(rows)
        assert met["n_trades"] == 2
        assert met["hit_rate"] == 0.5
        assert met["total_pnl_dollars"] == pytest.approx(
            rows[0]["pnl_dollars"] + rows[1]["pnl_dollars"])


class TestTargetTouch:
    def test_target_touch_does_not_fill(self):
        # Holding-day high exactly equals the target: preregistered rule is
        # strict high > target, so no fill on day 2 (then stopped out).
        panel = make_panel([(100, 101, 99, 100), (100, 102, 99, 101),
                            (103, 105, 102, 104), (103, 104, 102, 103.5),
                            (103, 104, 94, 95)])
        cal = panel.calendar
        spec = BracketSpec(symbol="AAA", signal_date=cal[0],
                           entry_session=cal[1], limit=100.0, stop=95.0,
                           target=105.0, shares=100)
        res = simulate_trade(panel, spec, BUF, SPREAD)
        assert res.entry is not None
        assert res.exit is not None and res.exit.kind == "stop"
        assert res.exit.session == cal[4]


class TestRunEvaluation:
    def _big_panel(self, n=60):
        # Random-walk-ish bars with enough history for the 21-session
        # trailing spread.
        ohlc = []
        px = 100.0
        for i in range(n):
            o = px
            h = o * 1.01
            lo = o * 0.99
            c = o * (1 + 0.001 * ((i % 3) - 1))
            ohlc.append((o, h, lo, c))
            px = c
        return make_panel(ohlc)

    def test_run_evaluation_logs_and_splits(self, tmp_path):
        from arcis.research.ledger import Candidate
        from arcis.research.registry import TrialRegistry
        from arcis.research.walkforward import make_folds, run_evaluation
        panel = self._big_panel(120)
        cal = panel.calendar
        cands = [Candidate(symbol="AAA", signal_date=cal[30],
                           limit=100.0, stop=95.0, target=110.0, shares=10),
                 Candidate(symbol="AAA", signal_date=cal[100],
                           limit=100.0, stop=95.0, target=110.0, shares=10)]
        folds = make_folds(cal, n_splits=2, val_size=20, embargo_sessions=15)
        reg = TrialRegistry(tmp_path / "r.jsonl")
        rec = run_evaluation(panel, cands, folds, registry=reg,
                             trial_id="WF-1", description="smoke",
                             params={"cost": "conservative"})
        assert reg.has("WF-1")
        assert rec["status"] == "complete"
        assert rec["n_folds"] == 2
        assert rec["n_candidates"] == 2
        trial = reg.trials()[0]
        assert len(trial["code_sha256"]) == 64
        # data_sha256 is panel_hash:candidate_hash (129 chars)
        assert len(trial["data_sha256"]) == 129
        assert trial["result_summary"]["n_folds"] == 2

    def test_run_evaluation_requires_registry(self, tmp_path):
        from arcis.research.walkforward import make_folds, run_evaluation
        panel = self._big_panel(120)
        folds = make_folds(panel.calendar, n_splits=2, val_size=20,
                           embargo_sessions=15)
        with pytest.raises(TypeError):
            run_evaluation(panel, [], folds, trial_id="X",
                           description="d", params={})

    def test_auto_cost_wiring_uses_trailing_spread(self):
        # build_ledger without explicit buffer/spread derives per-trade
        # costs; different volatility -> different buffers.
        from arcis.research.ledger import Candidate, build_ledger
        calm = [(100, 100.5, 99.5, 100)] * 60
        wild = [(100, 110, 90, 100)] * 60
        p_calm = make_panel(calm)
        p_wild = make_panel(wild)
        cal = p_calm.calendar
        def mk(p):
            return [Candidate(symbol="AAA", signal_date=cal[30],
                              limit=100.0, stop=90.0, target=110.0,
                              shares=10)]
        r_calm = build_ledger(p_calm, mk(p_calm))[0]
        r_wild = build_ledger(p_wild, mk(p_wild))[0]
        assert r_calm["filled"] and r_wild["filled"]
        # Wild bars -> larger spread -> larger execution addon on time exit
        # or a bigger buffer embedded in the fill. At minimum the rows
        # differ in cost accounting.
        assert (r_wild["execution_addon_dollars"]
                != r_calm["execution_addon_dollars"]
                or r_wild["entry_cost"] != r_calm["entry_cost"])


class TestCorporateActions:
    def test_blackout_suppresses_entry(self):
        from arcis.research.simulator import expand_blackouts
        panel = make_panel([(100, 101, 99, 100), (99, 100, 98, 99),
                            (99, 100, 98, 99)])
        cal = panel.calendar
        # Event on cal[2]: blackout covers cal[1] (prior session) and cal[2].
        bo = expand_blackouts({cal[2]}, panel)
        assert cal[1] in bo and cal[2] in bo
        spec = BracketSpec(symbol="AAA", signal_date=cal[0],
                           entry_session=cal[1], limit=100.0, stop=95.0,
                           target=105.0, shares=100, blackouts=bo)
        res = simulate_trade(panel, spec, BUF, SPREAD)
        assert res.entry is None
        assert res.unfilled_reason == "corporate_action"
        assert res.corporate_action is True

    def test_blackout_with_resolution(self):
        from arcis.research.simulator import expand_blackouts
        panel = make_panel([(100, 101, 99, 100)] * 6)
        cal = panel.calendar
        bo = expand_blackouts({cal[2]}, panel,
                              resolutions={cal[2]: cal[4]})
        assert bo == frozenset([cal[1], cal[2], cal[3], cal[4]])

    def test_split_reissues_levels(self):
        # 2:1 split on a holding day: stop/target halve, shares double.
        panel = make_panel([(100, 101, 99, 100), (100, 101, 99, 100.5),
                            (50, 51, 49, 50), (50, 53, 49, 52)])
        cal = panel.calendar
        spec = BracketSpec(symbol="AAA", signal_date=cal[0],
                           entry_session=cal[1], limit=100.0, stop=95.0,
                           target=105.0, shares=100,
                           splits={cal[2]: 2.0})
        res = simulate_trade(panel, spec, BUF, SPREAD)
        assert res.split_adjusted is True
        # Post-split target is 52.5; day-3 high of 53 fills it.
        assert res.exit is not None and res.exit.kind == "target"
        assert res.exit.price == pytest.approx(52.5)
        # P&L: entry 100 sh @ ~100 -> 200 sh @ ~50; exit 200 @ 52.5.
        # Must be a gain (~+5%), not a sign-flipped loss.
        assert res.pnl_dollars > 0
        assert 3.0 < res.return_pct < 7.0

    def test_exdiv_stop_flagged(self):
        panel = make_panel([(100, 101, 99, 100), (100, 101, 99, 100),
                            (98, 99, 94, 95)])
        cal = panel.calendar
        spec = BracketSpec(symbol="AAA", signal_date=cal[0],
                           entry_session=cal[1], limit=100.0, stop=95.0,
                           target=105.0, shares=100,
                           exdiv_dates=frozenset([cal[2]]))
        res = simulate_trade(panel, spec, BUF, SPREAD)
        assert res.exit is not None and res.exit.kind == "stop"
        assert res.exdiv_stop is True

    def test_halted_entry_session(self):
        bars = [(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100)]
        b = [Bar(date(2020, 1, 6) + timedelta(days=i), o, h, lo, c, 1_000_000)
             for i, (o, h, lo, c) in enumerate(bars)]
        # Drop the middle bar, declare it a halt.
        halt_day = date(2020, 1, 7)
        p = Panel({"AAA": [b[0], b[2]], "SPY": b},
                  halts={"AAA": {halt_day}})
        spec = BracketSpec(symbol="AAA", signal_date=b[0].date,
                           entry_session=halt_day, limit=100.0, stop=95.0,
                           target=105.0, shares=100)
        res = simulate_trade(p, spec, BUF, SPREAD)
        assert res.entry is None
        assert res.unfilled_reason == "halted"

    def test_undeclared_gap_raises(self):
        b = [Bar(date(2020, 1, 6) + timedelta(days=i), 100, 101, 99, 100,
                 1_000_000) for i in range(4)]
        # Gap on day 2, not declared: Panel construction fails closed.
        with pytest.raises(PanelError, match="missing bar"):
            Panel({"AAA": [b[0], b[2], b[3]], "SPY": b})

    def test_late_time_exit_flagged(self):
        # Halt the 15th counted session so the MOC exit slips a day.
        n = 20
        ohlc = [(100, 101, 99, 100)] * n
        bars = [Bar(date(2020, 1, 6) + timedelta(days=i), o, h, lo, c,
                    1_000_000) for i, (o, h, lo, c) in enumerate(ohlc)]
        halt_day = date(2020, 1, 6) + timedelta(days=10)
        aaa = [b for b in bars if b.date != halt_day]
        p = Panel({"AAA": aaa, "SPY": bars}, halts={"AAA": {halt_day}})
        cal = p.calendar
        spec = BracketSpec(symbol="AAA", signal_date=cal[0],
                           entry_session=cal[1], limit=100.0, stop=90.0,
                           target=200.0, shares=100)
        res = simulate_trade(p, spec, BUF, SPREAD)
        assert res.exit is not None and res.exit.kind == "time"
        assert res.late_time_exit is True
        assert res.sessions_held == 15

    def test_earnings_blackout_suppresses_entry(self):
        # PREREG §0: no new entry from t-1 through t+1 for earnings
        # with unknown timing.
        from arcis.research.ledger import Candidate, build_ledger
        panel = make_panel([(100, 101, 99, 100)] * 10)
        cal = panel.calendar
        # Earnings on cal[3]; entry would be cal[2] (t-1) -> suppressed.
        cand = Candidate(symbol="AAA", signal_date=cal[1],
                         limit=100.0, stop=95.0, target=105.0, shares=10,
                         earnings_dates=frozenset([cal[3]]))
        rows = build_ledger(panel, [cand], buffer=0.1, spread_frac=0.001)
        assert len(rows) == 1
        assert rows[0]["filled"] is False
        assert rows[0]["unfilled_reason"] == "corporate_action"
