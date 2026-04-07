"""Tests for safe_numeric type coercion utility."""

import pytest


class TestSafeNumeric:
    def test_string_float(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("25.3") == 25.3

    def test_none_returns_default(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric(None) == 0.0

    def test_unparseable_returns_default(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("abc", default=5) == 5.0

    def test_float_passthrough(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric(25.3) == 25.3

    def test_string_int(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("3", type_=int) == 3

    def test_single_element_tuple(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric((25.3,)) == 25.3

    def test_single_element_list(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric([7]) == 7.0

    def test_int_passthrough(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric(42, type_=int) == 42

    def test_empty_string_returns_default(self):
        from src.utils.type_safety import safe_numeric
        assert safe_numeric("", default=0) == 0.0
