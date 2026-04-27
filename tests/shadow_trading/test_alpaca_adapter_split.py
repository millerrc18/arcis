"""Regression-locking tests for alpaca_adapter.py Sprint-0.C/C.2 split.

Called by: test suite
Calls: src.shadow_trading.alpaca_adapter, alpaca_adapter_paper, alpaca_adapter_live, alpaca_adapter_verify
Owns tables: none
Config keys: none
Tests: self
"""
from pathlib import Path


def test_alpaca_adapter_under_400_lines():
    f = Path(__file__).resolve().parent.parent.parent / "src" / "shadow_trading" / "alpaca_adapter.py"
    n = sum(1 for _ in f.read_text(encoding="utf-8").splitlines())
    assert n < 400, f"alpaca_adapter.py is {n} lines, exceeds 400-line guardrail"


def test_alpaca_adapter_paper_under_400_lines():
    f = Path(__file__).resolve().parent.parent.parent / "src" / "shadow_trading" / "alpaca_adapter_paper.py"
    assert f.exists(), "alpaca_adapter_paper.py does not exist"
    n = sum(1 for _ in f.read_text(encoding="utf-8").splitlines())
    assert n < 400, f"alpaca_adapter_paper.py is {n} lines, exceeds 400-line guardrail"


def test_alpaca_adapter_live_under_400_lines():
    f = Path(__file__).resolve().parent.parent.parent / "src" / "shadow_trading" / "alpaca_adapter_live.py"
    assert f.exists(), "alpaca_adapter_live.py does not exist"
    n = sum(1 for _ in f.read_text(encoding="utf-8").splitlines())
    assert n < 400, f"alpaca_adapter_live.py is {n} lines, exceeds 400-line guardrail"


def test_alpaca_adapter_verify_under_400_lines():
    f = Path(__file__).resolve().parent.parent.parent / "src" / "shadow_trading" / "alpaca_adapter_verify.py"
    assert f.exists(), "alpaca_adapter_verify.py does not exist"
    n = sum(1 for _ in f.read_text(encoding="utf-8").splitlines())
    assert n < 400, f"alpaca_adapter_verify.py is {n} lines, exceeds 400-line guardrail"


def test_alpaca_adapter_helpers_modules_exist():
    from src.shadow_trading import alpaca_adapter_paper, alpaca_adapter_live, alpaca_adapter_verify
    assert alpaca_adapter_paper is not None
    assert alpaca_adapter_live is not None
    assert alpaca_adapter_verify is not None


def test_alpaca_adapter_public_api_unchanged():
    from src.shadow_trading.alpaca_adapter import AlpacaPaperBroker, AlpacaLiveBroker
    from src.shadow_trading.alpaca_adapter import verify_live_order_accepted
    assert AlpacaPaperBroker is not None
    assert AlpacaLiveBroker is not None
    assert callable(verify_live_order_accepted)


def test_alpaca_adapter_paper_public_surface():
    """Smoke: paper module exposes expected callables."""
    from src.shadow_trading import alpaca_adapter_paper
    assert callable(alpaca_adapter_paper.place_paper_entry)
    assert callable(alpaca_adapter_paper.place_paper_exit)
    assert callable(alpaca_adapter_paper.place_bracket_order)


def test_alpaca_adapter_live_public_surface():
    """Smoke: live module exposes expected callables."""
    from src.shadow_trading import alpaca_adapter_live
    assert callable(alpaca_adapter_live.place_live_entry)
    assert callable(alpaca_adapter_live.place_live_exit)
    assert callable(alpaca_adapter_live.place_live_bracket)


def test_alpaca_adapter_verify_public_surface():
    """Smoke: verify module exposes expected callables."""
    from src.shadow_trading import alpaca_adapter_verify
    assert callable(alpaca_adapter_verify.verify_live_order_accepted)


def test_known_violations_no_alpaca_adapter_entry():
    """The grandfathered 526-line entry for alpaca_adapter.py must be removed."""
    import json
    kv = json.loads(
        (Path(__file__).resolve().parent.parent.parent / "config" / "known_violations.json")
        .read_text(encoding="utf-8")
    )
    oversized = {v["file"] for v in kv.get("oversized_files", [])}
    assert "src/shadow_trading/alpaca_adapter.py" not in oversized, (
        "known_violations.json still contains the stale alpaca_adapter.py entry — remove it"
    )
