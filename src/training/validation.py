"""Training dataset validation and quality checks."""

import logging
import math
import sqlite3
from collections import Counter

from src.training.versioning import init_training_tables

logger = logging.getLogger(__name__)


def validate_training_dataset(db_path: str = "ai_research_desk.sqlite3") -> dict:
    """Run automated quality checks on the entire training dataset.

    Checks: format compliance (WHY NOW + DEEPER ANALYSIS present),
    diversity score (Shannon entropy over tickers), win/loss balance (50-65% wins),
    sector coverage, date range, duplicate detection (exact + near-duplicate via word overlap),
    output length statistics.

    Returns dict with all check results plus overall_health and recommendations.
    """
    init_training_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT example_id, ticker, input_text, output_text, created_at, source, "
            "quality_score_auto, difficulty, curriculum_stage "
            "FROM training_examples ORDER BY created_at ASC"
        ).fetchall()

    if not rows:
        return {
            "total_examples": 0,
            "overall_health": "empty",
            "recommendations": ["No training examples found. Run backfill or bootstrap first."],
        }

    examples = [dict(r) for r in rows]
    total = len(examples)

    # 1. Format compliance (XML or plain text)
    format_xml = 0
    format_plain = 0
    for ex in examples:
        output = ex.get("output_text") or ""
        if "<why_now>" in output and "<analysis>" in output:
            format_xml += 1
        elif "WHY NOW" in output.upper() and "DEEPER ANALYSIS" in output.upper():
            format_plain += 1
    format_pass = format_xml + format_plain
    format_compliance = format_pass / total if total > 0 else 0

    # 2. Diversity — Shannon entropy over tickers
    ticker_counts = Counter(ex.get("ticker") or "unknown" for ex in examples)
    tickers_represented = len(ticker_counts)
    diversity_score = _shannon_entropy(ticker_counts, total)

    # 3. Win/loss balance
    wins = sum(1 for ex in examples
               if any(w in (ex.get("input_text") or "")
                      for w in ("clean_win", "target_1_hit", "target_2_hit")))
    losses = sum(1 for ex in examples
                 if any(w in (ex.get("input_text") or "")
                        for w in ("clean_loss", "stop_hit")))
    win_pct = wins / (wins + losses) if (wins + losses) > 0 else 0
    balance_ok = 0.40 <= win_pct <= 0.65

    # 4. Sector coverage
    sectors = set()
    for ex in examples:
        input_text = ex.get("input_text") or ""
        import re
        match = re.search(r'Sector:\s*([^\n|]+)', input_text)
        if match:
            sectors.add(match.group(1).strip())

    # 5. Date range
    dates = [ex["created_at"][:10] for ex in examples if ex.get("created_at")]
    date_range = {"start": dates[0] if dates else None, "end": dates[-1] if dates else None}

    # 6. Duplicate detection
    exact_dupes = _find_exact_duplicates(examples)
    near_dupes = _find_near_duplicates(examples)

    # 7. Output length statistics
    lengths = [len((ex.get("output_text") or "").split()) for ex in examples]
    avg_length = sum(lengths) / len(lengths) if lengths else 0
    min_length = min(lengths) if lengths else 0
    max_length = max(lengths) if lengths else 0

    # 8. Source breakdown
    source_counts = Counter(ex.get("source") or "unknown" for ex in examples)

    # 9. Quality score stats
    quality_scores = [ex["quality_score_auto"] for ex in examples if ex.get("quality_score_auto")]
    avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else None

    # 10. Curriculum stage distribution
    stage_counts = Counter(ex.get("curriculum_stage") or "untagged" for ex in examples)

    # Overall health assessment
    issues = []
    if format_compliance < 0.90:
        issues.append(f"Low format compliance: {format_compliance:.0%} (target: 90%+)")
    if not balance_ok:
        issues.append(f"Win/loss imbalance: {win_pct:.0%} wins (target: 40-65%)")
    if tickers_represented < 20:
        issues.append(f"Low ticker diversity: {tickers_represented} tickers (target: 20+)")
    if exact_dupes:
        issues.append(f"{len(exact_dupes)} exact duplicate pairs found")
    if near_dupes:
        issues.append(f"{len(near_dupes)} near-duplicate pairs found")
    if total < 100:
        issues.append(f"Small dataset: {total} examples (target: 100+)")

    if not issues:
        overall_health = "good"
    elif len(issues) <= 2:
        overall_health = "fair"
    else:
        overall_health = "needs_attention"

    recommendations = []
    if total < 200:
        recommendations.append("Run more backfill to increase dataset size")
    if not balance_ok and win_pct > 0.65:
        recommendations.append("Add more losing trade examples for balance")
    if format_compliance < 0.90:
        recommendations.append("Re-generate non-compliant examples")
    if exact_dupes:
        recommendations.append("Remove exact duplicate examples")

    return {
        "total_examples": total,
        "format_compliance": round(format_compliance, 3),
        "format_breakdown": {"xml": format_xml, "plain_text": format_plain},
        "tickers_represented": tickers_represented,
        "diversity_score": round(diversity_score, 3),
        "wins": wins,
        "losses": losses,
        "win_pct": round(win_pct, 3),
        "balance_ok": balance_ok,
        "sectors_covered": len(sectors),
        "sector_list": sorted(sectors),
        "date_range": date_range,
        "exact_duplicates": len(exact_dupes),
        "near_duplicates": len(near_dupes),
        "output_length": {
            "avg_words": round(avg_length),
            "min_words": min_length,
            "max_words": max_length,
        },
        "source_breakdown": dict(source_counts),
        "avg_quality_score": round(avg_quality, 2) if avg_quality else None,
        "quality_scored_count": len(quality_scores),
        "stage_distribution": dict(stage_counts),
        "overall_health": overall_health,
        "issues": issues,
        "recommendations": recommendations,
    }


def _shannon_entropy(counts: Counter, total: int) -> float:
    """Compute Shannon entropy (higher = more diverse)."""
    if total == 0:
        return 0
    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def _find_exact_duplicates(examples: list[dict]) -> list[tuple[str, str]]:
    """Find pairs of examples with identical output_text."""
    seen = {}
    dupes = []
    for ex in examples:
        output = (ex.get("output_text") or "").strip()
        if output in seen:
            dupes.append((seen[output], ex["example_id"]))
        else:
            seen[output] = ex["example_id"]
    return dupes


def _find_near_duplicates(examples: list[dict], threshold: float = 0.85) -> list[tuple[str, str]]:
    """Find pairs with high word overlap (Jaccard similarity > threshold)."""
    dupes = []
    # Only check a sample for performance
    sample = examples[:200] if len(examples) > 200 else examples

    word_sets = []
    for ex in sample:
        words = set((ex.get("output_text") or "").lower().split())
        word_sets.append((ex["example_id"], words))

    for i in range(len(word_sets)):
        for j in range(i + 1, len(word_sets)):
            id_a, words_a = word_sets[i]
            id_b, words_b = word_sets[j]
            if not words_a or not words_b:
                continue
            intersection = len(words_a & words_b)
            union = len(words_a | words_b)
            if union > 0 and intersection / union > threshold:
                dupes.append((id_a, id_b))

    return dupes
