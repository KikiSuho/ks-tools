"""
Deferred log buffer and thread-safe dual-level logger for scrutiny.

Provide pre-logger message buffering via ``DeferredLogBuffer`` and
structured console + file logging via ``SCRLogger``.
``DeferredLogBuffer`` uses mutable ``ClassVar`` state that persists
across tests; call ``DeferredLogBuffer.clear()`` in test teardown to
prevent message bleed.

Classes
-------
DeferredLogBuffer : Buffer for messages captured before the logger exists.
SCRLogger : Thread-safe, dual-level logger with console and file output.

Examples
--------
>>> from scrutiny.output.logger import DeferredLogBuffer
>>> DeferredLogBuffer.clear()
>>> DeferredLogBuffer.capture("warning", "test message")
>>> len(DeferredLogBuffer._messages)
1

"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
    TextIO,
)

from scrutiny.core.enums import LoggerLevel
from scrutiny.core.exceptions import SCRLoggerFileError, handle_errors

if TYPE_CHECKING:
    from scrutiny.configs.dataclasses import GlobalConfig


class DeferredLogBuffer:
    """
    Buffer for messages captured before the logger is available.

    Messages are stored with a severity level and flushed to the
    logger once it is initialized.

    Attributes
    ----------
    _messages : ClassVar[list[tuple[str, str]]]
        Buffered ``(level, message)`` pairs.
    _lock : ClassVar[threading.Lock]
        Thread-safety lock for concurrent access.

    """

    _messages: ClassVar[list[tuple[str, str]]] = []
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def capture(cls, level: str, message: str) -> None:
        """
        Buffer a message for deferred logging.

        Parameters
        ----------
        level : str
            Log level (``"warning"`` or ``"error"``).
        message : str
            Message text.

        """
        with cls._lock:
            cls._messages.append((level, message))

    @classmethod
    def flush(cls, logger: Any) -> None:
        """
        Flush all buffered messages to the logger.

        Parameters
        ----------
        logger : Any
            Logger instance with ``warning()`` and ``error()`` methods.

        """
        # Copy and clear under lock, then emit without holding the lock.
        with cls._lock:
            messages = list(cls._messages)
            cls._messages.clear()
        # Route each buffered message to the appropriate logger method.
        for level, message in messages:
            # Dispatch errors and warnings to separate logger methods
            if level == "error":
                # Emit via logger.error for error-level messages
                logger.error(message)
            else:
                # Default to warning for all other severity levels
                logger.warning(message)

    @classmethod
    def flush_or_stderr(cls, logger: Optional[Any] = None) -> None:
        """
        Flush buffered messages to a logger or to stderr.

        When a logger is available, delegate to ``flush()``.  When no
        logger exists (pre-logger failure), write messages directly to
        stderr so the user still receives diagnostic output.

        Parameters
        ----------
        logger : Optional[Any]
            Logger instance.  When ``None``, messages go to stderr.

        """
        # Delegate to the logger when available; otherwise fall through to stderr.
        if logger is not None:
            cls.flush(logger)
            return
        with cls._lock:
            messages = list(cls._messages)
            cls._messages.clear()
        # Write each buffered message to stderr as a last resort
        for level, message in messages:
            print(f"  [{level.upper()}] {message}", file=sys.stderr)  # noqa: T201

    @classmethod
    def clear(cls) -> None:
        """Remove all buffered messages."""
        with cls._lock:
            cls._messages.clear()


class SCRLogger:
    """
    Thread-safe, dual-level logger with console and file output.

    Console output uses ANSI colors (when available) and respects
    the configured ``LoggerLevel``.  File output always captures at
    the file level (typically VERBOSE) to produce a complete audit
    log.

    Log files are only created in CLI / IDE contexts -- never in CI
    or pre-commit environments (controlled via ``GlobalConfig.create_log``).

    Parameters
    ----------
    project_root : Path
        Project root directory for log file placement.
    global_config : GlobalConfig
        Active configuration controlling levels and log creation.

    Attributes
    ----------
    console_level : LoggerLevel
        Current console verbosity.
    file_level : LoggerLevel
        Current file verbosity.
    log_file : Optional[TextIO]
        Open file handle, or None when logging to file is disabled.
    log_path : Optional[Path]
        Absolute path to the log file, or None.
    use_colors : bool
        Whether ANSI color codes are emitted.

    """

    def __init__(
        self,
        project_root: Path,
        global_config: GlobalConfig,
    ) -> None:
        # Resolve console and file levels (validated by GlobalConfig.__post_init__).
        self.console_level: LoggerLevel = global_config.console_logger_level
        self.file_level: LoggerLevel = global_config.file_logger_level

        # Open log file if enabled.
        self.log_file: Optional[TextIO] = None
        self.log_path: Optional[Path] = None

        # Set up log file path and validate directory when logging is enabled
        if global_config.create_log:
            # Resolve log path and prepare the directory; wrap unexpected errors
            try:
                filename = f"scrutiny_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
                log_dir = (project_root / global_config.log_dir).resolve()
                # Validate that the resolved log directory is within the
                # project root to prevent path traversal via log_dir config.
                resolved_root = project_root.resolve()
                # Reject log directories that escape the project root
                try:
                    # Confirm log_dir is a child of the project root
                    log_dir.relative_to(resolved_root)
                except ValueError as path_error:
                    # Log directory resolves outside project root; block traversal
                    raise SCRLoggerFileError(
                        f"Log directory '{global_config.log_dir}' resolves outside "
                        f"project root: {log_dir}"
                    ) from path_error
                self.log_path = log_dir / filename
                self._prepare_log_dir(self.log_path)
            except SCRLoggerFileError:
                # Already a structured error; let it propagate unchanged
                raise
            except (OSError, TypeError, ValueError) as log_init_error:
                raise SCRLoggerFileError(
                    f"Failed to initialise log file: {log_init_error}"
                ) from log_init_error

        self.use_colors: bool = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self._lock = threading.RLock()

    def __enter__(self) -> SCRLogger:
        """
        Enter the context manager and open the log file handle.

        The file handle is deferred from ``__init__`` so that it is
        always born inside a ``with`` block, preventing handle leaks.

        Returns
        -------
        SCRLogger
            This logger instance.

        """
        # Open the deferred file handle when a log path was configured
        if self.log_path is not None and self.log_file is None:
            self.log_file = self._open_log_file(self.log_path)
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> None:
        """
        Exit the context manager and close the log file.

        Parameters
        ----------
        exc_type : Optional[type]
            Exception type, if an exception was raised.
        exc_val : Optional[BaseException]
            Exception value, if an exception was raised.
        exc_tb : Any
            Traceback object, if an exception was raised.

        """
        self.close()

    @staticmethod
    def _prepare_log_dir(path: Path) -> None:
        """
        Create parent directories for *path*.

        Called during ``__init__`` so that path validation errors are
        raised at construction time (where ``_create_logger`` can catch
        them and fall back to console-only logging).

        Parameters
        ----------
        path : Path
            Log file path whose parent directory should exist.

        Raises
        ------
        SCRLoggerFileError
            On OS or permission errors creating directories.

        """
        # Create the parent directory tree for the log file
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as dir_error:
            # Wrap filesystem errors for structured handling upstream
            raise SCRLoggerFileError(
                f"Failed to create log directory {path.parent}: {dir_error}"
            ) from dir_error

    @staticmethod
    def _open_log_file(path: Path) -> TextIO:
        """
        Open *path* for append-writing.

        Called from ``__enter__`` so that the file handle is always
        created inside a ``with`` block.

        Parameters
        ----------
        path : Path
            Log file path.

        Returns
        -------
        TextIO
            Writable file handle.

        Raises
        ------
        SCRLoggerFileError
            On OS or permission errors.

        """
        # Open for append so multiple runs accumulate in the same file
        try:
            return path.open("a", encoding="utf-8", newline="\n")
        except (OSError, PermissionError) as file_open_error:
            # Wrap filesystem errors for structured handling upstream
            raise SCRLoggerFileError(
                f"Failed to open log file {path}: {file_open_error}"
            ) from file_open_error

    def _format_message(
        self,
        log_text: str,
        color_code: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Format *log_text* for console (with color) and file (plain).

        Parameters
        ----------
        log_text : str
            Text content to format.
        color_code : Optional[str]
            ANSI color code (e.g. ``"31"`` for red).

        Returns
        -------
        tuple[str, str]
            ``(console_message, file_message)``.

        """
        # Wrap with ANSI escape codes when the terminal supports color.
        if self.use_colors and color_code:
            return f"\033[{color_code}m{log_text}\033[0m", log_text
        return log_text, log_text

    def _log(
        self,
        log_text: str,
        min_level: LoggerLevel,
        color_code: Optional[str] = None,
    ) -> None:
        """
        Emit *log_text* to console and/or file based on levels.

        Parameters
        ----------
        log_text : str
            Text to emit.
        min_level : LoggerLevel
            Minimum level required for emission.
        color_code : Optional[str]
            ANSI color code for console.

        """
        with self._lock:
            console_output, file_output = self._format_message(log_text, color_code)

            # Emit to console if the configured level permits.
            if self.console_level >= min_level:
                print(console_output)  # noqa: T201

            # Emit to log file if open and the file level permits.
            if self.log_file is not None and self.file_level >= min_level:
                # Write and flush; degrade gracefully on filesystem errors
                try:
                    self.log_file.write(f"{file_output}\n")
                    self.log_file.flush()
                except OSError as log_write_error:
                    # Warn on stderr rather than crashing the tool run
                    print(  # noqa: T201
                        f"Warning: log write failed: {log_write_error}",
                        file=sys.stderr,
                    )

    # Quiet-level methods are always shown unless output is suppressed.
    def status(self, status_text: str) -> None:
        """
        Log essential progress updates (QUIET level, cyan).

        Parameters
        ----------
        status_text : str
            Status update text.

        """
        self._log(status_text, LoggerLevel.QUIET, "36")

    def success(self, success_text: str) -> None:
        """
        Log success confirmations (QUIET level, green).

        Parameters
        ----------
        success_text : str
            Success confirmation text.

        """
        self._log(success_text, LoggerLevel.QUIET, "32")

    def error(self, error_text: str) -> None:
        """
        Log critical errors (QUIET level, red).

        Parameters
        ----------
        error_text : str
            Error description text.

        """
        self._log(error_text, LoggerLevel.QUIET, "31")

    # Normal-level methods provide standard output for results and warnings.
    def warning(self, warning_text: str) -> None:
        """
        Log non-critical issues (NORMAL level, yellow).

        Parameters
        ----------
        warning_text : str
            Warning description text.

        """
        self._log(warning_text, LoggerLevel.NORMAL, "33")

    def result(self, result_text: str) -> None:
        """
        Log tool results and summaries (NORMAL level, magenta).

        Parameters
        ----------
        result_text : str
            Tool result text.

        """
        self._log(result_text, LoggerLevel.NORMAL, "35")

    def header(self, header_text: str) -> None:
        """
        Log structural headers and banners (NORMAL level, cyan).

        Parameters
        ----------
        header_text : str
            Header/banner text.

        """
        self._log(header_text, LoggerLevel.NORMAL, "36")

    def issue(self, issue_text: str) -> None:
        """
        Log compact issue lines (NORMAL level, no color).

        Parameters
        ----------
        issue_text : str
            Compact issue summary text.

        """
        self._log(issue_text, LoggerLevel.NORMAL, None)

    # Detailed-level methods include expanded metadata and source context.
    def detail(self, detail_text: str) -> None:
        """
        Log expanded output with metadata and source (DETAILED level, no color).

        Parameters
        ----------
        detail_text : str
            Expanded detail text.

        """
        self._log(detail_text, LoggerLevel.DETAILED, None)

    # Verbose-level methods expose internal operations and diagnostics.
    def info(self, info_text: str) -> None:
        """
        Log internal operations (VERBOSE level, reset/default color).

        Parameters
        ----------
        info_text : str
            Informational text.

        """
        self._log(info_text, LoggerLevel.VERBOSE, "0")

    def debug(self, debug_text: str) -> None:
        """
        Log debugging detail (VERBOSE level, grey).

        Parameters
        ----------
        debug_text : str
            Debug detail text.

        """
        self._log(debug_text, LoggerLevel.VERBOSE, "90")

    def write_split(
        self,
        console_text: Optional[str],
        file_text: Optional[str],
    ) -> None:
        """
        Write pre-formatted text to console and file independently.

        Used when console and file levels diverge, requiring different
        formatted output per destination.  Both writes occur under a
        single lock to prevent interleaving.

        Parameters
        ----------
        console_text : Optional[str]
            Text for console (already formatted by ``OutputFormatter``).
        file_text : Optional[str]
            Text for the log file.

        """
        with self._lock:
            # Write to console (pre-formatted by OutputFormatter).
            if console_text:
                formatted_console_text, _ = self._format_message(console_text, None)
                print(formatted_console_text)  # noqa: T201

            # Write to log file independently of console output.
            if file_text and self.log_file is not None:
                # Flush file output; degrade gracefully on write failure
                try:
                    self.log_file.write(f"{file_text}\n")
                    self.log_file.flush()
                except OSError as write_error:
                    # Warn on stderr rather than crashing the tool run
                    print(  # noqa: T201
                        f"Warning: log write failed: {write_error}",
                        file=sys.stderr,
                    )

    def log_tool_output(
        self,
        tool_name: str,
        tool_data: dict[str, Any],
        effective_root: Path,
    ) -> None:
        """
        Format and emit tool issues at the correct tier per destination.

        Delegate to the module-level ``format_and_log_tool_output``
        function which contains the full formatting logic.

        Parameters
        ----------
        tool_name : str
            Tool identifier (e.g. ``"ruff_linter"``, ``"mypy"``).
        tool_data : dict[str, Any]
            Parsed tool output from ``ToolResult.tool_data``.
        effective_root : Path
            Project root for relative path display.

        """
        from scrutiny.output.formatting import (
            format_and_log_tool_output,  # noqa: PLC0415
        )

        format_and_log_tool_output(self, tool_name, tool_data, effective_root)

    @handle_errors
    def close(self) -> None:
        """Close the log file handle if open."""
        with self._lock:
            # Release the file handle when one is open
            if self.log_file is not None:
                # Close the file; clear the reference even on failure
                try:
                    self.log_file.close()
                except OSError as close_error:
                    # Warn on stderr; the finally block still clears the handle
                    print(  # noqa: T201
                        f"Warning: log file close failed: {close_error}",
                        file=sys.stderr,
                    )
                finally:
                    self.log_file = None

    def get_log_info(self) -> dict[str, Any]:
        """
        Return dictionary of current logging configuration.

        Returns
        -------
        dict[str, Any]
            Configuration snapshot for ``--show-config`` output.

        """
        return {
            "console_level": self.console_level.name,
            "file_level": self.file_level.name,
            "log_file_enabled": self.log_file is not None,
            "log_file_path": str(self.log_path) if self.log_path else None,
            "use_colors": self.use_colors,
        }
