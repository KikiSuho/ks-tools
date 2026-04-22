"""
Base tool handler and concrete handlers for scrutiny execution.

Contain the base class that provides shared subprocess execution logic
for all tool handlers, five concrete handler implementations, and the
``ToolExecutor`` dispatcher.

Classes
-------
BaseToolHandler : Base class with shared subprocess execution logic.
RuffHandler : Handler for Ruff linter with 3-pass fix strategy.
RuffFormatterHandler : Handler for ``ruff format``.
MypyHandler : Handler for Mypy type checking with output parsing.
RadonCCHandler : Handler for Radon cyclomatic complexity analysis.
BanditHandler : Handler for Bandit security scanning with threshold filtering.
ToolExecutor : Dispatch tool names to their concrete handler and run them.

Examples
--------
>>> isinstance(ToolExecutor, type)
True

"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scrutiny.core.exceptions import (
    ExitCode,
    SCRConfigurationError,
    SCRSystemError,
    SCRTimeoutError,
    handle_errors,
)
from scrutiny.core.tool_data import (
    BANDIT_CLI_FLAGS,
    MYPY_CLI_FLAGS,
    RADON_CLI_FLAGS,
    RADON_COMPLEXITY_GRADES,
    RUFF_CLI_FLAGS,
    TOOL_REGISTRY,
)
from scrutiny.execution.results import ToolResult
from scrutiny.execution.services import which
from scrutiny.output import relative_display_path
from scrutiny.output.formatting import SourceReader
from scrutiny.output.logger import DeferredLogBuffer
from scrutiny.platforms import get_subprocess_creation_flags, get_subprocess_preexec_fn

if TYPE_CHECKING:
    from scrutiny.configs.dataclasses import (
        BanditConfig,
        GlobalConfig,
        MypyConfig,
        RadonConfig,
        RuffConfig,
    )


# Re-export issue classes from their canonical location for backward
# compatibility — existing importers can still use this import path.
from scrutiny.execution.issues import BanditIssue, RuffIssue

__all__ = [
    "BanditHandler",
    "BanditIssue",
    "BaseToolHandler",
    "MypyHandler",
    "RadonCCHandler",
    "RuffFormatterHandler",
    "RuffHandler",
    "RuffIssue",
    "ToolExecutor",
]


# ====================================== #
#          TOOL EXECUTION                #
# ====================================== #

# Compiled pattern for stripping ANSI escape sequences from subprocess
# output.  Some tools (e.g. radon) emit ANSI colour codes even when stdout
# is a pipe, particularly in IDE environments that set FORCE_COLOR or
# PY_COLORS.  Stripping before JSON parsing prevents decode failures.
_ANSI_ESCAPE_PATTERN: re.Pattern[str] = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class BaseToolHandler:
    """
    Base class for all tool execution handlers.

    Provides shared subprocess execution logic.  Subclasses implement
    ``run()`` and ``build_command()``.

    Parameters
    ----------
    timeout : int
        Maximum seconds per subprocess invocation.
    tool_name : str
        Logical tool name for result tracking (set by ``ToolExecutor``).

    """

    def __init__(self, timeout: int = 300, *, tool_name: str = "") -> None:
        self.timeout = timeout
        self.tool_name = tool_name

    @staticmethod
    def _append_valued_flag(
        command: list[str],
        flag_map: dict[str, str],
        key: str,
        value: str,
    ) -> None:
        """
        Append a flag with a ``{value}`` placeholder if present in *flag_map*.

        Parameters
        ----------
        command : list[str]
            Command list to append the flag to.
        flag_map : dict[str, str]
            Mapping of logical key names to CLI flag templates.
        key : str
            Logical key to look up in *flag_map*.
        value : str
            Value to substitute into the flag template placeholder.

        """
        flag_template = flag_map.get(key, "")
        if flag_template and "{value}" in flag_template:
            command.append(flag_template.format(value=value))

    @staticmethod
    def _append_boolean_flag(
        command: list[str],
        flag_map: dict[str, str],
        key: str,
    ) -> None:
        """
        Append a simple boolean flag if present in *flag_map*.

        Parameters
        ----------
        command : list[str]
            Command list to append the flag to.
        flag_map : dict[str, str]
            Mapping of logical key names to CLI flag strings.
        key : str
            Logical key to look up in *flag_map*.

        """
        flag = flag_map.get(key)
        if flag:
            command.append(flag)

    @staticmethod
    def _strip_ansi_codes(text: str) -> str:
        """
        Remove ANSI escape sequences from *text*.

        Some tools emit ANSI colour codes even when their stdout is a
        pipe rather than a TTY.  This happens in IDE environments that
        set ``FORCE_COLOR``, ``PY_COLORS``, or similar variables.
        Stripping the codes before JSON parsing or log-file writing
        prevents ``json.JSONDecodeError`` and keeps log output clean.

        Parameters
        ----------
        text : str
            Raw subprocess output that may contain ANSI sequences.

        Returns
        -------
        str
            Cleaned text with all ANSI escape sequences removed.

        """
        return _ANSI_ESCAPE_PATTERN.sub("", text)

    def _execute_subprocess(
        self,
        tool: str,
        command: list[str],
        cwd: Path,
    ) -> ToolResult:
        """
        Run *command* as a subprocess and return a ``ToolResult``.

        ANSI escape sequences are stripped from both stdout and stderr
        before the result is returned.  Some tools (notably radon) emit
        colour codes even when stdout is a pipe, which corrupts JSON
        output and causes downstream parse failures.

        Parameters
        ----------
        tool : str
            Tool name for result tracking.
        command : list[str]
            Command and arguments.
        cwd : Path
            Working directory.

        Returns
        -------
        ToolResult
            Execution result with stdout / stderr captured and ANSI
            escape sequences removed.

        Raises
        ------
        SCRTimeoutError
            If the subprocess exceeds *timeout*.
        SCRSystemError
            If the tool executable is not found.

        """
        # Resolve the executable via which() so tools installed in a
        # conda/venv Scripts directory are found even when that directory
        # is not on the system PATH (common when an IDE invokes the
        # interpreter directly).
        resolved = which(command[0])
        # Replace the command name with the resolved absolute path when found
        if resolved is not None:
            command = [resolved, *command[1:]]
        # When which() returns None the original command[0] is kept.
        # FileNotFoundError from subprocess is caught below and
        # re-raised as SCRSystemError with install instructions.

        start_time = time.time()
        # Run the subprocess; convert timeout and missing-binary errors to SCRErrors
        try:
            # nosec B603: list-form call avoids shell injection.  File paths
            # are validated by FileDiscoveryService which resolves them
            # relative to the project root before they reach this point.
            completed_process = subprocess.run(  # nosec B603
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                creationflags=get_subprocess_creation_flags(),
                preexec_fn=get_subprocess_preexec_fn(),
            )
        except subprocess.TimeoutExpired as exc:
            # Tool exceeded the configured timeout
            raise SCRTimeoutError(tool, f"timed out after {self.timeout}s", self.timeout) from exc
        except FileNotFoundError as exc:
            # Binary not found on PATH; provide install guidance
            executable = command[0]
            _, install_pkg = TOOL_REGISTRY.get(tool, (executable, executable))
            raise SCRSystemError(
                f"{executable} not found in PATH. "
                f"Install: pip install {install_pkg} | conda install {install_pkg}",
            ) from exc
        else:
            elapsed_time = time.time() - start_time
            result = ToolResult(
                tool=tool,
                success=completed_process.returncode == 0,
                exit_code=completed_process.returncode,
                execution_time=elapsed_time,
                files_processed=0,
                # Strip ANSI escape codes that some tools emit even when
                # stdout is a pipe (common in IDE environments with
                # FORCE_COLOR or PY_COLORS set).  Without this, ANSI
                # codes appended to JSON output cause parse failures.
                stdout=self._strip_ansi_codes(completed_process.stdout),
                stderr=self._strip_ansi_codes(completed_process.stderr),
            )
            result.tool_data["command"] = command
            return result

    def run(
        self,
        files: list[Path],
        tool_config: Any,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Execute the tool.  Must be overridden by subclasses.

        Parameters
        ----------
        files : list[Path]
            Python files to process.
        tool_config : Any
            Tool-specific configuration dataclass.
        global_config : GlobalConfig
            Global orchestration config.
        effective_root : Path
            Project root directory.

        Returns
        -------
        ToolResult
            Tool execution result.

        """
        raise NotImplementedError

    def build_command(
        self,
        files: list[Path],
        tool_config: Any,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> list[str]:
        """
        Build the CLI command.  Must be overridden by subclasses.

        Parameters
        ----------
        files : list[Path]
            Files to include in the command.
        tool_config : Any
            Tool-specific configuration dataclass.
        global_config : GlobalConfig
            Global orchestration config.
        effective_root : Path
            Project root directory.

        Returns
        -------
        list[str]
            Command tokens.

        """
        raise NotImplementedError


# ====================================== #
#          CONCRETE HANDLERS             #
# ====================================== #


class RuffHandler(BaseToolHandler):
    """
    Handler for Ruff linter with 3-pass fix strategy.

    When ``fix`` is enabled:
    1. Check (capture initial issues as JSON)
    2. Fix (apply auto-fixes)
    3. Check (capture remaining issues as JSON)

    When ``fix`` is disabled (check-only):
    1. Single check pass with JSON output.
    """

    @handle_errors
    def run(
        self,
        files: list[Path],
        ruff_config: RuffConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run Ruff with optional 3-pass fix strategy.

        Parameters
        ----------
        files : list[Path]
            Files to lint.
        ruff_config : RuffConfig
            Ruff configuration.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Result with parsed issues in ``tool_data``.

        """
        # Delegate to fix-mode or check-only-mode runner.
        if ruff_config.fix:
            return self._run_with_fix(
                files,
                ruff_config,
                global_config,
                effective_root,
            )
        return self._run_check_only(
            files,
            ruff_config,
            global_config,
            effective_root,
        )

    @handle_errors
    def _run_check_only(
        self,
        files: list[Path],
        ruff_config: RuffConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run a single Ruff check pass without applying fixes.

        Parameters
        ----------
        files : list[Path]
            Files to lint.
        ruff_config : RuffConfig
            Ruff configuration.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Result with parsed issues in ``tool_data``.

        """
        command = self.build_command(
            files,
            ruff_config,
            global_config,
            effective_root,
            fix_mode=False,
        )
        result = self._execute_subprocess(self.tool_name, command, effective_root)
        result.files_processed = len(files)
        # Parse JSON output into structured issues when available.
        if result.stdout:
            issues = self._parse_json_output(result.stdout)
            result.issues_found = len(issues)
            result.tool_data["issues"] = issues
        return result

    @handle_errors
    def _run_with_fix(
        self,
        files: list[Path],
        ruff_config: RuffConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Execute the three-pass fix strategy: check, fix, check remaining.

        Parameters
        ----------
        files : list[Path]
            Files to lint.
        ruff_config : RuffConfig
            Ruff configuration.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Result with parsed issues, initial issues, and fixed count
            stored in ``tool_data``.

        """
        # Step 1: initial check.
        check_command = self.build_command(
            files,
            ruff_config,
            global_config,
            effective_root,
            fix_mode=False,
        )
        result_initial = self._execute_subprocess(
            self.tool_name,
            check_command,
            effective_root,
        )
        initial_issues = (
            self._parse_json_output(result_initial.stdout) if result_initial.stdout else []
        )

        # Step 2: apply fixes.
        fix_command = self.build_command(
            files,
            ruff_config,
            global_config,
            effective_root,
            fix_mode=True,
        )
        fix_result = self._execute_subprocess(self.tool_name, fix_command, effective_root)
        # Warn when the fix pass exited with an error code
        if fix_result.exit_code != 0:
            DeferredLogBuffer.capture(
                "warning",
                f"[TOOL] Ruff fix pass exited with code {fix_result.exit_code}; "
                f"some fixes may not have been applied.",
            )

        # Fix pass modified files on disk; discard cached source lines
        # so post-fix output formatting reads updated content (R-2).
        SourceReader.clear_cache()

        # Step 3: check remaining.
        result_final = self._execute_subprocess(
            self.tool_name,
            check_command,
            effective_root,
        )
        remaining = self._parse_json_output(result_final.stdout) if result_final.stdout else []

        fixed_count = max(0, len(initial_issues) - len(remaining))
        result_final.files_processed = len(files)
        result_final.issues_found = len(remaining)
        result_final.issues_fixed = fixed_count
        result_final.tool_data["issues"] = remaining
        result_final.tool_data["initial_issues"] = initial_issues
        result_final.tool_data["fixed_count"] = fixed_count
        return result_final

    @handle_errors
    def build_command(
        self,
        files: list[Path],
        ruff_config: RuffConfig,
        global_config: GlobalConfig,
        _effective_root: Path,
        fix_mode: bool = False,
    ) -> list[str]:
        """
        Build a ``ruff check`` command from data-section mappings.

        Each flag is gated by ``global_config.should_emit`` so that a
        native pyproject.toml setting is never overridden by a
        scrutiny-built CLI flag.  Explicit scrutiny CLI overrides win
        over every other source, pyproject.toml wins over scrutiny's
        script defaults, and script defaults only fill in keys the
        user has not expressed.

        Parameters
        ----------
        files : list[Path]
            Files to lint.
        ruff_config : RuffConfig
            Ruff configuration.
        global_config : GlobalConfig
            Global configuration; carries provenance used for
            suppression decisions.
        _effective_root : Path
            Unused; required by interface contract.
        fix_mode : bool
            If True, build a fix command instead of check.

        Returns
        -------
        list[str]
            Command tokens.

        """
        command = ["ruff", "check"]
        append_valued_flag = self._append_valued_flag

        # Output format or fix flags (mutually exclusive modes).
        if not fix_mode:
            # Check mode: always capture issues as JSON; operational flag.
            append_valued_flag(command, RUFF_CLI_FLAGS, "output_format", "json")
        else:
            # Fix mode: emit --fix only when pyproject has not set fix natively.
            if global_config.should_emit("fix", "ruff", "fix"):
                self._append_boolean_flag(command, RUFF_CLI_FLAGS, "fix")
            # Emit --unsafe-fixes only when enabled and not covered by pyproject.
            if ruff_config.unsafe_fixes and global_config.should_emit(
                "unsafe_fixes", "ruff", "unsafe-fixes",
            ):
                self._append_boolean_flag(command, RUFF_CLI_FLAGS, "unsafe_fixes")

        # Line length: suppress when pyproject defines [tool.ruff] line-length.
        if global_config.should_emit("line_length", "ruff", "line-length"):
            append_valued_flag(
                command, RUFF_CLI_FLAGS, "line_length", str(ruff_config.line_length),
            )
        # Target version: suppress when pyproject defines [tool.ruff] target-version.
        if global_config.should_emit("python_version", "ruff", "target-version"):
            append_valued_flag(
                command, RUFF_CLI_FLAGS, "target_version", ruff_config.target_version,
            )

        # Select rules: suppress when pyproject defines [tool.ruff.lint] select.
        if ruff_config.select_rules and global_config.should_emit(
            "select_rules", "ruff.lint", "select",
        ):
            append_valued_flag(
                command, RUFF_CLI_FLAGS, "select_rules", ",".join(ruff_config.select_rules),
            )
        # Extend-select is always additive and only emitted when framework
        # rules need to augment an authoritative pyproject select list.
        # Suppress when pyproject defines [tool.ruff.lint] extend-select.
        if ruff_config.extend_select_rules and global_config.should_emit(
            "framework", "ruff.lint", "extend-select",
        ):
            append_valued_flag(
                command,
                RUFF_CLI_FLAGS,
                "extend_select_rules",
                ",".join(ruff_config.extend_select_rules),
            )
        # Ignore rules: suppress when pyproject defines [tool.ruff.lint] ignore.
        if ruff_config.ignore_rules and global_config.should_emit(
            "ignore_rules", "ruff.lint", "ignore",
        ):
            append_valued_flag(
                command, RUFF_CLI_FLAGS, "ignore_rules", ",".join(ruff_config.ignore_rules),
            )
        # no_cache is a scrutiny operational concern with no pyproject equivalent.
        if ruff_config.no_cache and global_config.should_emit("no_cache"):
            self._append_boolean_flag(command, RUFF_CLI_FLAGS, "no_cache")

        # Exclusions: suppress when pyproject defines [tool.ruff] exclude,
        # so ruff reads the user's list natively and scrutiny's own list
        # does not overwrite it via repeated --exclude flags.
        if global_config.should_emit("exclude_dirs", "ruff", "exclude"):
            # Emit every scrutiny-known exclusion as a separate --exclude flag.
            for exclusion in ruff_config.get_exclusions():
                command.extend(["--exclude", exclusion])

        command.extend(str(file_path) for file_path in files)
        return command

    @staticmethod
    def _parse_json_output(stdout: str) -> list[RuffIssue]:
        """
        Parse Ruff JSON output into ``RuffIssue`` objects.

        Parameters
        ----------
        stdout : str
            JSON string from Ruff.

        Returns
        -------
        list[RuffIssue]
            Parsed issues (empty on parse error).

        """
        # Parse JSON array into RuffIssue objects; return empty on failure
        try:
            data = json.loads(stdout)
            return [RuffIssue(issue_data) for issue_data in data]
        except (json.JSONDecodeError, KeyError, TypeError):
            # Malformed output; return empty rather than crashing
            return []


class RuffFormatterHandler(BaseToolHandler):
    """
    Handler for ``ruff format``.

    Runs the Ruff formatter on discovered files.
    """

    @handle_errors
    def run(
        self,
        files: list[Path],
        ruff_config: RuffConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run ``ruff format``.

        Parameters
        ----------
        files : list[Path]
            Files to format.
        ruff_config : RuffConfig
            Ruff configuration (uses ``line_length``, ``target_version``).
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Formatter result.

        """
        command = self.build_command(
            files,
            ruff_config,
            global_config,
            effective_root,
        )
        result = self._execute_subprocess(
            self.tool_name,
            command,
            effective_root,
        )
        result.files_processed = len(files)
        return result

    @handle_errors
    def build_command(
        self,
        files: list[Path],
        ruff_config: RuffConfig,
        global_config: GlobalConfig,
        _effective_root: Path,
    ) -> list[str]:
        """
        Build a ``ruff format`` command.

        Each scrutiny-built flag is gated by ``global_config.should_emit``
        so native pyproject.toml settings are not overridden via the
        command line.  ``--check`` is an operational mode switch driven
        by scrutiny and is emitted unconditionally when ``check_only``
        is active.

        Parameters
        ----------
        files : list[Path]
            Files to format.
        ruff_config : RuffConfig
            Ruff configuration.
        global_config : GlobalConfig
            Global configuration; carries provenance used for
            suppression decisions.
        _effective_root : Path
            Unused; required by interface contract.

        Returns
        -------
        list[str]
            Command tokens.

        """
        command = ["ruff", "format"]
        append_valued_flag = self._append_valued_flag
        append_boolean_flag = self._append_boolean_flag

        # Check mode (dry-run) is an operational mode, not a pyproject value.
        if global_config.check_only:
            append_boolean_flag(command, RUFF_CLI_FLAGS, "check")

        # Line length: suppress when pyproject defines [tool.ruff] line-length.
        if global_config.should_emit("line_length", "ruff", "line-length"):
            append_valued_flag(
                command, RUFF_CLI_FLAGS, "line_length", str(ruff_config.line_length),
            )
        # Target version: suppress when pyproject defines [tool.ruff] target-version.
        if global_config.should_emit("python_version", "ruff", "target-version"):
            append_valued_flag(
                command, RUFF_CLI_FLAGS, "target_version", ruff_config.target_version,
            )

        # Exclusions: suppress when pyproject defines [tool.ruff] exclude so
        # the formatter reads the user's list natively.
        if global_config.should_emit("exclude_dirs", "ruff", "exclude"):
            # Emit every scrutiny-known exclusion as a separate --exclude flag.
            for exclusion in ruff_config.get_exclusions():
                command.extend(["--exclude", exclusion])

        command.extend(str(file_path) for file_path in files)
        return command


class MypyHandler(BaseToolHandler):
    """Handler for Mypy type checking with output parsing."""

    @handle_errors
    def run(
        self,
        files: list[Path],
        mypy_config: MypyConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run Mypy type checking.

        Parameters
        ----------
        files : list[Path]
            Files to check.
        mypy_config : MypyConfig
            Mypy configuration.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Result with parsed issues in ``tool_data``.

        """
        command = self.build_command(
            files,
            mypy_config,
            global_config,
            effective_root,
        )
        result = self._execute_subprocess(self.tool_name, command, effective_root)
        result.files_processed = len(files)

        # JSON output goes to stdout; parse structured issue objects.
        if result.stdout:
            issues = self._parse_json_output(result.stdout)
            result.issues_found = len(issues)
            result.tool_data["issues"] = issues

        return result

    @handle_errors
    def build_command(
        self,
        files: list[Path],
        mypy_config: MypyConfig,
        global_config: GlobalConfig,
        _effective_root: Path,
    ) -> list[str]:
        """
        Build a ``mypy`` command from data-section mappings.

        Each flag is gated by ``global_config.should_emit`` so
        ``[tool.mypy]`` values from pyproject.toml take precedence
        over scrutiny's script defaults.  Operational flags
        (``--output=json``, ``--no-incremental``) have no pyproject
        equivalent and are emitted unconditionally when active.

        Parameters
        ----------
        files : list[Path]
            Files to type-check.
        mypy_config : MypyConfig
            Mypy configuration.
        global_config : GlobalConfig
            Global configuration; carries provenance used for
            suppression decisions.
        _effective_root : Path
            Unused; required by interface contract.

        Returns
        -------
        list[str]
            Command tokens.

        """
        command = ["mypy"]
        append_valued_flag = self._append_valued_flag
        append_boolean_flag = self._append_boolean_flag

        # Pairs of (scrutiny_key, mypy_config_field_value, native_key).  The
        # native key is the TOML key users would write under [tool.mypy]; when
        # present it suppresses the corresponding CLI flag.
        boolean_specs: tuple[tuple[str, bool, str], ...] = (
            ("strict_mode", mypy_config.strict_mode, "strict"),
            ("warn_unreachable", mypy_config.warn_unreachable, "warn_unreachable"),
            (
                "disallow_untyped_globals",
                mypy_config.disallow_untyped_globals,
                "disallow_untyped_globals",
            ),
            (
                "disallow_any_explicit",
                mypy_config.disallow_any_explicit,
                "disallow_any_explicit",
            ),
            (
                "ignore_missing_imports",
                mypy_config.ignore_missing_imports,
                "ignore_missing_imports",
            ),
            (
                "disable_error_code_import_untyped",
                mypy_config.disable_error_code_import_untyped,
                "disable_error_code",
            ),
            (
                "show_column_numbers",
                mypy_config.show_column_numbers,
                "show_column_numbers",
            ),
            (
                "show_error_codes",
                mypy_config.show_error_codes,
                "show_error_codes",
            ),
        )
        # Emit each enabled boolean flag that pyproject has not claimed.
        for scrutiny_key, is_enabled, native_key in boolean_specs:
            # Skip disabled flags; they never emit.
            if not is_enabled:
                continue
            # Suppress when pyproject.toml already covers the same setting.
            if global_config.should_emit(scrutiny_key, "mypy", native_key):
                append_boolean_flag(command, MYPY_CLI_FLAGS, scrutiny_key)

        # JSON output is operational and mirrors Ruff's --output-format=json.
        append_valued_flag(command, MYPY_CLI_FLAGS, "output", "json")

        # Cache control is a scrutiny operational concern with no pyproject equivalent.
        if global_config.no_cache and global_config.should_emit("no_cache"):
            command.append("--no-incremental")

        # Python version: suppress when pyproject defines [tool.mypy] python_version.
        if global_config.should_emit("python_version", "mypy", "python_version"):
            append_valued_flag(
                command, MYPY_CLI_FLAGS, "python_version", mypy_config.python_version,
            )

        # Exclusions: suppress when pyproject defines [tool.mypy] exclude.
        if global_config.should_emit("exclude_dirs", "mypy", "exclude"):
            # Emit every scrutiny-known exclusion as a separate --exclude flag.
            for exclusion in mypy_config.get_exclusions():
                command.extend(["--exclude", exclusion])

        command.extend(str(file_path) for file_path in files)
        return command

    @staticmethod
    def _parse_json_output(stdout: str) -> list[dict[str, Any]]:
        """
        Parse Mypy JSON output lines into issue dicts.

        Each line of ``--output json`` is a standalone JSON object with
        ``file``, ``line``, ``column``, ``severity``, ``message``, and
        ``code`` fields.  Non-JSON lines (e.g. summary text) are
        silently skipped.

        Parameters
        ----------
        stdout : str
            Mypy stdout produced with ``--output json``.

        Returns
        -------
        list[dict[str, Any]]
            Parsed issues with file, line, column, severity, message, code.

        """
        issues: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                issues.append(
                    {
                        "file": data.get("file", ""),
                        "line": data.get("line", 0),
                        "column": max(data.get("column", 0), 0),
                        "severity": data.get("severity", "error"),
                        "message": data.get("message", "").strip(),
                        "code": data.get("code", ""),
                    },
                )
            except (json.JSONDecodeError, TypeError):
                continue
        return issues


class RadonCCHandler(BaseToolHandler):
    """Handler for Radon cyclomatic complexity analysis."""

    @handle_errors
    def run(
        self,
        files: list[Path],
        radon_config: RadonConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run Radon complexity analysis.

        After subprocess execution the result is post-processed:

        * JSON output is parsed into per-function complexity entries.
        * If parsing fails (``json.JSONDecodeError``), the result is marked
          as an execution error (``TOOL_FAILURE``, exit code 11) so the
          failure surfaces in ``log_completed_result`` instead of silently
          reporting zero issues.
        * Radon always exits 0 on success regardless of findings, so the
          exit code is normalised to 1 when issues are found to stay
          consistent with ruff, mypy, and bandit.

        Parameters
        ----------
        files : list[Path]
            Files to analyze.
        radon_config : RadonConfig
            Radon configuration.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Result with complexity data in ``tool_data``.

        """
        command = self.build_command(
            files,
            radon_config,
            global_config,
            effective_root,
        )
        result = self._execute_subprocess(self.tool_name, command, effective_root)
        result.files_processed = len(files)

        # Parse JSON output into complexity function entries when available.
        if result.stdout:
            # Attempt structured parsing; mark as execution error on decode failure
            try:
                functions = self._parse_json_output(
                    result.stdout,
                    radon_config.minimum_complexity,
                )
            except json.JSONDecodeError:
                # Radon produced non-JSON output.  Mark as execution error
                # so log_completed_result shows the raw output and
                # determine_exit_code reports Script Code 11.
                result.success = False
                result.exit_code = ExitCode.TOOL_FAILURE
                functions = []
            result.issues_found = len(functions)
            result.tool_data["functions"] = functions
        elif result.stderr:
            # Radon produced no stdout but wrote to stderr — likely a crash
            # or configuration error.  Surface it as an execution error.
            result.success = False
            result.exit_code = ExitCode.TOOL_FAILURE

        # Normalise exit code when issues are found: radon exits 0 regardless,
        # when issues are detected so Tool Code is consistent with other
        # tools (ruff, mypy, bandit all exit non-zero on issues).
        # Uses bare 1 (not an ExitCode member) because this represents a
        # tool-level exit code, not a script-level code.  The value 1 matches
        # the native convention of ruff, mypy, and bandit for "issues found".
        if result.issues_found > 0 and result.exit_code == 0:
            result.exit_code = 1
            result.success = False

        return result

    @handle_errors
    def build_command(
        self,
        files: list[Path],
        radon_config: RadonConfig,
        _global_config: GlobalConfig,
        _effective_root: Path,
    ) -> list[str]:
        """
        Build a ``radon cc`` command from data-section mappings.

        Parameters
        ----------
        files : list[Path]
            Files to analyze.
        radon_config : RadonConfig
            Radon configuration.
        _global_config : GlobalConfig
            Unused; required by interface contract.
        _effective_root : Path
            Unused; required by interface contract.

        Returns
        -------
        list[str]
            Command tokens.

        """
        command = ["radon", "cc"]

        # Output mode flags.
        if radon_config.json_output:
            self._append_boolean_flag(command, RADON_CLI_FLAGS, "json_output")
        if radon_config.show_average:
            self._append_boolean_flag(command, RADON_CLI_FLAGS, "show_average")
        if radon_config.show_closures:
            self._append_boolean_flag(command, RADON_CLI_FLAGS, "show_closures")

        # Minimum complexity grade threshold.
        self._append_valued_flag(
            command, RADON_CLI_FLAGS, "minimum_complexity", radon_config.minimum_complexity
        )

        # Per-tool exclusions and file paths.
        for exclusion in radon_config.get_exclusions():
            self._append_valued_flag(command, RADON_CLI_FLAGS, "exclude", exclusion)

        command.extend(str(file_path) for file_path in files)
        return command

    @staticmethod
    def _parse_json_output(
        stdout: str,
        threshold: str,
    ) -> list[dict[str, Any]]:
        """
        Parse Radon JSON output and filter by complexity threshold.

        The threshold grade represents the **maximum acceptable** complexity.
        Functions at the threshold grade or simpler pass; only functions
        strictly exceeding the threshold are returned as issues.

        Raises ``json.JSONDecodeError`` when *stdout* is not valid JSON so the
        caller can surface the error instead of silently reporting zero issues.

        Parameters
        ----------
        stdout : str
            JSON output from Radon.
        threshold : str
            Maximum acceptable complexity grade (e.g. ``"B"`` means grades
            A and B pass; C, D, E, F are flagged).

        Returns
        -------
        list[dict[str, Any]]
            Functions whose complexity exceeds the threshold.

        Raises
        ------
        json.JSONDecodeError
            If *stdout* cannot be parsed as JSON.

        """
        # Determine numeric index for the complexity threshold grade.
        grade_order = list(RADON_COMPLEXITY_GRADES.keys())
        try:
            threshold_idx = grade_order.index(threshold)
        except ValueError:
            threshold_idx = 0

        # Parse JSON first; let JSONDecodeError propagate to the caller so
        # failures are visible rather than silently reporting zero issues.
        data = json.loads(stdout)

        functions: list[dict[str, Any]] = []
        try:
            # Iterate files and their function entries from Radon JSON.
            for file_path, file_data in data.items():
                if not isinstance(file_data, list):
                    continue
                for function_entry in file_data:
                    grade = function_entry.get("rank", "F")
                    try:
                        grade_idx = grade_order.index(grade)
                    except ValueError:
                        grade_idx = len(grade_order) - 1
                    # Flag only grades strictly above the threshold.  The
                    # threshold grade itself is the max acceptable complexity
                    # (e.g. threshold B means B is OK, C+ is an issue).
                    if grade_idx > threshold_idx:
                        functions.append(
                            {
                                "file": file_path,
                                "name": function_entry.get("name", ""),
                                "line": function_entry.get("lineno", 0),
                                "complexity": function_entry.get("complexity", 0),
                                "grade": grade,
                                "type": function_entry.get("type", ""),
                                "classname": function_entry.get("classname", ""),
                            },
                        )
        except (KeyError, TypeError) as parse_error:
            import warnings  # noqa: PLC0415

            total_files = len(data) if isinstance(data, dict) else 0
            warnings.warn(
                f"Radon CC: partial parse — collected {len(functions)} entries "
                f"from {total_files} files before {type(parse_error).__name__}: {parse_error}",
                stacklevel=2,
            )
        return functions

    @handle_errors
    def compute_maintainability_index(
        self,
        files: list[Path],
        effective_root: Path,
    ) -> dict[str, str]:
        """
        Compute the Maintainability Index for each file via ``radon mi``.

        Runs ``radon mi -j`` and returns a mapping of root-relative file
        paths to MI rank letters (``"A"`` through ``"C"``).  On any failure the
        method returns an empty dict so the MI display degrades gracefully
        rather than blocking the header output.

        Parameters
        ----------
        files : list[Path]
            Python files to analyze.
        effective_root : Path
            Project root used to make file paths relative.

        Returns
        -------
        dict[str, str]
            Mapping of root-relative path strings to MI rank letters.

        """
        command: list[str] = ["radon", "mi", "-j"]
        command.extend(str(file_path) for file_path in files)

        result = self._execute_subprocess("radon_mi", command, effective_root)

        if not result.stdout:
            return {}

        mi_ranks: dict[str, str] = {}
        try:
            data = json.loads(result.stdout)
            for file_path_str, file_mi in data.items():
                if not isinstance(file_mi, dict):
                    continue
                # Convert absolute path to root-relative for display.
                mi_ranks[relative_display_path(file_path_str, effective_root)] = file_mi.get(
                    "rank", "?"
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            # MI is best-effort; return whatever was collected.
            pass
        return mi_ranks


class BanditHandler(BaseToolHandler):
    """Handler for Bandit security scanning with threshold filtering."""

    @handle_errors
    def run(
        self,
        files: list[Path],
        bandit_config: BanditConfig,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run Bandit security scanning.

        Parameters
        ----------
        files : list[Path]
            Files to scan.
        bandit_config : BanditConfig
            Bandit configuration.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Result with filtered security issues in ``tool_data``.

        """
        command = self.build_command(
            files,
            bandit_config,
            global_config,
            effective_root,
        )
        result = self._execute_subprocess(self.tool_name, command, effective_root)
        result.files_processed = len(files)

        # Parse all issues then filter by severity/confidence thresholds.
        if result.stdout:
            all_issues = self._parse_json_output(result.stdout)
            filtered = [
                issue
                for issue in all_issues
                if issue.meets_threshold(
                    bandit_config.severity,
                    bandit_config.confidence,
                )
            ]
            result.issues_found = len(filtered)
            result.tool_data["issues"] = filtered
            result.tool_data["total_before_filter"] = len(all_issues)

        return result

    @handle_errors
    def build_command(
        self,
        files: list[Path],
        bandit_config: BanditConfig,
        global_config: GlobalConfig,
        _effective_root: Path,
    ) -> list[str]:
        """
        Build a ``bandit`` command from data-section mappings.

        Each flag is gated by ``global_config.should_emit`` so
        ``[tool.bandit]`` values from pyproject.toml take precedence
        over scrutiny's script defaults.  ``-f json`` is operational
        and emitted unconditionally.

        Parameters
        ----------
        files : list[Path]
            Files to scan.
        bandit_config : BanditConfig
            Bandit configuration.
        global_config : GlobalConfig
            Global configuration; carries provenance used for
            suppression decisions.
        _effective_root : Path
            Unused; required by interface contract.

        Returns
        -------
        list[str]
            Command tokens.

        """
        command = ["bandit"]
        append_valued_flag = self._append_valued_flag
        append_boolean_flag = self._append_boolean_flag

        # JSON output is operational; fallback to literal flags if template missing.
        format_template = BANDIT_CLI_FLAGS.get("format", "")
        # Use the template when available; fall back to literal flags
        if format_template and "{value}" in format_template:
            # Template-based flag from data section
            command.append(format_template.format(value="json"))
        else:
            # Hardcoded fallback when the template is absent
            command.extend(["-f", "json"])

        # Bandit exposes no canonical pyproject keys for severity or
        # confidence, so scrutiny emits these as CLI flags always; a
        # user CLI override still wins via the resolver's priority
        # chain.  Quiet mode and skip-tests likewise have no pyproject
        # equivalent beyond ``skips``, which is handled below.
        append_valued_flag(command, BANDIT_CLI_FLAGS, "severity", bandit_config.severity)
        append_valued_flag(command, BANDIT_CLI_FLAGS, "confidence", bandit_config.confidence)

        # Quiet mode is scrutiny-internal; no pyproject equivalent.
        if bandit_config.quiet:
            append_boolean_flag(command, BANDIT_CLI_FLAGS, "quiet")
        # Skip tests: suppress when pyproject defines [tool.bandit] skips.
        if bandit_config.skip_tests and global_config.should_emit(
            "skip_tests", "bandit", "skips",
        ):
            append_valued_flag(
                command, BANDIT_CLI_FLAGS, "skip_tests", ",".join(bandit_config.skip_tests),
            )

        # Exclusions: suppress when pyproject defines [tool.bandit] exclude_dirs.
        if global_config.should_emit("exclude_dirs", "bandit", "exclude_dirs"):
            # Emit every scrutiny-known exclusion as a separate CLI flag.
            for exclusion in bandit_config.get_exclusions():
                append_valued_flag(command, BANDIT_CLI_FLAGS, "exclude", exclusion)

        command.extend(str(file_path) for file_path in files)
        return command

    @staticmethod
    def _parse_json_output(stdout: str) -> list[BanditIssue]:
        """
        Parse Bandit JSON output into ``BanditIssue`` objects.

        Parameters
        ----------
        stdout : str
            JSON string from Bandit.

        Returns
        -------
        list[BanditIssue]
            Parsed issues (unfiltered).

        """
        try:
            data = json.loads(stdout)
            return [BanditIssue(issue_data) for issue_data in data.get("results", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []


# ====================================== #
#          TOOL EXECUTOR                 #
# ====================================== #


class ToolExecutor:
    """
    Dispatch and orchestrate tool execution.

    Lazily initializes tool handlers and routes execution requests
    by tool name.  Supports sequential and parallel execution.

    Parameters
    ----------
    timeout : int
        Default timeout for all handlers.

    """

    def __init__(self, timeout: int = 300) -> None:
        self.timeout = timeout
        self._handlers: dict[str, BaseToolHandler] = {}
        self._lock = threading.Lock()

    @handle_errors
    def _get_handler(self, tool_name: str) -> BaseToolHandler:
        """
        Get or create a handler for *tool_name*.

        Thread-safe: uses a lock to guard lazy initialization so
        parallel tool execution does not race on handler creation.

        Parameters
        ----------
        tool_name : str
            Tool identifier.

        Returns
        -------
        BaseToolHandler
            Handler instance.

        Raises
        ------
        SCRConfigurationError
            If *tool_name* is not recognized.

        """
        with self._lock:
            # Lazily create the handler on first request for this tool name
            if tool_name not in self._handlers:
                factory: dict[str, type] = {
                    "ruff_formatter": RuffFormatterHandler,
                    "ruff_linter": RuffHandler,
                    "mypy": MypyHandler,
                    "radon": RadonCCHandler,
                    "bandit": BanditHandler,
                    "ruff_security": RuffHandler,
                }
                handler_cls = factory.get(tool_name)
                # Reject unknown tool names before instantiation
                if handler_cls is None:
                    raise SCRConfigurationError(f"No handler for tool: {tool_name}")
                self._handlers[tool_name] = handler_cls(self.timeout, tool_name=tool_name)
            return self._handlers[tool_name]

    @handle_errors
    def run_tool(
        self,
        tool_name: str,
        files: list[Path],
        tool_config: Any,
        global_config: GlobalConfig,
        effective_root: Path,
    ) -> ToolResult:
        """
        Run a single tool.

        Parameters
        ----------
        tool_name : str
            Tool identifier.
        files : list[Path]
            Files to process.
        tool_config : Any
            Tool-specific config dataclass.
        global_config : GlobalConfig
            Global configuration.
        effective_root : Path
            Project root.

        Returns
        -------
        ToolResult
            Execution result.

        """
        handler = self._get_handler(tool_name)
        return handler.run(files, tool_config, global_config, effective_root)
