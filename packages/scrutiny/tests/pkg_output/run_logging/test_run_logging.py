"""Tests for output/run_logging.py: error extraction, fatal summary, verbose logging."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scrutiny.core.exceptions import ExitCode
from scrutiny.execution.results import ToolResult
from scrutiny.output.logger import SCRLogger
from scrutiny.output.run_logging import (
    _build_fatal_error_summary,
    _extract_error_message,
    log_completed_result,
    _log_verbose_command,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    tool: str = "mypy",
    success: bool = True,
    exit_code: int = 0,
    issues_found: int = 0,
    issues_fixed: int = 0,
    stdout: str = "",
    stderr: str = "",
    tool_data: dict[str, Any] | None = None,
    error_code: int = 0,
) -> ToolResult:
    """Build a ToolResult with sensible defaults."""
    return ToolResult(
        tool=tool,
        success=success,
        exit_code=exit_code,
        execution_time=0.5,
        files_processed=1,
        stdout=stdout,
        stderr=stderr,
        issues_found=issues_found,
        issues_fixed=issues_fixed,
        tool_data=tool_data if tool_data is not None else {},
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# _extract_error_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractErrorMessage:
    """Tests for error message extraction from raw tool output."""

    def test_returns_first_non_blank_lines(self) -> None:
        """Extracts contiguous non-blank lines from the start."""
        raw = "\n\nmypy: error: Cannot find module\nDetails here\n\nMore text"
        result = _extract_error_message(raw)
        assert "Cannot find module" in result
        assert "Details here" in result

    def test_returns_unknown_for_empty_output(self) -> None:
        """Returns 'unknown error' when output is empty."""
        assert _extract_error_message("") == "unknown error"

    def test_returns_unknown_for_blank_only_output(self) -> None:
        """Returns 'unknown error' when output is only whitespace."""
        assert _extract_error_message("   \n  \n  ") == "unknown error"

    def test_stops_at_noise_prefix(self) -> None:
        """Stops collecting at mypy's 'Found N error' summary line."""
        raw = "real error here\nFound 1 error in 1 file"
        result = _extract_error_message(raw)
        assert result == "real error here"
        assert "Found" not in result

    def test_stops_at_success_noise_prefix(self) -> None:
        """Stops collecting at 'Success:' noise line."""
        raw = "some output\nSuccess: no issues"
        result = _extract_error_message(raw)
        assert result == "some output"

    @pytest.mark.parametrize(
        ("raw", "expected_fragment"),
        [
            pytest.param(
                "error: bad config\n\ngap\nmore",
                "error: bad config",
                id="stops_at_blank_after_content",
            ),
            pytest.param(
                "\n\n\nactual error",
                "actual error",
                id="skips_leading_blanks",
            ),
        ],
    )
    def test_extraction_edge_cases(self, raw: str, expected_fragment: str) -> None:
        """Parametrized edge cases for blank-line handling."""
        result = _extract_error_message(raw)
        assert expected_fragment in result


# ---------------------------------------------------------------------------
# _build_fatal_error_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildFatalErrorSummary:
    """Tests for fatal error summary construction."""

    def test_uses_stderr_content(self) -> None:
        """Summary includes the error message from stderr."""
        result = _make_result(
            tool="mypy",
            success=False,
            exit_code=2,
            stderr="mypy: error: Cannot find implementation",
            error_code=ExitCode.TOOL_EXECUTION,
        )
        summary = _build_fatal_error_summary("mypy", result)
        assert "mypy" in summary
        assert "Cannot find implementation" in summary

    def test_handles_empty_output(self) -> None:
        """Produces 'unknown error' when both stdout and stderr are empty."""
        result = _make_result(
            tool="bandit",
            success=False,
            exit_code=2,
            error_code=ExitCode.TOOL_EXECUTION,
        )
        summary = _build_fatal_error_summary("bandit", result)
        assert "unknown error" in summary

    def test_combines_stderr_and_stdout(self) -> None:
        """Uses combined stderr+stdout for error extraction."""
        result = _make_result(
            tool="ruff",
            success=False,
            exit_code=2,
            stderr="partial ",
            stdout="error message",
            error_code=ExitCode.TOOL_EXECUTION,
        )
        summary = _build_fatal_error_summary("ruff", result)
        assert "ruff" in summary


# ---------------------------------------------------------------------------
# _log_verbose_command
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLogVerboseCommand:
    """Tests for verbose command logging."""

    def test_logs_flag_tokens_and_exit_code(self) -> None:
        """Logs command flags (between executable and file paths) and exit code."""
        result = _make_result(
            tool_data={"command": ["ruff", "--check", "--fix", "file.py"]},
        )
        logger = MagicMock(spec=SCRLogger)

        _log_verbose_command(result, logger)

        debug_calls = [str(c.args[0]) for c in logger.debug.call_args_list]
        assert any("--check" in msg and "--fix" in msg for msg in debug_calls)
        assert any("Tool Code:" in msg for msg in debug_calls)

    def test_logs_exit_code_with_no_command(self) -> None:
        """Logs exit code even when no command tokens are present."""
        result = _make_result(tool_data={})
        logger = MagicMock(spec=SCRLogger)

        _log_verbose_command(result, logger)

        debug_calls = [str(c.args[0]) for c in logger.debug.call_args_list]
        assert any("Tool Code:" in msg for msg in debug_calls)

    def test_no_flag_tokens_when_only_executable(self) -> None:
        """No 'Command:' line when only the executable is in command tokens."""
        result_obj = ToolResult(
            tool="ruff",
            success=True,
            exit_code=0,
            execution_time=0.1,
            files_processed=0,
            stdout="",
            stderr="",
            tool_data={"command": ["ruff"]},
        )
        logger = MagicMock(spec=SCRLogger)

        _log_verbose_command(result_obj, logger)

        debug_calls = [str(c.args[0]) for c in logger.debug.call_args_list]
        assert not any("Command:" in msg for msg in debug_calls)
        assert any("Tool Code:" in msg for msg in debug_calls)


# ---------------------------------------------------------------------------
# log_completed_result — integration/lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLogCompletedResultLifecycle:
    """Integration test for the full post-execution logging workflow."""

    def test_successful_result_logs_summary_and_context(self) -> None:
        """A successful result logs header, summary, checked context, and result."""
        result = _make_result(
            tool="ruff_linter",
            success=True,
            issues_found=0,
            tool_data={"command": ["ruff", "check", "file.py"]},
        )
        logger = MagicMock(spec=SCRLogger)
        tool_config_map = {"ruff_linter": MagicMock()}

        log_completed_result("ruff_linter", result, tool_config_map, logger, Path())

        # Header announces the tool
        header_calls = [str(c.args[0]) for c in logger.header.call_args_list]
        assert any("ruff_linter" in msg for msg in header_calls)

        # Result summary logged
        assert logger.result.called

    def test_fatal_error_result_logs_error_summary(self) -> None:
        """A failed result with no issues logs the fatal error summary."""
        result = _make_result(
            tool="mypy",
            success=False,
            exit_code=2,
            issues_found=0,
            stderr="mypy: error: crash",
            error_code=ExitCode.TOOL_EXECUTION,
        )
        logger = MagicMock(spec=SCRLogger)
        tool_config_map = {"mypy": MagicMock()}

        log_completed_result("mypy", result, tool_config_map, logger, Path())

        result_calls = [str(c.args[0]) for c in logger.result.call_args_list]
        combined = "\n".join(result_calls)
        assert "mypy" in combined.lower() or "crash" in combined.lower()

    def test_tool_data_triggers_log_tool_output(self) -> None:
        """Non-empty tool_data triggers log_tool_output on the logger."""
        result = _make_result(
            tool="ruff_linter",
            issues_found=2,
            tool_data={
                "issues": ["issue1", "issue2"],
                "command": ["ruff", "check"],
            },
        )
        logger = MagicMock(spec=SCRLogger)
        tool_config_map = {"ruff_linter": MagicMock()}

        log_completed_result("ruff_linter", result, tool_config_map, logger, Path())

        logger.log_tool_output.assert_called_once_with("ruff_linter", result.tool_data, Path())
