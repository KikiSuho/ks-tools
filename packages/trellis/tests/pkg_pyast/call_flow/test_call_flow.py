"""Tests for trellis.pyast.call_flow module.

Covers call flow formatting with width-aware truncation and
SMART call filtering with scoring, visibility, and ordering.
"""

from __future__ import annotations

from trellis.pyast.call_flow import (
    filter_smart_calls,
    format_call_flow_line,
)


def _never_hidden(name: str) -> bool:
    """Visibility predicate that hides nothing."""
    return False


def _hide_private(name: str) -> bool:
    """Visibility predicate that hides underscore-prefixed names."""
    return name.startswith("_")


# ---------------------------------------------------------------------------
# format_call_flow_line
# ---------------------------------------------------------------------------


def test_format_empty_call_list_returns_empty_string() -> None:
    # Arrange
    call_names: list[str] = []

    # Act
    result = format_call_flow_line(call_names, prefix="", max_line_width=100)

    # Assert
    assert result == ""


def test_format_single_call() -> None:
    # Arrange
    call_names = ["setup"]

    # Act
    result = format_call_flow_line(call_names, prefix="    ", max_line_width=100)

    # Assert
    assert "calls: setup" in result
    assert result.startswith("    ")


def test_format_multiple_calls_uses_arrow() -> None:
    # Arrange
    call_names = ["setup", "run", "cleanup"]

    # Act
    result = format_call_flow_line(call_names, prefix="", max_line_width=100)

    # Assert
    assert "setup -> run -> cleanup" in result


def test_format_truncates_when_exceeding_width() -> None:
    # Arrange
    long_calls = [f"function_{index}" for index in range(20)]

    # Act
    result = format_call_flow_line(long_calls, prefix="    ", max_line_width=60)

    # Assert
    assert "... +" in result
    assert "more" in result


def test_format_no_truncation_when_width_zero() -> None:
    # Arrange
    call_names = ["alpha", "beta", "gamma"]

    # Act
    result = format_call_flow_line(call_names, prefix="", max_line_width=0)

    # Assert
    assert "alpha -> beta -> gamma" in result


def test_format_custom_connector() -> None:
    # Arrange
    call_names = ["setup", "run"]
    branch_connector = "\u251c\u2500\u2500 "

    # Act
    result = format_call_flow_line(
        call_names, prefix="", max_line_width=100, connector=branch_connector
    )

    # Assert
    assert result.startswith(branch_connector)
    assert "calls: setup -> run" in result


# ---------------------------------------------------------------------------
# filter_smart_calls
# ---------------------------------------------------------------------------


def test_filter_smart_keeps_high_scoring_sibling_calls() -> None:
    # Arrange
    calls = ["process_data", "print", "setup_config"]
    siblings = frozenset({"process_data", "setup_config"})

    # Act
    result = filter_smart_calls(calls, siblings, frozenset(), _never_hidden)

    # Assert
    assert "process_data" in result
    assert "setup_config" in result


def test_filter_smart_falls_back_when_no_calls_survive() -> None:
    # Arrange
    calls = ["print", "len", "str"]

    # Act
    result = filter_smart_calls(calls, frozenset(), frozenset(), _never_hidden)

    # Assert
    assert result == calls


def test_filter_smart_respects_visibility() -> None:
    # Arrange
    calls = ["_private_setup", "public_run"]
    siblings = frozenset({"_private_setup", "public_run"})

    # Act
    result = filter_smart_calls(calls, siblings, frozenset(), _hide_private)

    # Assert
    assert "_private_setup" not in result


def test_filter_smart_preserves_source_order() -> None:
    # Arrange
    calls = ["validate_input", "process_data", "save_results"]
    siblings = frozenset(calls)

    # Act
    result = filter_smart_calls(calls, siblings, frozenset(), _never_hidden)

    # Assert
    assert result == ["validate_input", "process_data", "save_results"]


def test_filter_smart_falls_back_when_all_hidden() -> None:
    # Arrange
    calls = ["_alpha", "_beta"]

    # Act
    result = filter_smart_calls(calls, frozenset(), frozenset(), _hide_private)

    # Assert
    assert result == calls


def test_filter_smart_truncates_to_max_calls() -> None:
    # Arrange
    calls = [
        "process_data",
        "validate_input",
        "save_results",
        "build_config",
        "execute_pipeline",
        "render_output",
    ]
    siblings = frozenset(calls)

    # Act
    result = filter_smart_calls(calls, siblings, frozenset(), _never_hidden)

    # Assert
    assert len(result) <= 4


def test_filter_smart_imported_names_boost_score() -> None:
    # Arrange
    calls = ["process_data", "some_util"]
    imported = frozenset({"process_data"})

    # Act
    result = filter_smart_calls(calls, frozenset(), imported, _never_hidden)

    # Assert
    assert "process_data" in result
