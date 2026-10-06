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
    # Two spare flat sessions: an exit can land on the last data day, and
    # the SEC charge date (T+1) must exist past any exit.
    ohlc.append((last_c, last_c + 0.5, last_c - 0.5, last_c))
    ohlc.append((last_c, last_c + 0.5, last_c - 0.5, last_c))
    bars = [Bar(start + timedelta(days=i), o, h, lo, c, 1_000_000)
            for i, (o, h, lo, c) in enumerate(ohlc)]
    cal = [b.date for b in bars]
    return Panel({symbol: bars, "SPY": bars}, cal)


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
        # Conservative +2.0 bp on the exit notional, beyond the buffer.
        assert r.execution_addon_dollars == pytest.approx(
            0.00020 * r.exit.price * 100, abs=1e-9)

    def test_time_exit_addon(self):
        bars = [(100, 101, 99, 100), (101, 102, 99, 100)]
        bars += [(100, 101, 99, 100)] * 16
        panel = make_panel(bars)
        r = run(panel, spec_for(panel))
        assert r.exit is not None and r.exit.kind == "time"
        assert r.execution_addon_dollars == pytest.approx(
            (0.5 * SPREAD + 0.00010) * r.exit.price * 100, abs=1e-9)


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
                      stop=95.0, target=105.0, shares=100, score=80.0),
            Candidate(symbol="AAA", signal_date=cal[2], limit=100.0,
                      stop=95.0, target=105.0, shares=100, score=10.0),
        ]
        rows = build_ledger(panel, cands, BUF, SPREAD)
        assert len(rows) == 2
        assert rows[0]["filled"] is True
        assert rows[0]["score"] == 80.0
        assert rows[0]["next_open_return_pct"] == pytest.approx(1.0)
        assert rows[0]["mae_pct"] is not None
        assert rows[1]["filled"] is False  # low 100.5 > limit
        rep = ambiguity_report(rows)
        assert rep["n_candidates"] == 2
        assert rep["fill_rate"] == 0.5
        assert rep["unfilled_reasons"] == {"no_trade_through": 1}


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
