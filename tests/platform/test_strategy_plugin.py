"""Tests for Python plugin strategy interface (Sprint 4 cont. Task 2)."""
import pytest

from src.platform.plugin_registry import (
    _clear_registry_for_tests,
    get_plugin,
    list_registered_plugins,
    register_plugin,
)
from src.platform.strategy_plugin import Candidate, StrategyPlugin


@pytest.fixture(autouse=True)
def clean_registry():
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


def test_register_and_retrieve_plugin():
    @register_plugin
    class MockStrategy(StrategyPlugin):
        def strategy_id(self) -> str:
            return "mock_v1"

        def find_candidates(self, as_of, universe, context):
            return [Candidate(
                ticker="AAPL", as_of=as_of, signal_direction="long",
                signal_strength=0.8, metadata={"reason": "test"},
            )]

    plugin = get_plugin("mock_v1")
    assert plugin is not None
    assert plugin.strategy_id() == "mock_v1"


def test_get_plugin_returns_none_for_unknown_id():
    assert get_plugin("nonexistent_strategy") is None


def test_plugin_find_candidates_returns_candidates_list():
    @register_plugin
    class TestPlugin(StrategyPlugin):
        def strategy_id(self) -> str:
            return "test_find"

        def find_candidates(self, as_of, universe, context):
            return [
                Candidate(
                    ticker=t, as_of=as_of, signal_direction="long",
                    signal_strength=0.5,
                )
                for t in universe
            ]

    plugin = get_plugin("test_find")
    candidates = plugin.find_candidates(
        as_of="2026-04-18T10:00:00",
        universe=["AAPL", "MSFT"],
        context={"db_path": "/tmp/test.db"},
    )
    assert len(candidates) == 2
    assert all(isinstance(c, Candidate) for c in candidates)
    assert candidates[0].ticker == "AAPL"


def test_plugin_validate_candidate_default_true():
    @register_plugin
    class DefaultValidator(StrategyPlugin):
        def strategy_id(self) -> str:
            return "validator_default"

        def find_candidates(self, as_of, universe, context):
            return []

    plugin = get_plugin("validator_default")
    cand = Candidate(
        ticker="AAPL", as_of="x", signal_direction="long",
        signal_strength=0.5,
    )
    assert plugin.validate_candidate(cand, {}) is True


def test_plugin_validate_candidate_can_be_overridden():
    @register_plugin
    class StrictValidator(StrategyPlugin):
        def strategy_id(self) -> str:
            return "validator_strict"

        def find_candidates(self, as_of, universe, context):
            return []

        def validate_candidate(self, candidate, market_data):
            return candidate.signal_strength >= 0.9

    plugin = get_plugin("validator_strict")
    strong = Candidate("A", "x", "long", 0.95)
    weak = Candidate("A", "x", "long", 0.5)
    assert plugin.validate_candidate(strong, {}) is True
    assert plugin.validate_candidate(weak, {}) is False


def test_list_registered_plugins():
    @register_plugin
    class A(StrategyPlugin):
        def strategy_id(self) -> str:
            return "zzz_strategy"

        def find_candidates(self, as_of, universe, context):
            return []

    @register_plugin
    class B(StrategyPlugin):
        def strategy_id(self) -> str:
            return "aaa_strategy"

        def find_candidates(self, as_of, universe, context):
            return []

    plugins = list_registered_plugins()
    assert plugins == ["aaa_strategy", "zzz_strategy"]  # sorted


def test_candidate_dataclass_has_expected_fields():
    c = Candidate(
        ticker="AAPL",
        as_of="2026-04-18T10:00:00",
        signal_direction="long",
        signal_strength=0.8,
        metadata={"source": "test"},
    )
    assert c.ticker == "AAPL"
    assert c.signal_direction == "long"
    assert c.signal_strength == 0.8
    assert c.metadata == {"source": "test"}


def test_candidate_metadata_defaults_to_empty_dict():
    c = Candidate(
        ticker="AAPL", as_of="x", signal_direction="long",
        signal_strength=0.5,
    )
    assert c.metadata == {}


def test_cannot_instantiate_abstract_class_directly():
    """StrategyPlugin is ABC — direct instantiation must raise."""
    with pytest.raises(TypeError):
        StrategyPlugin()
