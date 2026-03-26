"""Tests for SCRError exception hierarchy and display_tag formatting.

Verifies that each exception subclass carries the correct exit code,
display tag, and message formatting for user-facing output.
"""

from __future__ import annotations

import pytest

from scrutiny.core.exceptions import (
    SCRConfigurationError,
    SCRError,
    SCRLoggerError,
    SCRLoggerFileError,
    SCRLoggerLevelError,
    SCRProjectRootError,
    SCRSystemError,
    SCRTimeoutError,
    SCRToolExecutionError,
    SCRUnexpectedError,
    SCRUserInputError,
    ExitCode,
)


# ====================================== #
#       display_tag per subclass         #
# ====================================== #


@pytest.mark.parametrize(
    "error_cls,expected_tag",
    [
        (SCRError, "[ERROR]"),
        (SCRSystemError, "[SYSTEM]"),
        (SCRProjectRootError, "[PROJECT]"),
        (SCRToolExecutionError, "[TOOL]"),
        (SCRTimeoutError, "[TIMEOUT]"),
        (SCRUserInputError, "[INPUT]"),
        (SCRConfigurationError, "[CONFIG]"),
        (SCRLoggerError, "[LOGGER]"),
        (SCRLoggerLevelError, "[LOGGER]"),
        (SCRLoggerFileError, "[LOGGER]"),
        (SCRUnexpectedError, "[UNEXPECTED]"),
    ],
)
def test_display_tag_value(
    error_cls: type[SCRError],
    expected_tag: str,
) -> None:
    """Test that each exception subclass has the correct display_tag."""
    assert error_cls.display_tag == expected_tag


# ====================================== #
#       exit_code per subclass           #
# ====================================== #


@pytest.mark.parametrize(
    "error_cls,constructor_args,expected_exit_code",
    [
        (SCRError, ("test",), ExitCode.GENERAL),
        (SCRSystemError, ("test",), ExitCode.SYSTEM),
        (SCRProjectRootError, ("test",), ExitCode.PROJECT_ROOT),
        (SCRToolExecutionError, ("tool", "test"), ExitCode.TOOL_EXECUTION),
        (SCRTimeoutError, ("tool", "test", 30), ExitCode.TOOL_EXECUTION),
        (SCRUserInputError, ("test",), ExitCode.USER_INPUT),
        (SCRConfigurationError, ("test",), ExitCode.CONFIGURATION),
        (SCRLoggerError, ("test",), ExitCode.LOGGER),
        (SCRLoggerLevelError, ("test",), ExitCode.LOGGER),
        (SCRLoggerFileError, ("test",), ExitCode.LOGGER),
        (SCRUnexpectedError, ("op", ValueError("oops")), ExitCode.UNEXPECTED),
    ],
)
def test_exit_code_value(
    error_cls: type[SCRError],
    constructor_args: tuple,
    expected_exit_code: int,
) -> None:
    """Test that each exception subclass sets the correct exit code."""
    error = error_cls(*constructor_args)
    assert error.exit_code == expected_exit_code


# ====================================== #
#       message preservation             #
# ====================================== #


def test_base_error_preserves_message() -> None:
    """Test that SCRError stores and returns the message."""
    error = SCRError("something broke")
    assert str(error) == "something broke"


def test_system_error_preserves_message() -> None:
    """Test that SCRSystemError stores and returns the message."""
    error = SCRSystemError("ruff not found")
    assert str(error) == "ruff not found"


def test_tool_execution_error_preserves_tool_name() -> None:
    """Test that SCRToolExecutionError stores the tool name."""
    error = SCRToolExecutionError("mypy", "crashed")
    assert error.tool_name == "mypy"
    assert str(error) == "crashed"


def test_timeout_error_preserves_timeout_seconds() -> None:
    """Test that SCRTimeoutError stores the timeout duration."""
    error = SCRTimeoutError("radon", "timed out", 120)
    assert error.timeout_seconds == 120
    assert error.tool_name == "radon"


def test_unexpected_error_preserves_original() -> None:
    """Test that SCRUnexpectedError wraps the original exception."""
    original = RuntimeError("segfault")
    error = SCRUnexpectedError("main", original)
    assert error.operation == "main"
    assert error.original_error is original
    assert "Unexpected error in main: segfault" in str(error)


# ====================================== #
#       inheritance chain                #
# ====================================== #


def test_all_subclasses_inherit_from_cqerror() -> None:
    """Test that all SCR exceptions are SCRError subclasses."""
    subclasses = [
        SCRSystemError,
        SCRProjectRootError,
        SCRToolExecutionError,
        SCRTimeoutError,
        SCRUserInputError,
        SCRConfigurationError,
        SCRLoggerError,
        SCRLoggerLevelError,
        SCRLoggerFileError,
        SCRUnexpectedError,
    ]
    for cls in subclasses:
        assert issubclass(cls, SCRError), f"{cls.__name__} is not a SCRError subclass"


def test_timeout_inherits_from_tool_execution() -> None:
    """Test that SCRTimeoutError is a SCRToolExecutionError."""
    assert issubclass(SCRTimeoutError, SCRToolExecutionError)


def test_logger_subclasses_inherit_logger_tag() -> None:
    """Test that logger sub-errors inherit the [LOGGER] display_tag."""
    assert SCRLoggerLevelError.display_tag == SCRLoggerError.display_tag
    assert SCRLoggerFileError.display_tag == SCRLoggerError.display_tag


# ====================================== #
#       display_tag in formatted output  #
# ====================================== #


@pytest.mark.parametrize(
    "error_cls,constructor_args",
    [
        (SCRSystemError, ("missing tools",)),
        (SCRConfigurationError, ("bad config",)),
        (SCRUserInputError, ("invalid path",)),
        (SCRProjectRootError, ("no root found",)),
        (SCRLoggerError, ("log failure",)),
        (SCRUnexpectedError, ("op", ValueError("oops"))),
    ],
)
def test_display_tag_formats_cleanly(
    error_cls: type[SCRError],
    constructor_args: tuple,
) -> None:
    """Test that display_tag + message produces clean output."""
    error = error_cls(*constructor_args)
    formatted = f"{error.display_tag} {error}"
    # Tag is at the start, followed by a space, then the message.
    assert formatted.startswith(error.display_tag + " ")
    # No class name in the formatted output.
    assert error_cls.__name__ not in formatted
