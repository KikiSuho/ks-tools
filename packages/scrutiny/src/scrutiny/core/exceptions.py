"""
Exception hierarchy and error-handling decorator for scrutiny.

All exceptions derive from ``SCRError``. Each subclass maps to a specific
``ExitCode`` member so the CLI can return a meaningful exit status.

Classes
-------
ExitCode : Process exit codes for the scrutiny CLI.
SCRError : Base exception for all scrutiny errors.
SCRSystemError : Raised when system requirements are not met.
SCRProjectRootError : Raised when the project root cannot be determined.
SCRToolExecutionError : Raised when a tool fails to execute.
SCRTimeoutError : Raised when a tool execution times out.
SCRUserInputError : Raised when the user provides invalid input.
SCRConfigurationError : Raised when configuration is invalid.
SCRLoggerError : Base exception for all logger-related errors.
SCRLoggerLevelError : Raised when an invalid log level is provided.
SCRLoggerFileError : Raised when there is an issue with the log file.
SCRUnexpectedError : Raised when an unexpected error occurs.

Functions
---------
handle_errors : Catch unexpected errors and wrap with SCRUnexpectedError.
format_scr_error : Format a SCRError for human-readable output.

Examples
--------
>>> error = SCRError("something failed", ExitCode.GENERAL)
>>> error.exit_code
1

"""

from __future__ import annotations

from enum import Enum, IntEnum
from functools import wraps
from typing import Any, ClassVar, TypeVar


class ExitCode(IntEnum):
    """
    Process exit codes for the scrutiny CLI.

    Exit code 0 indicates success and has no enum member. Value 9
    is reserved for future use and intentionally unassigned.

    Attributes
    ----------
    GENERAL : int
        Phase 1/2: general / unspecified error.
    SYSTEM : int
        Phase 1/2: system requirements not met (also ``--doctor`` mode).
    PROJECT_ROOT : int
        Phase 1/2: cannot determine project root.
    TOOL_EXECUTION : int
        Phase 1/2: tool execution or timeout failure.
    USER_INPUT : int
        Phase 1/2: invalid user input.
    CONFIGURATION : int
        Phase 1/2: invalid configuration.
    LOGGER : int
        Phase 1/2: logger initialisation or file error.
    UNEXPECTED : int
        Phase 1/2: unexpected exception.
    ISSUES_FOUND : int
        Phase 3: issues detected, all tools ran successfully.
    TOOL_FAILURE : int
        Phase 3: tool execution failure during analysis.

    """

    GENERAL = 1
    SYSTEM = 2
    PROJECT_ROOT = 3
    TOOL_EXECUTION = 4
    USER_INPUT = 5
    CONFIGURATION = 6
    LOGGER = 7
    UNEXPECTED = 8
    ISSUES_FOUND = 10
    TOOL_FAILURE = 11


class SCRError(Exception):
    """
    Base exception for all scrutiny errors.

    Parameters
    ----------
    message : str
        Human-readable error description.
    exit_code : int
        Process exit code (default ``ExitCode.GENERAL``).

    Attributes
    ----------
    exit_code : int
        Process exit code associated with this error category.
    display_tag : str
        Human-readable tag for formatted output (e.g. ``"[ERROR]"``).

    """

    display_tag: ClassVar[str] = "[ERROR]"

    def __init__(self, message: str, exit_code: int = ExitCode.GENERAL):
        super().__init__(message)
        self.exit_code = exit_code


class SCRSystemError(SCRError):
    """
    Raised when system requirements are not met.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    display_tag: ClassVar[str] = "[SYSTEM]"

    def __init__(self, message: str):
        super().__init__(message, exit_code=ExitCode.SYSTEM)


class SCRProjectRootError(SCRError):
    """
    Raised when the project root cannot be determined.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    display_tag: ClassVar[str] = "[PROJECT]"

    def __init__(self, message: str):
        super().__init__(message, exit_code=ExitCode.PROJECT_ROOT)


class SCRToolExecutionError(SCRError):
    """
    Raised when a code quality tool fails to execute.

    Parameters
    ----------
    tool_name : str
        Name of the tool that failed.
    message : str
        Human-readable error description.

    Attributes
    ----------
    tool_name : str
        Name of the tool that failed.

    """

    display_tag: ClassVar[str] = "[TOOL]"

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(message, exit_code=ExitCode.TOOL_EXECUTION)


class SCRTimeoutError(SCRToolExecutionError):
    """
    Raised when a tool execution times out.

    Parameters
    ----------
    tool_name : str
        Name of the tool that timed out.
    message : str
        Human-readable error description.
    timeout_seconds : int
        Number of seconds before the timeout occurred.

    Attributes
    ----------
    timeout_seconds : int
        Number of seconds before the timeout occurred.

    """

    display_tag: ClassVar[str] = "[TIMEOUT]"

    def __init__(self, tool_name: str, message: str, timeout_seconds: int):
        self.timeout_seconds = timeout_seconds
        super().__init__(tool_name, message)


class SCRUserInputError(SCRError):
    """
    Raised when the user provides invalid input.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    display_tag: ClassVar[str] = "[INPUT]"

    def __init__(self, message: str):
        super().__init__(message, exit_code=ExitCode.USER_INPUT)


class SCRConfigurationError(SCRError):
    """
    Raised when configuration is invalid.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    display_tag: ClassVar[str] = "[CONFIG]"

    def __init__(self, message: str):
        super().__init__(message, exit_code=ExitCode.CONFIGURATION)


class SCRLoggerError(SCRError):
    """
    Base exception for all logger-related errors.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    display_tag: ClassVar[str] = "[LOGGER]"

    def __init__(self, message: str):
        super().__init__(message, exit_code=ExitCode.LOGGER)


class SCRLoggerLevelError(SCRLoggerError):
    """
    Raised when an invalid log level is provided.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    def __init__(self, message: str):
        super().__init__(message)


class SCRLoggerFileError(SCRLoggerError):
    """
    Raised when there is an issue with the log file.

    Parameters
    ----------
    message : str
        Human-readable error description.

    """

    def __init__(self, message: str):
        super().__init__(message)


class SCRUnexpectedError(SCRError):
    """
    Raised when an unexpected error occurs.

    Parameters
    ----------
    operation : str
        Name of the operation that failed.
    original_error : Exception
        The underlying exception that was caught.

    Attributes
    ----------
    operation : str
        Name of the operation that failed.
    original_error : Exception
        The underlying exception that was caught.

    """

    display_tag: ClassVar[str] = "[UNEXPECTED]"

    def __init__(self, operation: str, original_error: Exception):
        self.operation = operation
        self.original_error = original_error
        error_message = f"Unexpected error in {operation}: {original_error!s}"
        super().__init__(error_message, exit_code=ExitCode.UNEXPECTED)


EnumT = TypeVar("EnumT", bound=Enum)
_FuncT = TypeVar("_FuncT")


def handle_errors(func: _FuncT) -> _FuncT:
    """
    Catch unexpected errors and wrap with SCRUnexpectedError.

    Allow SCRError exceptions to propagate normally while wrapping any other
    exceptions in SCRUnexpectedError with contextual information.

    Parameters
    ----------
    func : _FuncT
        Function to be decorated with standardized error handling.

    Returns
    -------
    _FuncT
        Wrapped function with standardized error handling.

    Raises
    ------
    SCRError
        Passes through any SCRError exceptions without modification.
    SCRUnexpectedError
        Wraps any non-SCRError exceptions with function context.

    """

    @wraps(func)  # type: ignore[arg-type]
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Execute the wrapped function and catch non-SCR exceptions
        try:
            return func(*args, **kwargs)  # type: ignore[operator]
        except SCRError:
            # Allow SCR exceptions to propagate unchanged
            raise
        except Exception as error:
            # Non-SCR exceptions are wrapped in SCRUnexpectedError.
            raise SCRUnexpectedError(func.__name__, error) from error  # type: ignore[attr-defined]

    return wrapper  # type: ignore[return-value]


def format_scr_error(error: SCRError) -> str:
    r"""
    Format a ``SCRError`` for human-readable output.

    Parameters
    ----------
    error : SCRError
        The error to format.

    Returns
    -------
    str
        Canonical ``"{tag} {message}\n  Error Code: {code} ({name})"`` string.

    """
    return (
        f"{error.display_tag} {error}\n"
        f"  Error Code: {error.exit_code} ({ExitCode(error.exit_code).name})"
    )
