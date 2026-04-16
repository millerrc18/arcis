"""Compile Arcis forensic report + charts + CSV appendix into a single PDF.

Iter 1: switch from base64 data URIs to Section(root=...) with relative paths
        (images now embed instead of rendering as literal text)
Iter 2: normalize Unicode to ASCII, simplify CSS to eliminate row-rendering
        glitches (markdown-pdf's pymupdf backend had black-overlay bugs)
Iter 3: switch to Chrome-headless print-to-pdf for full CSS compliance
        (markdown-pdf library was producing systematic layout artifacts).
        Build: markdown -> HTML -> Chrome print-to-PDF.
"""
import sys, io, os, re, subprocess, tempfile, base64
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
from pathlib import Path
import markdown

ROOT    = Path('C:/arcis/halcyon-lab/docs/research')
FIG     = ROOT / 'figures'
OUT     = Path('C:/Users/mille/Downloads/Arcis-Forensic-Analysis-2026-04-16.pdf')
CHROME  = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')

report_md = (ROOT / 'arcis-self-forensic-report.md').read_text(encoding='utf-8')

# Inline images as base64 so the HTML is self-contained and Chrome doesn't
# need file-system access during the headless render.
def img_b64(path: Path) -> str:
    with open(path, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()

for png in FIG.glob('*.png'):
    report_md = report_md.replace(f'figures/{png.name}', img_b64(png))

# ------- Appendix builder -------
def csv_to_md(path, title, drop_cols=None, narrow_cols=None):
    df = pd.read_csv(path)
    if drop_cols:
        df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors='ignore')
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(2)
    for c in df.columns:
        if df[c].dtype == object:
            max_len = narrow_cols.get(c, 40) if narrow_cols else 40
            df[c] = df[c].astype(str).str.slice(0, max_len)
    body = f"\n\n# {title}\n\nSource: `{path.name}` | Rows: {len(df)}\n\n"
    body += df.to_markdown(index=False)
    return body

cover_md = """# Arcis Self-Forensic Analysis

**Complete Compiled Report**

- **Date:** 2026-04-16
- **Classification:** FORENSIC — data-driven, not literature-driven
- **Dataset:** 84 closed trades (78 clean) from `C:/arcis/data/ai_research_desk.sqlite3`
- **Date range:** 2026-03-24 to 2026-04-13 (~22 trading days)

---

## Contents

1. **Main Forensic Report** — 10 sections with 4 embedded charts
2. **Appendix A** — Enriched Trade Dataset (78 rows)
3. **Appendix B** — Stale Trade Classifications (62 rows)
4. **Appendix C** — SPY Excess Returns (75 matched periods)
5. **Appendix D** — Kaminski-Lo Autocorrelations (76 rows)
6. **Appendix E** — Phase 1 Simulation (78 rows)

---

## Executive Verdict

**DIAGNOSTIC — DO NOT proceed with Phase 1 optimization until two data-quality issues are resolved.**

1. **Alpha vs SPY is statistically zero.** +0.039% mean excess, t=0.098, hit rate 56%.
   Per-trade Sharpe 3.38 is SPY beta, not alpha.
2. **Regime/sector instrumentation is broken.** NULL regime (67% of trades) outperforms every labeled regime.

Recommended action: instrument SPY-matched excess per trade and run 100 OOS trades with gate **excess-Sharpe > 0.5 at t > 2.0**.

<div class="page-break"></div>
"""

# Assemble full markdown document
full_md = cover_md + "\n\n" + report_md
full_md += csv_to_md(FIG / 'all-trades-enriched.csv',
                     'Appendix A — Enriched Trade Dataset',
                     drop_cols=['recommendation_id','trade_id','actual_entry_time',
                                'actual_exit_time','regime_at_entry','regime_at_exit',
                                'strategy_type','setup_type','direction','status',
                                'planned_allocation','ranking_at_entry','time_to_mfe_days',
                                'setup_confidence','entry_slippage_bps','timeout_days',
                                'vix_at_entry','vix_at_exit','time_to_target_days',
                                'drawdown_from_mfe','concurrent_positions','actual_shares'],
                     narrow_cols={'ticker':6,'exit_reason':22})
full_md += csv_to_md(FIG / 'stale-trades-classified.csv',
                     'Appendix B — 62 Stale Trades Classified',
                     narrow_cols={'ticker':6,'class':22})
full_md += csv_to_md(FIG / 'spy-excess-returns.csv',
                     'Appendix C — SPY Excess Returns (75 matched periods)',
                     narrow_cols={'ticker':6})
full_md += csv_to_md(FIG / 'autocorrelation.csv',
                     'Appendix D — Kaminski-Lo 5-day Pre-Entry Autocorrelations',
                     narrow_cols={'ticker':6})
full_md += csv_to_md(FIG / 'phase1-simulation.csv',
                     'Appendix E — Phase 1 Simulation per-Trade Results',
                     drop_cols=['exit_reason','vix','v30'],
                     narrow_cols={'ticker':6,'sector':12,'reason':18})

# Markdown -> HTML
md = markdown.Markdown(
    extensions=['tables','fenced_code','sane_lists','smarty','attr_list','toc'],
    extension_configs={'toc': {'toc_depth': 3}},
)
body_html = md.convert(full_md)

# Insert page-break divs before each Appendix h1 (after-the-fact, robust)
body_html = re.sub(
    r'(<h1[^>]*>Appendix [A-E])',
    r'<div class="page-break"></div>\1',
    body_html
)

CSS = """
@page {
    size: Letter;
    margin: 0.75in;
    @bottom-center { content: counter(page) " / " counter(pages); }
}
body {
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1f1f1f;
    max-width: 100%;
}
h1 {
    color: #0b1d3a;
    border-bottom: 3px solid #0b1d3a;
    padding-bottom: 8px;
    font-size: 22pt;
    margin-top: 0;
    margin-bottom: 18pt;
    page-break-after: avoid;
}
h2 {
    color: #16213e;
    margin-top: 22pt;
    margin-bottom: 8pt;
    font-size: 14pt;
    border-bottom: 1px solid #bbb;
    padding-bottom: 4px;
    page-break-after: avoid;
}
h3 {
    color: #0f3460;
    font-size: 12pt;
    margin-top: 16pt;
    margin-bottom: 6pt;
    page-break-after: avoid;
}
h4 { color: #333; font-size: 11pt; margin-top: 10pt; margin-bottom: 4pt; }
p  { margin: 7pt 0; }
strong { color: #0b1d3a; font-weight: 700; }
code {
    background: #f2f2f5;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: 'Cascadia Code','Consolas','Courier New',monospace;
    font-size: 9.5pt;
    color: #882f2f;
}
pre {
    background: #0e0e1e;
    color: #d4d4d4;
    padding: 10pt 12pt;
    border-radius: 4px;
    overflow-x: auto;
    font-family: 'Cascadia Code','Consolas',monospace;
    font-size: 9pt;
    line-height: 1.4;
    page-break-inside: avoid;
}
pre code { background: transparent; color: inherit; padding: 0; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 10pt 0;
    font-size: 9pt;
    page-break-inside: auto;
}
thead { display: table-header-group; }
tr { page-break-inside: avoid; page-break-after: auto; }
th, td {
    border: 1px solid #b0b0b0;
    padding: 5px 9px;
    text-align: left;
    vertical-align: top;
}
th {
    background: #0b1d3a;
    color: #fff;
    font-weight: 600;
    font-size: 9pt;
}
tr:nth-child(even) td { background: #f8f8fa; }
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 16pt auto;
    border: 1px solid #ccc;
    page-break-inside: avoid;
}
blockquote {
    border-left: 4px solid #0f3460;
    margin: 10pt 0;
    padding: 4pt 14pt;
    color: #444;
    font-style: italic;
    background: #f6f6fa;
}
hr { border: none; border-top: 1px solid #bbb; margin: 14pt 0; }
ul, ol { margin: 6pt 0 6pt 24pt; }
li { margin: 2pt 0; }
li p { margin: 2pt 0; }
.page-break { page-break-before: always; height: 0; }
"""

html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Arcis Self-Forensic Analysis 2026-04-16</title>
<style>{CSS}</style>
</head>
<body>
{body_html}
</body>
</html>
"""

# Write temp HTML, invoke Chrome headless
with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html', encoding='utf-8') as tmp:
    tmp.write(html_doc)
    html_path = Path(tmp.name)
print(f"HTML: {html_path} ({html_path.stat().st_size//1024} KB)")

OUT.parent.mkdir(parents=True, exist_ok=True)
cmd = [
    str(CHROME),
    '--headless=new',
    '--disable-gpu',
    '--no-pdf-header-footer',
    '--run-all-compositor-stages-before-draw',
    '--virtual-time-budget=20000',
    f'--print-to-pdf={str(OUT)}',
    html_path.as_uri(),
]
print("Running Chrome headless...")
res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
if res.returncode != 0:
    print("STDERR:", res.stderr[-800:])
    raise SystemExit(res.returncode)

size_mb = OUT.stat().st_size / 1024 / 1024
print(f"\nPDF saved: {OUT}")
print(f"Size: {size_mb:.2f} MB ({OUT.stat().st_size} bytes)")

# Cleanup
try:
    html_path.unlink()
except Exception:
    pass
