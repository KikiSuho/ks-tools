"""Tests for trellis.config module.

Covers build_filter_settings snapshot factory and parse_visibility_args
CLI parsing.
"""

from __future__ import annotations

import pytest

from trellis.config import (
    CallFlowMode,
    Config,
    VisibilitySettings,
    build_filter_settings,
    parse_visibility_args,
)


# ---------------------------------------------------------------------------
# build_filter_settings
# ---------------------------------------------------------------------------


def test_build_filter_settings_captures_enable_ignore_dirs() -> None:
    # Arrange
    expected = Config.ENABLE_IGNORE_DIRS

    # Act
    result = build_filter_settings()

    # Assert
    assert result.enable_ignore_dirs == expected


def test_build_filter_settings_captures_ignore_dirs_as_frozenset() -> None:
    # Arrange
    expected_item = "build"

    # Act
    result = build_filter_settings()

    # Assert
    assert isinstance(result.ignore_dirs, frozenset)
    assert expected_item in result.ignore_dirs


def test_build_filter_settings_captures_doc_extensions() -> None:
    # Arrange
    expected_extension = ".md"

    # Act
    result = build_filter_settings()

    # Assert
    assert expected_extension in result.doc_extensions


def test_build_filter_settings_captures_output_dir() -> None:
    # Arrange
    expected = Config.OUTPUT_DIR

    # Act
    result = build_filter_settings()

    # Assert
    assert result.output_dir == expected


def test_build_filter_settings_override_replaces_default() -> None:
    # Arrange
    custom_output_dir = "custom_output"

    # Act
    result = build_filter_settings(output_dir=custom_output_dir)

    # Assert
    assert result.output_dir == custom_output_dir


# ---------------------------------------------------------------------------
# parse_visibility_args
# ---------------------------------------------------------------------------


def test_parse_visibility_args_empty_returns_defaults() -> None:
    # Arrange
    argv: list[str] = []

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert isinstance(result, VisibilitySettings)
    assert result.show_private == Config.SHOW_PRIVATE
    assert result.show_mangled == Config.SHOW_MANGLED
    assert result.show_dunder == Config.SHOW_DUNDER


@pytest.mark.parametrize(
    "flag, field_name, expected_value",
    [
        pytest.param("--show-private", "show_private", True, id="show-private"),
        pytest.param("--hide-private", "show_private", False, id="hide-private"),
        pytest.param("--show-mangled", "show_mangled", True, id="show-mangled"),
        pytest.param("--hide-mangled", "show_mangled", False, id="hide-mangled"),
        pytest.param("--show-dunder", "show_dunder", True, id="show-dunder"),
        pytest.param("--hide-dunder", "show_dunder", False, id="hide-dunder"),
        pytest.param("--show-types", "show_types", True, id="show-types"),
        pytest.param("--hide-types", "show_types", False, id="hide-types"),
        pytest.param("--show-decorators", "show_decorators", True, id="show-decorators"),
        pytest.param("--hide-decorators", "show_decorators", False, id="hide-decorators"),
    ],
)
def test_parse_visibility_args_individual_flags(
    flag: str, field_name: str, expected_value: bool
) -> None:
    # Arrange
    argv = [flag]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert getattr(result, field_name) == expected_value


def test_parse_visibility_args_show_all_enables_visibility() -> None:
    # Arrange
    argv = ["--show-all"]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.show_private is True
    assert result.show_mangled is True
    assert result.show_dunder is True


def test_parse_visibility_args_hide_all_disables_visibility() -> None:
    # Arrange
    argv = ["--hide-all"]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.show_private is False
    assert result.show_mangled is False
    assert result.show_dunder is False
    assert result.call_flow_mode == CallFlowMode.OFF


@pytest.mark.parametrize(
    "mode_str, expected_mode",
    [
        pytest.param("raw", CallFlowMode.RAW, id="raw"),
        pytest.param("smart", CallFlowMode.SMART, id="smart"),
        pytest.param("off", CallFlowMode.OFF, id="off"),
    ],
)
def test_parse_visibility_args_call_flow_option(
    mode_str: str, expected_mode: CallFlowMode
) -> None:
    # Arrange
    argv = ["--call-flow", mode_str]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.call_flow_mode == expected_mode


def test_parse_visibility_args_call_flow_invalid_warns_and_keeps_default() -> None:
    # Arrange
    argv = ["--call-flow", "invalid"]

    # Act / Assert
    with pytest.warns(UserWarning, match="Unrecognized --call-flow value 'invalid'"):
        result = parse_visibility_args(argv)
    assert result.call_flow_mode == Config.CALL_FLOW_MODE


def test_parse_visibility_args_show_all_upgrades_call_flow_from_off() -> None:
    # Arrange
    argv = ["--call-flow", "off", "--show-all"]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.call_flow_mode == CallFlowMode.SMART


def test_parse_visibility_args_show_all_preserves_explicit_call_flow() -> None:
    # Arrange
    argv = ["--call-flow", "raw", "--show-all"]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.call_flow_mode == CallFlowMode.RAW


def test_parse_visibility_args_hide_all_wins_over_show_all() -> None:
    # Arrange
    argv = ["--show-all", "--hide-all"]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.show_private is False
    assert result.show_mangled is False
    assert result.show_dunder is False
    assert result.call_flow_mode == CallFlowMode.OFF


def test_parse_visibility_args_conflicting_flags_last_in_registry_wins() -> None:
    # Arrange
    argv = ["--show-private", "--hide-private"]

    # Act
    result = parse_visibility_args(argv)

    # Assert
    assert result.show_private is False
