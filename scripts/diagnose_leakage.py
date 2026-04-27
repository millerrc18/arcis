"""Leakage diagnostic — investigates TF-IDF accuracy above 0.55 threshold.

When to run:
    Ad-hoc when training quality metrics look suspicious, or after importing
    new training examples. A TF-IDF classifier that can predict outcomes
    from input text above 55% accuracy means outcomes are leaking into inputs.

What it reads:
    - training_examples table (input_text, output_text, outcome_type, ticker, source)
    - src/training/leakage_detector.py if available

What it writes:
    - Nothing — stdout-only diagnostic report. Paste output to Claude for analysis.

Prerequisites:
    - Database at one of the candidate paths
    - scikit-learn installed for the TF-IDF test (optional — degrades gracefully)

Run from repo root: python scripts/diagnose_leakage.py
"""

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.utils.db import connect_db  # noqa: E402

DB_CANDIDATES = ["ai_research_desk.sqlite3", "data/halcyon.db", "data/arcis.db"]
REPO_ROOT = Path(__file__).resolve().parent.parent

DB_PATH = None
for candidate in DB_CANDIDATES:
    p = REPO_ROOT / candidate
    if p.exists() and p.stat().st_size > 1000:
        DB_PATH = str(p)
        break

if not DB_PATH:
    print("ERROR: No database found")
    sys.exit(1)

conn = connect_db(DB_PATH)

print("=" * 60)
print("  LEAKAGE DIAGNOSTIC")
print("=" * 60)
print(f"Database: {DB_PATH}")
print()

# === 1. Check what columns exist in training_examples ===
print("[1/7] TRAINING EXAMPLES SCHEMA")
print("-" * 60)
columns = [r[1] for r in conn.execute("PRAGMA table_info(training_examples)").fetchall()]
print(f"Columns: {', '.join(columns)}")
print()

# === 2. Sample training examples — look for obvious leakage ===
print("[2/7] SAMPLE TRAINING EXAMPLES (last 10)")
print("-" * 60)
try:
    # Get available text columns
    text_cols = [c for c in columns if c in ['commentary', 'input_text', 'output_text', 'prompt', 'response', 'content', 'text']]
    if not text_cols:
        # Just show all columns for a few rows
        rows = conn.execute("SELECT * FROM training_examples ORDER BY created_at DESC LIMIT 5").fetchall()
        for r in rows:
            print(dict(r))
            print()
    else:
        col = text_cols[0]
        rows = conn.execute(f"SELECT example_id, created_at, {col} FROM training_examples ORDER BY created_at DESC LIMIT 5").fetchall()
        for r in rows:
            text = r[col] or ""
            print(f"ID: {r['example_id'][:12]}  Created: {str(r['created_at'])[:10]}")
            print(f"Text (first 200 chars): {text[:200]}")
            print()
except Exception as e:
    print(f"  Error: {e}")
print()

# === 3. Check for outcome/result words in training text ===
print("[3/7] OUTCOME LEAKAGE — searching for forbidden words in training text")
print("-" * 60)
# Words that should NEVER appear in training inputs because they reveal
# the trade outcome. If the model can "cheat" by seeing these, the fine-tuned
# model learns to parrot outcomes instead of analyzing setups.
FORBIDDEN_WORDS = [
    "profit", "loss", "gained", "lost", "winner", "loser",
    "hit target", "stopped out", "target_hit", "stop_hit",
    "returned", "pnl", "p&l", "made money", "lost money",
    "+$", "-$", "successful", "unsuccessful", "worked out",
    "outcome", "result was", "trade resulted", "ended up",
    "in hindsight", "looking back", "retrospect",
]
try:
    text_cols = [c for c in columns if c in ['commentary', 'input_text', 'output_text', 'prompt', 'response', 'content', 'text']]
    if text_cols:
        col = text_cols[0]
        rows = conn.execute(f"SELECT example_id, {col} FROM training_examples WHERE {col} IS NOT NULL").fetchall()
        total = len(rows)
        leaky_count = 0
        leaky_examples = []
        for r in rows:
            text = (r[col] or "").lower()
            found = [w for w in FORBIDDEN_WORDS if w in text]
            if found:
                leaky_count += 1
                if len(leaky_examples) < 5:
                    leaky_examples.append((r['example_id'][:12], found))
        
        print(f"Total examples with text: {total}")
        print(f"Examples with outcome words: {leaky_count} ({leaky_count/total*100:.1f}%)")
        if leaky_examples:
            print(f"\nExamples of leakage:")
            for eid, words in leaky_examples:
                print(f"  {eid}: {words}")
    else:
        print("  No text columns found to check")
except Exception as e:
    print(f"  Error: {e}")
print()

# === 4. Check ticker concentration ===
print("[4/7] TICKER CONCENTRATION")
print("-" * 60)
try:
    if 'ticker' in columns:
        tickers = conn.execute(
            "SELECT ticker, COUNT(*) as cnt FROM training_examples "
            "WHERE ticker IS NOT NULL GROUP BY ticker ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM training_examples WHERE ticker IS NOT NULL").fetchone()[0]
        print(f"Total with ticker: {total}")
        print(f"Unique tickers: {len(tickers)}")
        if tickers:
            top5_pct = sum(r['cnt'] for r in tickers[:5]) / total * 100 if total > 0 else 0
            print(f"Top 5 concentration: {top5_pct:.1f}%")
            print(f"\nTop 20 tickers:")
            for r in tickers:
                print(f"  {r['ticker']:6s} {r['cnt']:4d} ({r['cnt']/total*100:.1f}%)")
    else:
        print("  No ticker column")
except Exception as e:
    print(f"  Error: {e}")
print()

# === 5. Check source distribution ===
print("[5/7] SOURCE DISTRIBUTION")
print("-" * 60)
try:
    if 'source' in columns:
        sources = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM training_examples "
            "GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        for r in sources:
            print(f"  {r['source'] or 'NULL':30s} {r['cnt']:5d}")
    else:
        print("  No source column")
except Exception as e:
    print(f"  Error: {e}")
print()

# === 6. Check for duplicate or near-duplicate examples ===
print("[6/7] DUPLICATE DETECTION")
print("-" * 60)
try:
    text_cols = [c for c in columns if c in ['commentary', 'input_text', 'output_text', 'prompt', 'response', 'content', 'text']]
    if text_cols:
        col = text_cols[0]
        # Check exact duplicates
        dupes = conn.execute(f"""
            SELECT {col}, COUNT(*) as cnt 
            FROM training_examples 
            WHERE {col} IS NOT NULL 
            GROUP BY {col} 
            HAVING cnt > 1 
            ORDER BY cnt DESC 
            LIMIT 10
        """).fetchall()
        
        if dupes:
            total_dupes = sum(r['cnt'] - 1 for r in dupes)
            print(f"Exact duplicate texts: {total_dupes} redundant examples")
            for r in dupes:
                text = r[col][:80] if r[col] else "?"
                print(f"  {r['cnt']}x: {text}...")
        else:
            print("No exact duplicates found")
    else:
        print("  No text columns to check")
except Exception as e:
    print(f"  Error: {e}")
print()

# === 7. Run the actual TF-IDF leakage test ===
print("[7/7] TF-IDF LEAKAGE TEST (reproducing the 0.613 result)")
print("-" * 60)
try:
    sys.path.insert(0, str(REPO_ROOT))
    from src.training.leakage_detector import check_outcome_leakage
    result = check_outcome_leakage(DB_PATH)
    print(json.dumps(result, indent=2, default=str))
except ImportError:
    print("  Could not import leakage_detector — running manual TF-IDF test")
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score
        import numpy as np
        
        text_cols = [c for c in columns if c in ['commentary', 'input_text', 'output_text', 'prompt', 'response', 'content', 'text']]
        if not text_cols:
            print("  No text columns for TF-IDF test")
        else:
            col = text_cols[0]
            # Need an outcome column
            outcome_cols = [c for c in columns if c in ['outcome', 'outcome_type', 'label', 'win', 'result']]
            if not outcome_cols:
                print("  No outcome column found for TF-IDF classification test")
                print(f"  Available columns: {columns}")
            else:
                oc = outcome_cols[0]
                rows = conn.execute(f"SELECT {col}, {oc} FROM training_examples WHERE {col} IS NOT NULL AND {oc} IS NOT NULL").fetchall()
                texts = [r[col] for r in rows]
                labels = [r[oc] for r in rows]
                
                if len(set(labels)) < 2:
                    print(f"  Only one label class: {set(labels)} — can't run classification test")
                else:
                    vec = TfidfVectorizer(max_features=500, stop_words='english')
                    X = vec.fit_transform(texts)
                    y = np.array([1 if l in ('WIN', 'win', 'profit', 'good') else 0 for l in labels])
                    
                    scores = cross_val_score(LogisticRegression(max_iter=1000), X, y, cv=5, scoring='accuracy')
                    print(f"  TF-IDF accuracy: {scores.mean():.3f} (+/- {scores.std():.3f})")
                    print(f"  Threshold: 0.55 (above = leaking)")
                    print(f"  Status: {'⚠️ LEAKING' if scores.mean() > 0.55 else '✅ OK'}")
                    
                    # Show most predictive features
                    lr = LogisticRegression(max_iter=1000).fit(X, y)
                    feature_names = vec.get_feature_names_out()
                    top_positive = sorted(zip(feature_names, lr.coef_[0]), key=lambda x: x[1], reverse=True)[:10]
                    top_negative = sorted(zip(feature_names, lr.coef_[0]), key=lambda x: x[1])[:10]
                    
                    print(f"\n  Most predictive of WIN:")
                    for word, coef in top_positive:
                        print(f"    {word:20s} {coef:+.3f}")
                    print(f"\n  Most predictive of LOSS:")
                    for word, coef in top_negative:
                        print(f"    {word:20s} {coef:+.3f}")
    except ImportError:
        print("  sklearn not installed — can't run TF-IDF test")
        print("  Install with: pip install scikit-learn")
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()

print()

# === 8. Embedding-based semantic leakage detection ===
print("=" * 60)
print("  Section 8: Embedding-Based Semantic Leakage Detection")
print("=" * 60)
try:
    from src.training.leakage_detector import check_embedding_leakage
    result = check_embedding_leakage(DB_PATH)
    if "error" in result:
        print(f"  Skipped: {result['error']}")
    else:
        print(f"  Balanced accuracy: {result['balanced_accuracy']:.4f}")
        print(f"  Semantic leaking: {'YES — INVESTIGATE' if result['leaking'] else 'No'}")
        print(f"  Examples analyzed: {result['n_examples']}")
        print(f"  CV scores: {result.get('cv_scores', [])}")
        print(f"  Processing time: {result.get('processing_time_seconds', 0):.1f}s")
except Exception as e:
    print(f"  Error: {e}")
    import traceback
    traceback.print_exc()
print()

conn.close()
print("=" * 60)
print("  DIAGNOSTIC COMPLETE — paste to Claude for analysis")
print("=" * 60)
input("\nPress Enter to exit...")
