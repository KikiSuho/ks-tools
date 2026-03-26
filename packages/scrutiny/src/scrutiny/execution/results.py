"""
Result data types for scrutiny tool execution.

Contain ``ToolResult`` and ``ResultTotals``; pure data containers
with no dependencies on handler logic. These are the most widely
imported symbols from the execution package.

Classes
-------
ToolResult : Result from running a single code quality tool.
ResultTotals : Aggregated metrics from a list of tool results.

Examples
--------
>>> result = ToolResult("ruff", True, 0, 1.5, 10, "", "", 0, 0)
>>> result.success
True

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """
    Result from running a single code quality tool.

    Parameters
    ----------
    tool : str
        Tool name (e.g. ``"ruff"``, ``"mypy"``).
    success : bool
        Whether the tool exited cleanly (code 0).
    exit_code : int
        Exit code from subprocess, or a synthetic value assigned by the
        orchestrator (``ExitCode.TOOL_FAILURE`` for parse failures in
        ``RadonCCHandler``, or for ``SCRError`` in ``_run_tool_safe``).
    execution_time : float
        Wall-clock seconds.
    files_processed : int
        Number of files fed to the tool.
    stdout : str
        Captured standard output.
    stderr : str
        Captured standard error.
    issues_found : int
        Number of issues detected.
    issues_fixed : int
        Number of issues auto-fixed.
    tool_data : dict[str, Any]
        Extensible dict for parsed results, summaries, etc.
    error_code : int
        SCRError exit code (1-8) when the tool failed with an
        orchestration error (e.g. timeout, missing tool). Default
        ``0`` means no ``SCRError`` occurred. Distinct from
        ``exit_code``, which tracks the subprocess or synthetic exit
        code used by ``determine_exit_code()``.

    """

    tool: str
    success: bool
    exit_code: int
    execution_time: float
    files_processed: int
    stdout: str
    stderr: str
    issues_found: int = 0
    issues_fixed: int = 0
    tool_data: dict[str, Any] = field(default_factory=dict)
    error_code: int = 0


@dataclass
class ResultTotals:
    """
    Aggregated metrics from a list of tool results.

    Computed in a single pass over the results by
    ``_compute_result_totals`` for use in the final status summary.

    Parameters
    ----------
    worst_error_code : int
        Highest ``error_code`` across all results.
    total_issues : int
        Sum of ``issues_found`` across all results.
    total_fixed : int
        Sum of ``issues_fixed`` across all results.
    total_time : float
        Sum of ``execution_time`` across all results.
    max_name_len : int
        Length of the longest tool name (for column alignment).

    """

    worst_error_code: int
    total_issues: int
    total_fixed: int
    total_time: float
    max_name_len: int
