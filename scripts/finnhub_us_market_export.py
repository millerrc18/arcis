#!/usr/bin/env python3
r"""
Finnhub US Market Fundamental Exporter

Creates a local research warehouse on your Desktop for the full Finnhub US market universe
or a custom list of symbols. Designed for long runs: it saves raw JSON, appends CSVs after
each symbol, and maintains a checkpoint so you can resume after interruptions.

Outputs under ~/Desktop/finnhub_us_market_export_<timestamp>/ by default:

  csv/dim_security.csv
  csv/filing_index.csv
  csv/financial_statement_fact.csv
  csv/financial_metric_fact.csv
  csv/derived_factor_fact.csv
  csv/event_fact.csv
  csv/data_quality_log.csv
  csv/api_call_log.csv
  csv/symbol_universe.csv
  raw_json/<SYMBOL>/*.json
  completed_symbols.txt
  manifest.json

PowerShell examples:

  # 1) Set API key
  $env:FINNHUB_API_KEY="YOUR_KEY_HERE"

  # 2) Smoke test the first 25 US symbols only
  py .\finnhub_us_market_export.py --market US --max-symbols 25 --years 10

  # 3) Full US market pull
  py .\finnhub_us_market_export.py --market US --years 10 --sleep 1.1 --resume

  # 4) Cleaner fundamentals-only universe, common stocks only
  py .\finnhub_us_market_export.py --market US --common-stocks-only --years 10 --sleep 1.1 --resume

  # 5) Include optional raw endpoints if your plan allows them
  py .\finnhub_us_market_export.py --market US --years 10 --include-as-reported --include-revenue-breakdown --include-transcripts --resume

Notes:
- Pulling the entire US market is a long-running job. Use --max-symbols first.
- Use --resume with the same --output-dir if you need to restart a stopped run.
- Check Finnhub license terms before retaining licensed datasets after cancellation.
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

API_BASE = "https://api.finnhub.io/api/v1"

# Fixed CSV schemas make per-symbol append reliable during huge runs.
CSV_COLUMNS: Dict[str, List[str]] = {
    "symbol_universe.csv": [
        "symbol", "display_symbol", "description", "security_type", "type", "mic", "figi", "isin", "currency", "exchange", "source_endpoint", "fetched_at", "raw_json"
    ],
    "dim_security.csv": [
        "symbol", "name", "country", "currency", "exchange", "finnhub_industry", "ipo", "market_cap", "share_outstanding", "ticker", "weburl", "logo", "phone", "fetched_at", "raw_json"
    ],
    "filing_index.csv": [
        "symbol", "accession_number", "form", "filed_date", "accepted_date", "report_date", "filing_url", "report_url", "company_name", "cik", "source_endpoint", "fetched_at", "raw_json"
    ],
    "financial_statement_fact.csv": [
        "symbol", "statement_code", "statement_name", "frequency", "period", "fiscal_year", "fiscal_quarter", "form", "start_date", "end_date", "metric", "value", "value_numeric", "source_endpoint", "fetched_at"
    ],
    "financial_metric_fact.csv": [
        "symbol", "metric_group", "metric", "period", "value", "value_numeric", "source_endpoint", "fetched_at"
    ],
    "derived_factor_fact.csv": [
        "symbol", "frequency", "period", "fiscal_year", "fiscal_quarter", "factor", "value", "formula", "source", "calculated_at"
    ],
    "event_fact.csv": [
        "symbol", "event_type", "event_date", "period", "fiscal_year", "quarter", "eps_actual", "eps_estimate", "revenue_actual", "revenue_estimate", "surprise", "surprise_percent", "insider_name", "insider_role", "transaction_code", "shares", "price", "value", "source_endpoint", "fetched_at", "raw_json"
    ],
    "data_quality_log.csv": [
        "symbol", "severity", "issue_type", "message", "context_json", "logged_at"
    ],
    "api_call_log.csv": [
        "symbol", "endpoint", "params_json", "ok", "status_code", "error", "fetched_at"
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_filename(value: str) -> str:
    value = str(value).strip().upper()
    return re.sub(r"[^A-Z0-9._-]+", "_", value) or "UNKNOWN"


def desktop_dir() -> Path:
    return Path.home() / "Desktop"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
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


def chunk_date_ranges(start: date, end: date, max_days: int = 365) -> List[Tuple[date, date]]:
    ranges: List[Tuple[date, date]] = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=max_days - 1), end)
        ranges.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return ranges


def read_universe_csv(path: Path) -> List[str]:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    col = cols.get("symbol") or cols.get("ticker")
    if not col:
        raise ValueError("Universe CSV must include a column named 'symbol' or 'ticker'.")
    return sorted({str(x).strip().upper() for x in df[col].dropna() if str(x).strip()})


def append_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    if not rows:
        return
    ensure_dir(path.parent)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            clean = {col: row.get(col) for col in columns}
            writer.writerow(clean)


def init_empty_csvs(csv_dir: Path) -> None:
    ensure_dir(csv_dir)
    for name, columns in CSV_COLUMNS.items():
        path = csv_dir / name
        if not path.exists():
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()


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
    def __init__(self, api_key: str, sleep_seconds: float, timeout: float = 30.0, max_retries: int = 3):
        self.api_key = api_key
        self.sleep_seconds = sleep_seconds
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def get(self, endpoint: str, params: Dict[str, Any]) -> ApiResult:
        params = dict(params)
        params["token"] = self.api_key
        url = f"{API_BASE}{endpoint}"
        fetched_at = utc_now_iso()
        last_error: Optional[str] = None
        last_status = 0
        last_data: Any = {}

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                last_status = resp.status_code
                try:
                    last_data = resp.json()
                except Exception:
                    last_data = {"raw_text": resp.text[:5000]}

                if 200 <= resp.status_code < 300:
                    self._sleep_after_call()
                    return ApiResult(endpoint, {k: v for k, v in params.items() if k != "token"}, True, resp.status_code, last_data, None, fetched_at)

                last_error = f"HTTP {resp.status_code}: {str(last_data)[:500]}"
                # Back off more aggressively on rate-limit or gateway style errors.
                if resp.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(max(self.sleep_seconds, 1.0) * attempt * 2)
                    continue
                break

            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(max(self.sleep_seconds, 1.0) * attempt * 2)
                    continue

        self._sleep_after_call()
        return ApiResult(endpoint, {k: v for k, v in params.items() if k != "token"}, False, last_status, last_data, last_error, fetched_at)

    def _sleep_after_call(self) -> None:
        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)


class Warehouse:
    def __init__(self, root: Path):
        self.root = root
        self.raw_dir = root / "raw_json"
        self.csv_dir = root / "csv"
        self.log_dir = root / "logs"
        self.completed_path = root / "completed_symbols.txt"
        for p in [self.root, self.raw_dir, self.csv_dir, self.log_dir]:
            ensure_dir(p)
        init_empty_csvs(self.csv_dir)

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

    def append_table(self, name: str, rows: List[Dict[str, Any]]) -> None:
        append_csv(self.csv_dir / name, rows, CSV_COLUMNS[name])

    def log_call_row(self, symbol: str, result: ApiResult) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "endpoint": result.endpoint,
            "params_json": json.dumps(result.params, sort_keys=True),
            "ok": result.ok,
            "status_code": result.status_code,
            "error": result.error,
            "fetched_at": result.fetched_at,
        }

    def qlog_row(self, symbol: str, severity: str, issue_type: str, message: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "severity": severity,
            "issue_type": issue_type,
            "message": message,
            "context_json": json.dumps(context or {}, ensure_ascii=False, sort_keys=True),
            "logged_at": utc_now_iso(),
        }

    def completed_symbols(self) -> set[str]:
        if not self.completed_path.exists():
            return set()
        return {x.strip().upper() for x in self.completed_path.read_text(encoding="utf-8").splitlines() if x.strip()}

    def mark_completed(self, symbol: str) -> None:
        with self.completed_path.open("a", encoding="utf-8") as f:
            f.write(symbol.upper() + "\n")

    def write_manifest(self, args: argparse.Namespace, symbols_total: int, completed_count: int) -> None:
        manifest = {
            "created_or_updated_at": utc_now_iso(),
            "root": str(self.root),
            "csv_dir": str(self.csv_dir),
            "raw_json_dir": str(self.raw_dir),
            "symbols_total_in_run": symbols_total,
            "completed_count_known": completed_count,
            "args": {k: str(v) for k, v in vars(args).items()},
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class SymbolBatch:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.tables: Dict[str, List[Dict[str, Any]]] = {name: [] for name in CSV_COLUMNS if name != "symbol_universe.csv"}

    def add(self, table_name: str, row: Dict[str, Any]) -> None:
        self.tables[table_name].append(row)

    def extend(self, table_name: str, rows: Iterable[Dict[str, Any]]) -> None:
        self.tables[table_name].extend(rows)

    def qlog(self, severity: str, issue_type: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        self.add("data_quality_log.csv", {
            "symbol": self.symbol,
            "severity": severity,
            "issue_type": issue_type,
            "message": message,
            "context_json": json.dumps(context or {}, ensure_ascii=False, sort_keys=True),
            "logged_at": utc_now_iso(),
        })


def call_and_store(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, endpoint_name: str, endpoint: str, params: Dict[str, Any]) -> ApiResult:
    result = client.get(endpoint, params)
    batch.add("api_call_log.csv", wh.log_call_row(batch.symbol, result))
    wh.save_raw(batch.symbol, endpoint_name, result)
    if not result.ok:
        batch.qlog("ERROR", "api_error", f"{endpoint_name} failed: {result.error}", {"endpoint": endpoint, "params": params})
    return result


def discover_market_symbols(client: FinnhubClient, wh: Warehouse, market: str, args: argparse.Namespace) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"exchange": market}
    if args.discovery_mic:
        params["mic"] = args.discovery_mic
    if args.discovery_currency:
        params["currency"] = args.discovery_currency
    if args.discovery_security_type:
        params["securityType"] = args.discovery_security_type

    result = client.get("/stock/symbol", params)
    wh.save_raw(f"MARKET_{market}", "stock_symbol_discovery", result)
    wh.append_table("api_call_log.csv", [wh.log_call_row(f"MARKET_{market}", result)])
    if not result.ok:
        wh.append_table("data_quality_log.csv", [wh.qlog_row(f"MARKET_{market}", "ERROR", "symbol_discovery_failed", result.error or "Symbol discovery failed.", params)])
        raise SystemExit(f"Could not discover market symbols for {market}: {result.error}")

    data = result.data if isinstance(result.data, list) else []
    rows: List[Dict[str, Any]] = []
    seen = set()
    include_types = {x.lower().strip() for x in args.include_security_types} if args.include_security_types else set()
    exclude_regex = re.compile(args.exclude_symbol_regex) if args.exclude_symbol_regex else None

    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or item.get("displaySymbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)

        security_type = str(item.get("securityType") or item.get("type") or "").strip()
        security_type_l = security_type.lower()

        if args.common_stocks_only:
            # Finnhub type strings vary by exchange/universe. Keep this intentionally permissive.
            if not any(token in security_type_l for token in ["common stock", "common", "equity"]):
                continue
        if include_types and security_type_l not in include_types:
            continue
        if exclude_regex and exclude_regex.search(symbol):
            continue

        row = {
            "symbol": symbol,
            "display_symbol": item.get("displaySymbol"),
            "description": item.get("description"),
            "security_type": item.get("securityType"),
            "type": item.get("type"),
            "mic": item.get("mic"),
            "figi": item.get("figi"),
            "isin": item.get("isin"),
            "currency": item.get("currency"),
            "exchange": market,
            "source_endpoint": "/stock/symbol",
            "fetched_at": result.fetched_at,
            "raw_json": json.dumps(item, ensure_ascii=False),
        }
        rows.append(row)

    rows = sorted(rows, key=lambda r: r["symbol"])
    if args.max_symbols:
        rows = rows[: args.max_symbols]

    wh.append_table("symbol_universe.csv", rows)
    return rows


def pull_dim_security(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str) -> None:
    res = call_and_store(client, wh, batch, "company_profile2", "/stock/profile2", {"symbol": symbol})
    data = res.data if isinstance(res.data, dict) else {}
    if not data:
        batch.qlog("WARN", "missing_profile", "Company profile returned empty response.")
        return

    batch.add("dim_security.csv", {
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
    })


def pull_filings(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str, start_date: date, end_date: date, chunk_days: int) -> None:
    for d0, d1 in chunk_date_ranges(start_date, end_date, max_days=chunk_days):
        res = call_and_store(client, wh, batch, f"filings_{d0}_{d1}", "/stock/filings", {"symbol": symbol, "from": d0.isoformat(), "to": d1.isoformat()})
        data = res.data if isinstance(res.data, list) else []
        if not isinstance(res.data, list):
            batch.qlog("WARN", "unexpected_filings_shape", "Filings response was not a list.", {"type": type(res.data).__name__})
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            batch.add("filing_index.csv", {
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


def pull_financial_statements(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str) -> None:
    statements = {"bs": "balance_sheet", "ic": "income_statement", "cf": "cash_flow"}
    for statement_code, statement_name in statements.items():
        for freq in ["annual", "quarterly"]:
            res = call_and_store(client, wh, batch, f"financials_{statement_code}_{freq}", "/stock/financials", {"symbol": symbol, "statement": statement_code, "freq": freq})
            data = res.data if isinstance(res.data, dict) else {}
            financials = data.get("financials", [])
            if not financials:
                batch.qlog("WARN", "missing_financials", f"No {statement_name} {freq} financial rows returned.")
                continue
            for period_row in financials:
                if not isinstance(period_row, dict):
                    continue
                for metric_name, metric_value in period_row.items():
                    if metric_name in {"period", "year", "quarter", "form", "startDate", "endDate", "filedDate", "acceptedDate"}:
                        continue
                    batch.add("financial_statement_fact.csv", {
                        "symbol": symbol,
                        "statement_code": statement_code,
                        "statement_name": statement_name,
                        "frequency": freq,
                        "period": period_row.get("period"),
                        "fiscal_year": period_row.get("year"),
                        "fiscal_quarter": period_row.get("quarter"),
                        "form": period_row.get("form"),
                        "start_date": period_row.get("startDate"),
                        "end_date": period_row.get("endDate"),
                        "metric": metric_name,
                        "value": metric_value,
                        "value_numeric": to_float(metric_value),
                        "source_endpoint": "/stock/financials",
                        "fetched_at": res.fetched_at,
                    })


def pull_as_reported_financials(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str) -> None:
    for freq in ["annual", "quarterly"]:
        res = call_and_store(client, wh, batch, f"financials_reported_{freq}", "/stock/financials-reported", {"symbol": symbol, "freq": freq})
        if not isinstance(res.data, dict) or not res.data:
            batch.qlog("WARN", "missing_as_reported", f"No as-reported {freq} financials returned.")


def pull_basic_metrics(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str) -> None:
    res = call_and_store(client, wh, batch, "basic_financials_all", "/stock/metric", {"symbol": symbol, "metric": "all"})
    data = res.data if isinstance(res.data, dict) else {}
    metric = data.get("metric", {})
    series = data.get("series", {})

    if isinstance(metric, dict):
        for name, value in metric.items():
            batch.add("financial_metric_fact.csv", {
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
                            batch.add("financial_metric_fact.csv", {
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
                        batch.add("financial_metric_fact.csv", {
                            "symbol": symbol,
                            "metric_group": group_name,
                            "metric": metric_name,
                            "period": None,
                            "value": json.dumps(observations, ensure_ascii=False),
                            "value_numeric": None,
                            "source_endpoint": "/stock/metric",
                            "fetched_at": res.fetched_at,
                        })


def pull_events(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str, start_date: date, end_date: date, args: argparse.Namespace) -> None:
    # core = company earnings only. full = earnings calendar plus insider transactions chunks as well.
    res = call_and_store(client, wh, batch, "company_earnings", "/stock/earnings", {"symbol": symbol, "limit": args.earnings_limit})
    if isinstance(res.data, list):
        for item in res.data:
            if not isinstance(item, dict):
                continue
            batch.add("event_fact.csv", {
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

    if args.event_depth != "full":
        return

    for d0, d1 in chunk_date_ranges(start_date, end_date, max_days=args.events_chunk_days):
        res = call_and_store(client, wh, batch, f"earnings_calendar_{d0}_{d1}", "/calendar/earnings", {"symbol": symbol, "from": d0.isoformat(), "to": d1.isoformat()})
        data = res.data if isinstance(res.data, dict) else {}
        earnings = data.get("earningsCalendar", [])
        if isinstance(earnings, list):
            for item in earnings:
                if not isinstance(item, dict):
                    continue
                batch.add("event_fact.csv", {
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

    for d0, d1 in chunk_date_ranges(start_date, end_date, max_days=args.events_chunk_days):
        res = call_and_store(client, wh, batch, f"insider_transactions_{d0}_{d1}", "/stock/insider-transactions", {"symbol": symbol, "from": d0.isoformat(), "to": d1.isoformat()})
        data = res.data if isinstance(res.data, dict) else {}
        transactions = data.get("data", [])
        if isinstance(transactions, list):
            for item in transactions:
                if not isinstance(item, dict):
                    continue
                shares = to_float(item.get("share"))
                price = to_float(item.get("transactionPrice"))
                batch.add("event_fact.csv", {
                    "symbol": symbol,
                    "event_type": "insider_transaction",
                    "event_date": item.get("transactionDate"),
                    "insider_name": item.get("name"),
                    "insider_role": item.get("jobTitle") or item.get("relationship"),
                    "transaction_code": item.get("transactionCode"),
                    "shares": shares,
                    "price": price,
                    "value": shares * price if shares is not None and price is not None else None,
                    "source_endpoint": "/stock/insider-transactions",
                    "fetched_at": res.fetched_at,
                    "raw_json": json.dumps(item, ensure_ascii=False),
                })


def pull_revenue_breakdown_raw(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str) -> None:
    res = call_and_store(client, wh, batch, "revenue_breakdown", "/stock/revenue-breakdown", {"symbol": symbol})
    if not isinstance(res.data, dict) or not res.data:
        batch.qlog("WARN", "missing_revenue_breakdown", "Revenue breakdown returned empty response or is not available for this plan.")


def pull_transcript_metadata_raw(client: FinnhubClient, wh: Warehouse, batch: SymbolBatch, symbol: str) -> None:
    res = call_and_store(client, wh, batch, "earnings_call_transcripts_list", "/stock/transcripts/list", {"symbol": symbol})
    if not isinstance(res.data, dict) or not res.data:
        batch.qlog("WARN", "missing_transcript_metadata", "Transcript metadata returned empty response or is not available for this plan.")


def derive_factors_for_symbol(batch: SymbolBatch) -> None:
    rows = batch.tables.get("financial_statement_fact.csv", [])
    if not rows:
        return
    df = pd.DataFrame(rows)
    if df.empty:
        return

    id_cols = ["symbol", "frequency", "period", "fiscal_year", "fiscal_quarter"]
    try:
        pivot = df.pivot_table(index=id_cols, columns="metric", values="value_numeric", aggfunc="first").reset_index()
    except Exception as exc:
        batch.qlog("WARN", "derived_factor_pivot_failed", str(exc))
        return

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
    }

    for canonical, candidates in metric_candidates.items():
        pivot[canonical] = None
        for cand in candidates:
            if cand in pivot.columns:
                pivot[canonical] = pivot[canonical].where(pd.notna(pivot[canonical]), pivot[cand])

    pivot["period_dt"] = pd.to_datetime(pivot["period"], errors="coerce")
    pivot = pivot.sort_values(["symbol", "frequency", "period_dt"])

    def add_factor(row: pd.Series, factor: str, value: Any, formula: str) -> None:
        if value is None:
            return
        try:
            if pd.isna(value):
                return
        except Exception:
            pass
        batch.add("derived_factor_fact.csv", {
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
            fcf = to_float(cfo) + to_float(capex)

        for factor, value, formula in [
            ("gross_margin", safe_div(gross_profit, revenue), "gross_profit / revenue"),
            ("operating_margin", safe_div(op_income, revenue), "operating_income / revenue"),
            ("net_margin", safe_div(net_income, revenue), "net_income / revenue"),
            ("fcf", fcf, "cash_from_ops + capex"),
            ("fcf_margin", safe_div(fcf, revenue), "fcf / revenue"),
            ("return_on_assets", safe_div(net_income, assets), "net_income / total_assets"),
            ("return_on_equity", safe_div(net_income, equity), "net_income / total_equity"),
            ("debt_to_equity_proxy", safe_div(liabilities, equity), "total_liabilities / total_equity"),
            ("current_ratio", safe_div(current_assets, current_liabilities), "current_assets / current_liabilities"),
        ]:
            add_factor(row, factor, value, formula)

    if "revenue" in pivot.columns:
        pivot["revenue_numeric"] = pd.to_numeric(pivot["revenue"], errors="coerce")
        pivot["revenue_growth_sequential_period"] = pivot.groupby(["symbol", "frequency"])["revenue_numeric"].pct_change()
        for _, row in pivot.iterrows():
            add_factor(row, "revenue_growth_sequential_period", row.get("revenue_growth_sequential_period"), "pct_change(revenue) within symbol/frequency")


def flush_symbol_batch(wh: Warehouse, batch: SymbolBatch) -> None:
    for name, rows in batch.tables.items():
        wh.append_table(name, rows)


def run_symbol(client: FinnhubClient, wh: Warehouse, symbol: str, start: date, end: date, args: argparse.Namespace) -> None:
    batch = SymbolBatch(symbol)
    pull_dim_security(client, wh, batch, symbol)
    pull_filings(client, wh, batch, symbol, start, end, args.filings_chunk_days)
    pull_financial_statements(client, wh, batch, symbol)
    pull_basic_metrics(client, wh, batch, symbol)
    pull_events(client, wh, batch, symbol, start, end, args)

    if args.include_as_reported:
        pull_as_reported_financials(client, wh, batch, symbol)
    if args.include_revenue_breakdown:
        pull_revenue_breakdown_raw(client, wh, batch, symbol)
    if args.include_transcripts:
        pull_transcript_metadata_raw(client, wh, batch, symbol)

    derive_factors_for_symbol(batch)
    flush_symbol_batch(wh, batch)
    wh.mark_completed(symbol)


def resolve_symbols(client: FinnhubClient, wh: Warehouse, args: argparse.Namespace) -> List[str]:
    symbols: List[str] = []
    if args.market:
        universe_rows = discover_market_symbols(client, wh, args.market, args)
        symbols.extend([r["symbol"] for r in universe_rows])
    if args.universe_csv:
        symbols.extend(read_universe_csv(Path(args.universe_csv)))
    if args.symbols:
        symbols.extend([s.strip().upper() for s in args.symbols if s.strip()])

    symbols = sorted(set(symbols))
    if args.start_at_symbol:
        start_symbol = args.start_at_symbol.upper()
        symbols = [s for s in symbols if s >= start_symbol]
    if args.max_symbols and not args.market:
        symbols = symbols[: args.max_symbols]
    return symbols


def run_export(args: argparse.Namespace) -> Path:
    api_key = args.api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise SystemExit(
            "Missing API key. Set FINNHUB_API_KEY first, for example:\n"
            '  PowerShell: $env:FINNHUB_API_KEY="YOUR_KEY_HERE"\n'
            '  CMD:        set FINNHUB_API_KEY=YOUR_KEY_HERE'
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_root = Path(args.output_dir).expanduser() if args.output_dir else desktop_dir() / f"finnhub_us_market_export_{timestamp}"
    wh = Warehouse(out_root)
    client = FinnhubClient(api_key=api_key, sleep_seconds=args.sleep, timeout=args.timeout, max_retries=args.max_retries)

    symbols = resolve_symbols(client, wh, args)
    if not symbols:
        raise SystemExit("No symbols supplied. Use --market US, --symbols AAPL MSFT, or --universe-csv universe.csv")

    completed = wh.completed_symbols() if args.resume else set()
    symbols_to_run = [s for s in symbols if s not in completed]

    end = date.today()
    start = end - timedelta(days=365 * args.years)

    print(f"Output folder: {out_root}")
    print(f"Universe size: {len(symbols)}")
    print(f"Already completed: {len(completed)}")
    print(f"Symbols to run: {len(symbols_to_run)}")
    print(f"Date range: {start} to {end}")
    print(f"Event depth: {args.event_depth}")
    print("Starting export...\n")

    if args.dry_run_universe:
        print("Dry run only. Symbol universe was saved to csv/symbol_universe.csv.")
        wh.write_manifest(args, len(symbols), len(completed))
        return out_root

    for i, symbol in enumerate(symbols_to_run, start=1):
        print(f"[{i}/{len(symbols_to_run)}] {symbol}")
        try:
            run_symbol(client, wh, symbol, start, end, args)
        except KeyboardInterrupt:
            print("\nInterrupted by user. Re-run with --resume and the same --output-dir to continue.")
            wh.write_manifest(args, len(symbols), len(wh.completed_symbols()))
            raise
        except Exception as exc:
            # Log a symbol-level failure and keep going. Raw responses up to the failure are already saved.
            wh.append_table("data_quality_log.csv", [wh.qlog_row(symbol, "ERROR", "symbol_run_exception", str(exc))])
            print(f"  ERROR on {symbol}: {exc}")
            if args.stop_on_error:
                raise

        if i % args.manifest_every == 0:
            wh.write_manifest(args, len(symbols), len(wh.completed_symbols()))

    wh.write_manifest(args, len(symbols), len(wh.completed_symbols()))
    print("\nDone.")
    print(f"CSV files: {wh.csv_dir}")
    print(f"Raw JSON:  {wh.raw_dir}")
    print(f"Manifest:  {wh.root / 'manifest.json'}")
    return out_root


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Finnhub US market fundamentals into a local Desktop data warehouse.")
    parser.add_argument("--api-key", help="Finnhub API key. Prefer FINNHUB_API_KEY environment variable instead.")
    parser.add_argument("--market", default=None, help="Discover symbols from Finnhub stock symbols endpoint, e.g. --market US")
    parser.add_argument("--symbols", nargs="*", help="Ticker symbols, e.g. --symbols AAPL MSFT NVDA")
    parser.add_argument("--universe-csv", help="CSV with a symbol or ticker column.")
    parser.add_argument("--years", type=int, default=10, help="Lookback years for filings/events. Default: 10")
    parser.add_argument("--sleep", type=float, default=1.1, help="Seconds to sleep between API calls. Default: 1.1")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds. Default: 30")
    parser.add_argument("--max-retries", type=int, default=3, help="Retry count for transient HTTP/API failures. Default: 3")
    parser.add_argument("--earnings-limit", type=int, default=80, help="Company earnings history limit. Default: 80")
    parser.add_argument("--output-dir", help="Optional output folder. Default: Desktop/finnhub_us_market_export_<timestamp>")
    parser.add_argument("--resume", action="store_true", help="Skip symbols already listed in completed_symbols.txt in the output folder.")
    parser.add_argument("--dry-run-universe", action="store_true", help="Only discover and save the symbol universe, then exit.")
    parser.add_argument("--max-symbols", type=int, help="Limit number of symbols for testing. Applied after market discovery.")
    parser.add_argument("--start-at-symbol", help="Skip symbols alphabetically before this symbol, useful for manual restarts.")
    parser.add_argument("--common-stocks-only", action="store_true", help="After discovery, keep only symbols whose security type appears to be common stock/equity.")
    parser.add_argument("--include-security-types", nargs="*", default=[], help="Optional exact security type filters after discovery, case-insensitive.")
    parser.add_argument("--exclude-symbol-regex", default=None, help="Optional regex to exclude symbols after discovery, e.g. '[-.]W$|[-.]U$' for warrants/units patterns.")
    parser.add_argument("--discovery-mic", help="Optional Finnhub stock/symbol MIC filter.")
    parser.add_argument("--discovery-currency", help="Optional Finnhub stock/symbol currency filter, e.g. USD.")
    parser.add_argument("--discovery-security-type", help="Optional Finnhub stock/symbol securityType parameter.")
    parser.add_argument("--filings-chunk-days", type=int, default=365, help="Days per filings call. Default: 365")
    parser.add_argument("--events-chunk-days", type=int, default=365, help="Days per full event-depth call. Default: 365")
    parser.add_argument("--event-depth", choices=["core", "full"], default="core", help="core = company earnings only. full = also earnings calendar and insider transaction chunks. Default: core")
    parser.add_argument("--include-as-reported", action="store_true", help="Also save /stock/financials-reported raw JSON.")
    parser.add_argument("--include-revenue-breakdown", action="store_true", help="Also save /stock/revenue-breakdown raw JSON if available.")
    parser.add_argument("--include-transcripts", action="store_true", help="Also save transcript metadata raw JSON if available.")
    parser.add_argument("--manifest-every", type=int, default=25, help="Refresh manifest after every N completed symbols. Default: 25")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop instead of continuing when a symbol-level exception occurs.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    run_export(parse_args())
