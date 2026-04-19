"""Pass B — format drift detector (XML + plain-text label checks).

Two drift signals, both measured on a single row:

  1. Output XML integrity — `output_text` is XML-tagged with `<why_now>`
     and `<analysis>` at 95% prevalence in the production corpus.
     Missing either = drift; unbalanced open/close tags = malformed;
     any of the DEPRECATED tags present = deprecated-format leak.

  2. Input label schema — `input_text` is plain-text feature snapshot
     with canonical labels `Ticker:`, `Current Price:`, `Trend State:`,
     and a banner `=== ACTUAL OUTCOME ===`. Missing the banner is drift.

Strictness is MODERATE (per Pass 1 D1): whitespace variations and
formatting quirks pass; true absence of required markers fails. Parsing
is regex-based — the content inside `<why_now>` etc. is natural
language, not well-formed XML, so we deliberately do not use an XML
parser.

Called by: src.training.audit.core
Calls: src.training.audit.taxonomy
Owns tables: none
Tests: tests/training/test_pass_b.py
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Required XML open/close tags in output_text. Anchor on 95%-prevalence
# shape from Pass 2 research; narrower than the full list Halcyon may
# eventually emit (risk_management / execution_plan / monitoring).
REQUIRED_OUTPUT_TAGS: tuple[str, ...] = ("why_now", "analysis")

# Tags present in older format versions; if any row has them, we flag.
# Empty in the current corpus — presence = drift from a pre-v0.26 format.
DEPRECATED_OUTPUT_TAGS: tuple[str, ...] = (
    "risk_management", "execution_plan", "monitoring",
)

# Required plain-text labels in input_text. `Ticker:` and `Current Price:`
# anchor schema; the `=== ACTUAL OUTCOME ===` banner signals the outcome
# segment is present.
REQUIRED_INPUT_LABELS: tuple[str, ...] = (
    "Ticker:",
    "Current Price:",
    "=== ACTUAL OUTCOME ===",
)


@dataclass(frozen=True)
class PassBDecision:
    example_id: str
    quarantine: bool
    reason_code: str | None
    missing: list[str]
    deprecated_found: list[str]
    malformed: bool


def _find_open_tags(text: str) -> set[str]:
    """Return set of tag names seen as `<tag>` in text (no attributes)."""
    return set(re.findall(r"<([a-z_][a-z0-9_]*)>", text))


def _find_close_tags(text: str) -> set[str]:
    """Return set of tag names seen as `</tag>` in text."""
    return set(re.findall(r"</([a-z_][a-z0-9_]*)>", text))


def check_output_xml(output_text: str) -> tuple[list[str], list[str], bool]:
    """Return (missing_required, deprecated_found, malformed_bool).

    Malformed = for ANY required tag, open count != close count.
    Deprecated = any deprecated tag found (open or close).
    """
    if not output_text:
        return list(REQUIRED_OUTPUT_TAGS), [], False
    opens = _find_open_tags(output_text)
    closes = _find_close_tags(output_text)
    missing = [t for t in REQUIRED_OUTPUT_TAGS if t not in opens or t not in closes]
    deprecated_found = [
        t for t in DEPRECATED_OUTPUT_TAGS if t in opens or t in closes
    ]
    malformed = False
    for t in REQUIRED_OUTPUT_TAGS:
        n_open = len(re.findall(rf"<{t}>", output_text))
        n_close = len(re.findall(rf"</{t}>", output_text))
        if n_open != n_close:
            malformed = True
            break
    return missing, deprecated_found, malformed


def check_input_labels(input_text: str) -> list[str]:
    """Return list of required labels missing from input_text."""
    if not input_text:
        return list(REQUIRED_INPUT_LABELS)
    return [label for label in REQUIRED_INPUT_LABELS if label not in input_text]


def decide(
    *,
    example_id: str,
    output_text: str,
    input_text: str,
) -> PassBDecision:
    """Apply Pass B rules to one row.

    Priority of reason codes when multiple drift signals fire:
      1. malformed (output XML open/close mismatch)
      2. deprecated_marker (any deprecated tag present)
      3. missing_section (required tag or label absent)
    """
    missing_tags, deprecated_found, malformed = check_output_xml(output_text or "")
    missing_labels = check_input_labels(input_text or "")
    missing = [f"<{t}>" for t in missing_tags] + [
        f"label:{l}" for l in missing_labels
    ]

    if malformed:
        return PassBDecision(
            example_id=example_id,
            quarantine=True,
            reason_code="format_drift_malformed",
            missing=missing,
            deprecated_found=deprecated_found,
            malformed=True,
        )
    if deprecated_found:
        return PassBDecision(
            example_id=example_id,
            quarantine=True,
            reason_code="format_drift_deprecated_marker",
            missing=missing,
            deprecated_found=deprecated_found,
            malformed=False,
        )
    if missing:
        return PassBDecision(
            example_id=example_id,
            quarantine=True,
            reason_code="format_drift_missing_section",
            missing=missing,
            deprecated_found=[],
            malformed=False,
        )
    return PassBDecision(
        example_id=example_id,
        quarantine=False,
        reason_code=None,
        missing=[],
        deprecated_found=[],
        malformed=False,
    )


def run_pass_b(rows: list[dict]) -> list[PassBDecision]:
    """Apply Pass B to each row; expects example_id/input_text/output_text."""
    return [
        decide(
            example_id=r["example_id"],
            output_text=r.get("output_text") or "",
            input_text=r.get("input_text") or "",
        )
        for r in rows
    ]
