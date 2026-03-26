"""
Output formatting utilities for scrutiny tool results.

Render structured tool data into human-readable console and file
output at multiple verbosity tiers.

Functions
---------
format_and_log_tool_output : Format tool issues and emit them to the logger.

Classes
-------
SourceReader : Read and cache source file lines for issue context display.
OutputFormatter : Format tool output for display via static dispatch.

Examples
--------
>>> from scrutiny.output.formatting import OutputFormatter
>>> summary = OutputFormatter.generate_summary("mypy", 5, 0)
>>> "mypy" in summary
True

"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Optional,
)

from scrutiny.core.enums import LoggerLevel
from scrutiny.core.tool_data import RADON_COMPLEXITY_GRADES
from scrutiny.output import relative_display_path

if TYPE_CHECKING:
    from scrutiny.output.logger import SCRLogger

_ERROR_INDENT_WIDTH = 9

# ====================================== #
#         OUTPUT FORMATTING              #
# ====================================== #


class SourceReader:
    """
    Read and cache source file lines for issue context display.

    The cache is intentionally unbounded because the CLI process is
    short-lived and exits after each run.  Call ``clear_cache()`` in
    test teardown to prevent stale data between test cases.

    Attributes
    ----------
    _source_cache : ClassVar[dict[str, list[str]]]
        Cache of file path to line contents.

    """

    _source_cache: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Remove all cached source file contents."""
        cls._source_cache.clear()

    @classmethod
    def read_source_context(
        cls,
        file_path: str,
        line_number: int,
        context_lines: int = 2,
    ) -> list[str]:
        """
        Read source lines around an issue location.

        Parameters
        ----------
        file_path : str
            Path to the source file.
        line_number : int
            1-indexed line number of the issue.
        context_lines : int
            Number of lines before and after to include.

        Returns
        -------
        list[str]
            Formatted lines like ``'    10 | import os'``,
            or empty list if the file cannot be read.

        """
        # Lazily read and cache file contents on first access.
        if file_path not in cls._source_cache:
            # Read file contents; fall back to empty on read failure
            try:
                source_path = Path(file_path)
                file_lines = source_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                # File unreadable; cache empty list to avoid retrying
                file_lines = []
            cls._source_cache[file_path] = file_lines

        file_lines = cls._source_cache[file_path]
        # Return empty when file could not be loaded.
        if not file_lines:
            return []

        # Extract the surrounding context window and format with line numbers.
        start = max(0, line_number - 1 - context_lines)
        end = min(len(file_lines), line_number + context_lines)
        result: list[str] = []
        # Format each line in the context window with its line number
        for line_index in range(start, end):
            display_number = line_index + 1
            result.append(f"      {display_number:>4} | {file_lines[line_index]}")
        return result


class OutputFormatter:
    """
    Format tool output for display.

    Provide static methods to generate summaries, format individual
    tool issues, and compose clean-pass messages.  All public methods
    are static -- no instances are created.

    Attributes
    ----------
    _formatter_registry : ClassVar[dict[str, Callable[..., list[str]]]]
        Dispatch table mapping tool names to issue-formatting functions.
    _context_registry : ClassVar[dict[str, Callable[[Any], tuple[str, str]]]]
        Dispatch table mapping tool names to context-description functions.

    """

    _formatter_registry: ClassVar[dict[str, Callable[..., list[str]]]] = {}
    _context_registry: ClassVar[dict[str, Callable[[Any], tuple[str, str]]]] = {}

    @staticmethod
    def generate_summary(
        tool_name: str,
        files_processed: int,
        issues_found: int,
        issues_fixed: int = 0,
        execution_time: float = 0.0,
        extra_metrics: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Generate a standardized summary block for a tool run.

        Parameters
        ----------
        tool_name : str
            Tool name for the header.
        files_processed : int
            Number of files processed.
        issues_found : int
            Number of issues detected.
        issues_fixed : int
            Number of issues automatically fixed.
        execution_time : float
            Execution time in seconds.
        extra_metrics : Optional[dict[str, Any]]
            Additional tool-specific metrics to append.

        Returns
        -------
        str
            Multi-line summary string.

        """
        lines = [f"[{tool_name}]", f"  Files: {files_processed}"]

        # Show found/fixed/remaining breakdown when fixes occurred.
        if issues_fixed > 0:
            # Detailed breakdown showing what was found, fixed, and remaining
            lines.append(f"  Found: {issues_found}")
            lines.append(f"  Fixed: {issues_fixed}")
            lines.append(f"  Remaining: {issues_found - issues_fixed}")
        else:
            # Single issue count when no auto-fixes ran
            lines.append(f"  Issues: {issues_found}")

        # Append any extra tool-specific metrics (e.g. complexity scores).
        if extra_metrics:
            # Emit each metric as a key-value pair
            for key, value in extra_metrics.items():
                lines.append(f"  {key}: {value}")

        lines.append(f"  Time: {execution_time:.2f}s")
        return "\n".join(lines)

    @staticmethod
    def generate_error_summary(
        tool_name: str,
        error_message: str,
        execution_time: float = 0.0,
    ) -> str:
        """
        Generate a summary block for a tool that failed with a fatal error.

        Used instead of ``generate_summary`` when a tool exits with a
        non-zero code but produces zero parsed issues (e.g., mypy
        exit-code 2 "Duplicate module").

        Parameters
        ----------
        tool_name : str
            Tool name for the header.
        error_message : str
            Meaningful error message extracted from tool output.
        execution_time : float
            Execution time in seconds.

        Returns
        -------
        str
            Multi-line summary string.

        """
        indent = " " * _ERROR_INDENT_WIDTH
        indented_message = error_message.replace("\n", f"\n{indent}")
        lines = [
            f"[{tool_name}]",
            f"  Error: {indented_message}",
            f"  Time: {execution_time:.2f}s",
        ]
        return "\n".join(lines)

    @staticmethod
    def _append_source_context(
        lines: list[str],
        filename: str,
        line_number: int,
        context_lines: int = 2,
        embedded_source: Optional[str] = None,
    ) -> None:
        """
        Append source-context lines from file or embedded source.

        Parameters
        ----------
        lines : list[str]
            Accumulator to extend with context lines.
        filename : str
            Source file path.
        line_number : int
            Target line number.
        context_lines : int
            Number of surrounding lines above and below.
        embedded_source : Optional[str]
            Pre-extracted source code (Bandit).  When provided, used
            instead of reading from disk.

        """
        # Use pre-extracted source when available (Bandit embeds code in JSON).
        if embedded_source:
            lines.extend(
                f"      {source_line}" for source_line in embedded_source.rstrip("\n").split("\n")
            )
        else:
            # Read source context from disk for other tools.
            source_context = SourceReader.read_source_context(
                filename,
                line_number,
                context_lines=context_lines,
            )
            lines.extend(source_context)

    @staticmethod
    def _format_ruff_issues(
        tool_data: dict[str, Any],
        effective_root: Path,
        *,
        show_metadata: bool = False,
        show_source: bool = False,
        show_fixed: bool = False,
    ) -> list[str]:
        """
        Format ruff/ruff_linter issues into display lines.

        Parameters
        ----------
        tool_data : dict[str, Any]
            Parsed tool output.
        effective_root : Path
            Project root for relative path display.
        show_metadata : bool
            Include fixable flag and rule URL (DETAILED+).
        show_source : bool
            Include source code context (DETAILED+).
        show_fixed : bool
            Include items fixed by Ruff auto-fix (VERBOSE).

        Returns
        -------
        list[str]
            Formatted display lines for Ruff issues.

        """
        lines: list[str] = []
        # Format each ruff issue with location, code, and message
        for issue in tool_data.get("issues", []):
            # Build the base issue line (location + code + message).
            display_path = relative_display_path(issue.filename, effective_root)
            issue_line = (
                f"  {display_path}:{issue.line}:{issue.column}: {issue.code} {issue.message}"
            )
            # Append optional fixable badge and documentation URL.
            if show_metadata and issue.fixable:
                issue_line += " [fixable]"
            lines.append(issue_line)
            if show_metadata and issue.url:
                lines.append(f"    {issue.url}")
            # Source context reads from disk; use the absolute path.
            if show_source:
                OutputFormatter._append_source_context(lines, issue.filename, issue.line)

        # VERBOSE: show items that Ruff auto-fixed.
        if show_fixed:
            fixed_lines = OutputFormatter._format_ruff_fixed_items(tool_data, effective_root)
            # Append fixed-item details when the formatter produced output
            if fixed_lines:
                lines.extend(fixed_lines)

        return lines

    @staticmethod
    def _format_ruff_fixed_items(
        tool_data: dict[str, Any],
        effective_root: Path,
    ) -> list[str]:
        """
        Build display lines for issues that Ruff auto-fixed.

        Compare ``initial_issues`` against ``issues`` to determine which
        entries were removed by the fix pass.

        Parameters
        ----------
        tool_data : dict[str, Any]
            Parsed tool output containing ``initial_issues``, ``issues``,
            and ``fixed_count``.
        effective_root : Path
            Project root for relative path display.

        Returns
        -------
        list[str]
            Display lines listing each fixed issue, or empty list if
            nothing was fixed.

        """
        initial_issues = tool_data.get("initial_issues", [])
        remaining_issues = tool_data.get("issues", [])
        fixed_count = tool_data.get("fixed_count", 0)
        # Nothing to report when no issues existed or none were fixed.
        if not initial_issues or fixed_count == 0:
            return []

        # Build lookup of remaining issue identities.
        remaining_keys: set[tuple[str, int, int, str]] = {
            (issue.filename, issue.line, issue.column, issue.code) for issue in remaining_issues
        }

        # Collect issues present initially but absent after fix.
        fixed_lines: list[str] = ["  Fixed by Ruff:"]
        for issue in initial_issues:
            identity = (issue.filename, issue.line, issue.column, issue.code)
            # Include issues that were present initially but removed by auto-fix
            if identity not in remaining_keys:
                display_path = relative_display_path(issue.filename, effective_root)
                fixed_lines.append(
                    f"    {display_path}:{issue.line}:{issue.column}: {issue.code} {issue.message}"
                )
        return fixed_lines

    @staticmethod
    def _format_mypy_issues(
        tool_data: dict[str, Any],
        effective_root: Path,
        *,
        show_metadata: bool = False,
        show_source: bool = False,
    ) -> list[str]:
        """
        Format mypy issues into display lines.

        Parameters
        ----------
        tool_data : dict[str, Any]
            Parsed tool output.
        effective_root : Path
            Project root for relative path display.
        show_metadata : bool
            Include error code suffix (DETAILED+).
        show_source : bool
            Include source code context (DETAILED+).

        Returns
        -------
        list[str]
            Formatted display lines for mypy issues.

        """
        lines: list[str] = []
        # Format each mypy issue with file, line, severity, and message
        for issue in tool_data.get("issues", []):
            # Build optional suffixes for error code and column number.
            display_path = relative_display_path(issue["file"], effective_root)
            code_suffix = f"  [{issue['code']}]" if show_metadata and issue.get("code") else ""
            column_suffix = f":{issue['column']}" if issue.get("column") else ""
            lines.append(
                f"  {display_path}:{issue['line']}{column_suffix}: "
                f"{issue['severity']}: {issue['message']}{code_suffix}",
            )
            # Source context reads from disk; use the absolute path.
            if show_source:
                OutputFormatter._append_source_context(lines, issue["file"], issue["line"])
        return lines

    @staticmethod
    def _format_radon_issues(
        tool_data: dict[str, Any],
        effective_root: Path,
        *,
        show_metadata: bool = False,
        show_source: bool = False,
    ) -> list[str]:
        """
        Format radon issues into display lines.

        Parameters
        ----------
        tool_data : dict[str, Any]
            Parsed tool output.
        effective_root : Path
            Project root for relative path display.
        show_metadata : bool
            Include type and classname info (DETAILED+).
        show_source : bool
            Include source code context (DETAILED+).

        Returns
        -------
        list[str]
            Formatted display lines for Radon issues.

        """
        lines: list[str] = []
        # Format each radon function entry with complexity grade and score
        for func_entry in tool_data.get("functions", []):
            # Optionally qualify function name with its owning class.
            display_name = func_entry["name"]
            class_name = func_entry.get("classname", "")
            # Qualify with class name when metadata display is enabled
            if show_metadata and class_name:
                display_name = f"{class_name}.{display_name}"
            # Build the complexity line with grade and score.
            display_path = relative_display_path(func_entry["file"], effective_root)
            line = (
                f"  {display_path}:{func_entry['line']} "
                f"{display_name} - "
                f"{func_entry['grade']} ({func_entry['complexity']})"
            )
            # Append function type tag when metadata is requested.
            if show_metadata:
                function_type = func_entry.get("type", "")
                # Append the function type tag when available
                if function_type:
                    line += f"  [{function_type}]"
            lines.append(line)
            # Source context reads from disk; use the absolute path.
            if show_source:
                OutputFormatter._append_source_context(
                    lines, func_entry["file"], func_entry["line"], context_lines=0
                )
        return lines

    @staticmethod
    def _format_bandit_issues(
        tool_data: dict[str, Any],
        effective_root: Path,
        *,
        show_metadata: bool = False,
        show_source: bool = False,
    ) -> list[str]:
        """
        Format bandit issues into display lines.

        Parameters
        ----------
        tool_data : dict[str, Any]
            Parsed tool output.
        effective_root : Path
            Project root for relative path display.
        show_metadata : bool
            Include test_name and URL (DETAILED+).
        show_source : bool
            Include source code context (DETAILED+).

        Returns
        -------
        list[str]
            Formatted display lines for Bandit issues.

        """
        lines: list[str] = []
        # Format each bandit finding with severity, confidence, and description
        for issue in tool_data.get("issues", []):
            # Build issue line with optional test name and severity/confidence tag.
            display_path = relative_display_path(issue.filename, effective_root)
            issue_line = f"  {display_path}:{issue.line_number}: {issue.test_id}"
            if show_metadata and issue.test_name:
                issue_line += f" {issue.test_name}"
            issue_line += f" [{issue.severity}/{issue.confidence}] {issue.issue_text}"
            lines.append(issue_line)
            if show_metadata and issue.more_info:
                lines.append(f"    {issue.more_info}")
            # Source context reads from disk; use the absolute path.
            if show_source:
                OutputFormatter._append_source_context(
                    lines,
                    issue.filename,
                    issue.line_number,
                    embedded_source=issue.source_code,
                )
        return lines

    @staticmethod
    def format_tool_issues(
        tool_name: str,
        tool_data: dict[str, Any],
        effective_root: Path,
        *,
        show_metadata: bool = False,
        show_source: bool = False,
        show_fixed: bool = False,
    ) -> str:
        """
        Render parsed ``tool_data`` into human-readable issue strings.

        Dispatch by *tool_name* to format each tool's structured data.

        Parameters
        ----------
        tool_name : str
            Tool identifier (e.g. ``"ruff_linter"``, ``"mypy"``).
        tool_data : dict[str, Any]
            Parsed tool output from ``ToolResult.tool_data``.
        effective_root : Path
            Project root for relative path display.
        show_metadata : bool
            Include extended metadata per issue (DETAILED+).
        show_source : bool
            Include source code context (DETAILED+).
        show_fixed : bool
            Include items fixed by Ruff auto-fix (VERBOSE).

        Returns
        -------
        str
            Multi-line string of formatted issues, or empty string
            if there are no issues to display.

        """
        # Dispatch to the tool-specific formatter via class-level registry.
        formatter = OutputFormatter._formatter_registry.get(tool_name)
        if formatter is None:
            return ""
        # Build kwargs; only Ruff tools support the show_fixed parameter.
        kwargs: dict[str, Any] = {
            "show_metadata": show_metadata,
            "show_source": show_source,
        }
        # Only Ruff tools support the show_fixed parameter
        if tool_name in ("ruff", "ruff_linter", "ruff_security"):
            kwargs["show_fixed"] = show_fixed
        return "\n".join(formatter(tool_data, effective_root, **kwargs))

    @staticmethod
    def format_at_level(
        tool_name: str,
        tool_data: dict[str, Any],
        level: LoggerLevel,
        effective_root: Path,
    ) -> str:
        """
        Format tool issues for a specific verbosity level.

        Map each ``LoggerLevel`` to the appropriate formatting flags
        and delegate to ``format_tool_issues``.  The underlying
        *tool_data* is never mutated, so this method may be called
        multiple times with different levels on the same data.

        * **QUIET** — empty string (no issue output).
        * **NORMAL** — compact single-line issues.
        * **DETAILED** — issues with metadata and source context.
        * **VERBOSE** — issues with metadata, source, and fixed items.

        Parameters
        ----------
        tool_name : str
            Tool identifier (e.g. ``"ruff_linter"``, ``"mypy"``).
        tool_data : dict[str, Any]
            Parsed tool output from ``ToolResult.tool_data``.
        level : LoggerLevel
            Desired verbosity tier.
        effective_root : Path
            Project root for relative path display.

        Returns
        -------
        str
            Formatted issue text, or empty string if the level is
            QUIET or there are no issues to display.

        """
        # QUIET suppresses all issue output; higher levels add progressively more detail.
        if level <= LoggerLevel.QUIET:
            return ""
        # NORMAL: compact single-line issues without metadata
        if level == LoggerLevel.NORMAL:
            return OutputFormatter.format_tool_issues(
                tool_name,
                tool_data,
                effective_root,
            )
        # DETAILED: issues with metadata and source context
        if level == LoggerLevel.DETAILED:
            return OutputFormatter.format_tool_issues(
                tool_name,
                tool_data,
                effective_root,
                show_metadata=True,
                show_source=True,
            )
        # VERBOSE and above.
        return OutputFormatter.format_tool_issues(
            tool_name,
            tool_data,
            effective_root,
            show_metadata=True,
            show_source=True,
            show_fixed=True,
        )

    @staticmethod
    def _tool_context_ruff(tool_config: Any) -> tuple[str, str]:
        """Return (checked, result) context for ruff linter."""
        n_rules = len(getattr(tool_config, "select_rules", ())) if tool_config else 0
        checked = f"{n_rules} lint rule groups" if n_rules else "lint rules"
        return checked, "no issues found"

    @staticmethod
    def _tool_context_ruff_formatter(_tool_config: Any) -> tuple[str, str]:
        """Return (checked, result) context for ruff formatter."""
        return "formatting consistency", "all files formatted"

    @staticmethod
    def _tool_context_mypy(tool_config: Any) -> tuple[str, str]:
        """Return (checked, result) context for mypy."""
        # Return default description when no config is available
        if tool_config is None:
            return "type checking", "no type errors"
        # Build a description from enabled mypy strictness features.
        parts: list[str] = []
        if getattr(tool_config, "strict_mode", False):
            parts.append("strict type checking")
        else:
            parts.append("type checking")
        if getattr(tool_config, "warn_unreachable", False):
            parts.append("unreachable code")
        if getattr(tool_config, "disallow_untyped_globals", False):
            parts.append("untyped globals")
        if getattr(tool_config, "disallow_any_explicit", False):
            parts.append("explicit Any ban")
        return ", ".join(parts), "no type errors"

    @staticmethod
    def _tool_context_radon(tool_config: Any) -> tuple[str, str]:
        """Return (checked, result) context for radon."""
        # Return default description when no config is available
        if tool_config is None:
            return "cyclomatic complexity", "all functions within threshold"
        threshold = getattr(tool_config, "minimum_complexity", "B")
        max_score = RADON_COMPLEXITY_GRADES.get(threshold, {}).get("max_score", "?")
        return (
            f"cyclomatic complexity (threshold {threshold}, max score {max_score})",
            "all functions within threshold",
        )

    @staticmethod
    def _tool_context_bandit(tool_config: Any) -> tuple[str, str]:
        """Return (checked, result) context for bandit."""
        # Return default description when no config is available
        if tool_config is None:
            return "security", "no findings"
        severity = getattr(tool_config, "severity", "medium").upper()
        confidence = getattr(tool_config, "confidence", "medium").upper()
        return f"security ({severity}+ severity, {confidence}+ confidence)", "no findings"

    @staticmethod
    def get_tool_context(
        tool_name: str,
        tool_config: Any,
    ) -> tuple[str, str]:
        """
        Return a ``(checked, result)`` pair describing a tool's scope.

        Parameters
        ----------
        tool_name : str
            Tool identifier (e.g. ``"ruff_linter"``, ``"mypy"``).
        tool_config : Any
            Tool-specific config object.

        Returns
        -------
        tuple[str, str]
            ``(checked_description, clean_result_description)``
            or ``("", "")`` if the tool is not recognized.

        """
        # ruff_security has a fixed context string (no config dependency).
        if tool_name == "ruff_security":
            return "security (Ruff S-rules, all severity)", "no findings"
        # Dispatch to tool-specific context functions via class-level registry.
        context_fn = OutputFormatter._context_registry.get(tool_name)
        if context_fn is None:
            return "", ""
        return context_fn(tool_config)

    @classmethod
    def _init_registries(cls) -> None:
        """
        Populate class-level dispatch registries.

        Called once at module import time after all static methods are
        defined.  Separated from the class body because static-method
        descriptors are not directly referenceable during class
        construction on Python < 3.10.
        """
        cls._formatter_registry = {
            "ruff": cls._format_ruff_issues,
            "ruff_linter": cls._format_ruff_issues,
            "ruff_security": cls._format_ruff_issues,
            "mypy": cls._format_mypy_issues,
            "radon": cls._format_radon_issues,
            "bandit": cls._format_bandit_issues,
        }
        cls._context_registry = {
            "ruff": cls._tool_context_ruff,
            "ruff_linter": cls._tool_context_ruff,
            "ruff_formatter": cls._tool_context_ruff_formatter,
            "mypy": cls._tool_context_mypy,
            "radon": cls._tool_context_radon,
            "bandit": cls._tool_context_bandit,
        }


OutputFormatter._init_registries()  # noqa: SLF001


def format_and_log_tool_output(
    logger: SCRLogger,
    tool_name: str,
    tool_data: dict[str, Any],
    effective_root: Path,
) -> None:
    """
    Format tool issues and emit them to the logger at the correct tier.

    Each destination (console, file) independently receives the richest
    format its configured level permits.  When both destinations share
    the same level, the text is formatted once and routed through the
    logger's public methods for efficiency.

    Parameters
    ----------
    logger : SCRLogger
        Logger instance that receives the formatted output.
    tool_name : str
        Tool identifier (e.g. ``"ruff_linter"``, ``"mypy"``).
    tool_data : dict[str, Any]
        Parsed tool output from ``ToolResult.tool_data``.
    effective_root : Path
        Project root for relative path display.

    """
    # Fast path: identical levels; format once, use logger helpers.
    if logger.console_level == logger.file_level:
        text = OutputFormatter.format_at_level(
            tool_name,
            tool_data,
            logger.console_level,
            effective_root,
        )
        # Route through the appropriate tier-based logger method.
        if text:
            # Select the logger method matching the configured detail tier
            if logger.console_level >= LoggerLevel.DETAILED:
                logger.detail(text)
            elif logger.console_level >= LoggerLevel.NORMAL:
                logger.issue(text)
        return

    # Divergent levels: format each destination independently.
    console_text = OutputFormatter.format_at_level(
        tool_name,
        tool_data,
        logger.console_level,
        effective_root,
    )
    file_text = OutputFormatter.format_at_level(
        tool_name,
        tool_data,
        logger.file_level,
        effective_root,
    )

    # Emit both via the logger's split-write method.
    logger.write_split(console_text, file_text)
