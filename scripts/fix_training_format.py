"""Convert all training examples to standardized XML format.

Handles two source formats:
  Format A (XML): <why_now>...</why_now><analysis>...</analysis><metadata>...</metadata>
  Format B (plain text): WHY NOW:\n...\nDEEPER ANALYSIS:\n...\nCONVICTION: N

Both get normalized to clean XML output matching what the inference parser expects.

Usage:
    python scripts/fix_training_format.py
    python scripts/validate_training_format.py   # verify 100% pass after
"""

import re
import sqlite3
import sys


def convert_plain_to_xml(text: str) -> str | None:
    """Convert plain-text WHY NOW / DEEPER ANALYSIS format to XML."""

    # Strip markdown title lines (# PRE-TRADE ANALYSIS: ...)
    text = re.sub(r'^#+\s*[^\n]*\n+', '', text)
    # Strip markdown section headers (## WHY NOW:)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)

    upper = text.upper()

    # ── Locate WHY NOW section ──────────────────────────────────
    wn_markers = ["WHY NOW:", "WHY NOW :", "WHY NOW\n"]
    wn_start = -1
    wn_marker_len = 0
    for m in wn_markers:
        idx = upper.find(m)
        if idx != -1:
            wn_start = idx + len(m)
            wn_marker_len = len(m)
            break
    if wn_start == -1:
        return None  # Can't find WHY NOW

    # ── Locate DEEPER ANALYSIS / ANALYSIS section ───────────────
    analysis_markers = [
        "DEEPER ANALYSIS:", "DEEPER ANALYSIS :",
        "ANALYSIS:", "ANALYSIS :",
        "DETAILED ANALYSIS:", "TRADE ANALYSIS:",
    ]
    an_start = -1
    an_label_end = -1
    for m in analysis_markers:
        idx = upper.find(m, wn_start)
        if idx != -1:
            an_start = idx
            an_label_end = idx + len(m)
            break
    if an_start == -1:
        return None  # Can't find analysis section

    # ── Extract WHY NOW text ────────────────────────────────────
    why_now = text[wn_start:an_start].strip()

    # ── Locate CONVICTION / METADATA ────────────────────────────
    # Could be "CONVICTION: N", "Conviction: N/10", or inside a metadata block
    conv_markers = ["CONVICTION:", "CONVICTION :", "KEY RISK:"]
    conv_start = -1
    for m in conv_markers:
        idx = upper.find(m, an_label_end)
        if idx != -1:
            if conv_start == -1 or idx < conv_start:
                conv_start = idx
            break

    if conv_start == -1:
        # No conviction marker — analysis runs to end
        analysis = text[an_label_end:].strip()
        conviction = 6  # default
        key_risk = ""
        direction = "LONG"
        time_horizon = "5-15 trading days"
    else:
        analysis = text[an_label_end:conv_start].strip()

        # Parse conviction
        remaining = text[conv_start:]
        conv_match = re.search(r'CONVICTION[:\s]*(\d+\.?\d*)', remaining, re.IGNORECASE)
        conviction = round(float(conv_match.group(1))) if conv_match else 6
        conviction = max(1, min(10, conviction))

        # Parse key risk
        risk_match = re.search(r'KEY RISK[:\s]*([^\n]+)', remaining, re.IGNORECASE)
        key_risk = risk_match.group(1).strip() if risk_match else ""

        # Parse direction
        dir_match = re.search(r'DIRECTION[:\s]*([^\n]+)', remaining, re.IGNORECASE)
        direction = dir_match.group(1).strip() if dir_match else "LONG"

        # Parse time horizon
        th_match = re.search(r'TIME HORIZON[:\s]*([^\n]+)', remaining, re.IGNORECASE)
        time_horizon = th_match.group(1).strip() if th_match else "5-15 trading days"

    # ── Clean up extracted text ─────────────────────────────────
    # Remove bold markers
    why_now = why_now.replace('**', '')
    analysis = analysis.replace('**', '')

    # Remove any remaining markdown headers inside analysis
    analysis = re.sub(r'^#+\s*', '', analysis, flags=re.MULTILINE)

    if not why_now or not analysis:
        return None

    # ── Build XML output ────────────────────────────────────────
    xml = f"""<why_now>
{why_now}
</why_now>

<analysis>
{analysis}
</analysis>

<metadata>
Conviction: {conviction}
Direction: {direction}
Time Horizon: {time_horizon}
Key Risk: {key_risk if key_risk else 'Market regime shift invalidating the technical setup'}
</metadata>"""

    return xml.strip()


def clean_xml_format(text: str) -> str:
    """Clean an already-XML example (strip markdown, fix conviction)."""
    # Strip text before first XML tag
    match = re.search(r'<why_now>', text, re.IGNORECASE)
    if match:
        text = text[match.start():]

    # Strip text after </metadata>
    match = re.search(r'</metadata>', text, re.IGNORECASE)
    if match:
        text = text[:match.end()]

    # Strip bold markers
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)

    # Fix conviction in metadata
    meta_match = re.search(r'<metadata>(.*?)</metadata>', text, re.DOTALL | re.IGNORECASE)
    if meta_match:
        meta = meta_match.group(1)
        conv_match = re.search(r'Conviction:\s*(\d+\.?\d*)', meta)
        if conv_match:
            conv_val = max(1, min(10, round(float(conv_match.group(1)))))
            meta = re.sub(r'Conviction:\s*\d+\.?\d*(?:/\d+)?', f'Conviction: {conv_val}', meta)
        text = text[:meta_match.start()] + '<metadata>' + meta + '</metadata>'

    return text.strip()


def is_xml_format(text: str) -> bool:
    """Check if text already uses XML tags."""
    return bool(re.search(r'<why_now>', text, re.IGNORECASE))


def main():
    db_path = "ai_research_desk.sqlite3"
    conn = sqlite3.connect(db_path)
    rows = conn.execute('SELECT example_id, output_text FROM training_examples').fetchall()

    converted = 0
    cleaned = 0
    failed = 0
    failed_ids = []

    for eid, output in rows:
        if is_xml_format(output):
            # Already XML — just clean it
            new_output = clean_xml_format(output)
            if new_output != output:
                conn.execute('UPDATE training_examples SET output_text = ? WHERE example_id = ?',
                             (new_output, eid))
                cleaned += 1
        else:
            # Plain text — convert to XML
            new_output = convert_plain_to_xml(output)
            if new_output:
                conn.execute('UPDATE training_examples SET output_text = ? WHERE example_id = ?',
                             (new_output, eid))
                converted += 1
            else:
                failed += 1
                failed_ids.append(eid)

    conn.commit()
    conn.close()

    total = len(rows)
    print(f"Total examples: {total}")
    print(f"  Converted plain→XML: {converted}")
    print(f"  Cleaned existing XML: {cleaned}")
    print(f"  Already clean: {total - converted - cleaned - failed}")
    print(f"  Failed to convert: {failed}")
    if failed_ids:
        print(f"\n  Failed IDs (first 10): {failed_ids[:10]}")
        print("  These may need manual review or deletion.")


if __name__ == "__main__":
    main()
