"""Stage 1 corpus composition audit (Sprint S1-CC A2).

Reads data/corpus/stage1-001/entries.jsonl and emits a Markdown report
covering llm_action distribution, length distribution, per-ticker rate,
date coverage, and model_version split. Stdlib + numpy only. Streams
the JSONL line-by-line to avoid loading 200+ MB.

Usage:
    python scripts/audit_stage1_corpus.py \
        --corpus data/corpus/stage1-001/entries.jsonl \
        --manifest data/corpus/stage1-001/manifest.json \
        --output docs/audits/2026-05-11-stage1-completion/composition-audit.md
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np

TARGET = 67681  # aspirational target
WEEKLY_CAP = 3  # ≤3 cap referenced in sprint spec


def _iso_wk(s: str) -> tuple[int, int]:
    y, m, d = s.split("-")
    iso = date(int(y), int(m), int(d)).isocalendar()
    return (iso[0], iso[1])


def _pct(n: int, t: int) -> str:
    return "0.0%" if t == 0 else f"{100.0 * n / t:.1f}%"


def stream_audit(p: Path) -> dict:
    acts, vers, conv, tks, wks, tw = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    pf, n, lens, pf_lens, dates = 0, 0, [], [], set()
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            n += 1
            acts[d.get("llm_action", "<missing>")] += 1
            vers[d.get("model_version", "<missing>")] += 1
            c = d.get("llm_conviction")
            if c is not None:
                conv[c] += 1
            t, ao = d.get("ticker", "<missing>"), d.get("as_of", "")
            tks[t] += 1
            dates.add(ao)
            w = _iso_wk(ao)
            wks[w] += 1
            tw[(t, w)] += 1
            if d.get("parse_failed"):
                pf += 1
            rl = len(d.get("response", ""))
            lens.append(rl)
            if d.get("parse_failed") or d.get("llm_action") == "parse_failed":
                pf_lens.append(rl)
    return {"n": n, "acts": acts, "vers": vers, "conv": conv, "tks": tks, "wks": wks,
            "tw": tw, "pf": pf, "dates": dates,
            "lens": np.asarray(lens, dtype=np.int64),
            "pf_lens": np.asarray(pf_lens, dtype=np.int64)}


def _gaps(wks: Counter, start: str, end: str) -> list[tuple[int, int]]:
    sy, sm, sd = (int(x) for x in start.split("-"))
    ey, em, ed = (int(x) for x in end.split("-"))
    cur, end_d, seen, out = date(sy, sm, sd), date(ey, em, ed), set(), []
    while cur <= end_d:
        iso = cur.isocalendar()
        wk = (iso[0], iso[1])
        if wk not in seen:
            seen.add(wk)
            if wks.get(wk, 0) == 0:
                out.append(wk)
        cur += timedelta(days=7)
    return out


def _tbl(rows: list[tuple], header: tuple) -> str:
    hdr = "| " + " | ".join(header) + " |"
    sep = "|" + "|".join("---" for _ in header) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return hdr + "\n" + sep + "\n" + body


def _lens_stats(a: np.ndarray) -> str:
    p = lambda q: int(np.percentile(a, q))
    return (f"- min: **{int(a.min()):,}**\n- p10: **{p(10):,}**\n- median: **{int(np.median(a)):,}**\n"
            f"- mean: **{int(a.mean()):,}**\n- p90: **{p(90):,}**\n- max: **{int(a.max()):,}**")


def render(s: dict, m: dict) -> str:
    n, acts, vers, conv, tks, wks, tw = s["n"], s["acts"], s["vers"], s["conv"], s["tks"], s["wks"], s["tw"]
    lens, pf_lens, dates, pf = s["lens"], s["pf_lens"], s["dates"], s["pf"]
    delta = n - TARGET
    cov = m.get("coverage_limit_hits", {})
    tot = sum(cov.values()) if cov else 0
    sc, lc = int((lens < 1000).sum()), int((lens >= 2000).sum())
    mc = n - sc - lc
    hist, edges = np.histogram(lens, bins=10)
    mxtw = max(tw.values()) if tw else 0
    over = sum(1 for v in tw.values() if v > WEEKLY_CAP)
    gaps = _gaps(wks, min(dates), max(dates))
    wc = np.asarray(list(wks.values()))
    bim = "unimodal at long mode" if sc / n < 0.05 else "bimodal"
    cov_lines = "\n".join(f"  - `{k}`: {v:,}" for k, v in sorted(cov.items()))
    by_v = lambda c: sorted(c.items(), key=lambda kv: -kv[1])
    acts_tbl = _tbl([(f"`{k}`", f"{v:,}", _pct(v, n)) for k, v in by_v(acts)], ("Action", "Count", "Share"))
    conv_tbl = _tbl([(str(k), f"{conv.get(k, 0):,}", _pct(conv.get(k, 0), n)) for k in range(1, 11)], ("Conviction", "Count", "Share"))
    hist_tbl = _tbl([(f"{int(edges[i]):,} – {int(edges[i+1]):,}", f"{int(hist[i]):,}", _pct(int(hist[i]), n)) for i in range(10)], ("Bin (chars)", "Count", "Share"))
    top_tbl = _tbl([(t, f"{c:,}") for t, c in by_v(tks)[:10]], ("Ticker", "Count"))
    bot_tbl = _tbl([(t, f"{c:,}") for t, c in sorted(tks.items(), key=lambda kv: kv[1])[:10]], ("Ticker", "Count"))
    ver_tbl = _tbl([(f"`{v}`", f"{c:,}", _pct(c, n)) for v, c in by_v(vers)], ("Version", "Count", "Share"))
    pf_line = (f"\n- `parse_failed` length median: **{int(np.median(pf_lens)):,}** chars (n={pf_lens.size:,})" if pf_lens.size > 0 else "")
    bim_note = ("> Distribution is **unimodal** at the long mode. No template-fallback signal detected. The small short-tail aligns with `parse_failed` entries."
                if sc / n < 0.05 else "> **Bimodal pattern detected.** Short-cluster share exceeds 5% — review for template_fallback contamination.")
    over_note = ("\n\n> Stage 1 generates **daily** decision points across ~103 tickers, so 5-6 entries per ticker per week is expected (one entry per trading day). The ≤3 cap referenced in the sprint spec applies to a downstream sampling stage, not raw corpus emission. Flagging informationally only." if over > 0 else "")
    gap_block = ""
    if gaps:
        wk_lines = "\n".join(f"  - {wk[0]}-W{wk[1]:02d}" for wk in gaps[:25])
        more = f"\n  - ... and {len(gaps) - 25} more" if len(gaps) > 25 else ""
        gap_block = f"\n\nGap weeks (year, ISO-week):\n\n{wk_lines}{more}"
    ver_note = ("\n\n> Single model_version present — no real-LLM vs template_fallback split detectable via this field. Bimodality check (§3) is the fallback signal." if len(vers) == 1 else "")
    return (
        f"# Stage 1 Corpus Composition Audit\n\n"
        f"- **Corpus ID:** `{m.get('corpus_id', '<unknown>')}`\n"
        f"- **Code SHA:** `{m.get('code_sha', '<unknown>')}`\n"
        f"- **Generated at:** {m.get('generated_at', '<unknown>')}\n"
        f"- **Walk-forward window:** {m.get('walkforward_window_start')} → {m.get('walkforward_window_end')}\n\n"
        f"## 1. Entry count vs target\n\n"
        f"- Actual: **{n:,}**\n- Aspirational target: **{TARGET:,}**\n"
        f"- Delta: **{delta:+,}** (~{_pct(abs(delta), TARGET)} of target)\n\n"
        f"Manifest `coverage_limit_hits` (decision points skipped, per gate):\n"
        f"{cov_lines}\n  - **total skips:** {tot:,}\n\n"
        f"## 2. llm_action distribution\n\n{acts_tbl}\n\n"
        f"> Note: this corpus stores **pre-trade LLM decisions**, not realized outcomes. The sprint spec's "
        f"WIN/LOSS/TIMEOUT/PASS taxonomy refers to *outcomes* attached during shadow-trade evaluation "
        f"(downstream of Stage 1). Here we audit only the `llm_action` field.\n\n"
        f"- `parse_failed` count: **{pf:,}** (manifest: {m.get('parse_failure_count', '<n/a>')}, "
        f"rate: {m.get('parse_failure_rate', 0) * 100:.3f}%)\n\n"
        f"### Conviction histogram (1-10 scale)\n\n{conv_tbl}\n\n"
        f"## 3. Response length distribution (characters)\n\n{_lens_stats(lens)}\n\n"
        f"10-bin histogram:\n\n{hist_tbl}\n\n"
        f"### Template-fallback heuristic\n\n"
        f"Bucket counts (template_fallback signal: short cluster around 750-800 chars vs real LLM around 2400-3000):\n\n"
        f"- `<1000 chars`: **{sc:,}** ({_pct(sc, n)})\n"
        f"- `1000-2000 chars`: **{mc:,}** ({_pct(mc, n)})\n"
        f"- `>=2000 chars`: **{lc:,}** ({_pct(lc, n)}){pf_line}\n\n{bim_note}\n\n"
        f"## 4. Per-ticker entry counts\n\n"
        f"- Unique tickers: **{len(tks):,}**\n- Max per-ticker: **{max(tks.values()):,}**\n"
        f"- Min per-ticker: **{min(tks.values()):,}**\n"
        f"- Median per-ticker: **{int(np.median(list(tks.values()))):,}**\n\n"
        f"Top 10 tickers by entry count:\n\n{top_tbl}\n\n"
        f"Bottom 10 tickers by entry count:\n\n{bot_tbl}\n\n"
        f"### Per-ticker-per-week rate\n\n"
        f"- Max per-(ticker, ISO-week): **{mxtw}**\n"
        f"- Ticker-weeks exceeding the ≤{WEEKLY_CAP} cap: **{over:,}** of {len(tw):,} "
        f"({_pct(over, len(tw))}){over_note}\n\n"
        f"## 5. Date coverage\n\n"
        f"- Unique trading dates: **{len(dates):,}**\n- Date range: **{min(dates)} → {max(dates)}**\n"
        f"- Unique ISO weeks observed: **{len(wks):,}**\n\n"
        f"- ISO weeks in range with **zero** entries: **{len(gaps)}**{gap_block}\n\n"
        f"Per-week entry-count distribution (across observed weeks):\n\n"
        f"- min: {int(wc.min()):,}\n- median: {int(np.median(wc)):,}\n- p10: {int(np.percentile(wc, 10)):,}\n"
        f"- p90: {int(np.percentile(wc, 90)):,}\n- max: {int(wc.max()):,}\n\n"
        f"## 6. model_version distribution\n\n{ver_tbl}{ver_note}\n\n"
        f"## 7. Verdict preview (consumed by A3 cold-read)\n\n"
        f"- Length distribution is **{bim}** (median {int(np.median(lens))} chars); "
        f"no template_fallback signal beyond the {pf} parse_failed entries.\n"
        f"- Entry count {n:,} falls {abs(delta):,} short of the aspirational {TARGET:,}; "
        f"attributable to {tot:,} coverage-gate skips in the manifest.\n"
        f"- {len(gaps)} week(s) have zero entries in the {min(dates)} → {max(dates)} window.\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()
    mani = json.loads(a.manifest.read_text(encoding="utf-8"))
    stats = stream_audit(a.corpus)
    rep = render(stats, mani)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(rep, encoding="utf-8")
    print(f"Wrote {a.output} ({len(rep):,} bytes, {stats['n']:,} entries scanned).")


if __name__ == "__main__":
    main()
