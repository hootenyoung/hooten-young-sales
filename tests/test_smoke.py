"""Smoke test — confirms the test harness and the package import correctly."""

import hy_analytics


def test_package_imports() -> None:
    assert hy_analytics.__version__
