"""Tests for the odd-lot tender engine."""

import pytest

from arcis.oddlot.edgar import check_oddlot_provision
from arcis.oddlot.reader import (
    OddLotOpportunity,
    OfferTerms,
    parse_extraction_response,
)
from arcis.oddlot.tracker import (
    OppStatus,
    TrackedOpportunity,
    run_pretrade_checklist,
)


class TestOddlotDetection:
    def test_detects_oddlot_clause(self):
        text = (
            "The Company will accept all shares tendered by odd lot holders "
            "owning fewer than 100 shares before prorating all other shares."
        )
        has_it, evidence = check_oddlot_provision(text)
        assert has_it
        assert len(evidence) >= 1

    def test_no_oddlot(self):
        text = "All shares will be prorated equally among tendering shareholders."
        has_it, _ = check_oddlot_provision(text)
        assert not has_it

    def test_case_insensitive(self):
        text = "ODD-LOT holders will receive priority."
        has_it, _ = check_oddlot_provision(text)
        assert has_it


class TestOfferReader:
    def test_parse_valid_json(self):
        resp = """{
            "has_oddlot_priority": true,
            "oddlot_threshold": 99,
            "offer_price": 25.50,
            "price_range_low": null,
            "price_range_high": null,
            "is_dutch_auction": false,
            "expiration_date": "2026-11-15",
            "expiration_time": "11:59 PM ET",
            "min_tender_condition": null,
            "proration_description": "Odd lots first, then prorate",
            "withdrawal_rights": "Until expiration",
            "conditions": ["No MAE"],
            "issuer_cik": "1234567",
            "risk_flags": []
        }"""
        terms = parse_extraction_response(resp)
        assert terms.has_oddlot_priority is True
        assert terms.offer_price == 25.50
        assert terms.expiration_date == "2026-11-15"
        assert terms.effective_price == 25.50

    def test_parse_markdown_fences(self):
        resp = (
            '```json\n'
            '{"has_oddlot_priority": false, "is_dutch_auction": true, '
            '"price_range_low": 20.0, "price_range_high": 25.0}\n```'
        )
        terms = parse_extraction_response(resp)
        assert terms.is_dutch_auction is True
        assert terms.effective_price == 20.0  # conservative: range low

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            parse_extraction_response("not json at all")


class TestOpportunity:
    def _make_opp(self, offer_px=25.50, market_px=24.00):
        terms = OfferTerms(
            has_oddlot_priority=True,
            oddlot_threshold=99,
            offer_price=offer_px,
            expiration_date="2026-12-31",
        )
        return OddLotOpportunity(
            ticker="TEST",
            company="Test Corp",
            terms=terms,
            current_price=market_px,
        )

    def test_spread_calc(self):
        opp = self._make_opp()
        assert opp.gross_spread_per_share == pytest.approx(1.50)
        assert opp.gross_profit == pytest.approx(148.50)  # 99 shares
        assert opp.capital_required == pytest.approx(2376.00)

    def test_no_price_no_spread(self):
        opp = self._make_opp()
        opp.current_price = None
        assert opp.gross_spread_per_share is None


class TestChecklist:
    def _make_opp(self):
        terms = OfferTerms(
            has_oddlot_priority=True,
            oddlot_threshold=99,
            offer_price=25.50,
            expiration_date="2026-12-31",
        )
        return OddLotOpportunity(
            ticker="TEST",
            company="Test Corp",
            terms=terms,
            current_price=24.00,
        )

    def test_passes_clean(self):
        opp = self._make_opp()
        result = run_pretrade_checklist(opp, account_capital=10000)
        assert result.passed
        assert result.failures == []

    def test_fails_no_oddlot(self):
        opp = self._make_opp()
        opp.terms.has_oddlot_priority = False
        result = run_pretrade_checklist(opp, account_capital=10000)
        assert not result.passed
        assert any("Odd-lot" in f for f in result.failures)

    def test_fails_negative_spread(self):
        opp = self._make_opp()
        opp.current_price = 26.00  # above offer
        result = run_pretrade_checklist(opp, account_capital=10000)
        assert not result.passed

    def test_fails_insufficient_capital(self):
        opp = self._make_opp()
        result = run_pretrade_checklist(opp, account_capital=1000)
        assert not result.passed

    def test_warns_dutch_auction(self):
        opp = self._make_opp()
        opp.terms.is_dutch_auction = True
        opp.terms.offer_price = None
        opp.terms.price_range_low = 22.00
        opp.terms.price_range_high = 26.00
        result = run_pretrade_checklist(opp, account_capital=10000)
        assert any("Dutch" in w for w in result.warnings)


class TestLifecycle:
    def test_valid_transitions(self):
        from arcis.oddlot.tracker import ChecklistResult
        terms = OfferTerms(has_oddlot_priority=True)
        opp = OddLotOpportunity(ticker="T", company="C", terms=terms)
        tracked = TrackedOpportunity(opp=opp)
        assert tracked.status == OppStatus.IDENTIFIED
        # Must set a passed checklist before VETTED
        tracked.checklist = ChecklistResult(passed=True)
        tracked.transition(OppStatus.VETTED, "passed checklist")
        assert tracked.status == OppStatus.VETTED
        tracked.transition(OppStatus.POSITIONED, "bought 99 @ 24.00")
        tracked.shares_bought = 99
        tracked.avg_buy_price = 24.00
        tracked.transition(OppStatus.TENDERED, "election filed")
        tracked.proceeds = 99 * 25.50
        tracked.transition(OppStatus.CLOSED, "settled")
        assert tracked.realized_pnl == pytest.approx(148.50)

    def test_vetted_requires_checklist(self):
        terms = OfferTerms(has_oddlot_priority=True)
        opp = OddLotOpportunity(ticker="T", company="C", terms=terms)
        tracked = TrackedOpportunity(opp=opp)
        with pytest.raises(ValueError, match="checklist"):
            tracked.transition(OppStatus.VETTED)

    def test_vetted_requires_passed_checklist(self):
        from arcis.oddlot.tracker import ChecklistResult
        terms = OfferTerms(has_oddlot_priority=True)
        opp = OddLotOpportunity(ticker="T", company="C", terms=terms)
        tracked = TrackedOpportunity(opp=opp)
        tracked.checklist = ChecklistResult(
            passed=False, failures=["no edge"]
        )
        with pytest.raises(ValueError, match="Checklist failed"):
            tracked.transition(OppStatus.VETTED)

    def test_invalid_transition_raises(self):
        terms = OfferTerms()
        opp = OddLotOpportunity(ticker="T", company="C", terms=terms)
        tracked = TrackedOpportunity(opp=opp)
        with pytest.raises(ValueError):
            tracked.transition(OppStatus.CLOSED)  # skip steps
