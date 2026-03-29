"""Tests for grammar-constrained generation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.llm.grammar_client import _resolve_model_path, generate_with_grammar
from src.llm.packet_writer import enhance_packet_with_llm
from src.models import PositionSizing, TradePacket


GRAMMAR_PATH = Path("config/trade_commentary.gbnf")


def _make_packet() -> TradePacket:
    return TradePacket(
        ticker="AAPL",
        company_name="Apple Inc.",
        recommendation="BUY",
        setup_type="pullback",
        why_now="Template why now",
        entry_zone="190-192",
        stop_invalidation="187",
        targets="196, 200",
        expected_hold_period="3-5 days",
        confidence=7,
        event_risk="Low",
        position_sizing=PositionSizing(
            allocation_dollars=1000.0,
            allocation_pct=1.0,
            estimated_risk_dollars=25.0,
        ),
        deeper_analysis="Template deeper analysis",
    )


def test_grammar_file_contains_required_sections():
    content = GRAMMAR_PATH.read_text(encoding="utf-8")
    assert "root ::=" in content
    assert "<why_now>" in content
    assert "<analysis>" in content
    assert "<metadata>" in content
    assert "Direction: " in content


def test_resolve_model_path_prefers_explicit_existing_path(tmp_path):
    model_path = tmp_path / "model.gguf"
    model_path.write_text("stub", encoding="utf-8")

    resolved = _resolve_model_path(
        {"llm": {"grammar_model_path": str(model_path)}}
    )

    assert resolved == model_path


def test_generate_with_grammar_returns_none_when_runtime_unavailable():
    with patch("src.llm.grammar_client._load_runtime", return_value=(None, None)):
        assert generate_with_grammar("prompt", "system") is None


def test_generate_with_grammar_returns_llama_output():
    fake_model = MagicMock()
    fake_model.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "<why_now>x</why_now>"}}]
    }

    with patch("src.llm.grammar_client._load_runtime", return_value=(fake_model, object())):
        result = generate_with_grammar("prompt", "system", max_tokens=123, temperature=0.2)

    assert result == "<why_now>x</why_now>"
    fake_model.create_chat_completion.assert_called_once()


def test_packet_writer_uses_grammar_path_when_enabled():
    packet = _make_packet()
    xml = (
        "<why_now>Grammar path why now with enough text to pass parsing.</why_now>"
        "<analysis>Grammar path analysis with enough detail to be used by the packet writer.</analysis>"
        "<metadata>Conviction: 8\nDirection: LONG\nTime Horizon: 3-5 days\nKey Risk: Event volatility</metadata>"
    )

    with patch("src.llm.grammar_client.generate_with_grammar", return_value=xml) as mock_grammar, patch(
        "src.llm.packet_writer.generate"
    ) as mock_ollama:
        result = enhance_packet_with_llm(
            packet,
            {"current_price": 190.0},
            {"llm": {"enabled": True, "use_grammar_enforcement": True}},
        )

    assert result.why_now.startswith("Grammar path why now")
    assert result.deeper_analysis.startswith("Grammar path analysis")
    assert result.llm_conviction == 8
    mock_grammar.assert_called_once()
    mock_ollama.assert_not_called()


def test_packet_writer_falls_back_to_ollama_when_grammar_returns_none():
    packet = _make_packet()
    xml = (
        "<why_now>Fallback why now with enough text to pass parsing.</why_now>"
        "<analysis>Fallback analysis with enough detail to be used by the packet writer.</analysis>"
        "<metadata>Conviction: 6\nDirection: LONG\nTime Horizon: 3-5 days\nKey Risk: Event volatility</metadata>"
    )

    with patch("src.llm.grammar_client.generate_with_grammar", return_value=None), patch(
        "src.llm.packet_writer.is_llm_available", return_value=True
    ), patch("src.llm.packet_writer.generate", return_value=xml) as mock_ollama:
        result = enhance_packet_with_llm(
            packet,
            {"current_price": 190.0},
            {"llm": {"enabled": True, "use_grammar_enforcement": True}},
        )

    assert result.why_now.startswith("Fallback why now")
    mock_ollama.assert_called_once()
