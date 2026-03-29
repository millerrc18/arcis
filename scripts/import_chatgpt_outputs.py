import os
import re
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def import_outputs(inputs_file, outputs_file, db_path="ai_research_desk.sqlite3"):
    # Parse recommendation IDs from inputs
    with open(inputs_file) as f:
        input_text = f.read()
    rec_ids = re.findall(r'Recommendation ID:\s*(\S+)', input_text)

    # Parse XML outputs
    with open(outputs_file) as f:
        output_text = f.read()
    # Split by the EXAMPLE header, ignoring the first empty split if it exists
    examples = [e.strip() for e in re.split(r'===\s*EXAMPLE\s*\d+.*===', output_text) if e.strip()]

    conn = sqlite3.connect(db_path)
    imported = 0

    for rec_id, output in zip(rec_ids, examples):
        # Validate XML format
        has_why = bool(re.search(r'<why_now>', output))
        has_analysis = bool(re.search(r'<analysis>', output))
        has_metadata = bool(re.search(r'<metadata>', output))

        if not (has_why and has_analysis and has_metadata):
            print(f"SKIP {rec_id}: missing XML tags")
            continue

        # Get the original trade outcome for metadata (NOT included in training)
        trade = conn.execute(
            "SELECT ticker, pnl_dollars FROM shadow_trades WHERE recommendation_id = ?",
            (rec_id,)
        ).fetchone()
        ticker, pnl = (trade[0], trade[1]) if trade else (None, 0)
        source = "chatgpt_blinded_win" if pnl > 0 else "chatgpt_blinded_loss"

        example_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()

        conn.execute("""
            INSERT INTO training_examples
            (example_id, created_at, source, ticker, recommendation_id,
             output_text, curriculum_stage)
            VALUES (?, ?, ?, ?, ?, ?, 'structure')
        """, (example_id, created_at, source, ticker, rec_id, output))
        imported += 1

    conn.commit()
    print(f"Imported {imported}/{len(rec_ids)} ChatGPT examples")
    print(f"Run 'python -m src.main validate-training-data' to verify format compliance")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", required=True)
    p.add_argument("--outputs", required=True)
    p.add_argument("--db", default="ai_research_desk.sqlite3")
    args = p.parse_args()
    import_outputs(args.inputs, args.outputs, args.db)
