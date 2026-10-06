"""S05 T5: Known-answer tests for the R06 cost model.

Tests dated fees, spread proxies, and execution costs against
hand-computed values from docs/research/research-log.md.

Fail-closed: unknown fee rates raise UnresolvedFeeError.
Tick floor is price-aware. Spread estimators raise on bad input.
"""

from datetime import date

import pytest

from arcis.research import costs as r06
from arcis.research.fee_schedules import UnresolvedFeeError


class TestDatedFees:
    def test_sec_fee_current_rate(self):
        # 2026-04-04+: $20.60 per $1M = 0.206 bp
        # $50,000 sale -> $50,000 * 20.60 / 1e6 = $1.03
        fee = r06.sec_fee(50_000.0, date(2026, 6, 1))
        assert abs(fee - 1.03) < 0.01

    def test_sec_fee_zero_period(self):
        # 2025-05-14 to 2026-04-03: rate was zero
        assert r06.sec_fee(50_000.0, date(2025, 8, 1)) == 0.0
        assert r06.sec_fee(50_000.0, date(2026, 4, 3)) == 0.0

    def test_sec_fee_historical_rates_verified(self):
        # Full 33-period schedule now verified (S06-fee-tables).
        # 2024-06-03: $27.80/M -> $50,000 * 27.80 / 1e6 = $1.39
        assert abs(r06.sec_fee(50_000.0, date(2024, 6, 3)) - 1.39) < 0.01
        # 2020-01-02: $20.70/M -> $50,000 * 20.70 / 1e6 = $1.035
        assert abs(r06.sec_fee(50_000.0, date(2020, 1, 2)) - 1.035) < 0.01
        # 2008-06-01: $5.60/M -> $50,000 * 5.60 / 1e6 = $0.28
        assert abs(r06.sec_fee(50_000.0, date(2008, 6, 1)) - 0.28) < 0.01
        # Schedule starts at the panel start (2000-01-01); the 1934-1999
        # rate history was not reconstructed -> fail-closed before it.
        assert abs(r06.sec_fee(50_000.0, date(2000, 6, 1))
                   - 50_000.0 * 33.33 / 1e6) < 0.01
        with pytest.raises(UnresolvedFeeError, match="not verified"):
            r06.sec_fee(50_000.0, date(1999, 12, 31))

    def test_sec_fee_boundary_dates(self):
        # $0 through charge date 2026-04-03; $20.60 from 2026-04-04.
        assert r06.sec_fee_rate(date(2026, 4, 3)) == 0.0
        assert r06.sec_fee_rate(date(2026, 4, 4)) == 20.60
        # $27.80 through 2025-05-13; $0 from 2025-05-14.
        assert r06.sec_fee_rate(date(2025, 5, 13)) == 27.80
        assert r06.sec_fee_rate(date(2025, 5, 14)) == 0.0

    def test_fee_windows_close_at_2026_end(self):
        # Dated snapshots, not timeless constants: 2027+ raises instead of
        # silently reusing 2026 rates/caps.
        with pytest.raises(UnresolvedFeeError, match="not verified"):
            r06.sec_fee_rate(date(2027, 1, 1))
        with pytest.raises(UnresolvedFeeError, match="not verified"):
            r06.finra_taf(500.0, date(2027, 6, 1))

    def test_finra_taf_2026_cap(self):
        # R06: maximum $9.79 per trade in 2026.
        # 100,000 shares @ $0.000195 = $19.50 -> capped at $9.79
        fee = r06.finra_taf(100_000.0, date(2026, 6, 1))
        assert abs(fee - 9.79) < 0.01

    def test_finra_taf_cap_below_threshold(self):
        # 500 shares @ $0.000195 = $0.0975 < $9.79 cap: uncapped
        fee = r06.finra_taf(500.0, date(2026, 6, 1))
        assert abs(fee - 0.0975) < 0.001

    def test_finra_taf_before_inception(self):
        # Before 2002-10-01: zero (pre-TAF)
        assert r06.finra_taf(500.0, date(2000, 1, 1)) == 0.0

    def test_finra_taf_2004_2011_cap_verified(self):
        # 2004-11-01–2011-06-30: $0.000075/share, $3.75 cap (NTM 04-84).
        # 1000 shares -> $0.075 < $3.75 cap: uncapped
        assert abs(r06.finra_taf(1000.0, date(2008, 6, 1)) - 0.075) < 1e-9
        # 100,000 shares -> $7.50 > $3.75 cap: capped
        assert abs(r06.finra_taf(100_000.0, date(2008, 6, 1)) - 3.75) < 1e-9
        assert abs(r06.finra_taf_cap(date(2008, 6, 1)) - 3.75) < 1e-9

    def test_finra_taf_2012_2023_rate_verified(self):
        # Research correction: the TAF was NOT $0 in 2012-2023.
        # 2012-07-01–2023-12-31: $0.000119/share, $5.95 cap (Notice 12-31).
        assert abs(r06.finra_taf_rate(date(2016, 6, 1)) - 0.000119) < 1e-9
        assert abs(r06.finra_taf(1000.0, date(2016, 6, 1)) - 0.119) < 1e-9
        assert abs(r06.finra_taf_cap(date(2016, 6, 1)) - 5.95) < 1e-9

    def test_finra_taf_q4_2026_holiday(self):
        # $0 assessment 2026-10-01 through 2026-12-31 (FR Doc. 2026-19392).
        assert r06.finra_taf(100_000.0, date(2026, 10, 1)) == 0.0
        assert r06.finra_taf(100_000.0, date(2026, 11, 15)) == 0.0
        assert r06.finra_taf(100_000.0, date(2026, 12, 31)) == 0.0
        # Cap has no meaning during the $0 holiday: fail-closed.
        with pytest.raises(UnresolvedFeeError, match="not applicable"):
            r06.finra_taf_cap(date(2026, 11, 15))

    def test_finra_taf_holiday_boundaries(self):
        # $0.000195 through trade date 2026-09-30; $0 from 2026-10-01.
        assert abs(r06.finra_taf_rate(date(2026, 9, 30)) - 0.000195) < 1e-9
        assert r06.finra_taf_rate(date(2026, 10, 1)) == 0.0
        # 2027: ambiguous which scheduled rate resumes -> fail-closed.
        with pytest.raises(UnresolvedFeeError, match="not verified"):
            r06.finra_taf_rate(date(2027, 1, 5))

    def test_cat_fee_zero_per_r06(self):
        # R06: zero until verified CAT schedule; no invented $0.000003
        assert r06.cat_fee(500.0) == 0.0

    def test_commission_modern(self):
        assert r06.commission(100, "modern") == 0.0

    def test_commission_historical(self):
        assert r06.commission(100, "hist_5") == 5.0
        assert r06.commission(100, "hist_10") == 10.0


class TestSpreadProxies:
    def test_tick_floor_price_aware(self):
        # $100 stock: 1bp floor; $10 stock: 10bp floor
        assert abs(r06.tick_floor_fraction(100.0) - 0.0001) < 1e-9
        assert abs(r06.tick_floor_fraction(10.0) - 0.001) < 1e-9
        with pytest.raises(ValueError, match="positive"):
            r06.tick_floor_fraction(0.0)

    def test_corwin_schultz_zero_spread(self):
        # Flat prices -> zero spread (high == low is valid, not degenerate)
        highs = [100.0, 100.0]
        lows = [100.0, 100.0]
        assert r06.corwin_schultz_spread(highs, lows) == 0.0

    def test_corwin_schultz_raises_on_bad_input(self):
        with pytest.raises(ValueError, match="need 2 days"):
            r06.corwin_schultz_spread([100.0], [100.0])
        with pytest.raises(ValueError, match="positive"):
            r06.corwin_schultz_spread([0.0, 100.0], [0.0, 99.0])
        with pytest.raises(ValueError, match="high must be"):
            r06.corwin_schultz_spread([98.0, 99.0], [100.0, 101.0])

    def test_corwin_schultz_positive(self):
        # Wide high-low range -> positive spread estimate
        highs = [102.0, 103.0]
        lows = [98.0, 99.0]
        spread = r06.corwin_schultz_spread(highs, lows)
        assert spread > 0, f"spread={spread}"
        assert spread < 0.5, f"spread unreasonably large: {spread}"

    def test_corwin_schultz_known_answer(self):
        # Hand-computed from the published Corwin-Schultz (2012) formula:
        # beta = ln(102/100)^2 + ln(103/99)^2, gamma = ln(103/99)^2,
        # alpha = (sqrt(2b)-sqrt(b))/(3-2√2) - sqrt(gamma/(3-2√2)),
        # spread = 2(e^a-1)/(1+e^a) = 0.011284774415546862
        spread = r06.corwin_schultz_spread([102.0, 103.0], [100.0, 99.0])
        assert abs(spread - 0.011284774415546862) < 1e-12

    def test_abdi_ranaldo_known_answer(self):
        # Hand-computed from Abdi & Ranaldo (2017):
        # S = 2*sqrt((ln C0 - eta0)(ln C0 - eta1)) = 0.030545899055541358
        # eta0 = (ln105+ln95)/2, eta1 = (ln106+ln96)/2, C0 = 102
        spread = r06.abdi_ranaldo_spread(
            [105.0, 106.0], [95.0, 96.0], [102.0, 101.0])
        assert spread > 0
        assert abs(spread - 0.030545899055541358) < 1e-12

    def test_abdi_ranaldo_raises_on_bad_input(self):
        with pytest.raises(ValueError, match="need 2 days"):
            r06.abdi_ranaldo_spread([100.0], [99.0], [100.0])
        with pytest.raises(ValueError, match="positive"):
            r06.abdi_ranaldo_spread([10.0, 10.0], [0.0, 10.0],
                                    [10.0, 10.0])

    def test_spread_proxy_central_price_aware(self):
        # Zero-range bars on a $10 stock: floor is 10bp, not 1bp
        highs = [10.0, 10.0]
        lows = [10.0, 10.0]
        closes = [10.0, 10.0]
        spread = r06.spread_proxy_central(highs, lows, closes, price=10.0)
        assert abs(spread - 0.001) < 1e-9  # 0.01 / 10

    def test_spread_proxy_conservative_gte_central(self):
        highs = [102.0, 103.0]
        lows = [98.0, 99.0]
        closes = [100.0, 101.0]
        central = r06.spread_proxy_central(highs, lows, closes, price=100.0)
        conservative = r06.spread_proxy_conservative(highs, lows, closes,
                                                     price=100.0)
        assert conservative >= central


class TestExecution:
    def test_marketable_central(self):
        # 0.5 * 0.001 (10 bp spread) + 0.25 bp = 5.25 bp
        cost = r06.execution_marketable_exit(0.001, "central")
        assert abs(cost - 0.000525) < 0.00001

    def test_marketable_conservative(self):
        # 0.5 * 0.001 + 1.0 bp = 6 bp
        cost = r06.execution_marketable_exit(0.001, "conservative")
        assert abs(cost - 0.0006) < 0.00001

    def test_stop_no_gap(self):
        # 0.5 * 0.001 + 0.5 bp = 5.5 bp
        cost = r06.execution_stop_exit(0.001, 0.0, "central")
        assert abs(cost - 0.00055) < 0.00001

    def test_stop_with_gap(self):
        # Gap shortfall added
        cost = r06.execution_stop_exit(0.001, 0.02, "central")
        assert abs(cost - 0.02055) < 0.00001


class TestTotalCost:
    def test_modern_zero_commission(self):
        # $10,000 sale, 100 shares, 10bp spread, marketable exit
        result = r06.total_trade_cost(
            notional=10_000.0, shares=100, is_sell=True,
            as_of=date(2026, 6, 1), spread=0.001,
            exit_type="marketable", commission_model="modern",
            cost_model="central", charge_date=date(2026, 6, 2),
        )
        assert result["commission"] == 0.0
        # SEC: $10,000 * 20.60 / 1e6 = $0.206
        assert abs(result["sec_fee"] - 0.206) < 0.01
        # TAF: 100 * 0.000195 = $0.0195
        assert abs(result["finra_taf"] - 0.0195) < 0.001
        # Execution: 5.25 bp * $10,000 = $5.25
        assert abs(result["execution"] - 5.25) < 0.01
        # Total should be in the 2-6 bp central range (plus explicit fees)
        assert 2.0 < result["total_bp"] < 10.0

    def test_buy_has_no_sell_fees(self):
        result = r06.total_trade_cost(
            notional=10_000.0, shares=100, is_sell=False,
            as_of=date(2026, 6, 1), spread=0.001,
            exit_type="passive",
        )
        assert result["sec_fee"] == 0.0
        assert result["finra_taf"] == 0.0
        assert result["execution"] == 0.0  # passive: no added cost

    def test_total_trade_cost_degenerate_raises(self):
        # Basis points are undefined without a positive notional
        with pytest.raises(ValueError, match="notional must be positive"):
            r06.total_trade_cost(
                notional=0.0, shares=100, is_sell=True,
                as_of=date(2026, 6, 1), spread=0.001)

    def test_charge_date_required_for_sells(self):
        # Fail-closed: no silent trade-date default for the SEC lookup.
        # A 2026-12-31 sale settles 2027-01-04 (past the verified window);
        # defaulting would bill $20.60/M instead of raising.
        with pytest.raises(ValueError, match="charge_date is required"):
            r06.total_trade_cost(
                notional=10_000.0, shares=100, is_sell=True,
                as_of=date(2026, 12, 31), spread=0.001, exit_type="passive")
        # A charge date before the trade date is a caller error.
        with pytest.raises(ValueError, match="precedes the trade date"):
            r06.total_trade_cost(
                notional=10_000.0, shares=100, is_sell=True,
                as_of=date(2026, 4, 6), spread=0.001, exit_type="passive",
                charge_date=date(2026, 4, 3))
        # Buys need no charge date.
        result = r06.total_trade_cost(
            notional=10_000.0, shares=100, is_sell=False,
            as_of=date(2026, 12, 31), spread=0.001, exit_type="passive")
        assert result["sec_fee"] == 0.0

    def test_charge_date_vs_trade_date(self):
        # Trade date 2026-04-03 (Fri); T+1 settlement = 2026-04-06 (Mon).
        # SEC $0 through charge date 2026-04-03, $20.60 from 2026-04-04:
        # the trade-date default would bill $0 for a sale that settles
        # at $20.60/M — hence the required charge_date.
        result = r06.total_trade_cost(
            notional=10_000.0, shares=100, is_sell=True,
            as_of=date(2026, 4, 3), spread=0.001, exit_type="passive",
            charge_date=date(2026, 4, 6))
        assert abs(result["sec_fee"] - 0.206) < 0.01  # 10k * 20.60 / 1e6
        # TAF always uses the trade date, unaffected by charge_date.
        assert abs(result["finra_taf"] - 0.0195) < 0.001

    def test_taf_2002_2004_periods(self):
        # 2002-10-01: $0.00005/share, $5 cap (SR-NASD-2002-147,
        # retroactively effective; the $0.0001/$10 was superseded).
        assert abs(r06.finra_taf_rate(date(2002, 11, 1)) - 0.00005) < 1e-9
        assert abs(r06.finra_taf(1000.0, date(2003, 1, 15)) - 0.05) < 1e-9
        assert abs(r06.finra_taf(100_000.0, date(2003, 6, 1)) - 5.00) < 1e-9
        # 2003-09-01: $0.0001/share, $10 cap (NTM 03-43).
        assert abs(r06.finra_taf_rate(date(2003, 8, 31)) - 0.00005) < 1e-9
        assert abs(r06.finra_taf_rate(date(2003, 9, 1)) - 0.0001) < 1e-9
        assert abs(r06.finra_taf(100_000.0, date(2003, 10, 1)) - 10.00) < 1e-9
        # 2004-11-01: $0.000075/share, $3.75 cap (NTM 04-84).
        assert abs(r06.finra_taf_rate(date(2004, 10, 31)) - 0.0001) < 1e-9
        assert abs(r06.finra_taf_rate(date(2004, 11, 1)) - 0.000075) < 1e-9
