"""
Per-tool post-execution logging: error extraction and result output.

Handle the formatting and emission of tool results after each tool
completes execution.  Extract error messages from raw tool output,
build summary blocks for both successful and failed runs, and emit
structured log entries through the logger.

Functions
---------
log_completed_result : Emit all post-execution log output for a finished tool run.

Examples
--------
>>> callable(log_completed_result)
True

"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scrutiny.execution.results import ToolResult
from scrutiny.output.formatting import OutputFormatter
from scrutiny.output.logger import SCRLogger

_NOISE_PREFIXES: tuple[str, ...] = ("Found ", "Success:")


def _extract_error_message(raw_output: str) -> str:
    """
    Extract the meaningful error message from tool output.

    Collects contiguous non-noise lines from the beginning of the
    output (skipping leading blanks), stopping at the first noise
    line or blank line after content has been collected.  Noise
    lines such as mypy's ``Found N error`` summary are excluded.

    Parameters
    ----------
    raw_output : str
        Combined stdout + stderr from the tool.

    Returns
    -------
    str
        Newline-joined error message, or ``"unknown error"`` if
        nothing meaningful is found.

    """
    collected_lines: list[str] = []
    # Collect contiguous non-noise lines, skipping leading blanks
    for line in raw_output.splitlines():
        stripped_line = line.strip()
        # Skip leading blank lines; stop at a blank line after content.
        if not stripped_line:
            # Content already collected; a blank line signals the end
            if collected_lines:
                break
            continue
        # Stop at noise lines (mypy summary, etc.).
        if any(stripped_line.startswith(prefix) for prefix in _NOISE_PREFIXES):
            break
        collected_lines.append(stripped_line)
    return "\n".join(collected_lines) if collected_lines else "unknown error"


def _build_fatal_error_summary(tool_name: str, result: ToolResult) -> str:
    """
    Build an error summary for a tool that failed without parsed issues.

    Concatenate stderr and stdout, extract the most relevant error
    message, and format it via ``OutputFormatter.generate_error_summary``.

    Parameters
    ----------
    tool_name : str
        Tool identifier (e.g. ``"ruff_formatter"``, ``"mypy"``).
    result : ToolResult
        Completed result with no parsed issues.

    Returns
    -------
    str
        Formatted error summary block.

    """
    raw_output = (result.stderr or "") + (result.stdout or "")
    raw_output = raw_output.strip()
    error_msg = _extract_error_message(raw_output) if raw_output else "unknown error"
    return OutputFormatter.generate_error_summary(
        tool_name,
        error_msg,
        result.execution_time,
    )


def _log_verbose_command(result: ToolResult, logger: SCRLogger) -> None:
    """
    Log the command flags and exit code at VERBOSE level.

    Extract only the flag tokens between the executable name and the
    trailing file paths, then emit them as a single debug line.

    Parameters
    ----------
    result : ToolResult
        Completed result containing ``tool_data["command"]``.
    logger : SCRLogger
        Logger instance for debug messages.

    """
    command_tokens: list[str] = result.tool_data.get("command", [])
    # Log flag tokens when the tool recorded its command
    if command_tokens:
        file_count = result.files_processed
        # Extract only the flag tokens between executable and file paths.
        flag_tokens = command_tokens[1:-file_count] if file_count > 0 else command_tokens[1:]
        # Emit flags only when there are tokens beyond the executable name
        if flag_tokens:
            logger.debug(f"Command: {' '.join(flag_tokens)}")
    logger.debug(f"Tool Code: {result.exit_code}")


def log_completed_result(
    tool_name: str,
    result: ToolResult,
    tool_config_map: dict[str, Any],
    logger: SCRLogger,
    effective_root: Path,
) -> None:
    """
    Emit all post-execution log output for a finished tool run.

    Centralize the logging previously duplicated between
    ``_run_tool_safe`` (sequential path) and the parallel-execution
    callback.  The function is intentionally **not** decorated with
    ``@handle_errors`` because callers already handle failures.

    Parameters
    ----------
    tool_name : str
        Tool identifier (e.g. ``"ruff_formatter"``, ``"mypy"``).
    result : ToolResult
        Completed execution result to summarize.
    tool_config_map : dict[str, Any]
        Mapping of tool name to its configuration object.  Used to
        retrieve "Checked:" / "Result:" context strings.
    logger : SCRLogger
        Logger instance for status, result, and debug messages.
    effective_root : Path
        Project root for relative path display.

    """
    logger.header(f"\nRunning {tool_name}...")

    # Build summary: fatal error path or normal metrics path.
    is_fatal_error = not result.success and result.issues_found == 0
    if is_fatal_error:
        # Tool crashed without producing parseable issues; extract raw error
        summary = _build_fatal_error_summary(tool_name, result)
    else:
        # Normal path; format file count, issues, and timing metrics
        summary = OutputFormatter.generate_summary(
            tool_name,
            result.files_processed,
            result.issues_found,
            result.issues_fixed,
            result.execution_time,
        )

    # Append "Checked:" context; include "Result:" only on a clean pass.
    checked, result_msg = OutputFormatter.get_tool_context(
        tool_name,
        tool_config_map.get(tool_name),
    )
    # Append context lines when the tool provides them
    if checked:
        summary = f"{summary}\n  Checked: {checked}"
        # Include "Result:" line only when the tool passed cleanly
        if result.issues_found == 0 and result.success:
            summary = f"{summary}\n  Result: {result_msg}"

    logger.result(summary)

    # Emit formatted issue details via the logger's tool output handler.
    if result.tool_data:
        logger.log_tool_output(tool_name, result.tool_data, effective_root)

    # Verbose command and exit code logging.
    _log_verbose_command(result, logger)
