"""Tests for _extract_error_message, _build_fatal_error_summary, and generate_error_summary."""

from __future__ import annotations

import pytest

from scrutiny.execution.results import ToolResult
from scrutiny.output.run_logging import _build_fatal_error_summary, _extract_error_message
from scrutiny.output.formatting import OutputFormatter


# ── _extract_error_message ── #


@pytest.mark.unit
class TestExtractErrorMessage:
    """Test extracting meaningful error messages from raw tool output."""

    def test_extracts_first_content_block(self) -> None:
        """Return the first contiguous non-blank, non-noise lines."""
        raw_output = "error: cannot find module 'foo'\ncheck your imports\n"

        result = _extract_error_message(raw_output)

        assert "cannot find module" in result
        assert "check your imports" in result

    def test_stops_at_blank_line_after_content(self) -> None:
        """Stop collecting at the first blank line after content starts."""
        raw_output = "real error here\n\nsome trailing noise\n"

        result = _extract_error_message(raw_output)

        assert result == "real error here"

    def test_skips_leading_blank_lines(self) -> None:
        """Skip leading blank lines before content."""
        raw_output = "\n\n\nactual error\n"

        result = _extract_error_message(raw_output)

        assert result == "actual error"

    def test_stops_at_found_noise_prefix(self) -> None:
        """Stop at mypy's 'Found N error' summary line."""
        raw_output = "app.py:10: error: Name 'x' is not defined\nFound 1 error in 1 file\n"

        result = _extract_error_message(raw_output)

        assert "Name 'x' is not defined" in result
        assert "Found 1 error" not in result

    def test_stops_at_success_noise_prefix(self) -> None:
        """Stop at 'Success:' noise prefix."""
        raw_output = "some message\nSuccess: no issues found\n"

        result = _extract_error_message(raw_output)

        assert result == "some message"

    def test_returns_unknown_error_on_empty_input(self) -> None:
        """Return 'unknown error' when input is empty."""
        assert _extract_error_message("") == "unknown error"

    def test_returns_unknown_error_on_only_blanks(self) -> None:
        """Return 'unknown error' when input contains only whitespace."""
        assert _extract_error_message("   \n  \n  ") == "unknown error"

    def test_returns_unknown_error_when_first_line_is_noise(self) -> None:
        """Return 'unknown error' when only noise lines are present."""
        raw_output = "Found 3 errors in 2 files\n"

        result = _extract_error_message(raw_output)

        assert result == "unknown error"

    def test_multiline_error_joined_with_newlines(self) -> None:
        """Multiple content lines are joined with newlines."""
        raw_output = "line one\nline two\nline three\n"

        result = _extract_error_message(raw_output)

        assert result == "line one\nline two\nline three"


# ── OutputFormatter.generate_error_summary ── #


@pytest.mark.unit
class TestGenerateErrorSummary:
    """Test error summary block generation for fatal tool failures."""

    def test_includes_tool_name_and_error(self) -> None:
        """Verify summary includes tool name header and error message."""
        result = OutputFormatter.generate_error_summary(
            "mypy",
            "Duplicate module named 'app'",
            execution_time=2.5,
        )

        assert "[mypy]" in result
        assert "Duplicate module named 'app'" in result
        assert "2.50s" in result

    def test_multiline_error_indented(self) -> None:
        """Verify multiline errors are indented after the first line."""
        result = OutputFormatter.generate_error_summary(
            "ruff_linter",
            "first line\nsecond line",
            execution_time=0.0,
        )

        assert "first line" in result
        assert "second line" in result
        # The second line should be indented
        lines = result.split("\n")
        error_lines = [line for line in lines if "second line" in line]
        assert len(error_lines) == 1
        assert error_lines[0].startswith(" ")

    def test_default_execution_time_is_zero(self) -> None:
        """Verify default execution_time shows 0.00s."""
        result = OutputFormatter.generate_error_summary("bandit", "crash")

        assert "0.00s" in result


# ── _build_fatal_error_summary ── #


@pytest.mark.unit
class TestBuildFatalErrorSummary:
    """Test fatal error summary construction from ToolResult."""

    def test_uses_stderr_and_stdout(self) -> None:
        """Verify combined stderr+stdout is used to extract the error message."""
        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=1.5,
            files_processed=0,
            stdout="stdout content",
            stderr="stderr content",
        )

        summary = _build_fatal_error_summary("mypy", result)

        assert "[mypy]" in summary
        assert "1.50s" in summary

    def test_empty_output_shows_unknown_error(self) -> None:
        """Verify 'unknown error' when both stderr and stdout are empty."""
        result = ToolResult(
            tool="ruff_linter",
            success=False,
            exit_code=2,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="",
        )

        summary = _build_fatal_error_summary("ruff_linter", result)

        assert "unknown error" in summary

    def test_none_stderr_handled(self) -> None:
        """Verify None stderr does not cause a crash."""
        result = ToolResult(
            tool="bandit",
            success=False,
            exit_code=1,
            execution_time=0.1,
            files_processed=0,
            stdout="some output",
            stderr=None,
        )

        summary = _build_fatal_error_summary("bandit", result)

        assert "[bandit]" in summary
