"""Regression tests for parser_strategy_succeeded instrumentation (#98).

`_parse_llm_response` keeps its 5-tuple return shape (dozens of existing test
sites depend on that). The strategy label is produced by an independent
post-hoc pass, `_detect_conviction_strategy(response)`, that mirrors the
parser's cleanup + cascade in the same order. `enhance_packet_with_llm` then
sets the result as ``packet.parser_strategy_succeeded``. The corpus generator
reads it via ``getattr(packet, "parser_strategy_succeeded", None)``.

Strategy identifiers (stable — these are part of the dataset contract):

    metadata_block    — XML <metadata>Conviction: N</metadata>
    plain_conviction  — plain "CONVICTION: N"
    conviction_tag    — <conviction>N</conviction>
    conviction_score  — "Conviction: N/10" / "Conviction Score: N"
    markdown_bold     — **Conviction**: N
    catchall          — any digit within 20 chars of "conviction"
    confidence_label  — "confidence: N", "confidence level: N"
    bare_score        — bare "N/10" alone on a line
"""

from types import SimpleNamespace

import pytest

from src.llm.packet_writer import _detect_conviction_strategy, _parse_llm_response


# ── _detect_conviction_strategy: per-strategy probes ────────────────────────

class TestDetectConvictionStrategy:
    """Each strategy identifier is asserted with a synthetic response that ONLY
    that strategy can match. Order matters in the cascade: each strategy is
    tried only if the previous one(s) returned None, so a probe that happens
    to be parseable by an earlier strategy will report that one instead.
    """

    def test_metadata_block_strategy(self):
        """XML <metadata>Conviction: N</metadata> → 'metadata_block'."""
        response = (
            "<why_now>Pullback to 50-day MA on contracting volume.</why_now>\n"
            "<analysis>Paragraph one.\n\nParagraph two follow-up.</analysis>\n"
            "<metadata>\nConviction: 7\nDirection: LONG\n</metadata>"
        )
        assert _detect_conviction_strategy(response) == "metadata_block"

    def test_plain_conviction_strategy(self):
        """Plain "CONVICTION: N" line outside a <metadata> block → 'plain_conviction'."""
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\nCONVICTION: 8\n"
        )
        assert _detect_conviction_strategy(response) == "plain_conviction"

    def test_conviction_tag_strategy(self):
        """Bare <conviction>N</conviction> tag outside metadata → 'conviction_tag'."""
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "<conviction>6</conviction>\n"
        )
        assert _detect_conviction_strategy(response) == "conviction_tag"

    def test_conviction_score_strategy(self):
        """'Conviction Score: N' (no metadata, no CONVICTION: prefix, no <conviction> tag)
        → 'conviction_score'."""
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "Conviction Score: 9\n"
        )
        assert _detect_conviction_strategy(response) == "conviction_score"

    def test_markdown_bold_strategy(self):
        """'**Conviction**: N' (asterisks flank the stem, then colon-space-N)
        → 'markdown_bold'.

        The conviction_score regex (Stage 4) ``conviction\\s*(?:score)?[:\\s]+(\\d+)``
        does NOT match ``**Conviction**: 7`` because after consuming
        ``conviction`` the next char is ``*`` (not in ``[:\\s]``). Stage 5's
        ``\\*\\*conviction\\*\\*[:\\s]+(\\d+)`` does match.
        """
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "**Conviction**: 7\n"
        )
        assert _detect_conviction_strategy(response) == "markdown_bold"

    def test_catchall_strategy(self):
        """Catch-all: digit within 20 chars of 'conviction', no colon → 'catchall'.

        Earlier strategies all require a colon separator or specific pattern;
        a freeform sentence with the word 'conviction' followed by a number
        without a colon should fall through to stage 6.
        """
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "My conviction is approximately 6\n"
        )
        assert _detect_conviction_strategy(response) == "catchall"

    def test_confidence_label_strategy(self):
        """'confidence: N' (no 'conviction' word at all) → 'confidence_label'."""
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "Overall confidence: 8\n"
        )
        assert _detect_conviction_strategy(response) == "confidence_label"

    def test_bare_score_strategy(self):
        """Standalone 'N/10' on a line by itself, no 'conviction' or 'confidence'
        words anywhere → 'bare_score'."""
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "Final score:\n9/10\n"
        )
        assert _detect_conviction_strategy(response) == "bare_score"

    def test_none_when_no_strategy_matches(self):
        """If conviction can't be extracted at all, _detect_conviction_strategy
        returns None (mirrors conviction=None semantics in the parser)."""
        response = (
            "<why_now>Setup.</why_now><analysis>Body.</analysis>\n"
            "No score given anywhere.\n"
        )
        assert _detect_conviction_strategy(response) is None

    def test_empty_response_returns_none(self):
        """Empty / whitespace-only response → None (no cascade can fire)."""
        assert _detect_conviction_strategy("") is None
        assert _detect_conviction_strategy("   \n  ") is None

    def test_strategy_agrees_with_parser_conviction(self):
        """Whenever _parse_llm_response returns a non-None conviction,
        _detect_conviction_strategy must return a non-None label, and vice
        versa. This catches drift between the two functions.
        """
        # 8 cases — one per strategy — exercising the contract.
        cases = [
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>"
             "<metadata>Conviction: 7</metadata>", 7, "metadata_block"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>CONVICTION: 8", 8,
             "plain_conviction"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>"
             "<conviction>6</conviction>", 6, "conviction_tag"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>Conviction Score: 9",
             9, "conviction_score"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>**Conviction**: 7",
             7, "markdown_bold"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>"
             "My conviction is approximately 6", 6, "catchall"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>Overall confidence: 8",
             8, "confidence_label"),
            ("<why_now>x</why_now><analysis>y\n\nz</analysis>Final score:\n9/10",
             9, "bare_score"),
        ]
        for response, expected_conviction, expected_strategy in cases:
            conv = _parse_llm_response(response)[0]
            strategy = _detect_conviction_strategy(response)
            assert conv == expected_conviction, (
                f"parser conviction mismatch for {expected_strategy!r}: "
                f"got {conv}, want {expected_conviction}"
            )
            assert strategy == expected_strategy, (
                f"detector mismatch for {expected_strategy!r}: got {strategy}"
            )


# ── enhance_packet_with_llm wiring ──────────────────────────────────────────

class TestEnhancePacketWiring:
    """Verify enhance_packet_with_llm sets ``packet.parser_strategy_succeeded``
    using the strategy identifier produced by _detect_conviction_strategy. The
    test uses SimpleNamespace as the packet stand-in so attribute assignment
    is unrestricted (same approach test_corpus_generator uses with MagicMock).
    """

    def _make_packet(self) -> SimpleNamespace:
        """Minimal packet stub with the attributes enhance_packet_with_llm reads/writes."""
        return SimpleNamespace(
            ticker="AAPL",
            company_name="Apple Inc.",
            confidence=7,
            entry_zone="$100",
            stop_invalidation="$95",
            targets="$110",
            event_risk="Low",
            position_sizing=SimpleNamespace(
                allocation_dollars=5000.0, allocation_pct=5.0,
                estimated_risk_dollars=250.0,
            ),
            why_now="",
            deeper_analysis="",
            llm_conviction=None,
            llm_conviction_reason=None,
            llm_timeout_days=None,
            llm_conviction_parse_failed=False,
            parser_strategy_succeeded=None,
        )

    def test_metadata_block_attached_to_packet(self, monkeypatch):
        """enhance_packet_with_llm sets parser_strategy_succeeded='metadata_block'
        when the response is a clean XML metadata block."""
        from src.llm import packet_writer

        response = (
            "<why_now>Pullback to 50-day MA.</why_now>\n"
            "<analysis>Para one.\n\nPara two.</analysis>\n"
            "<metadata>\nConviction: 7\nDirection: LONG\n</metadata>"
        )

        monkeypatch.setattr(packet_writer, "is_llm_available", lambda: True)
        monkeypatch.setattr(packet_writer, "generate", lambda *a, **kw: response)

        packet = self._make_packet()
        features = {"current_price": 150.0, "_score": 80}
        config = {"llm": {"enabled": True}}

        result = packet_writer.enhance_packet_with_llm(packet, features, config)

        assert result.llm_conviction == 7
        assert result.parser_strategy_succeeded == "metadata_block"

    def test_catchall_attached_to_packet(self, monkeypatch):
        """enhance_packet_with_llm sets parser_strategy_succeeded='catchall'
        when only the catch-all strategy (stage 6) matches."""
        from src.llm import packet_writer

        response = (
            "<why_now>Setup looks fine.</why_now>\n"
            "<analysis>Para one.\n\nPara two.</analysis>\n"
            "My conviction is approximately 6\n"
        )

        monkeypatch.setattr(packet_writer, "is_llm_available", lambda: True)
        monkeypatch.setattr(packet_writer, "generate", lambda *a, **kw: response)

        packet = self._make_packet()
        features = {"current_price": 150.0, "_score": 80}
        config = {"llm": {"enabled": True}}

        result = packet_writer.enhance_packet_with_llm(packet, features, config)
        assert result.llm_conviction == 6
        assert result.parser_strategy_succeeded == "catchall"

    def test_none_when_parse_fails(self, monkeypatch):
        """Parse failure path leaves parser_strategy_succeeded as None.

        When `_parse_llm_response` can't recover why_now/deeper_analysis AND
        the response has no recognizable conviction signal, conviction defaults
        to 5 in enhance_packet_with_llm's fallback. parser_strategy_succeeded
        must remain None — the dataset contract is that this field reflects
        which parse strategy actually fired, not the default conviction.
        """
        from src.llm import packet_writer

        # No why_now/analysis tags AND no usable conviction signal — parse fails.
        response = "Just a short, non-XML reply with no usable signal."

        monkeypatch.setattr(packet_writer, "is_llm_available", lambda: True)
        monkeypatch.setattr(packet_writer, "generate", lambda *a, **kw: response)

        packet = self._make_packet()
        features = {"current_price": 150.0, "_score": 80}
        config = {"llm": {"enabled": True}}

        result = packet_writer.enhance_packet_with_llm(packet, features, config)
        # Default conviction is 5 per #168 — strategy still None.
        assert result.parser_strategy_succeeded is None


# ── corpus_generator.{_packet_to_entry, _dry_run_entry} read-through ────────

class TestCorpusGeneratorReadsAttribute:
    """Verify the corpus generator picks up parser_strategy_succeeded from
    the packet attribute. End-to-end coverage of the field flow:
    parser → packet attribute → CorpusEntry field.
    """

    def test_packet_to_entry_reads_strategy_from_packet(self):
        """_packet_to_entry copies packet.parser_strategy_succeeded into the
        CorpusEntry. The literal string flows through when present."""
        from src.evaluation.corpus_generator import _packet_to_entry

        packet = SimpleNamespace(
            ticker="AAPL",
            why_now="The setup is constructive on contracting volume.",
            deeper_analysis="Paragraph one.\n\nParagraph two of the analysis.",
            llm_conviction=7,
            llm_conviction_parse_failed=False,
            parser_strategy_succeeded="metadata_block",
        )
        entry = _packet_to_entry(
            as_of="2024-01-15", ticker="AAPL", model_version="arcis:v1.0.0",
            prompt_sha256="a" * 64, packet=packet,
        )
        assert entry.parser_strategy_succeeded == "metadata_block"

    def test_packet_to_entry_strategy_none_when_packet_missing_attr(self):
        """If packet doesn't have parser_strategy_succeeded at all,
        _packet_to_entry stores None (graceful fallback via getattr default)."""
        from src.evaluation.corpus_generator import _packet_to_entry

        # SimpleNamespace without parser_strategy_succeeded — getattr default fires.
        packet = SimpleNamespace(
            ticker="AAPL",
            why_now="One.",
            deeper_analysis="Two.\n\nThree.",
            llm_conviction=5,
            llm_conviction_parse_failed=True,
        )
        entry = _packet_to_entry(
            as_of="2024-01-15", ticker="AAPL", model_version="arcis:v1.0.0",
            prompt_sha256="b" * 64, packet=packet,
        )
        assert entry.parser_strategy_succeeded is None

    def test_packet_to_entry_strategy_coerces_non_string_to_none(self):
        """Defensive guard (#98): non-string values (e.g. an auto-mocked
        attribute) must collapse to None so the CorpusEntry contract
        ``parser_strategy_succeeded: str | None`` is never violated and JSONL
        serialization can't fail downstream."""
        from src.evaluation.corpus_generator import _packet_to_entry

        # MagicMock-like packet that returns a non-string for the attribute.
        class _FakeMock:
            ticker = "AAPL"
            why_now = "One."
            deeper_analysis = "Two.\n\nThree."
            llm_conviction = 7
            llm_conviction_parse_failed = False
            parser_strategy_succeeded = object()  # not a str — must coerce to None

        entry = _packet_to_entry(
            as_of="2024-01-15", ticker="AAPL", model_version="arcis:v1.0.0",
            prompt_sha256="d" * 64, packet=_FakeMock(),
        )
        assert entry.parser_strategy_succeeded is None

    def test_dry_run_entry_strategy_is_none(self):
        """Dry-run path never calls the parser, so strategy is always None."""
        from src.evaluation.corpus_generator import _dry_run_entry

        entry = _dry_run_entry(
            as_of="2024-01-15", ticker="AAPL",
            model_version="arcis:v1.0.0", prompt_sha256="c" * 64,
        )
        assert entry.parser_strategy_succeeded is None


# ── #108 Lever 1 — batch_mode plumbing ──────────────────────────────────────


class TestBatchModePlumbing:
    """#108 Lever 1 — batch_mode kwarg threading from corpus runner through
    enhance_packet_with_llm to the underlying generate() call. The 2s sleep
    in src/llm/client.py:205 (added for #388 to prevent Ollama overload during
    scan cycles) is gated on batch_mode: corpus runs (which naturally smooth
    request rate via parallelism) skip it; live-scan callers (default) keep it.
    """

    def _make_packet(self) -> SimpleNamespace:
        return SimpleNamespace(
            ticker="AAPL",
            company_name="Apple Inc.",
            confidence=7,
            entry_zone="$100",
            stop_invalidation="$95",
            targets="$110",
            event_risk="Low",
            position_sizing=SimpleNamespace(
                allocation_dollars=5000.0, allocation_pct=5.0,
                estimated_risk_dollars=250.0,
            ),
            why_now="",
            deeper_analysis="",
            llm_conviction=None,
            llm_conviction_reason=None,
            llm_timeout_days=None,
            llm_conviction_parse_failed=False,
            parser_strategy_succeeded=None,
        )

    def test_enhance_packet_threads_batch_mode_through_to_generate(self, monkeypatch):
        """When enhance_packet_with_llm(..., batch_mode=True) is called, the
        underlying client.generate() must receive batch_mode=True as a kwarg.
        """
        from src.llm import packet_writer

        captured_kwargs: list[dict] = []

        def fake_generate(prompt, system_prompt, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return (
                "<why_now>x</why_now><analysis>y\n\nz</analysis>"
                "<metadata>Conviction: 7</metadata>"
            )

        monkeypatch.setattr(packet_writer, "is_llm_available", lambda: True)
        monkeypatch.setattr(packet_writer, "generate", fake_generate)

        packet = self._make_packet()
        packet_writer.enhance_packet_with_llm(
            packet, {"current_price": 150.0, "_score": 80},
            {"llm": {"enabled": True}},
            batch_mode=True,
        )

        assert captured_kwargs, "generate() was never called"
        assert captured_kwargs[0].get("batch_mode") is True

    def test_enhance_packet_default_batch_mode_is_false(self, monkeypatch):
        """Default callers (live scan path) must not opt into batch mode."""
        from src.llm import packet_writer

        captured_kwargs: list[dict] = []

        def fake_generate(prompt, system_prompt, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return (
                "<why_now>x</why_now><analysis>y\n\nz</analysis>"
                "<metadata>Conviction: 7</metadata>"
            )

        monkeypatch.setattr(packet_writer, "is_llm_available", lambda: True)
        monkeypatch.setattr(packet_writer, "generate", fake_generate)

        packet = self._make_packet()
        packet_writer.enhance_packet_with_llm(
            packet, {"current_price": 150.0, "_score": 80},
            {"llm": {"enabled": True}},
        )

        assert captured_kwargs, "generate() was never called"
        # Default must be False (or absent — both mean live-scan behavior).
        assert captured_kwargs[0].get("batch_mode", False) is False

    def test_client_generate_skips_sleep_in_batch_mode(self, monkeypatch):
        """src/llm/client.py:205 ``time.sleep(2)`` must be skipped when
        generate(batch_mode=True). This is the #108 Lever 1 mechanism that
        lets the corpus runner avoid the per-call 2s cooldown without
        affecting the runtime scan path (#388)."""
        from src.llm import client

        sleep_calls: list[float] = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        # Mock requests.post to return a successful response
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        monkeypatch.setattr(client, "_consecutive_failures", 0)
        monkeypatch.setattr(client.time, "sleep", fake_sleep)
        monkeypatch.setattr(client.requests, "post", lambda *a, **kw: mock_resp)

        result = client.generate("hi", "system", batch_mode=True)
        assert result == "Hello world"
        # The 2.0 second sleep must NOT have fired in batch_mode
        assert 2 not in sleep_calls, (
            f"batch_mode=True must skip the 2s cooldown (#108 Lever 1). "
            f"Got sleep_calls={sleep_calls!r}"
        )

    def test_client_generate_sleeps_when_not_batch_mode(self, monkeypatch):
        """Default (batch_mode=False) generate() still fires the 2s cooldown.
        Preserves #388 behavior for the live-scan path."""
        from src.llm import client

        sleep_calls: list[float] = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }
        mock_resp.raise_for_status = MagicMock()

        monkeypatch.setattr(client, "_consecutive_failures", 0)
        monkeypatch.setattr(client.time, "sleep", fake_sleep)
        monkeypatch.setattr(client.requests, "post", lambda *a, **kw: mock_resp)

        result = client.generate("hi", "system")
        assert result == "Hello world"
        # 2s cooldown MUST have fired in default mode (#388 behavior preserved)
        assert 2 in sleep_calls, (
            f"Default mode must still fire the 2s cooldown (#388). "
            f"Got sleep_calls={sleep_calls!r}"
        )
