from src.evaluation.metrics import expectancy


def test_expectancy_basic():
    assert expectancy([1.0, -0.5, 2.0]) == 0.8333333333333334
