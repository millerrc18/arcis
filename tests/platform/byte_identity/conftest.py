from __future__ import annotations

from pathlib import Path

import pytest

from .helpers import (
    FIXTURE_DATES,
    PRIMARY_FIXTURE_DATE,
    build_sprint_f_incumbent_strategy,
    fixture_path,
    load_fixture,
)


@pytest.fixture(scope="session")
def sprint_f_strategy():
    return build_sprint_f_incumbent_strategy()


@pytest.fixture(scope="session")
def primary_fixture_date() -> str:
    return PRIMARY_FIXTURE_DATE


@pytest.fixture(scope="session")
def all_fixture_dates() -> tuple[str, ...]:
    return FIXTURE_DATES


@pytest.fixture(scope="session")
def load_sprint_f_fixture():
    def _load(kind: str, as_of_date: str) -> dict:
        return load_fixture(fixture_path(kind, as_of_date))

    return _load
