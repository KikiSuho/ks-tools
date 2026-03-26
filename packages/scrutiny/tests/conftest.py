"""Shared helpers for scrutiny test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.execution.services import which
from scrutiny.output.logger import DeferredLogBuffer


@pytest.fixture(autouse=True)
def _cleanup_classvars() -> Iterator[None]:
    """Clear process-global mutable state between tests.

    Prevents ``DeferredLogBuffer._messages`` bleed and stale
    ``which()`` cache entries from polluting subsequent tests.
    """
    DeferredLogBuffer.clear()
    which.cache_clear()
    yield
    DeferredLogBuffer.clear()
    which.cache_clear()


def make_global_config(**overrides: object) -> GlobalConfig:
    """Build a GlobalConfig with default values for testing.

    Parameters
    ----------
    **overrides : object
        Field overrides passed to the GlobalConfig constructor.

    Returns
    -------
    GlobalConfig
        A GlobalConfig instance.
    """
    return GlobalConfig(**overrides)
