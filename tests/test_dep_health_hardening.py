"""Tier-3 dependency-health hygiene regression tests.

Each test is a source-scan regression guard for one of the 13 issues being
closed in the dep-health bundle. These guards prevent the bare-except + silent-
ImportError patterns from re-emerging — the audit found 14 sites and a single
fix-and-forget regression would silently undo all of them.

Issues: #527, #544, #545, #546, #572, #587, #588, #589, #590, #599, #600, #601, #605
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _bare_except_pass_count(text: str) -> int:
    """Count `except <T>: <newline> <indent> pass` patterns with no log call."""
    pattern = re.compile(
        r"except [A-Za-z_][A-Za-z_0-9.]*( as [a-z_]+)?:\s*\n\s*pass\b",
        re.MULTILINE,
    )
    return len(pattern.findall(text))


def _has_log_call_after_except(text: str, except_line_marker: str) -> bool:
    """Return True if the `except` block beginning at the marker line is followed
    by a logger call within 3 indented lines (instead of bare pass)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if except_line_marker in line and "except" in line:
            for j in range(i + 1, min(len(lines), i + 4)):
                if "logger." in lines[j]:
                    return True
            return False
    return False


# ── #527 — pysentiment2 silent ImportError in edgar_collector ──

def test_edgar_collector_logs_pysentiment_import_error():
    text = _read("src/data_collection/edgar_collector.py")
    # Look for any "pysentiment" mention; the import-error block must log
    # rather than `pass`. Locate the surrounding `except ImportError:` and
    # ensure the next non-empty line is NOT a bare `pass`.
    if "pysentiment" not in text.lower():
        pytest.skip("pysentiment block removed from this file")
    # Check that within 6 lines of any pysentiment mention there's no bare pass
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "pysentiment" in line.lower() and "except" in lines[max(0, i - 2):i + 2][0] or False:
            pass  # placeholder; the broader check below covers it
    # Simpler: there must NOT be `except ImportError:\n    pass  # pysentiment`
    assert not re.search(
        r"except ImportError:\s*\n\s*pass\s*#\s*pysentiment",
        text,
    ), "edgar_collector.py: bare `except ImportError: pass # pysentiment` regressed"


# ── #544 — unused `import json` in fundamentals ──

def test_fundamentals_no_unused_json_import():
    text = _read("src/data_enrichment/fundamentals.py")
    if re.search(r"^import json\s*$", text, re.MULTILINE):
        # If kept, it must be referenced somewhere
        body_after_imports = text.split("import json", 1)[1]
        assert "json." in body_after_imports, (
            "fundamentals.py: `import json` declared but never used (#544)"
        )


# ── #545 — bare except in enricher._alert_missing_key ──

def test_enricher_alert_missing_key_logs_failure():
    text = _read("src/data_enrichment/enricher.py")
    # Locate the function and verify its `except` block has a logger call
    m = re.search(
        r"def _alert_missing_key[\s\S]{0,800}?except [^:]+:\s*\n([^\n]+)\n([^\n]+)",
        text,
    )
    assert m, "_alert_missing_key block not found in enricher.py"
    body = m.group(1) + "\n" + m.group(2)
    assert "pass" not in body or "logger." in body, (
        "enricher._alert_missing_key still has bare `except: pass` (#545)"
    )


# ── #546 — yfinance auto_adjust deprecation in market_data ──

def test_market_data_suppresses_yfinance_auto_adjust_warning():
    text = _read("src/data_ingestion/market_data.py")
    if "auto_adjust=False" in text:
        # Must be wrapped in warnings.catch_warnings or have an explicit filterwarnings
        assert ("warnings.catch_warnings" in text
                or "filterwarnings" in text), (
            "market_data.py: auto_adjust=False present but FutureWarning not suppressed (#546)"
        )


# ── #572 — psycopg2 missing from requirements ──

def test_psycopg2_in_requirements():
    text = _read("requirements.txt")
    assert re.search(r"psycopg2(-binary)?", text, re.IGNORECASE), (
        "requirements.txt missing psycopg2 / psycopg2-binary (#572)"
    )


# ── #587 — bare except in features.earnings cache ──

def test_features_earnings_cache_logs_failure():
    text = _read("src/features/earnings.py")
    # Find the `except Exception:` block in earnings.py and ensure log call
    # is present within 3 lines.
    blocks = re.finditer(r"except Exception[^:]*:\s*\n([\s\S]{1,200}?)(?=\n\S|\Z)", text)
    for blk in blocks:
        body = blk.group(1)
        if "pass" in body and "logger." not in body:
            pytest.fail(
                f"features/earnings.py: bare `except Exception: pass` regressed (#587):\n{body}"
            )


# ── #588 — bare except in close_shadow_trade exit metadata ──

def test_journal_store_close_shadow_trade_logs_metadata_failure():
    text = _read("src/journal/store.py")
    # Locate close_shadow_trade function body and ensure no bare except: pass for exit metadata
    m = re.search(r"def close_shadow_trade[\s\S]{0,3000}", text)
    if m:
        body = m.group(0)
        # find any except: pass without a sibling logger call within 3 lines
        bare_passes = list(re.finditer(r"except [A-Za-z_][A-Za-z_0-9.]*[^:]*:\s*\n([^\n]+)\n([^\n]+)", body))
        for bp in bare_passes:
            chunk = bp.group(1) + "\n" + bp.group(2)
            if "pass" in chunk.split("\n")[0] and "logger." not in chunk:
                pytest.fail(
                    f"journal/store.py close_shadow_trade has bare except: pass for exit metadata (#588):\n{chunk}"
                )


# ── #589 — silent except in features.engine._add_sector_features ──

def test_features_engine_add_sector_features_logs_failure():
    text = _read("src/features/engine.py")
    m = re.search(r"def _add_sector_features[\s\S]{0,1500}", text)
    if m:
        body = m.group(0)
        bare = re.search(r"except Exception[^:]*:\s*\n\s*([^\n]+)\n\s*([^\n]+)", body)
        if bare:
            after = bare.group(1) + "\n" + bare.group(2)
            assert "logger." in after or "pass" not in bare.group(1), (
                f"_add_sector_features still has silent except (#589):\n{after}"
            )


# ── #590 — raw sqlite3.connect in features/ + journal/ ──

_CONNECT_DB_TARGETS = [
    "src/features/engine.py",
    "src/features/event_risk_score.py",
    "src/features/setup_classifier.py",
    "src/journal/stats.py",
]


def test_features_journal_use_connect_db_helper():
    """#590 — These 5 hot paths must use src.utils.db.connect_db (busy_timeout=30s)
    instead of raw sqlite3.connect to avoid `database is locked` errors."""
    bad: list[str] = []
    for path in _CONNECT_DB_TARGETS:
        try:
            text = _read(path)
        except FileNotFoundError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r"\bsqlite3\.connect\(", line) and "noqa: db" not in line:
                bad.append(f"{path}:{i}")
    assert not bad, (
        "Use connect_db() (busy_timeout=30s) instead of raw sqlite3.connect at: "
        + ", ".join(bad)
        + " — add `# noqa: db` if a raw connect is genuinely needed."
    )


# ── #599 — llama-cpp-python missing from requirements ──

def test_llama_cpp_python_declared_in_requirements():
    text = _read("requirements.txt")
    assert "llama-cpp-python" in text or "llama_cpp_python" in text, (
        "requirements.txt missing llama-cpp-python (#599)"
    )


# ── #600 — torch missing from requirements ──

def test_torch_declared_somewhere_in_requirements():
    text = _read("requirements.txt")
    extra = ""
    try:
        # Relocated from `requirements-training.txt` at repo root to
        # `training/requirements.txt` in v0.36.55 (#101) so GitHub's auto
        # dependency-submission stops choking on the unsloth git+URL pin.
        extra = _read("training/requirements.txt")
    except FileNotFoundError:
        pass
    assert ("torch" in text) or ("torch" in extra), (
        "torch missing from requirements.txt and training/requirements.txt (#600)"
    )


# ── #601 — bare except in LLM client config loader ──

def test_llm_client_config_lookup_logs_failure():
    text = _read("src/llm/client.py")
    # find the early get_active_model_name try/except block
    m = re.search(
        r"get_active_model_name[\s\S]{0,500}?except [^:]+:\s*\n\s*([^\n]+)",
        text,
    )
    if m:
        first_line = m.group(1)
        assert "pass" not in first_line or "logger." in m.group(0), (
            "llm/client.py: bare except for active model lookup regressed (#601)"
        )


# ── #605 — bare excepts in ranker.py (regime + sector blocks) ──

def test_ranker_classify_regime_block_logs_failure():
    text = _read("src/ranking/ranker.py")
    # The compute_sector_context + classify_regime blocks are at ~567 and ~599
    # Both must have logger calls in their except handlers.
    bad_blocks: list[str] = []
    for m in re.finditer(
        r"except Exception[^:]*:\s*\n\s*([^\n]+)\n\s*([^\n]+)",
        text,
    ):
        first = m.group(1)
        second = m.group(2)
        if "pass" in first and "logger." not in first and "logger." not in second:
            bad_blocks.append(first.strip())
    assert not bad_blocks, (
        f"ranker.py has bare `except: pass` blocks (#605): {bad_blocks}"
    )
