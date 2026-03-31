"""SEC filing NLP feature extraction.

Called by: data_collection.edgar_collector
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_filing_nlp.py

Loughran-McDonald dictionary sentiment, cautionary phrase detection,
and filing-to-filing sentiment delta computation.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Loughran-McDonald word lists (core subset)
LM_NEGATIVE = {
    "abandon", "adverse", "against", "allegation", "bankrupt", "breach", "burden",
    "catastrophe", "caution", "cease", "claim", "collapse", "complain", "concern",
    "condemn", "conflict", "constrain", "contention", "crisis", "critical", "curtail",
    "damage", "danger", "decline", "default", "deficit", "delay", "delinquent",
    "deny", "deplete", "depreciate", "depress", "deteriorate", "detrimental",
    "difficult", "diminish", "disadvantage", "disappoint", "disaster", "discontinue",
    "dismiss", "disrupt", "distress", "doubt", "downgrade", "downturn", "drop",
    "erode", "error", "fail", "false", "fear", "fine", "foreclose", "forfeit",
    "fraud", "hinder", "impair", "impose", "inability", "inadequate", "incur",
    "insolvent", "investigate", "jeopardize", "lack", "lag", "lapse", "late",
    "layoff", "liability", "liquidate", "litigation", "lose", "loss", "misstate",
    "negate", "neglect", "objection", "obsolete", "obstacle", "omit", "onerous",
    "overdue", "overstate", "penalty", "poor", "postpone", "problem", "prohibit",
    "prosecute", "recall", "recession", "reckless", "reduce", "reject", "reluctant",
    "restructure", "revoke", "risk", "scandal", "scrutiny", "severe", "shortage",
    "shrink", "shutdown", "slump", "strain", "stress", "subpoena", "suffer",
    "suspend", "terminate", "threat", "turmoil", "unable", "uncertain", "undermine",
    "underperform", "unfavorable", "unprofitable", "unstable", "violate", "volatile",
    "warn", "weak", "worsen", "writedown", "writeoff",
}

LM_POSITIVE = {
    "achieve", "advance", "assure", "attain", "benefit", "bolster", "breakthrough",
    "competent", "confident", "deliver", "earn", "effective", "enable", "encourage",
    "enhance", "excellent", "expand", "favorable", "gain", "great", "grow", "ideal",
    "improve", "increase", "innovate", "lead", "lucrative", "optimal", "outperform",
    "overcome", "positive", "profitable", "progress", "prosper", "rebound", "recover",
    "resolve", "reward", "robust", "solid", "stable", "strength", "succeed",
    "superior", "surpass", "sustain", "thrive", "upturn", "valuable", "win",
}

LM_UNCERTAINTY = {
    "almost", "ambiguity", "anticipate", "appear", "approximate", "assume",
    "believe", "conceivable", "conditional", "depend", "doubt", "estimate",
    "expect", "fluctuate", "forecast", "if", "indefinite", "likelihood", "may",
    "might", "nearly", "pending", "perhaps", "possible", "predict", "preliminary",
    "presume", "probable", "project", "random", "risk", "roughly", "seem",
    "suggest", "tentative", "uncertain", "unclear", "unknown", "unlikely",
    "unpredictable", "unsettled", "variable",
}

CAUTIONARY_PHRASES = [
    "material weakness", "going concern", "restatement", "restated",
    "non-reliance", "inability to timely file", "late filing", "impairment",
    "write-down", "write-off", "goodwill impairment", "sec investigation",
    "securities class action", "delisted", "covenant violation", "default",
    "qualified opinion",
]


def score_filing_sentiment(filing_text: str) -> dict:
    """Loughran-McDonald dictionary sentiment scoring."""
    if not filing_text:
        return {"polarity": 0, "subjectivity": 0, "positive_count": 0,
                "negative_count": 0, "uncertainty_count": 0, "word_count": 0}

    words = re.findall(r'\b[a-z]+\b', filing_text.lower())
    total = len(words)
    if total == 0:
        return {"polarity": 0, "subjectivity": 0, "positive_count": 0,
                "negative_count": 0, "uncertainty_count": 0, "word_count": 0}

    pos = sum(1 for w in words if w in LM_POSITIVE)
    neg = sum(1 for w in words if w in LM_NEGATIVE)
    unc = sum(1 for w in words if w in LM_UNCERTAINTY)

    polarity = (pos - neg) / total
    subjectivity = (pos + neg) / total

    return {
        "polarity": round(polarity, 6),
        "subjectivity": round(subjectivity, 6),
        "positive_count": pos,
        "negative_count": neg,
        "uncertainty_count": unc,
        "word_count": total,
    }


def detect_cautionary_phrases(filing_text: str) -> list[dict]:
    """Detect high-signal cautionary phrases."""
    if not filing_text:
        return []
    text_lower = filing_text.lower()
    found = []
    for phrase in CAUTIONARY_PHRASES:
        count = text_lower.count(phrase)
        if count > 0:
            pos = text_lower.find(phrase)
            found.append({"phrase": phrase, "count": count, "first_position": pos})
    return found


def compute_filing_delta(current_scores: dict, previous_scores: dict) -> dict:
    """Compute sentiment change between consecutive filings."""
    if not previous_scores:
        return {"delta_polarity": None, "delta_negative": None, "is_first_filing": True}
    return {
        "delta_polarity": round(current_scores["polarity"] - previous_scores["polarity"], 6),
        "delta_negative": current_scores["negative_count"] - previous_scores["negative_count"],
        "delta_uncertainty": current_scores["uncertainty_count"] - previous_scores.get("uncertainty_count", 0),
        "delta_word_count": current_scores["word_count"] - previous_scores["word_count"],
        "is_first_filing": False,
    }


def compute_tech_fundamental_divergence(features: dict, filing_data: dict) -> str:
    """Detect when technical setup and fundamental picture diverge."""
    tech_bullish = features.get("trend_state") in ("strong_uptrend", "uptrend")
    fund_bullish = (
        (filing_data.get("delta_polarity") or 0) > 0
        or filing_data.get("cautionary_count", 0) == 0
    )
    fund_bearish = (
        (filing_data.get("delta_polarity") or 0) < -0.05
        or filing_data.get("cautionary_count", 0) > 0
    )
    if tech_bullish and fund_bullish:
        return "convergence_bullish"
    elif tech_bullish and fund_bearish:
        return "divergence_caution"
    return "neutral"
