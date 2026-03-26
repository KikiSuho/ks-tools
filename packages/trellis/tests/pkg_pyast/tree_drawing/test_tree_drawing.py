"""Tests for trellis.pyast.tree_drawing module.

Covers the get_tree_connectors function that produces tree branch
symbols and child prefixes.
"""

from __future__ import annotations

import pytest

from trellis.pyast.tree_drawing import get_tree_connectors


@pytest.mark.parametrize(
    "is_last, expected_connector, expected_prefix_suffix",
    [
        pytest.param(True, "\u2514\u2500\u2500 ", "    ", id="last-item"),
        pytest.param(False, "\u251c\u2500\u2500 ", "\u2502   ", id="non-last-item"),
    ],
)
def test_connectors_for_position(
    is_last: bool, expected_connector: str, expected_prefix_suffix: str
) -> None:
    # Arrange
    prefix = ""

    # Act
    connector, next_prefix = get_tree_connectors(prefix, is_last)

    # Assert
    assert connector == expected_connector
    assert next_prefix == expected_prefix_suffix


def test_next_prefix_includes_parent_prefix() -> None:
    # Arrange
    parent_prefix = "\u2502   "

    # Act
    _connector, next_prefix = get_tree_connectors(parent_prefix, is_last_item=True)

    # Assert
    assert next_prefix.startswith(parent_prefix)
