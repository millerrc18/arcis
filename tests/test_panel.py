"""Tests for the S07 panel loader and session calendar."""

from datetime import date, timedelta

import pytest

from arcis.research.panel import Bar, Panel, PanelError, load_panel


def bars(n: int, start: date = date(2020, 1, 6)) -> list[Bar]:
    return [Bar(start + timedelta(days=i), 100.0 + i, 101.0 + i, 99.0 + i,
                100.5 + i, 1_000_000) for i in range(n)]


def panel(n: int = 10) -> Panel:
    b = bars(n)
    cal = [x.date for x in b]
    return Panel({"AAA": b, "SPY": b}, cal)


class TestCalendar:
    def test_session_index_and_next(self):
        p = panel()
        assert p.session_index(date(2020, 1, 6)) == 0
        assert p.next_session(date(2020, 1, 6)) == date(2020, 1, 7)
        assert p.is_session(date(2020, 1, 6))
        assert not p.is_session(date(2020, 1, 5))

    def test_next_session_past_end_raises(self):
        p = panel(3)
        with pytest.raises(PanelError, match="no session after"):
            p.next_session(date(2020, 1, 8))

    def test_add_sessions(self):
        p = panel(20)
        assert p.add_sessions(date(2020, 1, 6), 15) == date(2020, 1, 21)
        with pytest.raises(PanelError):
            p.add_sessions(date(2020, 1, 6), 25)

    def test_charge_date_is_t_plus_one(self):
        p = panel()
        assert p.charge_date(date(2020, 1, 6)) == date(2020, 1, 7)

    def test_non_session_raises(self):
        p = panel()
        with pytest.raises(PanelError, match="not a session"):
            p.session_index(date(2019, 1, 1))

    def test_empty_calendar_raises(self):
        with pytest.raises(PanelError, match="empty"):
            Panel({"AAA": []}, [])


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
        # AAA starts late: drop the first two bars.
        cal = [x.date for x in b]
        p = Panel({"AAA": b[2:], "SPY": b}, cal)
        assert p.bar("AAA", cal[0]) is None
        assert p.bar("AAA", cal[2]) is not None

    def test_unknown_symbol_raises(self):
        with pytest.raises(PanelError, match="unknown symbol"):
            panel().bar("ZZZ", date(2020, 1, 6))

    def test_load_panel_requires_spy(self):
        with pytest.raises(PanelError, match="SPY"):
            load_panel("/nonexistent", ["AAA"])
