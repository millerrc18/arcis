"""Tests for quality drift metrics computation."""

import os
import sqlite3
import tempfile

import pytest

from src.training.quality_drift import (
    _tokenize,
    distinct_1,
    distinct_2,
    self_bleu,
    vocab_size,
    avg_length,
    compute_all_metrics,
    check_degradation,
    store_metrics,
    get_previous_metrics,
    init_quality_drift_tables,
    _bleu_4_sentence,
    _count_ngrams,
)


@pytest.fixture
def db_path():
    """Create a temporary database."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Hello, world! This is a test.")
        assert tokens == ["hello", "world", "this", "is", "a", "test"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_punctuation_stripping(self):
        tokens = _tokenize('"quoted" (parens) [brackets]')
        assert tokens == ["quoted", "parens", "brackets"]


class TestDistinct1:
    def test_all_unique(self):
        texts = ["alpha beta gamma", "delta epsilon zeta"]
        result = distinct_1(texts)
        assert result == 1.0  # All 6 tokens are unique

    def test_all_same(self):
        texts = ["the the the", "the the"]
        result = distinct_1(texts)
        assert result == pytest.approx(1 / 5)  # 1 unique out of 5 total

    def test_empty_input(self):
        assert distinct_1([]) == 0.0

    def test_empty_strings(self):
        assert distinct_1(["", ""]) == 0.0

    def test_mixed(self):
        texts = ["the cat sat", "the dog sat"]
        # tokens: the, cat, sat, the, dog, sat -> 4 unique / 6 total
        result = distinct_1(texts)
        assert result == pytest.approx(4 / 6)


class TestDistinct2:
    def test_all_unique_bigrams(self):
        texts = ["alpha beta gamma", "delta epsilon zeta"]
        result = distinct_2(texts)
        assert result == 1.0  # All bigrams are unique

    def test_repeated_bigrams(self):
        texts = ["a b c", "a b d"]
        # bigrams: (a,b), (b,c), (a,b), (b,d) -> 3 unique / 4 total
        result = distinct_2(texts)
        assert result == pytest.approx(3 / 4)

    def test_empty_input(self):
        assert distinct_2([]) == 0.0

    def test_single_word_texts(self):
        # No bigrams possible
        assert distinct_2(["hello", "world"]) == 0.0


class TestSelfBleu:
    def test_identical_texts_high_bleu(self):
        texts = [
            "the quick brown fox jumps over the lazy dog near the river bank",
            "the quick brown fox jumps over the lazy dog near the river bank",
            "the quick brown fox jumps over the lazy dog near the river bank",
        ]
        result = self_bleu(texts)
        assert result > 0.5  # Identical texts should have high self-BLEU

    def test_diverse_texts_low_bleu(self):
        texts = [
            "the stock market experienced significant volatility today due to macroeconomic factors",
            "quarterly earnings reports showed mixed results across technology sector companies",
            "federal reserve policy decisions continue impacting treasury yield curve movements",
            "emerging market currencies depreciated against major developed world safe havens",
        ]
        result = self_bleu(texts)
        assert result < 0.5  # Diverse texts should have lower self-BLEU

    def test_single_text_returns_zero(self):
        assert self_bleu(["only one text here"]) == 0.0

    def test_empty_returns_zero(self):
        assert self_bleu([]) == 0.0

    def test_short_texts_returns_zero(self):
        # Texts with fewer than 4 tokens can't compute BLEU-4
        assert self_bleu(["hi", "bye"]) == 0.0


class TestVocabSize:
    def test_basic(self):
        texts = ["hello world", "world foo bar"]
        assert vocab_size(texts) == 4  # hello, world, foo, bar

    def test_empty(self):
        assert vocab_size([]) == 0

    def test_empty_strings(self):
        assert vocab_size(["", ""]) == 0


class TestAvgLength:
    def test_basic(self):
        texts = ["one two three", "four five"]  # 3 tokens, 2 tokens
        result = avg_length(texts)
        assert result == pytest.approx(2.5)

    def test_empty(self):
        assert avg_length([]) == 0.0

    def test_single(self):
        result = avg_length(["a b c d"])
        assert result == pytest.approx(4.0)


class TestBleu4:
    def test_identical_sentences(self):
        tokens = "the quick brown fox jumps over the lazy dog near the bank".split()
        score = _bleu_4_sentence(tokens, tokens)
        assert score == pytest.approx(1.0)

    def test_completely_different(self):
        hyp = "alpha beta gamma delta epsilon zeta eta theta".split()
        ref = "one two three four five six seven eight".split()
        score = _bleu_4_sentence(hyp, ref)
        assert score == 0.0

    def test_short_sentences_return_zero(self):
        assert _bleu_4_sentence(["a", "b"], ["c", "d"]) == 0.0

    def test_partial_overlap(self):
        hyp = "the cat sat on the mat in the room".split()
        ref = "the cat sat on the floor in the house".split()
        score = _bleu_4_sentence(hyp, ref)
        assert 0.0 < score < 1.0


class TestCountNgrams:
    def test_unigrams(self):
        tokens = ["a", "b", "a"]
        counts = _count_ngrams(tokens, 1)
        assert counts[("a",)] == 2
        assert counts[("b",)] == 1

    def test_bigrams(self):
        tokens = ["a", "b", "c"]
        counts = _count_ngrams(tokens, 2)
        assert counts[("a", "b")] == 1
        assert counts[("b", "c")] == 1
        assert len(counts) == 2


class TestComputeAllMetrics:
    def test_returns_all_keys(self):
        texts = [
            "the market showed strong momentum in technology sector today",
            "energy stocks declined amid falling crude oil prices globally",
        ]
        metrics = compute_all_metrics(texts)
        assert "distinct_1" in metrics
        assert "distinct_2" in metrics
        assert "self_bleu" in metrics
        assert "vocab_size" in metrics
        assert "avg_length" in metrics


class TestCheckDegradation:
    def test_no_previous_clean(self):
        current = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 500,
        }
        result = check_degradation(current, previous=None)
        assert result["degradation_flag"] == 0

    def test_distinct_2_drop_detected(self):
        previous = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 500,
        }
        current = {
            "distinct_1": 0.5,
            "distinct_2": 0.4,  # >10% drop from 0.6
            "self_bleu": 0.2,
            "vocab_size": 500,
        }
        result = check_degradation(current, previous)
        assert result["degradation_flag"] == 1
        assert "distinct_2 dropped" in result["details"]

    def test_self_bleu_rise_detected(self):
        previous = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 500,
        }
        current = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.35,  # >15% rise from 0.2
            "vocab_size": 500,
        }
        result = check_degradation(current, previous)
        assert result["degradation_flag"] == 1
        assert "self_bleu rose" in result["details"]

    def test_vocab_shrinkage_detected(self):
        previous = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 1000,
        }
        current = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 800,  # 20% shrinkage
        }
        result = check_degradation(current, previous)
        assert result["degradation_flag"] == 1
        assert "vocab_size shrank" in result["details"]

    def test_critical_low_distinct_1(self):
        current = {
            "distinct_1": 0.05,  # Below 0.1 floor
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 500,
        }
        result = check_degradation(current, previous=None)
        assert result["degradation_flag"] == 1
        assert "distinct_1 critically low" in result["details"]

    def test_critical_high_self_bleu(self):
        current = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.8,  # Above 0.7 ceiling
            "vocab_size": 500,
        }
        result = check_degradation(current, previous=None)
        assert result["degradation_flag"] == 1
        assert "self_bleu critically high" in result["details"]

    def test_healthy_metrics_pass(self):
        previous = {
            "distinct_1": 0.5,
            "distinct_2": 0.6,
            "self_bleu": 0.2,
            "vocab_size": 500,
        }
        current = {
            "distinct_1": 0.52,
            "distinct_2": 0.58,  # Small drop, within tolerance
            "self_bleu": 0.21,  # Small rise, within tolerance
            "vocab_size": 490,
        }
        result = check_degradation(current, previous)
        assert result["degradation_flag"] == 0


class TestStoreAndRetrieveMetrics:
    def test_store_and_retrieve(self, db_path):
        metrics = {
            "distinct_1": 0.45,
            "distinct_2": 0.62,
            "self_bleu": 0.18,
            "vocab_size": 450,
            "avg_length": 85.3,
        }
        metric_id = store_metrics(
            metrics,
            cycle_number=1,
            model_version="v1.0",
            degradation_flag=0,
            details="all clear",
            db_path=db_path,
        )
        assert metric_id is not None

        previous = get_previous_metrics(db_path)
        assert previous is not None
        assert previous["metric_id"] == metric_id
        assert previous["distinct_1"] == pytest.approx(0.45)
        assert previous["model_version"] == "v1.0"

    def test_get_previous_empty_db(self, db_path):
        result = get_previous_metrics(db_path)
        assert result is None

    def test_multiple_stores_returns_latest(self, db_path):
        for i in range(3):
            store_metrics(
                {"distinct_1": 0.5 + i * 0.01, "distinct_2": 0.6, "self_bleu": 0.2, "vocab_size": 500, "avg_length": 80.0},
                cycle_number=i,
                model_version=f"v1.{i}",
                db_path=db_path,
            )
        latest = get_previous_metrics(db_path)
        assert latest["cycle_number"] == 2
        assert latest["model_version"] == "v1.2"
