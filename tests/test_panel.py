"""Tests for the S07 panel loader and session calendar."""

from datetime import date, timedelta

import pytest

from arcis.research.panel import Bar, Panel, PanelError, load_panel


def bars(n: int, start: date = date(2020, 1, 6)) -> list[Bar]:
    return [Bar(start + timedelta(days=i), 100.0 + i, 101.0 + i, 99.0 + i,
                100.5 + i, 1_000_000) for i in range(n)]


def panel(n: int = 10) -> Panel:
    b = bars(n)
    return Panel({"AAA": b, "SPY": b})


class TestCalendar:
    def test_session_index_and_next(self):
        p = panel()
        assert p.session_index(date(2020, 1, 6)) == 0
        assert p.next_session(date(2020, 1, 6)) == date(2020, 1, 7)
        assert p.prev_session(date(2020, 1, 7)) == date(2020, 1, 6)
        assert p.is_session(date(2020, 1, 6))
        assert not p.is_session(date(2020, 1, 5))

    def test_next_session_past_end_raises(self):
        p = panel(3)
        with pytest.raises(PanelError, match="no session after"):
            p.next_session(date(2020, 1, 8))

    def test_prev_session_before_start_raises(self):
        p = panel(3)
        with pytest.raises(PanelError, match="no session before"):
            p.prev_session(date(2020, 1, 6))

    def test_add_sessions(self):
        p = panel(20)
        assert p.add_sessions(date(2020, 1, 6), 15) == date(2020, 1, 21)
        assert p.add_sessions(date(2020, 1, 21), -15) == date(2020, 1, 6)
        with pytest.raises(PanelError):
            p.add_sessions(date(2020, 1, 6), 25)

    def test_charge_date_follows_settlement_regime(self):
        b = bars(3100, start=date(2016, 1, 4))
        p = Panel({"AAA": b, "SPY": b})
        # T+3 before 2017-09-05.
        assert p.charge_date(date(2016, 2, 11)) == date(2016, 2, 14)
        # T+2 from 2017-09-05 to 2024-05-27.
        assert p.charge_date(date(2020, 1, 6)) == date(2020, 1, 8)
        # T+1 from 2024-05-28.
        assert p.charge_date(date(2024, 6, 3)) == date(2024, 6, 4)

    def test_non_session_raises(self):
        p = panel()
        with pytest.raises(PanelError, match="not a session"):
            p.session_index(date(2019, 1, 1))

    def test_empty_bars_raise(self):
        with pytest.raises(PanelError, match="no bars"):
            Panel({"AAA": []})


class TestBars:
    def test_trailing(self):
        p = panel(10)
        t = p.trailing("AAA", date(2020, 1, 15), 3)
        assert len(t) == 3
        assert t[0].date == date(2020, 1, 13)
        assert t[-1].date == date(2020, 1, 15)
        assert t[-1].close == pytest.approx(109.5)

    def test_trailing_short_history_raises(self):
        p = panel(10)
        with pytest.raises(PanelError, match="only 3 bars"):
            p.trailing("AAA", date(2020, 1, 8), 5)

    def test_bar_missing_session_returns_none(self):
        b = bars(10)
        # AAA starts late: drop the first two bars (outside its range: OK).
        p = Panel({"AAA": b[2:], "SPY": b})
        assert p.bar("AAA", date(2020, 1, 6)) is None
        assert p.bar("AAA", date(2020, 1, 8)) is not None

    def test_unknown_symbol_raises(self):
        with pytest.raises(PanelError, match="unknown symbol"):
            panel().bar("ZZZ", date(2020, 1, 6))

    def test_load_panel_requires_spy(self):
        with pytest.raises(PanelError, match="SPY"):
            load_panel("/nonexistent", ["AAA"])


class TestGapsAndHalts:
    def test_undeclared_gap_raises(self):
        b = bars(10)
        bad = b[:5] + b[6:]  # drop 2020-01-11 inside AAA's range
        with pytest.raises(PanelError, match="missing bar"):
            Panel({"AAA": bad, "SPY": b})

    def test_declared_halt_is_ok_and_reported(self):
        b = bars(10)
        bad = b[:5] + b[6:]
        halt_day = date(2020, 1, 11)
        p = Panel({"AAA": bad, "SPY": b}, halts={"AAA": {halt_day}})
        assert p.is_halt("AAA", halt_day)
        assert not p.is_halt("AAA", date(2020, 1, 12))
        assert p.bar("AAA", halt_day) is None

    def test_halt_outside_range_ignored(self):
        b = bars(10)
        p = Panel({"AAA": b[2:], "SPY": b},
                  halts={"AAA": {date(2020, 1, 6)}})
        assert p.bar("AAA", date(2020, 1, 6)) is None
