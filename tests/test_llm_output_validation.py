"""Tests for LLM output validation (#384)."""

from src.llm.packet_writer import _validate_llm_output


class TestValidateLlmOutput:
    """Verify contaminated LLM responses are rejected."""

    def test_clean_response_passes(self):
        response = "<why_now>Pullback to 20-day MA</why_now>\n<analysis>Strong setup</analysis>"
        assert _validate_llm_output(response, "AAPL") == response

    def test_empty_response_rejected(self):
        assert _validate_llm_output("", "AAPL") is None
        assert _validate_llm_output("   ", "AAPL") is None
        assert _validate_llm_output(None, "AAPL") is None

    def test_prompt_leakage_rejected(self):
        response = "Write a concise trade commentary for a training dataset..."
        assert _validate_llm_output(response, "AAPL") is None

    def test_output_format_leakage_rejected(self):
        response = "<why_now>Good setup</why_now>\nOUTPUT FORMAT:\n<why_now>...</why_now>"
        assert _validate_llm_output(response, "AAPL") is None

    def test_rules_leakage_rejected(self):
        response = "Analysis here\nRULES:\n1. No disclaimers"
        assert _validate_llm_output(response, "AAPL") is None

    def test_template_stub_rejected(self):
        response = "<why_now>Strong momentum setup</why_now><analysis>Detailed analysis here</analysis>"
        assert _validate_llm_output(response, "AAPL") is None

    def test_repetition_loop_rejected(self):
        response = "Good analysis\n" + "===\n" * 10
        assert _validate_llm_output(response, "AAPL") is None

    def test_data_field_repetition_rejected(self):
        response = "Setup looks good.\nAnalysis follows.\n" + "RS vs SPY -- 3m: 15.2% | 6m: 17.1%\n" * 10
        assert _validate_llm_output(response, "AAPL") is None

    def test_few_repeats_allowed(self):
        # 4 repeats is below threshold
        response = "<why_now>Good</why_now>\n" + "---\n" * 4 + "<analysis>Strong</analysis>"
        assert _validate_llm_output(response, "AAPL") is not None

    def test_short_response_not_false_positive(self):
        # Short responses shouldn't trigger repetition check
        response = "<why_now>Buy</why_now>\n<analysis>Setup</analysis>"
        assert _validate_llm_output(response, "AAPL") is not None
