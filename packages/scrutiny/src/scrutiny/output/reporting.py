"""
Post-execution result aggregation, exit code logic, and final status display.

Aggregate tool results, compute process exit codes, and format the
final summary table displayed at the end of a scrutiny run.

Functions
---------
determine_exit_code : Compute process exit code from tool results.
report_final_status : Compute exit code and log the final status summary.

Examples
--------
>>> from scrutiny.output.reporting import determine_exit_code
>>> determine_exit_code([])
0

"""

from __future__ import annotations

from pathlib import Path

from scrutiny.core.exceptions import ExitCode, handle_errors
from scrutiny.execution.results import ResultTotals, ToolResult
from scrutiny.output.logger import SCRLogger

_NORMAL_EXIT_THRESHOLD = 1
_SEPARATOR_WIDTH = 70


def _compute_result_totals(results: list[ToolResult]) -> ResultTotals:
    """
    Aggregate metrics from tool results in a single pass.

    Parameters
    ----------
    results : list[ToolResult]
        Completed tool execution results.

    Returns
    -------
    ResultTotals
        Aggregated worst error code, issue counts, timing, and
        column-alignment width.

    """
    worst_error_code = 0
    total_issues = 0
    total_fixed = 0
    total_time = 0.0
    max_name_len = 0
    # Accumulate worst error code, counts, timing, and name width in one pass
    for tool_result in results:
        worst_error_code = max(worst_error_code, tool_result.error_code)
        total_issues += tool_result.issues_found
        total_fixed += tool_result.issues_fixed
        total_time += tool_result.execution_time
        max_name_len = max(max_name_len, len(tool_result.tool))
    return ResultTotals(
        worst_error_code,
        total_issues,
        total_fixed,
        total_time,
        max_name_len,
    )


def _format_tool_status_line(
    tool_result: ToolResult,
    max_name_len: int,
) -> str:
    """
    Format a single tool's pass/fail status for the summary table.

    Parameters
    ----------
    tool_result : ToolResult
        Completed result for one tool.
    max_name_len : int
        Column width for tool name alignment.

    Returns
    -------
    str
        Formatted status line (e.g. ``"  ruff_linter ... 3 issues"``).

    """
    padded = tool_result.tool.ljust(max_name_len)
    # Report a clean pass when no issues and tool succeeded
    if tool_result.issues_found == 0 and tool_result.success:
        return f"  {padded} ... passed"
    # Report issue count when the tool found problems
    if tool_result.issues_found > 0:
        return f"  {padded} ... {tool_result.issues_found} issues"
    # Report error code details when the tool crashed
    if tool_result.error_code > 0:
        return (
            f"  {padded} ... failed "
            f"(Error Code: {tool_result.error_code} "
            f"{ExitCode(tool_result.error_code).name})"
        )
    return f"  {padded} ... failed"


@handle_errors
def determine_exit_code(results: list[ToolResult]) -> int:
    """
    Compute process exit code from tool results.

    A tool result with ``exit_code > _NORMAL_EXIT_THRESHOLD`` and
    ``success=False`` is classified as an execution error
    (``TOOL_FAILURE``).  Exit code 1 alone, such as the normalised
    radon exit code when issues are found, is not treated as an error;
    those results are detected via ``issues_found > 0`` instead and
    produce ``ISSUES_FOUND``.

    Parameters
    ----------
    results : list[ToolResult]
        Results from all tool runs.

    Returns
    -------
    int
        0 = all clean, ``ExitCode.ISSUES_FOUND`` = issues found,
        ``ExitCode.TOOL_FAILURE`` = execution errors.

    """
    # Check for fatal tool errors (exit code above normal threshold indicates a crash).
    has_errors = any(
        not tool_result.success and tool_result.exit_code > _NORMAL_EXIT_THRESHOLD
        for tool_result in results
    )
    # Check for detected issues across all tools.
    has_issues = any(tool_result.issues_found > 0 for tool_result in results)

    # Prioritize TOOL_FAILURE over ISSUES_FOUND over clean exit.
    if has_errors:
        return ExitCode.TOOL_FAILURE
    # Fall back to ISSUES_FOUND when tools reported problems without crashing
    if has_issues:
        return ExitCode.ISSUES_FOUND
    return 0


def report_final_status(
    results: list[ToolResult],
    discovered_files: list[Path],
    logger: SCRLogger,
) -> int:
    """
    Compute exit code and log the final status summary.

    Parameters
    ----------
    results : list[ToolResult]
        Results from all tool runs.
    discovered_files : list[Path]
        Files that were analyzed.
    logger : SCRLogger
        Logger instance.

    Returns
    -------
    int
        Process exit code.

    """
    exit_code = determine_exit_code(results)
    totals = _compute_result_totals(results)

    # Opening separator and Script Code.
    logger.status("\n" + "=" * _SEPARATOR_WIDTH)
    logger.status(f"Script Code: {exit_code}")

    # Show worst Error Code from tools that raised SCRErrors.
    if totals.worst_error_code > 0:
        logger.status(
            f"Error Code: {totals.worst_error_code} ({ExitCode(totals.worst_error_code).name})",
        )

    # Emit success, issue count, or generic failure headline.
    if exit_code == 0:
        # All tools passed without issues
        logger.success(
            f"All checks passed ({len(discovered_files)} files, {totals.total_time:.2f}s)",
        )
    elif totals.total_issues > 0:
        # At least one tool reported issues
        logger.error(
            f"Issues found: {totals.total_issues} "
            f"(fixed: {totals.total_fixed}, "
            f"remaining: {totals.total_issues - totals.total_fixed})",
        )
    else:
        # Tool crashed without producing parseable issue counts
        logger.error(
            "Tool execution failed — check tool output above for details, "
            "or run --doctor to verify tool availability"
        )

    # Per-tool status table.
    for tool_result in results:
        logger.status(_format_tool_status_line(tool_result, totals.max_name_len))

    logger.status("=" * _SEPARATOR_WIDTH)
    return exit_code
