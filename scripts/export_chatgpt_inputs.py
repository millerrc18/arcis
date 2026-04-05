"""Export feature inputs for closed trades to paste into ChatGPT for training data.

When to run:
    Ad-hoc when building training data via the ChatGPT-blinded pipeline.
    This is a manual bootstrap process used before the automated training
    collector was ready. Outputs a text file; each section is one prompt.

What it reads:
    - recommendations and shadow_trades tables (joined on recommendation_id)

What it writes:
    - chatgpt_batch.txt (or custom --output path) with prompts for ChatGPT

Prerequisites:
    - Database with closed shadow_trades linked to recommendations
    - After ChatGPT generates outputs, import them with import_chatgpt_outputs.py

Usage:
    python scripts/export_chatgpt_inputs.py --count 20
"""

import sqlite3
import random

def export_inputs(db_path="ai_research_desk.sqlite3", count=20, output="chatgpt_batch.txt"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get closed trades that DON'T already have training examples.
    # The NOT IN subquery prevents duplicate generation — once a trade
    # has a chatgpt-sourced example, it is excluded from future exports.
    rows = conn.execute("""
        SELECT r.*, st.pnl_dollars, st.exit_reason
        FROM recommendations r
        JOIN shadow_trades st ON r.recommendation_id = st.recommendation_id
        WHERE st.status = 'closed'
        AND r.recommendation_id NOT IN (
            SELECT recommendation_id FROM training_examples
            WHERE recommendation_id IS NOT NULL AND source LIKE '%chatgpt%'
        )
        ORDER BY RANDOM()
        LIMIT ?
    """, (count,)).fetchall()

    with open(output, 'w') as f:
        for i, row in enumerate(rows):
            f.write(f"=== EXAMPLE {i+1} / {len(rows)} ===\n")
            f.write(f"Recommendation ID: {row['recommendation_id']}\n")
            f.write(f"(DO NOT include this ID in ChatGPT — it's for your records)\n\n")

            # Use the enriched_prompt if available (best quality)
            if row['enriched_prompt']:
                f.write("Analyze the following pullback-in-strong-trend setup:\n\n")
                f.write(row['enriched_prompt'])
            else:
                f.write(f"Analyze the following pullback-in-strong-trend setup:\n\n")
                f.write(f"Ticker: {row['ticker']}\n")
                f.write(f"Date: {str(row['created_at'])[:10]}\n")
                price = row['price_at_recommendation'] if row['price_at_recommendation'] is not None else 'N/A'
                score = row['priority_score'] if row['priority_score'] is not None else 'N/A'
                f.write(f"Price: ${price}\n")
                f.write(f"Score: {score}\n")

            f.write("\n\n---\n\n")

    print(f"Exported {len(rows)} feature inputs to {output}")
    print(f"Paste each one into ChatGPT with the system prompt above.")
    print(f"Save ChatGPT's XML outputs, then import with import_chatgpt_outputs.py")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--output", default="chatgpt_batch.txt")
    p.add_argument("--db", default="ai_research_desk.sqlite3")
    args = p.parse_args()
    export_inputs(args.db, args.count, args.output)