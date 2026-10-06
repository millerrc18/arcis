"""Verified historical SEC Section 31 and FINRA TAF fee schedules.

Reconstructed 2026-10-06 from primary sources (SEC fee-rate advisories,
SEC orders, Federal Register documents; FINRA Regulatory Notices, NASD
Notices to Members, FINRA rule filings). Full research notes, per-entry
verification flags, and uncertain/inferred entries:
`~/workspace/research_notes/sec-taf-fee-schedules-20261006-0046/`
(not in the repo; see docs/sprints/S05-fee-tables.md).

Date conventions (per research):
- SEC Section 31: looked up by CHARGE date, which generally means
  settlement date (T+1 for equities since 2024-05-28, T+2 before).
  Pre-2004 orders phrase effectiveness as transaction dates.
- FINRA TAF: looked up by TRADE date.

Two Section 31 effective dates are inferred from statutory formula and
flagged below (#11, #12); both are corroborated by secondary sources.
"""

from __future__ import annotations

from datetime import date


class UnresolvedFeeError(Exception):
    """Raised when a fee rate is not verified for the given date.

    Fail-closed: unknown rates raise instead of silently returning zero.
    """


# --- SEC Section 31: (first effective charge date, $ per $1M sale principal,
# primary source). 33 periods, 1934-06-06 through 2026-12-31 (verified end;
# the $20.60 FY2026 rate runs "until 60 days after FY2027 appropriation,"
# whose date is unknown, so 2027+ raises).
SEC_SECTION31_SCHEDULE: list[tuple[date, float, str]] = [
    (date(1934, 6, 6), 33.33,
     "https://www.federalregister.gov/documents/full_text/html/2002/02/07/02-2961.html"),
    (date(2001, 12, 28), 15.00,
     "https://www.federalregister.gov/documents/full_text/html/2002/02/07/02-2961.html"),
    (date(2002, 4, 1), 30.10,
     "https://www.sec.gov/rules/other/34-45489.htm"),
    (date(2003, 3, 22), 25.20,
     "http://www.sec.gov/newsroom/press-releases/2003-24-fee-rate-advisory-11-fiscal-year-2003"),
    (date(2003, 4, 1), 46.80,
     "http://www.sec.gov/newsroom/press-releases/2003-27-fee-rate-advisory-12-fiscal-year-2003"),
    (date(2004, 2, 22), 39.00,
     "http://www.sec.gov/news/press/2004-10.htm"),
    (date(2004, 4, 1), 23.40,
     "https://www.sec.gov/news/press/2004-24.htm"),
    (date(2005, 1, 7), 32.90,
     "http://www.sec.gov/newsroom/press-releases/2004-59-fee-rate-advisory-1-fiscal-year-2005"),
    (date(2005, 4, 1), 41.80,
     "https://www.sec.gov/rules/other/34-51277.pdf"),
    (date(2005, 12, 22), 30.70,
     "http://www.sec.gov/news/press/2005-163.htm"),
    (date(2007, 3, 17), 15.30,  # inferred: 30 days after H.J.Res. 20 signed
     "http://www.sec.gov/rules/other/2006/33-8681.pdf"),
    (date(2008, 1, 25), 11.00,  # inferred: 30 days after FY2008 appropriation
     "https://www.sec.gov/newsroom/press-releases/2007-89-fee-rate-advisory-1-fiscal-year-2008"),
    (date(2008, 4, 1), 5.60,
     "https://www.sec.gov/newsroom/press-releases/2008-25-fee-rate-advisory-7-fiscal-year-2008"),
    (date(2009, 4, 10), 25.70,
     "https://www.sec.gov/news/press/2009/2009-56.htm"),
    (date(2010, 1, 15), 12.70,
     "http://www.sec.gov/news/press/2009/2009-270.htm"),
    (date(2010, 4, 1), 16.90,
     "https://www.sec.gov/news/press/2010/2010-29.htm"),
    (date(2011, 1, 21), 19.20,
     "https://www.sec.gov/news/press/2010/2010-255.htm"),
    (date(2012, 2, 21), 18.00,
     "https://www.sec.gov/news/press/2012/2012-15.htm"),
    (date(2012, 4, 1), 22.40,
     "https://www.sec.gov/news/press/2012/2012-35.htm"),
    (date(2013, 5, 25), 17.40,
     "https://www.sec.gov/news/press/2013/2013-74.htm"),
    (date(2014, 3, 18), 22.10,
     "https://www.sec.gov/newsroom/press-releases/2014-30"),
    (date(2015, 2, 14), 18.40,
     "http://www.sec.gov/news/press-release/2015-8"),
    (date(2016, 2, 16), 21.80,
     "https://www.sec.gov/newsroom/press-releases/2016-2"),
    (date(2017, 7, 4), 23.10,
     "https://www.sec.gov/news/press-release/2017-111"),
    (date(2018, 5, 22), 13.00,
     "https://www.sec.gov/news/press-release/2018-67"),
    (date(2019, 4, 16), 20.70,
     "https://www.sec.gov/newsroom/press-releases/2019-30"),
    (date(2020, 2, 18), 22.10,
     "https://www.sec.gov/newsroom/press-releases/2020-7"),
    (date(2021, 2, 25), 5.10,
     "https://www.sec.gov/news/press-release/2022-60"),
    (date(2022, 5, 14), 22.90,
     "https://www.sec.gov/news/press-release/2022-60"),
    (date(2023, 2, 27), 8.00,
     "https://www.SEC.gov/newsroom/press-releases/2023-15"),
    (date(2024, 5, 22), 27.80,
     "https://www.sec.gov/rules-regulations/fee-rate-advisories/2024-2"),
    (date(2025, 5, 14), 0.00,
     "http://www.sec.gov/rules-regulations/fee-rate-advisories/2025-2"),
    (date(2026, 4, 4), 20.60,
     "https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2"),
]
SEC_SCHEDULE_START = date(1934, 6, 6)
SEC_SCHEDULE_VERIFIED_END = date(2026, 12, 31)


# --- FINRA TAF: (first effective trade date, $ per share, $ cap per trade
# or None, primary source). 8 periods, 2002-10-01 through 2026-12-31.
# 2027+ raises: SR-FINRA-2024-019 schedules $0.000232/$11.61 for 2027, but
# the Sep 2026 pause filing says "the previous TAF fee rates will resume,"
# which is ambiguous — fail-closed until resolved.
TAF_SCHEDULE: list[tuple[date, float, float | None, str]] = [
    (date(2002, 10, 1), 0.0001, 10.00,
     "https://www.federalregister.gov/documents/full_text/html/2002/11/19/02-29314.html"),
    (date(2004, 11, 1), 0.000075, 3.75,
     "https://WWW.FINRA.ORG/rules-guidance/notices/04-84"),
    (date(2011, 7, 1), 0.000090, 4.50,
     "https://stage.acquia.finra.org/sites/default/files/NoticeDocument/p123766.pdf"),
    (date(2012, 3, 1), 0.000095, 4.75,
     "https://stage.acquia.finra.org/sites/default/files/NoticeDocument/p125499.pdf"),
    (date(2012, 7, 1), 0.000119, 5.95,
     "https://www.finra.org/rules-guidance/notices/12-31"),
    (date(2024, 1, 1), 0.000166, 8.30,
     "https://www.finra.org/sites/default/files/2023-06/sr-finra-2023-009.pdf"),
    (date(2026, 1, 1), 0.000195, 9.79,
     "https://stage.acquia.finra.org/sites/default/files/2024-11/sr-finra-2024-019.pdf"),
    (date(2026, 10, 1), 0.00, None,  # $0 holiday through 2026-12-31
     "https://www.federalregister.gov/documents/2026/09/23/2026-19392/self-regulatory-organizations-financial-industry-regulatory-authority-inc-notice-of-filing-and"),
]
TAF_INCEPTION = date(2002, 10, 1)
TAF_VERIFIED_END = date(2026, 12, 31)


def sec_section31_rate(charge_date: date) -> float:
    """SEC Section 31 rate per $1M of sale principal for `charge_date`.

    `charge_date` is the charge date, which generally means settlement
    date (not trade date). Raises UnresolvedFeeError outside the verified
    window (before 1934-06-06 or after 2026-12-31).
    """
    if charge_date < SEC_SCHEDULE_START:
        raise UnresolvedFeeError(
            f"SEC fee rate not verified for {charge_date} "
            f"(before {SEC_SCHEDULE_START})")
    if charge_date > SEC_SCHEDULE_VERIFIED_END:
        raise UnresolvedFeeError(
            f"SEC fee rate not verified for {charge_date} "
            f"(after {SEC_SCHEDULE_VERIFIED_END})")
    rate = 0.0
    for eff_date, r, _ in SEC_SECTION31_SCHEDULE:
        if charge_date >= eff_date:
            rate = r
        else:
            break
    return rate


def taf_rate(trade_date: date) -> float:
    """FINRA TAF rate per share for `trade_date` (cap applied separately).

    Zero before TAF inception (2002-10-01) per R06. Raises
    UnresolvedFeeError after 2026-12-31 (2027 rate ambiguous).
    """
    if trade_date < TAF_INCEPTION:
        return 0.0
    if trade_date > TAF_VERIFIED_END:
        raise UnresolvedFeeError(
            f"FINRA TAF rate not verified for {trade_date} "
            f"(after {TAF_VERIFIED_END}; 2027 rate ambiguous)")
    rate = 0.0
    for eff_date, r, _, _ in TAF_SCHEDULE:
        if trade_date >= eff_date:
            rate = r
        else:
            break
    return rate


def taf_cap(trade_date: date) -> float:
    """FINRA TAF cap in dollars per trade for `trade_date`.

    Raises UnresolvedFeeError during the $0 assessment holiday
    (2026-10-01–2026-12-31: no cap concept when no fee is assessed)
    and outside the verified window.
    """
    if trade_date < TAF_INCEPTION:
        raise UnresolvedFeeError(
            f"FINRA TAF cap not verified for {trade_date} (pre-inception)")
    if trade_date > TAF_VERIFIED_END:
        raise UnresolvedFeeError(
            f"FINRA TAF cap not verified for {trade_date} "
            f"(after {TAF_VERIFIED_END})")
    cap: float | None = None
    for eff_date, _, c, _ in TAF_SCHEDULE:
        if trade_date >= eff_date:
            cap = c
        else:
            break
    if cap is None:
        raise UnresolvedFeeError(
            f"FINRA TAF cap not applicable for {trade_date} "
            f"($0 assessment period)")
    return cap
