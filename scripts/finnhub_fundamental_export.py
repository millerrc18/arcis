#!/usr/bin/env python3
r"""
Finnhub Fundamental Exporter

Creates a local research warehouse on your Desktop with these 7 outputs:

1. dim_security.csv
2. filing_index.csv
3. financial_statement_fact.csv
4. financial_metric_fact.csv
5. derived_factor_fact.csv
6. event_fact.csv
7. data_quality_log.csv

It also saves raw API responses as JSON so you can audit exactly what came back.

Usage examples:

  # PowerShell
  $env:FINNHUB_API_KEY="YOUR_KEY_HERE"
  py .\finnhub_fundamental_export.py --symbols AAPL MSFT NVDA

  # Use a universe CSV with a column named symbol or ticker
  py .\finnhub_fundamental_export.py --universe-csv .\universe.csv --years 10 --sleep 1.1

Notes:
- This script writes to: ~/Desktop/finnhub_export_<timestamp>/
- Start with 3 to 5 symbols first. Then scale.
- Check your Finnhub subscription terms before retaining licensed datasets after cancellation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import requests
except ImportError as exc:
    raise SystemExit("Missing dependency: requests. Install with: py -m pip install requests") from exc

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("Missing dependency: pandas. Install with: py -m pip install pandas") from exc


API_BASE = "https://finnhub.io/api/v1"


# -----------------------------
# Utility helpers
# -----------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_str() -> str:
    return date.today().isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_filename(value: str) -> str:
    value = value.strip().upper()
    return re.sub(r"[^A-Z0-9._-]+", "_", value)


def desktop_dir() -> Path:
    # Works for Windows, macOS, and Linux. On Windows this resolves to C:\Users\<you>\Desktop.
    return Path.home() / "Desktop"


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    if isinstance(value, str):
        v = value.replace(",", "").strip()
        if v in {"", "None", "null", "nan", "NaN", "-"}:
            return None
        try:
            return float(v)
        except ValueError:
            return None
    return None


def safe_div(num: Any, den: Any) -> Optional[float]:
    n = to_float(num)
    d = to_float(den)
    if n is None or d is None or d == 0:
        return None
    return n / d


def first_present(row: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, "", "None"):
            return row[key]
    return None


def read_universe_csv(path: Path) -> List[str]:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    col = cols.get("symbol") or cols.get("ticker")
    if not col:
        raise ValueError("Universe CSV must include a column named 'symbol' or 'ticker'.")
    return sorted({str(x).strip().upper() for x in df[col].dropna() if str(x).strip()})


def chunk_date_ranges(start: date, end: date, max_days: int = 365) -> List[Tuple[date, date]]:
    """Finnhub endpoints may cap records per call. Chunking reduces missed filings/events."""
    ranges = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=max_days - 1), end)
        ranges.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return ranges


def flatten_json(prefix: str, obj: Any) -> Dict[str, Any]:
    """Flatten small nested dicts for CSV output. Lists are JSON encoded."""
    out: Dict[str, Any] = {}

    def _walk(p: str, v: Any) -> None:
        if isinstance(v, dict):
            for k, val in v.items():
                _walk(f"{p}_{k}" if p else str(k), val)
        elif isinstance(v, list):
            out[p] = json.dumps(v, ensure_ascii=False)
        else:
            out[p] = v

    _walk(prefix, obj)
    return out


@dataclass
class ApiResult:
    endpoint: str
    params: Dict[str, Any]
    ok: bool
    status_code: int
    data: Any
    error: Optional[str]
    fetched_at: str


class FinnhubClient:
    def __init__(self, api_key: str, sleep_seconds: float, timeout: float = 30.0):
        self.api_key = api_key
        self.sleep_seconds = sleep_seconds
        self.timeout = timeout
        self.session = requests.Session()

    def get(self, endpoint: str, params: Dict[str, Any]) -> ApiResult:
        params = dict(params)
        params["token"] = self.api_key
        url = f"{API_BASE}{endpoint}"
        fetched_at = utc_now_iso()

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            status = resp.status_code
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text[:5000]}

            ok = 200 <= status < 300
            error = None if ok else f"HTTP {status}: {str(data)[:500]}"

            # Gentle pacing. Tune with --sleep for your plan/rate limit.
            if self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)

            return ApiResult(endpoint, {k: v for k, v in params.items() if k != "token"}, ok, status, data, error, fetched_at)

        except requests.RequestException as exc:
            if self.sleep_seconds > 0:
                time.sleep(self.sleep_seconds)
            return ApiResult(endpoint, {k: v for k, v in params.items() if k != "token"}, False, 0, {}, str(exc), fetched_at)


class Warehouse:
    def __init__(self, root: Path):
        self.root = root
        self.raw_dir = root / "raw_json"
        self.csv_dir = root / "csv"
        self.log_dir = root / "logs"
        for p in [self.root, self.raw_dir, self.csv_dir, self.log_dir]:
            ensure_dir(p)

        self.dim_security: List[Dict[str, Any]] = []
        self.filing_index: List[Dict[str, Any]] = []
        self.financial_statement_fact: List[Dict[str, Any]] = []
        self.financial_metric_fact: List[Dict[str, Any]] = []
        self.derived_factor_fact: List[Dict[str, Any]] = []
        self.event_fact: List[Dict[str, Any]] = []
        self.data_quality_log: List[Dict[str, Any]] = []
        self.api_call_log: List[Dict[str, Any]] = []

    def save_raw(self, symbol: str, endpoint_name: str, result: ApiResult) -> None:
        symbol_dir = self.raw_dir / safe_filename(symbol)
        ensure_dir(symbol_dir)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        file_path = symbol_dir / f"{ts}_{safe_filename(endpoint_name)}.json"
        payload = {
            "endpoint": result.endpoint,
            "params": result.params,
            "ok": result.ok,
            "status_code": result.status_code,
            "error": result.error,
            "fetched_at": result.fetched_at,
            "data": result.data,
        }
        file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def log_call(self, symbol: str, result: ApiResult) -> None:
        self.api_call_log.append({
            "symbol": symbol,
            "endpoint": result.endpoint,
            "params_json": json.dumps(result.params, sort_keys=True),
            "ok": result.ok,
            "status_code": result.status_code,
            "error": result.error,
            "fetched_at": result.fetched_at,
        })

    def qlog(self, symbol: str, severity: str, issue_type: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self.data_quality_log.append({
            "symbol": symbol,
            "severity": severity,
            "issue_type": issue_type,
            "message": message,
            "context_json": json.dumps(context or {}, ensure_ascii=False, sort_keys=True),
            "logged_at": utc_now_iso(),
        })

    def write_csvs(self) -> None:
        outputs = {
            "dim_security.csv": self.dim_security,
            "filing_index.csv": self.filing_index,
            "financial_statement_fact.csv": self.financial_statement_fact,
            "financial_metric_fact.csv": self.financial_metric_fact,
            "derived_factor_fact.csv": self.derived_factor_fact,
            "event_fact.csv": self.event_fact,
            "data_quality_log.csv": self.data_quality_log,
            "api_call_log.csv": self.api_call_log,
        }

        for name, rows in outputs.items():
            path = self.csv_dir / name
            if rows:
                pd.DataFrame(rows).to_csv(path, index=False)
            else:
                # Write an empty file so the output contract is obvious.
                path.write_text("", encoding="utf-8")

        # Convenience manifest
        manifest = {
            "created_at": utc_now_iso(),
            "root": str(self.root),
            "csv_dir": str(self.csv_dir),
            "raw_json_dir": str(self.raw_dir),
            "tables": {k: len(v) for k, v in outputs.items()},
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# -----------------------------
# Finnhub pull/transform logic
# -----------------------------

def call_and_store(client: FinnhubClient, wh: Warehouse, symbol: str, endpoint_name: str, endpoint: str, params: Dict[str, Any]) -> ApiResult:
    result = client.get(endpoint, params)
    wh.log_call(symbol, result)
    wh.save_raw(symbol, endpoint_name, result)
    if not result.ok:
        wh.qlog(symbol, "ERROR", "api_error", f"{endpoint_name} failed: {result.error}", {"endpoint": endpoint, "params": params})
    return result


def pull_dim_security(client: FinnhubClient, wh: Warehouse, symbol: str) -> None:
    res = call_and_store(client, wh, symbol, "company_profile2", "/stock/profile2", {"symbol": symbol})
    data = res.data if isinstance(res.data, dict) else {}

    if not data:
        wh.qlog(symbol, "WARN", "missing_profile", "Company profile returned empty response.")
        return

    row = {
        "symbol": symbol,
        "name": data.get("name"),
        "country": data.get("country"),
        "currency": data.get("currency"),
        "exchange": data.get("exchange"),
        "finnhub_industry": data.get("finnhubIndustry"),
        "ipo": data.get("ipo"),
        "market_cap": data.get("marketCapitalization"),
        "share_outstanding": data.get("shareOutstanding"),
        "ticker": data.get("ticker"),
        "weburl": data.get("weburl"),
        "logo": data.get("logo"),
        "phone": data.get("phone"),
        "fetched_at": res.fetched_at,
        "raw_json": json.dumps(data, ensure_ascii=False),
    }
    wh.dim_security.append(row)

    if not data.get("name"):
        wh.qlog(symbol, "WARN", "missing_company_name", "Profile did not include a company name.", data)


def pull_filings(client: FinnhubClient, wh: Warehouse, symbol: str, start_date: date, end_date: date) -> None:
    for d0, d1 in chunk_date_ranges(start_date, end_date, max_days=365):
        res = call_and_store(
            client,
            wh,
            symbol,
            f"filings_{d0}_{d1}",
            "/stock/filings",
            {"symbol": symbol, "from": d0.isoformat(), "to": d1.isoformat()},
        )
        data = res.data if isinstance(res.data, list) else []
        if not isinstance(res.data, list):
            wh.qlog(symbol, "WARN", "unexpected_filings_shape", "Filings response was not a list.", {"type": type(res.data).__name__})
            continue

        for item in data:
            if not isinstance(item, dict):
                continue
            wh.filing_index.append({
                "symbol": symbol,
                "accession_number": item.get("accessionNumber") or item.get("accessionNo"),
                "form": item.get("form"),
                "filed_date": item.get("filedDate"),
                "accepted_date": item.get("acceptedDate"),
                "report_date": item.get("reportDate"),
                "filing_url": item.get("filingUrl"),
                "report_url": item.get("reportUrl"),
                "company_name": item.get("companyName"),
                "cik": item.get("cik"),
                "source_endpoint": "/stock/filings",
                "fetched_at": res.fetched_at,
                "raw_json": json.dumps(item, ensure_ascii=False),
            })


def pull_financial_statements(client: FinnhubClient, wh: Warehouse, symbol: str) -> None:
    statements = {
        "bs": "balance_sheet",
        "ic": "income_statement",
        "cf": "cash_flow",
    }
    freqs = ["annual", "quarterly"]

    for statement_code, statement_name in statements.items():
        for freq in freqs:
            res = call_and_store(
                client,
                wh,
                symbol,
                f"financials_{statement_code}_{freq}",
                "/stock/financials",
                {"symbol": symbol, "statement": statement_code, "freq": freq},
            )
            data = res.data if isinstance(res.data, dict) else {}
            financials = data.get("financials", [])
            if not financials:
                wh.qlog(symbol, "WARN", "missing_financials", f"No {statement_name} {freq} financial rows returned.")
                continue

            for period_row in financials:
                if not isinstance(period_row, dict):
                    continue

                period = period_row.get("period")
                year = period_row.get("year")
                quarter = period_row.get("quarter")
                form = period_row.get("form")
                start_date_val = period_row.get("startDate")
                end_date_val = period_row.get("endDate")

                for metric_name, metric_value in period_row.items():
                    if metric_name in {"period", "year", "quarter", "form", "startDate", "endDate", "filedDate", "acceptedDate"}:
                        continue
                    wh.financial_statement_fact.append({
                        "symbol": symbol,
                        "statement_code": statement_code,
                        "statement_name": statement_name,
                        "frequency": freq,
                        "period": period,
                        "fiscal_year": year,
                        "fiscal_quarter": quarter,
                        "form": form,
                        "start_date": start_date_val,
                        "end_date": end_date_val,
                        "metric": metric_name,
                        "value": metric_value,
                        "value_numeric": to_float(metric_value),
                        "source_endpoint": "/stock/financials",
                        "fetched_at": res.fetched_at,
                    })


def pull_as_reported_financials(client: FinnhubClient, wh: Warehouse, symbol: str) -> None:
    """
    Raw as-reported financials are saved to raw_json. We do not flatten them into the standardized
    fact table because the taxonomy can be deeply nested and inconsistent across issuers.
    """
    for freq in ["annual", "quarterly"]:
        res = call_and_store(
            client,
            wh,
            symbol,
            f"financials_reported_{freq}",
            "/stock/financials-reported",
            {"symbol": symbol, "freq": freq},
        )
        data = res.data if isinstance(res.data, dict) else {}
        if not data:
            wh.qlog(symbol, "WARN", "missing_as_reported", f"No as-reported {freq} financials returned.")


def pull_basic_metrics(client: FinnhubClient, wh: Warehouse, symbol: str) -> None:
    res = call_and_store(
        client,
        wh,
        symbol,
        "basic_financials_all",
        "/stock/metric",
        {"symbol": symbol, "metric": "all"},
    )
    data = res.data if isinstance(res.data, dict) else {}
    metric = data.get("metric", {})
    series = data.get("series", {})

    if isinstance(metric, dict):
        for name, value in metric.items():
            wh.financial_metric_fact.append({
                "symbol": symbol,
                "metric_group": "snapshot",
                "metric": name,
                "period": None,
                "value": value,
                "value_numeric": to_float(value),
                "source_endpoint": "/stock/metric",
                "fetched_at": res.fetched_at,
            })

    if isinstance(series, dict):
        for group_name, group_data in series.items():
            if isinstance(group_data, dict):
                for metric_name, observations in group_data.items():
                    if isinstance(observations, list):
                        for obs in observations:
                            if not isinstance(obs, dict):
                                continue
                            wh.financial_metric_fact.append({
                                "symbol": symbol,
                                "metric_group": group_name,
                                "metric": metric_name,
                                "period": obs.get("period"),
                                "value": obs.get("v"),
                                "value_numeric": to_float(obs.get("v")),
                                "source_endpoint": "/stock/metric",
                                "fetched_at": res.fetched_at,
                            })
                    else:
                        wh.financial_metric_fact.append({
                            "symbol": symbol,
                            "metric_group": group_name,
                            "metric": metric_name,
                            "period": None,
                            "value": json.dumps(observations, ensure_ascii=False),
                            "value_numeric": None,
                            "source_endpoint": "/stock/metric",
                            "fetched_at": res.fetched_at,
                        })


def pull_events(client: FinnhubClient, wh: Warehouse, symbol: str, start_date: date, end_date: date, earnings_limit: int) -> None:
    # Earnings calendar, chunked.
    for d0, d1 in chunk_date_ranges(start_date, end_date, max_days=365):
        res = call_and_store(
            client,
            wh,
            symbol,
            f"earnings_calendar_{d0}_{d1}",
            "/calendar/earnings",
            {"symbol": symbol, "from": d0.isoformat(), "to": d1.isoformat()},
        )
        data = res.data if isinstance(res.data, dict) else {}
        earnings = data.get("earningsCalendar", [])
        if isinstance(earnings, list):
            for item in earnings:
                if not isinstance(item, dict):
                    continue
                wh.event_fact.append({
                    "symbol": symbol,
                    "event_type": "earnings_calendar",
                    "event_date": item.get("date"),
                    "period": item.get("period"),
                    "fiscal_year": item.get("year"),
                    "quarter": item.get("quarter"),
                    "eps_actual": item.get("epsActual"),
                    "eps_estimate": item.get("epsEstimate"),
                    "revenue_actual": item.get("revenueActual"),
                    "revenue_estimate": item.get("revenueEstimate"),
                    "source_endpoint": "/calendar/earnings",
                    "fetched_at": res.fetched_at,
                    "raw_json": json.dumps(item, ensure_ascii=False),
                })

    # Company earnings history / surprises.
    res = call_and_store(
        client,
        wh,
        symbol,
        "company_earnings",
        "/stock/earnings",
        {"symbol": symbol, "limit": earnings_limit},
    )
    data = res.data if isinstance(res.data, list) else []
    if isinstance(res.data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            wh.event_fact.append({
                "symbol": symbol,
                "event_type": "company_earnings",
                "event_date": item.get("period"),
                "period": item.get("period"),
                "fiscal_year": item.get("year"),
                "quarter": item.get("quarter"),
                "eps_actual": item.get("actual"),
                "eps_estimate": item.get("estimate"),
                "surprise": item.get("surprise"),
                "surprise_percent": item.get("surprisePercent"),
                "source_endpoint": "/stock/earnings",
                "fetched_at": res.fetched_at,
                "raw_json": json.dumps(item, ensure_ascii=False),
            })

    # Insider transactions as event overlay, if your plan permits it.
    for d0, d1 in chunk_date_ranges(start_date, end_date, max_days=365):
        res = call_and_store(
            client,
            wh,
            symbol,
            f"insider_transactions_{d0}_{d1}",
            "/stock/insider-transactions",
            {"symbol": symbol, "from": d0.isoformat(), "to": d1.isoformat()},
        )
        data = res.data if isinstance(res.data, dict) else {}
        transactions = data.get("data", [])
        if isinstance(transactions, list):
            for item in transactions:
                if not isinstance(item, dict):
                    continue
                wh.event_fact.append({
                    "symbol": symbol,
                    "event_type": "insider_transaction",
                    "event_date": item.get("transactionDate"),
                    "period": None,
                    "insider_name": item.get("name"),
                    "insider_role": item.get("jobTitle") or item.get("relationship"),
                    "transaction_code": item.get("transactionCode"),
                    "shares": item.get("share"),
                    "price": item.get("transactionPrice"),
                    "value": to_float(item.get("share")) * to_float(item.get("transactionPrice")) if to_float(item.get("share")) is not None and to_float(item.get("transactionPrice")) is not None else None,
                    "source_endpoint": "/stock/insider-transactions",
                    "fetched_at": res.fetched_at,
                    "raw_json": json.dumps(item, ensure_ascii=False),
                })


def pull_revenue_breakdown_raw(client: FinnhubClient, wh: Warehouse, symbol: str) -> None:
    """
    Saves revenue breakdown raw JSON if your plan has access.
    Endpoint shape can vary, so this stores raw payload and logs access issues rather than forcing a brittle schema.
    """
    res = call_and_store(
        client,
        wh,
        symbol,
        "revenue_breakdown",
        "/stock/revenue-breakdown",
        {"symbol": symbol},
    )
    data = res.data if isinstance(res.data, dict) else {}
    if not data:
        wh.qlog(symbol, "WARN", "missing_revenue_breakdown", "Revenue breakdown returned empty response or is not available for this plan.")


def pull_transcript_metadata_raw(client: FinnhubClient, wh: Warehouse, symbol: str) -> None:
    """
    Saves transcript metadata raw JSON if your plan has access. Full transcript retrieval often requires
    a transcript id from this metadata.
    """
    res = call_and_store(
        client,
        wh,
        symbol,
        "earnings_call_transcripts_list",
        "/stock/transcripts/list",
        {"symbol": symbol},
    )
    data = res.data if isinstance(res.data, dict) else {}
    if not data:
        wh.qlog(symbol, "WARN", "missing_transcript_metadata", "Transcript metadata returned empty response or is not available for this plan.")


def derive_factors(wh: Warehouse) -> None:
    if not wh.financial_statement_fact:
        return

    df = pd.DataFrame(wh.financial_statement_fact)
    if df.empty:
        return

    # Pivot standardized financial statement rows into periods so we can calculate rough factors.
    id_cols = ["symbol", "frequency", "period", "fiscal_year", "fiscal_quarter"]
    pivot = (
        df.pivot_table(
            index=id_cols,
            columns="metric",
            values="value_numeric",
            aggfunc="first",
        )
        .reset_index()
    )

    # Candidate names because vendor labels can differ across statement datasets.
    metric_candidates = {
        "revenue": ["revenue", "totalRevenue", "netSales", "sales", "Revenue"],
        "gross_profit": ["grossProfit", "grossIncome", "Gross Profit"],
        "operating_income": ["operatingIncome", "ebit", "incomeFromOperations", "Operating Income"],
        "net_income": ["netIncome", "netIncomeCommonStockholders", "Net Income"],
        "cash_from_ops": ["cashFlowFromOperatingActivities", "netCashProvidedByOperatingActivities", "operatingCashFlow"],
        "capex": ["capitalExpenditure", "capitalExpenditures", "purchaseOfPPE"],
        "total_assets": ["totalAssets", "Total Assets"],
        "total_liabilities": ["totalLiabilities", "Total Liabilities"],
        "total_equity": ["totalEquity", "totalStockholderEquity", "shareholdersEquity"],
        "current_assets": ["totalCurrentAssets", "currentAssets"],
        "current_liabilities": ["totalCurrentLiabilities", "currentLiabilities"],
        "shares": ["basicAverageShares", "dilutedAverageShares", "weightedAverageShsOut", "weightedAverageSharesOutstandingDiluted"],
    }

    for canonical, candidates in metric_candidates.items():
        pivot[canonical] = None
        for cand in candidates:
            if cand in pivot.columns:
                pivot[canonical] = pivot[canonical].where(pd.notna(pivot[canonical]), pivot[cand])

    # Sort for growth calculations.
    pivot["period_dt"] = pd.to_datetime(pivot["period"], errors="coerce")
    pivot = pivot.sort_values(["symbol", "frequency", "period_dt"])

    factor_rows: List[Dict[str, Any]] = []

    def add_factor(row: pd.Series, factor: str, value: Any, formula: str) -> None:
        factor_rows.append({
            "symbol": row.get("symbol"),
            "frequency": row.get("frequency"),
            "period": row.get("period"),
            "fiscal_year": row.get("fiscal_year"),
            "fiscal_quarter": row.get("fiscal_quarter"),
            "factor": factor,
            "value": value,
            "formula": formula,
            "source": "derived_from_financial_statement_fact",
            "calculated_at": utc_now_iso(),
        })

    for _, row in pivot.iterrows():
        revenue = row.get("revenue")
        gross_profit = row.get("gross_profit")
        op_income = row.get("operating_income")
        net_income = row.get("net_income")
        cfo = row.get("cash_from_ops")
        capex = row.get("capex")
        assets = row.get("total_assets")
        liabilities = row.get("total_liabilities")
        equity = row.get("total_equity")
        current_assets = row.get("current_assets")
        current_liabilities = row.get("current_liabilities")

        fcf = None
        if to_float(cfo) is not None and to_float(capex) is not None:
            # Capex is often negative in cash flow statements. Adding it usually yields CFO - capex_outflow.
            fcf = to_float(cfo) + to_float(capex)

        calculations = [
            ("gross_margin", safe_div(gross_profit, revenue), "gross_profit / revenue"),
            ("operating_margin", safe_div(op_income, revenue), "operating_income / revenue"),
            ("net_margin", safe_div(net_income, revenue), "net_income / revenue"),
            ("fcf", fcf, "cash_from_ops + capex"),
            ("fcf_margin", safe_div(fcf, revenue), "fcf / revenue"),
            ("return_on_assets", safe_div(net_income, assets), "net_income / total_assets"),
            ("return_on_equity", safe_div(net_income, equity), "net_income / total_equity"),
            ("debt_to_equity_proxy", safe_div(liabilities, equity), "total_liabilities / total_equity"),
            ("current_ratio", safe_div(current_assets, current_liabilities), "current_assets / current_liabilities"),
        ]

        for factor, value, formula in calculations:
            if value is not None:
                add_factor(row, factor, value, formula)

    # Revenue growth by symbol/frequency.
    if "revenue" in pivot.columns:
        pivot["revenue_numeric"] = pd.to_numeric(pivot["revenue"], errors="coerce")
        pivot["revenue_growth_yoy_like"] = pivot.groupby(["symbol", "frequency"])["revenue_numeric"].pct_change()
        for _, row in pivot.iterrows():
            val = row.get("revenue_growth_yoy_like")
            if pd.notna(val):
                factor_rows.append({
                    "symbol": row.get("symbol"),
                    "frequency": row.get("frequency"),
                    "period": row.get("period"),
                    "fiscal_year": row.get("fiscal_year"),
                    "fiscal_quarter": row.get("fiscal_quarter"),
                    "factor": "revenue_growth_sequential_period",
                    "value": float(val),
                    "formula": "pct_change(revenue) within symbol/frequency",
                    "source": "derived_from_financial_statement_fact",
                    "calculated_at": utc_now_iso(),
                })

    wh.derived_factor_fact.extend(factor_rows)

    # Data quality checks.
    for symbol, g in pivot.groupby("symbol"):
        if g["period"].isna().all():
            wh.qlog(symbol, "WARN", "missing_periods", "No parseable financial statement periods found.")
        for metric in ["revenue", "net_income", "cash_from_ops"]:
            if metric in g.columns:
                coverage = g[metric].notna().mean()
                if coverage < 0.25:
                    wh.qlog(symbol, "WARN", "low_metric_coverage", f"Low coverage for derived input metric: {metric}", {"coverage": coverage})


def run_export(args: argparse.Namespace) -> Path:
    api_key = args.api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise SystemExit(
            "Missing API key. Set FINNHUB_API_KEY first, for example:\n"
            '  PowerShell: $env:FINNHUB_API_KEY="YOUR_KEY_HERE"\n'
            '  CMD:        set FINNHUB_API_KEY=YOUR_KEY_HERE'
        )

    symbols: List[str] = []
    if args.universe_csv:
        symbols.extend(read_universe_csv(Path(args.universe_csv)))
    if args.symbols:
        symbols.extend([s.strip().upper() for s in args.symbols if s.strip()])
    symbols = sorted(set(symbols))

    if not symbols:
        raise SystemExit("No symbols supplied. Use --symbols AAPL MSFT or --universe-csv universe.csv")

    end = date.today()
    start = end - timedelta(days=365 * args.years)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path(args.output_dir).expanduser() if args.output_dir else desktop_dir() / f"finnhub_export_{timestamp}"
    wh = Warehouse(out_root)
    client = FinnhubClient(api_key=api_key, sleep_seconds=args.sleep, timeout=args.timeout)

    print(f"Output folder: {out_root}")
    print(f"Symbols: {len(symbols)}")
    print(f"Date range: {start} to {end}")
    print("Starting export...\n")

    for i, symbol in enumerate(symbols, start=1):
        print(f"[{i}/{len(symbols)}] {symbol}")

        pull_dim_security(client, wh, symbol)
        pull_filings(client, wh, symbol, start, end)
        pull_financial_statements(client, wh, symbol)
        pull_basic_metrics(client, wh, symbol)
        pull_events(client, wh, symbol, start, end, earnings_limit=args.earnings_limit)

        if args.include_as_reported:
            pull_as_reported_financials(client, wh, symbol)

        if args.include_revenue_breakdown:
            pull_revenue_breakdown_raw(client, wh, symbol)

        if args.include_transcripts:
            pull_transcript_metadata_raw(client, wh, symbol)

    print("\nCalculating derived factors...")
    derive_factors(wh)

    print("Writing CSVs...")
    wh.write_csvs()

    print("\nDone.")
    print(f"CSV files: {wh.csv_dir}")
    print(f"Raw JSON:  {wh.raw_dir}")
    print(f"Manifest:  {wh.root / 'manifest.json'}")
    return out_root


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Finnhub fundamentals into a local Desktop data warehouse.")
    parser.add_argument("--api-key", help="Finnhub API key. Prefer FINNHUB_API_KEY environment variable instead.")
    parser.add_argument("--symbols", nargs="*", help="Ticker symbols, e.g. --symbols AAPL MSFT NVDA")
    parser.add_argument("--universe-csv", help="CSV with a symbol or ticker column.")
    parser.add_argument("--years", type=int, default=10, help="Lookback years for filings/events. Default: 10")
    parser.add_argument("--sleep", type=float, default=1.1, help="Seconds to sleep between API calls. Default: 1.1")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds. Default: 30")
    parser.add_argument("--earnings-limit", type=int, default=80, help="Company earnings history limit. Default: 80")
    parser.add_argument("--output-dir", help="Optional output folder. Default: Desktop/finnhub_export_<timestamp>")
    parser.add_argument("--include-as-reported", action="store_true", help="Also save /stock/financials-reported raw JSON.")
    parser.add_argument("--include-revenue-breakdown", action="store_true", help="Also save /stock/revenue-breakdown raw JSON if available.")
    parser.add_argument("--include-transcripts", action="store_true", help="Also save transcript metadata raw JSON if available.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_export(parse_args())
