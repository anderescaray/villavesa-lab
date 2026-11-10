"""Smoke test: the package imports and exposes a version."""

import vlab


def test_version() -> None:
    assert vlab.__version__
