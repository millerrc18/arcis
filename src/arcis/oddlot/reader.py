"""LLM-powered tender offer document reader for odd-lot harvesting.

Extracts structured deal terms from SC TO-I offer documents:
- Odd-lot priority clause (present/absent, share threshold)
- Offer price or Dutch auction range
- Expiration date and conditions
- Proration and withdrawal terms
- Risk flags (offer withdrawal history, conditional tenders)

Uses a pinned LLM with schema-constrained output. All prompts and
outputs are logged for audit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


OFFER_READER_SYSTEM = """You are a precise extractor of tender offer terms from SEC filings.
Read the provided tender offer document text and extract the requested fields.
Output ONLY valid JSON matching the schema. Do not add explanations.
If a field cannot be determined from the text, use null.
Be conservative: only report what the document explicitly states."""

OFFER_READER_SCHEMA = {
    "has_oddlot_priority": "boolean | null — does the offer give priority to odd-lot holders (< 100 shares)?",
    "oddlot_threshold": "integer | null — max shares for odd-lot priority (usually 99)",
    "offer_price": "number | null — fixed offer price per share in USD",
    "price_range_low": "number | null — Dutch auction range low",
    "price_range_high": "number | null — Dutch auction range high",
    "is_dutch_auction": "boolean",
    "expiration_date": "string | null — YYYY-MM-DD",
    "expiration_time": "string | null — e.g. '11:59 PM ET'",
    "min_tender_condition": "string | null — minimum shares that must be tendered",
    "proration_description": "string | null — how proration works if oversubscribed",
    "withdrawal_rights": "string | null — can shareholders withdraw? deadline?",
    "conditions": "array of strings — offer conditions that could cause withdrawal",
    "issuer_cik": "string | null",
    "risk_flags": "array of strings — red flags: conditional, financing contingency, prior withdrawal, etc.",
}


@dataclass
class OfferTerms:
    """Structured terms extracted from a tender offer document."""

    has_oddlot_priority: bool | None = None
    oddlot_threshold: int | None = None
    offer_price: float | None = None
    price_range_low: float | None = None
    price_range_high: float | None = None
    is_dutch_auction: bool = False
    expiration_date: str | None = None
    expiration_time: str | None = None
    min_tender_condition: str | None = None
    proration_description: str | None = None
    withdrawal_rights: str | None = None
    conditions: list[str] = field(default_factory=list)
    issuer_cik: str | None = None
    risk_flags: list[str] = field(default_factory=list)
    raw_response: str = ""
    model_id: str = ""
    extraction_date: str = ""

    @property
    def effective_price(self) -> float | None:
        """Best estimate of price per share (fixed, or low end of Dutch range)."""
        if self.offer_price:
            return self.offer_price
        return self.price_range_low

    def to_dict(self) -> dict:
        return {
            "has_oddlot_priority": self.has_oddlot_priority,
            "oddlot_threshold": self.oddlot_threshold,
            "offer_price": self.offer_price,
            "price_range_low": self.price_range_low,
            "price_range_high": self.price_range_high,
            "is_dutch_auction": self.is_dutch_auction,
            "expiration_date": self.expiration_date,
            "expiration_time": self.expiration_time,
            "min_tender_condition": self.min_tender_condition,
            "proration_description": self.proration_description,
            "withdrawal_rights": self.withdrawal_rights,
            "conditions": self.conditions,
            "issuer_cik": self.issuer_cik,
            "risk_flags": self.risk_flags,
            "model_id": self.model_id,
            "extraction_date": self.extraction_date,
        }


def build_extraction_prompt(document_text: str, max_chars: int = 60000) -> str:
    """Build the user prompt for offer term extraction."""
    # Truncate very long documents (offer docs can be 100+ pages)
    text = document_text[:max_chars]
    schema_str = json.dumps(OFFER_READER_SCHEMA, indent=2)
    return f"""Extract tender offer terms from the following document.

Schema (output JSON with exactly these keys):
{schema_str}

Document text:
---
{text}
---

Output ONLY the JSON object."""


def parse_extraction_response(response: str) -> OfferTerms:
    """Parse LLM JSON response into OfferTerms. Raises on invalid JSON."""
    # Strip markdown code fences if present
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)
    return OfferTerms(
        has_oddlot_priority=data.get("has_oddlot_priority"),
        oddlot_threshold=data.get("oddlot_threshold"),
        offer_price=data.get("offer_price"),
        price_range_low=data.get("price_range_low"),
        price_range_high=data.get("price_range_high"),
        is_dutch_auction=data.get("is_dutch_auction", False),
        expiration_date=data.get("expiration_date"),
        expiration_time=data.get("expiration_time"),
        min_tender_condition=data.get("min_tender_condition"),
        proration_description=data.get("proration_description"),
        withdrawal_rights=data.get("withdrawal_rights"),
        conditions=data.get("conditions", []),
        issuer_cik=data.get("issuer_cik"),
        risk_flags=data.get("risk_flags", []),
        raw_response=response,
    )


# ---------------------------------------------------------------------------
# Opportunity scoring
# ---------------------------------------------------------------------------

@dataclass
class OddLotOpportunity:
    """A scored odd-lot tender opportunity."""

    ticker: str
    company: str
    terms: OfferTerms
    current_price: float | None = None
    shares_to_buy: int = 99  # odd-lot max

    @property
    def gross_spread_per_share(self) -> float | None:
        """Offer price minus current market price."""
        px = self.terms.effective_price
        if px and self.current_price:
            return px - self.current_price
        return None

    @property
    def gross_profit(self) -> float | None:
        """Total gross profit for odd-lot position."""
        spread = self.gross_spread_per_share
        if spread:
            return spread * self.shares_to_buy
        return None

    @property
    def capital_required(self) -> float | None:
        """Capital to buy 99 shares at market."""
        if self.current_price:
            return self.current_price * self.shares_to_buy
        return None

    @property
    def return_pct(self) -> float | None:
        """Gross return on capital."""
        profit = self.gross_profit
        capital = self.capital_required
        if profit and capital:
            return profit / capital * 100
        return None

    def risk_summary(self) -> str:
        """Human-readable risk assessment."""
        risks = list(self.terms.risk_flags)
        if self.terms.is_dutch_auction:
            risks.append("Dutch auction: may clear at low end of range")
        if not self.terms.has_oddlot_priority:
            risks.append("NO odd-lot priority confirmed — do not trade")
        return "; ".join(risks) if risks else "No flags"
