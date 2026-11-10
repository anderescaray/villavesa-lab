"""Shared pytest fixtures for the engine and API test suites."""

from __future__ import annotations

import pytest

from vlab.access.service import Evaluator
from vlab.model import Model, Window


@pytest.fixture(scope="session")
def model() -> Model:
    """The real world model (processed bundle + GTFS), loaded once per session."""
    return Model.load()


@pytest.fixture(scope="session")
def evaluator(model: Model) -> Evaluator:
    return Evaluator(model, Window())
