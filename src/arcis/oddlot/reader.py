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
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OFFER_READER_SYSTEM = """You are a precise extractor of tender offer terms from SEC filings.
Read the provided tender offer document text and extract the requested fields.
Output ONLY valid JSON matching the schema. Do not add explanations.
If a field cannot be determined from the text, use null.
Be conservative: only report what the document explicitly states."""

OFFER_READER_SCHEMA = {
    "has_oddlot_priority": (
        "boolean | null — does the offer give priority "
        "to odd-lot holders (< 100 shares)?"
    ),
    "oddlot_threshold": (
        "integer | null — max shares for odd-lot priority (usually 99)"
    ),
    "offer_price": "number | null — fixed offer price per share in USD",
    "price_range_low": "number | null — Dutch auction range low",
    "price_range_high": "number | null — Dutch auction range high",
    "is_dutch_auction": "boolean",
    "expiration_date": "string | null — YYYY-MM-DD",
    "expiration_time": "string | null — e.g. '11:59 PM ET'",
    "min_tender_condition": (
        "string | null — minimum shares that must be tendered"
    ),
    "proration_description": (
        "string | null — how proration works if oversubscribed"
    ),
    "withdrawal_rights": (
        "string | null — can shareholders withdraw? deadline?"
    ),
    "conditions": (
        "array of strings — offer conditions that could cause withdrawal"
    ),
    "issuer_cik": "string | null",
    "risk_flags": (
        "array of strings — red flags: conditional, financing "
        "contingency, prior withdrawal, etc."
    ),
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

    def to_dict(self) -> dict[str, object]:
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
    """Build the user prompt for offer term extraction.

    Raises:
        ValueError: if document exceeds max_chars (fail-closed; truncation
            could lose the odd-lot clause, so we refuse rather than silently cut)
    """
    if len(document_text) > max_chars:
        raise ValueError(
            f"Document is {len(document_text)} chars, exceeds {max_chars} limit. "
            "Split into sections or increase limit explicitly; refusing to "
            "truncate silently because the odd-lot clause could be lost."
        )
    schema_str = json.dumps(OFFER_READER_SCHEMA, indent=2)
    return f"""Extract tender offer terms from the following document.

Schema (output JSON with exactly these keys):
{schema_str}

Document text:
---
{document_text}
---

Output ONLY the JSON object."""


def _require_bool(data: dict[str, object], key: str, default: bool | None = None) -> bool | None:
    """Get a boolean value with strict type checking. Rejects truthy strings."""
    val = data.get(key, default)
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    raise ValueError(f"Field '{key}' must be boolean, got {type(val).__name__}: {val!r}")


def _require_float(data: dict[str, object], key: str) -> float | None:
    """Get a float value with strict type checking."""
    val = data.get(key)
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    raise ValueError(f"Field '{key}' must be numeric, got {type(val).__name__}: {val!r}")


def _require_int(data: dict[str, object], key: str) -> int | None:
    """Get an int value with strict type checking."""
    val = data.get(key)
    if val is None:
        return None
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    raise ValueError(f"Field '{key}' must be integer, got {type(val).__name__}: {val!r}")


def _require_str(data: dict[str, object], key: str) -> str | None:
    """Get a string value with strict type checking."""
    val = data.get(key)
    if val is None:
        return None
    if isinstance(val, str):
        return val
    raise ValueError(f"Field '{key}' must be string, got {type(val).__name__}: {val!r}")


def _require_str_list(data: dict[str, object], key: str) -> list[str]:
    """Get a list of strings with strict type checking."""
    val = data.get(key, [])
    if not isinstance(val, list):
        raise ValueError(f"Field '{key}' must be list, got {type(val).__name__}")
    for item in val:
        if not isinstance(item, str):
            raise ValueError(f"Field '{key}' must be list of strings, got {item!r}")
    return val


def _validate_response_dict(data: object) -> dict[str, object]:
    """Validate the parsed JSON is a dict with required fields."""
    if not isinstance(data, dict):
        raise ValueError(
            f"LLM response must be a JSON object, got {type(data).__name__}"
        )

    # Required fields (fail-closed if missing)
    required = ["has_oddlot_priority", "is_dutch_auction"]
    for key in required:
        if key not in data:
            raise ValueError(f"Required field '{key}' missing from LLM response")

    # At least one price indicator must be present
    price_keys = ["offer_price", "price_range_low", "price_range_high"]
    if not any(k in data and data[k] is not None for k in price_keys):
        raise ValueError(
            "No price data in LLM response; need offer_price or price_range"
        )

    # Reject unknown keys (typos in LLM output)
    known_keys = {
        "has_oddlot_priority", "oddlot_threshold", "offer_price",
        "price_range_low", "price_range_high", "is_dutch_auction",
        "expiration_date", "expiration_time", "min_tender_condition",
        "proration_description", "withdrawal_rights", "conditions",
        "issuer_cik", "risk_flags",
    }
    unknown = set(data.keys()) - known_keys
    if unknown:
        raise ValueError(f"Unknown fields in LLM response: {unknown}")
    return data


def parse_extraction_response(response: str) -> OfferTerms:
    """Parse LLM JSON response into OfferTerms with strict schema validation.

    Raises:
        json.JSONDecodeError: if response is not valid JSON
        ValueError: if any field has the wrong type or required fields are
            missing (fail-closed)
    """
    # Strip markdown code fences if present
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines)

    data = _validate_response_dict(json.loads(cleaned))

    return OfferTerms(
        has_oddlot_priority=_require_bool(data, "has_oddlot_priority"),
        oddlot_threshold=_require_int(data, "oddlot_threshold"),
        offer_price=_require_float(data, "offer_price"),
        price_range_low=_require_float(data, "price_range_low"),
        price_range_high=_require_float(data, "price_range_high"),
        is_dutch_auction=_require_bool(data, "is_dutch_auction") or False,
        expiration_date=_require_str(data, "expiration_date"),
        expiration_time=_require_str(data, "expiration_time"),
        min_tender_condition=_require_str(data, "min_tender_condition"),
        proration_description=_require_str(data, "proration_description"),
        withdrawal_rights=_require_str(data, "withdrawal_rights"),
        conditions=_require_str_list(data, "conditions"),
        issuer_cik=_require_str(data, "issuer_cik"),
        risk_flags=_require_str_list(data, "risk_flags"),
        raw_response=response,
    )


# ---------------------------------------------------------------------------
# Gemini Flash extraction
# ---------------------------------------------------------------------------

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class ReaderConfigError(Exception):
    """Missing reader configuration (fail-closed)."""


class ReaderNetworkError(Exception):
    """LLM API network failure (after retries)."""


def _gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise ReaderConfigError("GEMINI_API_KEY not set; see "
                                "https://aistudio.google.com/apikey")
    return key


def _call_gemini(prompt: str, retries: int = 3) -> str:
    """POST prompt to Gemini Flash; return raw response text.

    Raises ReaderConfigError (no API key), ReaderNetworkError (HTTP/
    network failure after retries), ValueError (no usable text).
    """
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={_gemini_api_key()}"
    body = json.dumps(
        {
            "system_instruction": {"parts": [{"text": OFFER_READER_SYSTEM}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0,
                                 "response_mime_type": "application/json"},
        }
    ).encode()

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read())
            parts = payload["candidates"][0]["content"]["parts"]
            return str(parts[0]["text"])
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(
                f"Gemini response missing text: {str(payload)[:200]}") from e
        except urllib.error.HTTPError as e:
            if e.code == 429 or 500 <= e.code < 600:
                last_error = e
            else:
                raise ReaderNetworkError(f"Gemini HTTP {e.code}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
        if attempt < retries - 1:
            time.sleep(2**attempt)

    raise ReaderNetworkError(f"Gemini failed after {retries}: {last_error}")


def extract_offer_terms(document_text: str) -> OfferTerms:
    """Extract offer terms via Gemini Flash. Fail-closed throughout."""
    prompt = build_extraction_prompt(document_text)
    return parse_extraction_response(_call_gemini(prompt))


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
    def qualifies_for_oddlot(self) -> bool:
        """Check if our position size qualifies for odd-lot priority.

        If the document specifies a threshold (usually 99), our shares_to_buy
        must be <= threshold. If no threshold specified, fail closed.
        """
        if not self.terms.has_oddlot_priority:
            return False
        threshold = self.terms.oddlot_threshold
        if threshold is None:
            return False  # fail closed: no threshold = cannot verify qualification
        return self.shares_to_buy <= threshold

    @property
    def gross_spread_per_share(self) -> float | None:
        """Offer price minus current market price."""
        px = self.terms.effective_price
        if px is not None and self.current_price is not None:
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
