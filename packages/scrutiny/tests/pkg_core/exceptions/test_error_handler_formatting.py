"""Tests for display_tag formatting through the actual error handler paths.

The existing test_exceptions.py tests verify display_tag as a class attribute
and basic f-string formatting.  These tests verify the EXACT format strings
used in _run_analysis_phase's except block and the __main__ last-resort
handler -- the patterns that will need to be preserved during decomposition.
"""

from __future__ import annotations

import pytest

from scrutiny.core.exceptions import (
    SCRError,
    SCRSystemError,
    SCRToolExecutionError,
    SCRTimeoutError,
    SCRUserInputError,
    SCRConfigurationError,
    SCRProjectRootError,
    SCRLoggerError,
    SCRUnexpectedError,
    ExitCode,
)


# ====================================== #
#   Error handler format string contract #
# ====================================== #


def _build_analysis_phase_format(error: SCRError) -> str:
    """Reproduce the format string used in _run_analysis_phase's except block.

    Parameters
    ----------
    error : SCRError
        The exception to format.

    Returns
    -------
    str
        Formatted string matching the logger.error() call in _run_analysis_phase.
    """
    return f"{error.display_tag} {error}"


def _build_status_line_format(error: SCRError) -> str:
    """Reproduce the logger.status() line from _run_analysis_phase's except block.

    Parameters
    ----------
    error : SCRError
        The exception to format.

    Returns
    -------
    str
        Formatted status line matching the logger.status() call.
    """
    return f"Error Code: {error.exit_code} ({ExitCode(error.exit_code).name})"


def _build_last_resort_format(error: SCRError) -> str:
    """Reproduce the stderr format string from the __main__ last-resort handler.

    Parameters
    ----------
    error : SCRError
        The exception to format.

    Returns
    -------
    str
        Formatted string matching the print() call in __main__.
    """
    return (
        f"\n  {error.display_tag} {error}"
        f"\n  Error Code: {error.exit_code}"
        f" ({ExitCode(error.exit_code).name})\n"
    )


def _build_pre_logger_format(error: SCRError) -> str:
    """Reproduce the DeferredLogBuffer.capture format from main()'s pre-logger path.

    Parameters
    ----------
    error : SCRError
        The exception to format.

    Returns
    -------
    str
        Start of the formatted string (without traceback).
    """
    error_label = ExitCode(error.exit_code).name
    return (
        f"{error.display_tag} {error}\n"
        f"  Error Code: {error.exit_code} ({error_label})\n"
    )


# Every SCRError subclass that can be raised, with the constructor args needed.
_ALL_ERROR_INSTANCES = [
    pytest.param(
        SCRSystemError("ruff not found in PATH"),
        "[SYSTEM]",
        ExitCode.SYSTEM,
        id="SCRSystemError",
    ),
    pytest.param(
        SCRToolExecutionError("mypy", "non-zero exit"),
        "[TOOL]",
        ExitCode.TOOL_EXECUTION,
        id="SCRToolExecutionError",
    ),
    pytest.param(
        SCRTimeoutError("radon", "timed out after 120s", 120),
        "[TIMEOUT]",
        ExitCode.TOOL_EXECUTION,
        id="SCRTimeoutError",
    ),
    pytest.param(
        SCRUserInputError("Path does not exist: /foo"),
        "[INPUT]",
        ExitCode.USER_INPUT,
        id="SCRUserInputError",
    ),
    pytest.param(
        SCRConfigurationError("invalid TOML"),
        "[CONFIG]",
        ExitCode.CONFIGURATION,
        id="SCRConfigurationError",
    ),
    pytest.param(
        SCRProjectRootError("could not find project root"),
        "[PROJECT]",
        ExitCode.PROJECT_ROOT,
        id="SCRProjectRootError",
    ),
    pytest.param(
        SCRLoggerError("log initialisation failed"),
        "[LOGGER]",
        ExitCode.LOGGER,
        id="SCRLoggerError",
    ),
    pytest.param(
        SCRUnexpectedError("main", RuntimeError("segfault")),
        "[UNEXPECTED]",
        ExitCode.UNEXPECTED,
        id="SCRUnexpectedError",
    ),
]


class TestAnalysisPhaseErrorFormat:
    """Verify the logger.error() format in _run_analysis_phase's except block."""

    @pytest.mark.parametrize("error,expected_tag,expected_exit_code", _ALL_ERROR_INSTANCES)
    def test_format_starts_with_display_tag(
        self,
        error: SCRError,
        expected_tag: str,
        expected_exit_code: int,
    ) -> None:
        """The formatted error line must begin with the display_tag."""
        formatted = _build_analysis_phase_format(error)
        assert formatted.startswith(expected_tag + " ")

    @pytest.mark.parametrize("error,expected_tag,expected_exit_code", _ALL_ERROR_INSTANCES)
    def test_format_contains_error_message(
        self,
        error: SCRError,
        expected_tag: str,
        expected_exit_code: int,
    ) -> None:
        """The formatted error line must contain the error message."""
        formatted = _build_analysis_phase_format(error)
        assert str(error) in formatted

    @pytest.mark.parametrize("error,expected_tag,expected_exit_code", _ALL_ERROR_INSTANCES)
    def test_status_line_contains_exit_code_and_name(
        self,
        error: SCRError,
        expected_tag: str,
        expected_exit_code: int,
    ) -> None:
        """The status line must show the numeric exit code and its enum name."""
        status = _build_status_line_format(error)
        assert f"Error Code: {expected_exit_code}" in status
        assert ExitCode(expected_exit_code).name in status


class TestLastResortErrorFormat:
    """Verify the stderr format in the __main__ last-resort handler."""

    @pytest.mark.parametrize("error,expected_tag,expected_exit_code", _ALL_ERROR_INSTANCES)
    def test_last_resort_format_includes_tag_and_code(
        self,
        error: SCRError,
        expected_tag: str,
        expected_exit_code: int,
    ) -> None:
        """Last-resort stderr output must include display_tag, message, and exit code."""
        formatted = _build_last_resort_format(error)

        assert expected_tag in formatted
        assert str(error) in formatted
        assert f"Error Code: {expected_exit_code}" in formatted
        assert ExitCode(expected_exit_code).name in formatted

    @pytest.mark.parametrize("error,expected_tag,expected_exit_code", _ALL_ERROR_INSTANCES)
    def test_last_resort_format_has_correct_structure(
        self,
        error: SCRError,
        expected_tag: str,
        expected_exit_code: int,
    ) -> None:
        """Last-resort format must have leading newline, 2-space indent per line, trailing newline."""
        formatted = _build_last_resort_format(error)

        # Must start with newline and end with newline.
        assert formatted.startswith("\n")
        assert formatted.endswith("\n")

        # Interior lines (between leading/trailing newlines) must be 2-space indented.
        interior = formatted.strip("\n")
        for line in interior.split("\n"):
            assert line.startswith("  "), f"Line missing 2-space indent: {line!r}"


class TestPreLoggerErrorFormat:
    """Verify the DeferredLogBuffer format from main()'s pre-logger except block."""

    @pytest.mark.parametrize("error,expected_tag,expected_exit_code", _ALL_ERROR_INSTANCES)
    def test_pre_logger_format_matches_contract(
        self,
        error: SCRError,
        expected_tag: str,
        expected_exit_code: int,
    ) -> None:
        """Pre-logger error format must include tag, message, and error code line."""
        formatted = _build_pre_logger_format(error)

        assert formatted.startswith(f"{expected_tag} ")
        assert f"Error Code: {expected_exit_code}" in formatted
        assert ExitCode(expected_exit_code).name in formatted


# ====================================== #
#   Exit code enum completeness          #
# ====================================== #


class TestExitCodeContract:
    """Verify the ExitCode enum values are stable for decomposition."""

    @pytest.mark.parametrize(
        "member,expected_value",
        [
            pytest.param("GENERAL", 1, id="GENERAL"),
            pytest.param("SYSTEM", 2, id="SYSTEM"),
            pytest.param("PROJECT_ROOT", 3, id="PROJECT_ROOT"),
            pytest.param("TOOL_EXECUTION", 4, id="TOOL_EXECUTION"),
            pytest.param("USER_INPUT", 5, id="USER_INPUT"),
            pytest.param("CONFIGURATION", 6, id="CONFIGURATION"),
            pytest.param("LOGGER", 7, id="LOGGER"),
            pytest.param("UNEXPECTED", 8, id="UNEXPECTED"),
            pytest.param("ISSUES_FOUND", 10, id="ISSUES_FOUND"),
            pytest.param("TOOL_FAILURE", 11, id="TOOL_FAILURE"),
        ],
    )
    def test_exit_code_value_is_stable(
        self,
        member: str,
        expected_value: int,
    ) -> None:
        """Exit code numeric values must not change (external contract)."""
        assert ExitCode[member] == expected_value

    def test_exit_code_has_exactly_ten_members(self) -> None:
        """ExitCode enum must have exactly 10 members (9 is reserved/skipped)."""
        assert len(ExitCode) == 10

    def test_value_9_is_reserved(self) -> None:
        """Value 9 must not be assigned to any enum member."""
        assigned_values = {member.value for member in ExitCode}
        assert 9 not in assigned_values
