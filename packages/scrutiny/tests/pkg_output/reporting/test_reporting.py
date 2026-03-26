"""Tests for final status reporting helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scrutiny.core.exceptions import ExitCode
from scrutiny.execution.results import ToolResult
from scrutiny.output.reporting import (
    _compute_result_totals,
    _format_tool_status_line,
    report_final_status,
    determine_exit_code,
)
from scrutiny.output.logger import SCRLogger


def _make_tool_result(
    tool: str = "ruff_linter",
    success: bool = True,
    issues_found: int = 0,
    issues_fixed: int = 0,
    execution_time: float = 0.1,
    error_code: int = 0,
) -> object:
    """Create a ToolResult instance for testing."""
    return ToolResult(
        tool=tool,
        success=success,
        exit_code=0 if success else 1,
        execution_time=execution_time,
        files_processed=1,
        stdout="",
        stderr="",
        issues_found=issues_found,
        issues_fixed=issues_fixed,
        error_code=error_code,
    )


# ── _compute_result_totals ── #


@pytest.mark.unit
class TestComputeResultTotals:
    """Test single-pass aggregation of tool results."""

    def test_empty_results_returns_zeroes(self) -> None:
        """Verify all fields are zero when no results are provided."""
        # Arrange / Act
        totals = _compute_result_totals([])

        # Assert
        assert totals.worst_error_code == 0
        assert totals.total_issues == 0
        assert totals.total_fixed == 0
        assert totals.total_time == 0.0
        assert totals.max_name_len == 0

    def test_single_result_accumulates_correctly(self) -> None:
        """Verify metrics from a single result are captured."""
        # Arrange
        result = _make_tool_result(
            tool="mypy",
            issues_found=5,
            issues_fixed=2,
            execution_time=1.5,
            error_code=3,
        )

        # Act
        totals = _compute_result_totals([result])

        # Assert
        assert totals.worst_error_code == 3
        assert totals.total_issues == 5
        assert totals.total_fixed == 2
        assert totals.total_time == 1.5
        assert totals.max_name_len == len("mypy")

    def test_multiple_results_aggregate_correctly(self) -> None:
        """Verify metrics sum across multiple results."""
        # Arrange
        results = [
            _make_tool_result(
                tool="ruff_linter",
                issues_found=10,
                issues_fixed=3,
                execution_time=0.5,
                error_code=1,
            ),
            _make_tool_result(
                tool="mypy",
                issues_found=2,
                issues_fixed=0,
                execution_time=1.0,
                error_code=5,
            ),
        ]

        # Act
        totals = _compute_result_totals(results)

        # Assert
        assert totals.worst_error_code == 5
        assert totals.total_issues == 12
        assert totals.total_fixed == 3
        assert totals.total_time == pytest.approx(1.5)
        assert totals.max_name_len == len("ruff_linter")


# ── _format_tool_status_line ── #


@pytest.mark.unit
class TestFormatToolStatusLine:
    """Test per-tool status line formatting."""

    @pytest.mark.parametrize(
        "issues_found,success,error_code,expected_suffix",
        [
            (0, True, 0, "... passed"),
            (3, True, 0, "... 3 issues"),
            (0, False, 1, "... failed (Error Code:"),
            (0, False, 0, "... failed"),
        ],
        ids=["passed", "issues", "error_code", "generic_fail"],
    )
    def test_status_line_variants(
        self,
        issues_found: int,
        success: bool,
        error_code: int,
        expected_suffix: str,
    ) -> None:
        """Verify each status variant produces the expected output."""
        # Arrange
        result = _make_tool_result(
            tool="ruff",
            issues_found=issues_found,
            success=success,
            error_code=error_code,
        )

        # Act
        line = _format_tool_status_line(result, max_name_len=14)

        # Assert
        assert expected_suffix in line

    def test_tool_name_padded_to_max_length(self) -> None:
        """Verify tool name is left-justified to max_name_len."""
        # Arrange
        result = _make_tool_result(tool="mypy")

        # Act
        line = _format_tool_status_line(result, max_name_len=14)

        # Assert
        assert "mypy          " in line


# ── determine_exit_code ── #


@pytest.mark.unit
class TestDetermineExitCode:
    """Test process exit code computation from tool results."""

    def test_all_clean_returns_zero(self) -> None:
        """All tools passed with no issues returns exit code 0."""
        # Arrange
        results = [
            _make_tool_result(tool="ruff_linter"),
            _make_tool_result(tool="mypy"),
        ]

        # Act / Assert
        assert determine_exit_code(results) == 0

    def test_issues_found_returns_ten(self) -> None:
        """Issues detected but no fatal errors returns exit code 10."""
        # Arrange
        results = [
            _make_tool_result(tool="ruff_linter", issues_found=3),
            _make_tool_result(tool="mypy"),
        ]

        # Act / Assert
        assert determine_exit_code(results) == 10

    def test_fatal_error_returns_eleven(self) -> None:
        """Tool crash (exit_code > 1, not success) returns exit code 11."""
        # Arrange
        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="crash",
        )

        # Act / Assert
        assert determine_exit_code([result]) == 11

    def test_error_takes_priority_over_issues(self) -> None:
        """Fatal error (11) takes priority over issues (10)."""
        # Arrange
        error_result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="crash",
        )
        issue_result = _make_tool_result(tool="ruff_linter", issues_found=5)

        # Act / Assert
        assert determine_exit_code([error_result, issue_result]) == 11

    def test_empty_results_returns_zero(self) -> None:
        """No results at all returns exit code 0."""
        # Act / Assert
        assert determine_exit_code([]) == 0

    def test_issues_found_code_is_exit_code_enum_member(self) -> None:
        """Exit code 10 matches ExitCode.ISSUES_FOUND."""
        # Arrange
        results = [_make_tool_result(tool="ruff_linter", issues_found=1)]

        # Act
        code = determine_exit_code(results)

        # Assert
        assert code == ExitCode.ISSUES_FOUND
        assert code == 10

    def test_tool_failure_code_is_exit_code_enum_member(self) -> None:
        """Exit code 11 matches ExitCode.TOOL_FAILURE."""
        # Arrange
        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="crash",
        )

        # Act
        code = determine_exit_code([result])

        # Assert
        assert code == ExitCode.TOOL_FAILURE
        assert code == 11

    def test_mixed_issues_and_errors_returns_tool_failure(self) -> None:
        """Mixed results with both issues and errors returns 11."""
        # Arrange
        error_result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=3,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="crash",
        )
        issue_result = _make_tool_result(tool="ruff_linter", issues_found=5)
        clean_result = _make_tool_result(tool="bandit")

        # Act / Assert
        assert (
            determine_exit_code(
                [error_result, issue_result, clean_result],
            )
            == ExitCode.TOOL_FAILURE
        )

    def test_issues_only_no_errors_returns_issues_found(self) -> None:
        """Multiple tools with issues but no errors returns 10."""
        # Arrange
        results = [
            _make_tool_result(tool="ruff_linter", issues_found=3),
            _make_tool_result(tool="mypy", issues_found=2),
            _make_tool_result(tool="bandit"),
        ]

        # Act / Assert
        assert determine_exit_code(results) == ExitCode.ISSUES_FOUND

    def test_exit_codes_do_not_collide_with_phase1_phase2(self) -> None:
        """Phase 3 codes 10 and 11 do not overlap with Phase 1/2 codes 1-8."""
        # Assert
        phase12_codes = {1, 2, 3, 4, 5, 6, 7, 8}
        assert ExitCode.ISSUES_FOUND not in phase12_codes
        assert ExitCode.TOOL_FAILURE not in phase12_codes


# ── report_final_status ── #


@pytest.mark.unit
class TestReportFinalStatus:
    """Test report_final_status logging output."""

    def test_tool_failure_logs_doctor_hint(self) -> None:
        """Verify the --doctor hint appears when a tool execution fails."""
        # Arrange — a tool failure: success=False, exit_code=2, issues_found=0
        failed_result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.5,
            files_processed=1,
            stdout="",
            stderr="crash",
            issues_found=0,
            issues_fixed=0,
            error_code=0,
        )
        mock_logger = MagicMock(spec=SCRLogger)
        discovered_files = [Path("example.py")]

        # Act
        report_final_status([failed_result], discovered_files, mock_logger)

        # Assert — find the error call that contains the doctor hint
        error_messages = [str(call.args[0]) for call in mock_logger.error.call_args_list]
        assert any("--doctor" in message for message in error_messages), (
            f"Expected '--doctor' hint in error messages, got: {error_messages}"
        )
