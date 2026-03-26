"""Tests for logger level output routing and issue formatting."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.configs.dataclasses import (
    BanditConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.core.enums import LoggerLevel
from scrutiny.execution.handlers import (
    BanditIssue,
    RadonCCHandler,
    RuffHandler,
    RuffIssue,
)
from scrutiny.execution.results import ToolResult
from scrutiny.main import _run_tool_safe
from scrutiny.output.header import _log_discovered_files
from scrutiny.output.run_logging import (
    _build_fatal_error_summary,
    _extract_error_message,
    log_completed_result,
    _log_verbose_command,
)
from scrutiny.output.formatting import OutputFormatter
from scrutiny.output.logger import SCRLogger


def _make_test_logger(
    console_level: object,
    file_level: object,
    log_file: Optional[Any] = None,
) -> object:
    """Create a SCRLogger instance for testing without __init__ side effects."""
    logger = SCRLogger.__new__(SCRLogger)
    logger.console_level = console_level
    logger.file_level = file_level
    logger.use_colors = False
    logger.log_file = log_file
    logger._lock = __import__("threading").RLock()
    return logger


# ── OutputFormatter.format_tool_issues ── #


@pytest.mark.unit
class TestFormatToolIssues:
    """Test OutputFormatter.format_tool_issues renders each tool's data."""

    def test_ruff_issues_render_as_one_liners(self) -> None:
        """Ruff issues produce file:line:col: CODE message format."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "F401",
                "message": "os imported but unused",
                "location": {"row": 5, "column": 1},
                "filename": "app.py",
                "fix": None,
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues("ruff_linter", tool_data, Path())

        # Assert
        assert "app.py:5:1: F401 os imported but unused" in result

    def test_ruff_tool_name_alias(self) -> None:
        """The 'ruff' tool name also renders ruff issues."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "E501",
                "message": "line too long",
                "location": {"row": 10, "column": 80},
                "filename": "utils.py",
                "fix": None,
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues("ruff", tool_data, Path())

        # Assert
        assert "utils.py:10:80: E501 line too long" in result

    def test_mypy_issues_render_with_severity_and_code(self) -> None:
        """Mypy issues produce file:line:col: severity: message [code]."""
        # Arrange
        tool_data = {
            "issues": [
                {
                    "file": "main.py",
                    "line": 42,
                    "column": 12,
                    "severity": "error",
                    "message": "Incompatible types",
                    "code": "assignment",
                },
            ],
        }

        # Act
        result = OutputFormatter.format_tool_issues(
            "mypy",
            tool_data,
            Path(),
            show_metadata=True,
        )

        # Assert
        assert "main.py:42:12: error: Incompatible types  [assignment]" in result

    def test_mypy_issues_without_code(self) -> None:
        """Mypy issues with no code omit the bracket suffix."""
        # Arrange
        tool_data = {
            "issues": [
                {
                    "file": "main.py",
                    "line": 1,
                    "column": 0,
                    "severity": "note",
                    "message": "See docs",
                    "code": "",
                },
            ],
        }

        # Act
        result = OutputFormatter.format_tool_issues("mypy", tool_data, Path())

        # Assert
        assert "main.py:1: note: See docs" in result
        assert "[" not in result

    def test_radon_functions_render_with_grade(self) -> None:
        """Radon functions produce file:line name - grade (complexity)."""
        # Arrange
        tool_data = {
            "functions": [
                {
                    "file": "code.py",
                    "name": "main",
                    "line": 100,
                    "complexity": 51,
                    "grade": "F",
                },
            ],
        }

        # Act
        result = OutputFormatter.format_tool_issues("radon", tool_data, Path())

        # Assert
        assert "code.py:100 main - F (51)" in result

    def test_bandit_issues_render_with_severity_confidence(self) -> None:
        """Bandit issues produce file:line: TEST_ID [SEV/CONF] text."""
        # Arrange
        issue = BanditIssue(
            {
                "test_id": "B603",
                "test_name": "subprocess_without_shell_equals_true",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "line_number": 45,
                "filename": "run.py",
                "issue_text": "subprocess call with untrusted input",
                "more_info": "https://example.com",
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues("bandit", tool_data, Path())

        # Assert
        assert "run.py:45: B603 [LOW/HIGH] subprocess call with untrusted input" in result

    def test_empty_tool_data_returns_empty_string(self) -> None:
        """Empty tool_data produces no output."""
        # Arrange

        # Act
        result = OutputFormatter.format_tool_issues("ruff_linter", {}, Path())

        # Assert
        assert result == ""

    def test_unknown_tool_returns_empty_string(self) -> None:
        """Unrecognised tool names produce no output."""
        # Arrange

        # Act
        result = OutputFormatter.format_tool_issues(
            "unknown_tool",
            {"issues": [{"a": 1}]},
            Path(),
        )

        # Assert
        assert result == ""

    def test_ruff_formatter_has_no_issues_key(self) -> None:
        """Ruff formatter tool_data has no 'issues' key; returns empty."""
        # Arrange

        # Act
        result = OutputFormatter.format_tool_issues(
            "ruff_formatter",
            {"command": ["ruff", "format"]},
            Path(),
        )

        # Assert
        assert result == ""

    def test_ruff_verbose_includes_url(self) -> None:
        """Verbose ruff output includes the rule URL."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "F401",
                "message": "unused import",
                "location": {"row": 5, "column": 1},
                "filename": "app.py",
                "fix": None,
                "url": "https://docs.astral.sh/ruff/rules/unused-import",
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues(
            "ruff_linter",
            tool_data,
            Path(),
            show_metadata=True,
        )

        # Assert
        assert "https://docs.astral.sh/ruff/rules/unused-import" in result

    def test_ruff_verbose_shows_fixable(self) -> None:
        """Metadata ruff output shows 'fixable' when fix is available."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "F401",
                "message": "unused import",
                "location": {"row": 5, "column": 1},
                "filename": "app.py",
                "fix": {"applicability": "safe"},
                "url": "https://example.com",
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues(
            "ruff_linter",
            tool_data,
            Path(),
            show_metadata=True,
        )

        # Assert
        assert "fixable" in result

    def test_ruff_compact_omits_url(self) -> None:
        """Compact ruff output does not include the rule URL."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "F401",
                "message": "unused import",
                "location": {"row": 5, "column": 1},
                "filename": "app.py",
                "fix": None,
                "url": "https://docs.astral.sh/ruff/rules/unused-import",
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues(
            "ruff_linter",
            tool_data,
            Path(),
            show_metadata=False,
        )

        # Assert
        assert "https://" not in result

    def test_bandit_verbose_includes_more_info_url(self) -> None:
        """Metadata bandit output includes the more_info URL on a new line."""
        # Arrange
        issue = BanditIssue(
            {
                "test_id": "B603",
                "test_name": "subprocess_without_shell_equals_true",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "line_number": 45,
                "filename": "run.py",
                "issue_text": "subprocess call",
                "more_info": "https://bandit.readthedocs.io/en/1.8.5/plugins/b603.html",
            }
        )
        tool_data = {"issues": [issue]}

        # Act
        result = OutputFormatter.format_tool_issues(
            "bandit",
            tool_data,
            Path(),
            show_metadata=True,
        )

        # Assert
        assert "https://bandit.readthedocs.io" in result

    def test_radon_verbose_includes_type_info(self) -> None:
        """Metadata radon output includes function type and dotted class name."""
        # Arrange
        tool_data = {
            "functions": [
                {
                    "file": "code.py",
                    "name": "build_command",
                    "line": 100,
                    "complexity": 16,
                    "grade": "C",
                    "type": "method",
                    "classname": "BanditHandler",
                },
            ],
        }

        # Act
        result = OutputFormatter.format_tool_issues(
            "radon",
            tool_data,
            Path(),
            show_metadata=True,
        )

        # Assert
        assert "method" in result
        assert "BanditHandler.build_command" in result


# ── Radon parser field coverage ── #


@pytest.mark.unit
class TestRadonParseIncludesTypeAndClassname:
    """Verify _parse_json_output preserves type and classname fields."""

    def test_parse_includes_type_and_classname(self) -> None:
        """Radon JSON with type/classname fields produces dicts with them."""
        # Arrange

        radon_json = json.dumps(
            {
                "code.py": [
                    {
                        "type": "method",
                        "rank": "C",
                        "complexity": 16,
                        "lineno": 100,
                        "endline": 150,
                        "name": "build_command",
                        "classname": "BanditHandler",
                        "col_offset": 4,
                        "closures": [],
                    },
                ]
            }
        )

        # Act
        result = RadonCCHandler._parse_json_output(radon_json, "B")

        # Assert
        assert len(result) == 1
        assert result[0]["type"] == "method"
        assert result[0]["classname"] == "BanditHandler"
        assert result[0]["name"] == "build_command"
        assert result[0]["grade"] == "C"

    def test_parse_defaults_for_missing_type_classname(self) -> None:
        """Radon JSON without type/classname uses empty string defaults."""
        # Arrange

        radon_json = json.dumps(
            {
                "code.py": [
                    {
                        "rank": "F",
                        "complexity": 51,
                        "lineno": 5041,
                        "name": "main",
                    },
                ]
            }
        )

        # Act
        result = RadonCCHandler._parse_json_output(radon_json, "B")

        # Assert
        assert len(result) == 1
        assert result[0]["type"] == ""
        assert result[0]["classname"] == ""


# ── _run_tool_safe detail logging ── #


@pytest.mark.unit
class TestRunToolSafeDetailLogging:
    """Verify _run_tool_safe emits detail and debug logging."""

    def test_calls_log_tool_output_when_tool_data_has_issues(self) -> None:
        """log_tool_output() is called when tool_data contains issues."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "F401",
                "message": "unused import",
                "location": {"row": 1, "column": 1},
                "filename": "a.py",
                "fix": None,
            }
        )
        tool_data: dict[str, Any] = {
            "issues": [issue],
            "command": ["ruff", "check"],
        }
        expected = ToolResult(
            tool="ruff_linter",
            success=False,
            exit_code=1,
            execution_time=0.5,
            files_processed=3,
            stdout="",
            stderr="",
            issues_found=1,
            tool_data=tool_data,
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert — log_tool_output receives the tool data.
        logger.log_tool_output.assert_called_once_with("ruff_linter", tool_data, Path())
        # Verify format_at_level produces the expected detail content.
        detail_msg = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.DETAILED,
            Path(),
        )
        assert "a.py:1:1: F401 unused import" in detail_msg

    def test_calls_logger_debug_with_command(self) -> None:
        """logger.debug() is called with the subprocess command."""
        # Arrange
        expected = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=1.2,
            files_processed=5,
            stdout="",
            stderr="",
            tool_data={
                "command": [
                    "mypy",
                    "--strict",
                    "--warn-unreachable",
                    "a.py",
                    "b.py",
                    "c.py",
                    "d.py",
                    "e.py",
                ],
            },
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "mypy",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert — debug call contains only flags (no exe, no file paths).
        debug_calls = [call[0][0] for call in logger.debug.call_args_list]
        assert any("--strict --warn-unreachable" in msg for msg in debug_calls)
        # Executable and file paths must NOT appear in the Command line.
        cmd_calls = [debug_message for debug_message in debug_calls if "Command:" in debug_message]
        for msg in cmd_calls:
            assert "mypy" not in msg.split("Command:")[1]
            assert ".py" not in msg

    def test_calls_logger_debug_with_tool_code(self) -> None:
        """logger.debug() is called with Tool Code (no Time on that line)."""
        # Arrange
        expected = ToolResult(
            tool="bandit",
            success=True,
            exit_code=0,
            execution_time=2.5,
            files_processed=1,
            stdout="",
            stderr="",
            tool_data={"command": ["bandit", "-f", "json"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "bandit",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        debug_calls = [call[0][0] for call in logger.debug.call_args_list]
        assert any("Tool Code: 0" in msg for msg in debug_calls)
        # Time must NOT appear on the Tool Code line (it belongs in summary).
        tool_code_msgs = [msg for msg in debug_calls if "Tool Code:" in msg]
        assert tool_code_msgs
        for msg in tool_code_msgs:
            assert "Time:" not in msg

    def test_skips_issue_detail_when_no_tool_data(self) -> None:
        """Issue detail is not emitted when tool_data has no issues.

        The clean-pass context is appended to the result summary.
        """
        # Arrange
        expected = ToolResult(
            tool="ruff_formatter",
            success=True,
            exit_code=0,
            execution_time=0.1,
            files_processed=2,
            stdout="",
            stderr="",
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "ruff_formatter",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert — no issue detail calls; clean-pass in result summary.
        logger.detail.assert_not_called()
        result_msg = logger.result.call_args[0][0]
        assert "formatted" in result_msg

    def test_emits_clean_pass_in_result_for_mypy(self) -> None:
        """logger.result() includes clean-pass context for mypy --strict."""
        # Arrange
        expected = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=1.0,
            files_processed=10,
            stdout="",
            stderr="",
            tool_data={"command": ["mypy", "--strict", "src/"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        mypy_config = MypyConfig(strict_mode=True)
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "mypy",
            [],
            mypy_config,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert — result summary includes strict type checking clean-pass context.
        result_msg = logger.result.call_args[0][0]
        assert "strict type checking" in result_msg

    def test_no_clean_pass_in_result_when_issues_found(self) -> None:
        """Clean-pass context is not appended to result when tool found issues."""
        # Arrange
        issue = RuffIssue(
            {
                "code": "F401",
                "message": "unused import",
                "location": {"row": 1, "column": 1},
                "filename": "a.py",
                "fix": None,
            }
        )
        tool_data: dict[str, Any] = {
            "issues": [issue],
            "command": ["ruff", "check"],
        }
        expected = ToolResult(
            tool="ruff_linter",
            success=False,
            exit_code=1,
            execution_time=0.5,
            files_processed=3,
            stdout="",
            stderr="",
            issues_found=1,
            tool_data=tool_data,
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        ruff_config = RuffConfig()
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            ruff_config,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert — log_tool_output was called; content has F401.
        logger.log_tool_output.assert_called_once()
        detail_msg = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.DETAILED,
            Path(),
        )
        assert "F401" in detail_msg
        # No clean-pass in result summary.
        result_msg = logger.result.call_args[0][0]
        assert "No lint issues" not in result_msg


# ── End-to-end log output verification ── #


@pytest.mark.unit
class TestLogOutputIncludesCleanPass:
    """Verify the complete log output contains clean-pass context.

    These tests use a real SCRLogger writing to a StringIO buffer so we
    can inspect every line that would appear in the log file, exactly as
    the user sees it.
    """

    def test_mypy_clean_pass_appears_in_log_file(self) -> None:
        """Log file output includes clean-pass line for mypy --strict."""
        # Arrange
        log_buf = io.StringIO()
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.VERBOSE, log_buf)

        expected = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=0.27,
            files_processed=45,
            stdout="",
            stderr="",
            tool_data={"command": ["mypy", "--strict", "src/"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        mypy_config = MypyConfig(strict_mode=True)

        # Act
        _run_tool_safe(
            executor,
            "mypy",
            [],
            mypy_config,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert — the log file buffer contains both the summary and
        # the clean-pass context on the same result() call.
        log_output = log_buf.getvalue()
        assert "[mypy]" in log_output
        assert "Files: 45" in log_output
        assert "Issues: 0" in log_output
        assert "Checked: strict type checking" in log_output
        assert "Result: no type errors" in log_output

    def test_bandit_clean_pass_appears_in_log_file(self) -> None:
        """Log file output includes clean-pass line for bandit thresholds."""
        # Arrange
        log_buf = io.StringIO()
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.VERBOSE, log_buf)

        expected = ToolResult(
            tool="bandit",
            success=True,
            exit_code=0,
            execution_time=0.32,
            files_processed=45,
            stdout="",
            stderr="",
            tool_data={"command": ["bandit", "-f", "json"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        bandit_config = BanditConfig(severity="medium", confidence="high")

        # Act
        _run_tool_safe(
            executor,
            "bandit",
            [],
            bandit_config,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        log_output = log_buf.getvalue()
        assert "[bandit]" in log_output
        assert "Issues: 0" in log_output
        assert "MEDIUM+" in log_output
        assert "HIGH+" in log_output

    def test_radon_clean_pass_appears_in_log_file(self) -> None:
        """Log file output includes clean-pass line for radon threshold."""
        # Arrange
        log_buf = io.StringIO()
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.VERBOSE, log_buf)

        expected = ToolResult(
            tool="radon",
            success=True,
            exit_code=0,
            execution_time=0.30,
            files_processed=45,
            stdout="",
            stderr="",
            tool_data={"command": ["radon", "cc", "-j"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        radon_config = RadonConfig(minimum_complexity="B")

        # Act
        _run_tool_safe(
            executor,
            "radon",
            [],
            radon_config,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        log_output = log_buf.getvalue()
        assert "[radon]" in log_output
        assert "Issues: 0" in log_output
        assert "Checked: cyclomatic complexity (threshold B, max score 10)" in log_output
        assert "Result: all functions within threshold" in log_output

    def test_clean_pass_appears_on_console_at_normal_level(self) -> None:
        """Clean-pass context appears on console at default NORMAL level."""
        # Arrange
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.QUIET)

        expected = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=0.27,
            files_processed=45,
            stdout="",
            stderr="",
            tool_data={"command": ["mypy", "--strict", "src/"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        mypy_config = MypyConfig(strict_mode=True)

        # Act — capture stdout to verify console output.
        captured = io.StringIO()
        with patch("builtins.print", side_effect=lambda msg: captured.write(msg + "\n")):
            _run_tool_safe(
                executor,
                "mypy",
                [],
                mypy_config,
                MagicMock(),
                Path(),
                logger,
            )

        # Assert — console output includes clean-pass context.
        console_output = captured.getvalue()
        assert "[mypy]" in console_output
        assert "Checked: strict type checking" in console_output
        assert "Result: no type errors" in console_output

    def test_clean_pass_absent_when_issues_found(self) -> None:
        """Clean-pass context is absent from both console and file on issues."""
        # Arrange
        log_buf = io.StringIO()
        logger = _make_test_logger(LoggerLevel.VERBOSE, LoggerLevel.VERBOSE, log_buf)

        issue = RuffIssue(
            {
                "code": "F401",
                "message": "unused import",
                "location": {"row": 1, "column": 1},
                "filename": "a.py",
                "fix": None,
            }
        )
        expected = ToolResult(
            tool="ruff_linter",
            success=False,
            exit_code=1,
            execution_time=0.5,
            files_processed=3,
            stdout="",
            stderr="",
            issues_found=1,
            tool_data={"issues": [issue], "command": ["ruff", "check"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        ruff_config = RuffConfig(select_rules=("E", "F", "W"))

        # Act
        captured = io.StringIO()
        with patch("builtins.print", side_effect=lambda msg: captured.write(msg + "\n")):
            _run_tool_safe(
                executor,
                "ruff_linter",
                [],
                ruff_config,
                MagicMock(),
                Path(),
                logger,
            )

        # Assert — no clean-pass line anywhere.
        console_output = captured.getvalue()
        log_output = log_buf.getvalue()
        assert "No lint issues" not in console_output
        assert "No lint issues" not in log_output
        # New format: Checked: still appears, but Result: does not when issues found.
        assert "Checked:" in console_output
        assert "Result:" not in console_output
        assert "Result:" not in log_output

    def test_all_clean_tools_produce_context_in_log(self) -> None:
        """Simulate all 5 tools passing clean; each gets context in log."""
        # Arrange
        log_buf = io.StringIO()
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.VERBOSE, log_buf)

        tools_and_configs: list[tuple[str, Any]] = [
            ("ruff_linter", RuffConfig(select_rules=("E", "F", "W", "B", "I"))),
            ("ruff_formatter", None),
            ("mypy", MypyConfig(strict_mode=True)),
            ("radon", RadonConfig(minimum_complexity="B")),
            ("bandit", BanditConfig(severity="medium", confidence="high")),
        ]

        for tool_name, config in tools_and_configs:
            expected = ToolResult(
                tool=tool_name,
                success=True,
                exit_code=0,
                execution_time=0.25,
                files_processed=45,
                stdout="",
                stderr="",
                tool_data={"command": [tool_name.split("_")[0]]},
            )
            executor = MagicMock()
            executor.run_tool.return_value = expected

            # Act
            _run_tool_safe(
                executor,
                tool_name,
                [],
                config,
                MagicMock(),
                Path(),
                logger,
            )

        # Assert — every tool's clean-pass context appears in the log.
        log_output = log_buf.getvalue()
        # Ruff linter: Checked + Result
        assert "Checked: 5 lint rule groups" in log_output
        assert "Result: no issues found" in log_output
        # Ruff formatter: Checked + Result
        assert "Checked: formatting consistency" in log_output
        assert "Result: all files formatted" in log_output
        # Mypy: Checked + Result
        assert "Checked: strict type checking" in log_output
        assert "Result: no type errors" in log_output
        # Radon: Checked + Result
        assert "Checked: cyclomatic complexity (threshold B, max score 10)" in log_output
        assert "Result: all functions within threshold" in log_output
        # Bandit: Checked + Result
        assert "Checked: security (MEDIUM+ severity, HIGH+ confidence)" in log_output
        assert "Result: no findings" in log_output


# ── _execute_subprocess command storage ── #


@pytest.mark.unit
class TestCommandStoredInToolData:
    """Verify _execute_subprocess stores the command in tool_data."""

    @patch("subprocess.run")
    def test_command_stored_in_tool_data(self, mock_run: MagicMock) -> None:
        """The executed command list is stored in tool_data['command']."""
        # Arrange
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="ok",
            stderr="",
        )
        handler = RuffHandler(timeout=300)
        cmd = ["ruff", "check", "--output-format=json", "src/"]

        # Act — mock which so the bare tool name is preserved.
        with patch("scrutiny.execution.handlers.which", return_value=None):
            result = handler._execute_subprocess(
                tool="ruff_linter",
                command=cmd,
                cwd=Path(),
            )

        # Assert
        assert result.tool_data["command"] == cmd


# ── LoggerLevel tier behaviour ── #


def _make_ruff_issue(
    code: str = "F401",
    message: str = "unused import",
    filename: str = "a.py",
    row: int = 1,
    column: int = 1,
    fix: Any = None,
    url: str = "",
) -> Any:
    """Create a RuffIssue for testing."""
    raw: dict[str, Any] = {
        "code": code,
        "message": message,
        "location": {"row": row, "column": column},
        "filename": filename,
        "fix": fix,
    }
    if url:
        raw["url"] = url
    return RuffIssue(raw)


def _make_ruff_result(
    issues: list[Any],
    *,
    initial_issues: Optional[list[Any]] = None,
    fixed_count: int = 0,
) -> Any:
    """Create a ToolResult containing ruff issues for testing."""
    tool_data: dict[str, Any] = {
        "issues": issues,
        "command": ["ruff", "check"],
    }
    if initial_issues is not None:
        tool_data["initial_issues"] = initial_issues
        tool_data["fixed_count"] = fixed_count
    issues_found = len(issues)
    return ToolResult(
        tool="ruff_linter",
        success=issues_found == 0,
        exit_code=0 if issues_found == 0 else 1,
        execution_time=0.5,
        files_processed=3,
        stdout="",
        stderr="",
        issues_found=issues_found,
        issues_fixed=fixed_count,
        tool_data=tool_data,
    )


@pytest.mark.unit
class TestNormalLevelCompactIssues:
    """Verify NORMAL level produces compact issues via format_at_level()."""

    def test_normal_level_routes_through_log_tool_output(self) -> None:
        """At NORMAL level, log_tool_output() is called with the tool data."""
        # Arrange
        issue = _make_ruff_issue()
        result = _make_ruff_result([issue])
        executor = MagicMock()
        executor.run_tool.return_value = result
        logger = MagicMock()
        logger.console_level = LoggerLevel.NORMAL
        logger.file_level = LoggerLevel.NORMAL

        # Act
        _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        logger.log_tool_output.assert_called_once()

    def test_normal_level_compact_output_has_no_metadata(self) -> None:
        """Compact issue lines at NORMAL omit fixable flag and URL."""
        # Arrange
        issue = _make_ruff_issue(
            fix={"applicability": "safe"},
            url="https://docs.astral.sh/ruff/rules/unused-import",
        )
        tool_data: dict[str, Any] = {
            "issues": [issue],
            "command": ["ruff", "check"],
        }

        # Act
        issue_msg = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.NORMAL,
            Path(),
        )

        # Assert
        assert "a.py:1:1: F401 unused import" in issue_msg
        assert "fixable" not in issue_msg
        assert "https://" not in issue_msg


@pytest.mark.unit
class TestDetailedLevelRichIssues:
    """Verify DETAILED level produces rich issues via format_at_level()."""

    def test_detailed_level_routes_through_log_tool_output(self) -> None:
        """At DETAILED level, log_tool_output() is called with the tool data."""
        # Arrange
        issue = _make_ruff_issue()
        result = _make_ruff_result([issue])
        executor = MagicMock()
        executor.run_tool.return_value = result
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        # Act
        _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        logger.log_tool_output.assert_called_once()

    def test_detailed_level_includes_metadata(self) -> None:
        """Detail output at DETAILED includes fixable flag and URL."""
        # Arrange
        issue = _make_ruff_issue(
            fix={"applicability": "safe"},
            url="https://docs.astral.sh/ruff/rules/unused-import",
        )
        tool_data: dict[str, Any] = {
            "issues": [issue],
            "command": ["ruff", "check"],
        }

        # Act
        detail_msg = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.DETAILED,
            Path(),
        )

        # Assert
        assert "fixable" in detail_msg
        assert "https://docs.astral.sh/ruff/rules/unused-import" in detail_msg


@pytest.mark.unit
class TestVerboseLevelFixedItems:
    """Verify VERBOSE vs DETAILED formatting of Ruff fixed items."""

    def test_verbose_level_shows_fixed_items(self) -> None:
        """format_at_level at VERBOSE includes fixed-by-Ruff section."""
        # Arrange
        remaining = _make_ruff_issue(code="W291", message="trailing whitespace")
        fixed_issue = _make_ruff_issue(code="F401", message="unused import")
        initial = [fixed_issue, remaining]
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": initial,
            "fixed_count": 1,
            "command": ["ruff", "check"],
        }

        # Act
        verbose_msg = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.VERBOSE,
            Path(),
        )

        # Assert
        assert "Fixed by Ruff:" in verbose_msg
        assert "F401 unused import" in verbose_msg

    def test_detailed_level_omits_fixed_items(self) -> None:
        """format_at_level at DETAILED does not include fixed-by-Ruff section."""
        # Arrange
        remaining = _make_ruff_issue(code="W291", message="trailing whitespace")
        fixed_issue = _make_ruff_issue(code="F401", message="unused import")
        initial = [fixed_issue, remaining]
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": initial,
            "fixed_count": 1,
            "command": ["ruff", "check"],
        }

        # Act
        detail_msg = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.DETAILED,
            Path(),
        )

        # Assert
        assert "Fixed by Ruff:" not in detail_msg


# ── OutputFormatter._format_ruff_fixed_items ── #


@pytest.mark.unit
class TestFormatRuffFixedItems:
    """Verify _format_ruff_fixed_items diff logic."""

    def test_identifies_fixed_issues_by_diff(self) -> None:
        """Fixed items are those in initial_issues but not in remaining issues."""
        # Arrange
        remaining = _make_ruff_issue(code="W291", message="trailing whitespace")
        fixed = _make_ruff_issue(code="F401", message="unused import")
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": [fixed, remaining],
            "fixed_count": 1,
        }

        # Act
        lines = OutputFormatter._format_ruff_fixed_items(tool_data, Path())

        # Assert
        assert lines[0] == "  Fixed by Ruff:"
        assert any("F401 unused import" in line for line in lines)
        assert not any("W291" in line for line in lines)

    def test_returns_empty_when_no_fixes(self) -> None:
        """No output when fixed_count is zero."""
        # Arrange
        tool_data: dict[str, Any] = {
            "issues": [],
            "initial_issues": [],
            "fixed_count": 0,
        }

        # Act
        lines = OutputFormatter._format_ruff_fixed_items(tool_data, Path())

        # Assert
        assert lines == []

    def test_returns_empty_when_no_initial_issues(self) -> None:
        """No output when initial_issues key is absent (check-only mode)."""
        # Arrange
        tool_data: dict[str, Any] = {"issues": []}

        # Act
        lines = OutputFormatter._format_ruff_fixed_items(tool_data, Path())

        # Assert
        assert lines == []

    def test_multiple_fixed_issues_listed(self) -> None:
        """All fixed issues appear in the output."""
        # Arrange
        remaining = _make_ruff_issue(code="E501", message="line too long")
        fixed_one = _make_ruff_issue(code="F401", message="unused import")
        fixed_two = _make_ruff_issue(
            code="I001",
            message="unsorted imports",
            row=3,
        )
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": [fixed_one, fixed_two, remaining],
            "fixed_count": 2,
        }

        # Act
        lines = OutputFormatter._format_ruff_fixed_items(tool_data, Path())

        # Assert
        fixed_text = "\n".join(lines)
        assert "F401 unused import" in fixed_text
        assert "I001 unsorted imports" in fixed_text
        assert "E501" not in fixed_text


@pytest.mark.unit
class TestFormatToolIssuesShowFixed:
    """Verify show_fixed parameter passes through to ruff formatter."""

    def test_show_fixed_renders_fixed_section(self) -> None:
        """format_tool_issues with show_fixed=True includes fixed items."""
        # Arrange
        remaining = _make_ruff_issue(code="W291", message="trailing whitespace")
        fixed = _make_ruff_issue(code="F401", message="unused import")
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": [fixed, remaining],
            "fixed_count": 1,
        }

        # Act
        result = OutputFormatter.format_tool_issues(
            "ruff_linter",
            tool_data,
            Path(),
            show_fixed=True,
        )

        # Assert
        assert "Fixed by Ruff:" in result
        assert "F401 unused import" in result

    def test_show_fixed_false_omits_fixed_section(self) -> None:
        """format_tool_issues with show_fixed=False omits fixed items."""
        # Arrange
        remaining = _make_ruff_issue(code="W291", message="trailing whitespace")
        fixed = _make_ruff_issue(code="F401", message="unused import")
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": [fixed, remaining],
            "fixed_count": 1,
        }

        # Act
        result = OutputFormatter.format_tool_issues(
            "ruff_linter",
            tool_data,
            Path(),
            show_fixed=False,
        )

        # Assert
        assert "Fixed by Ruff:" not in result

    def test_show_fixed_ignored_for_non_ruff_tools(self) -> None:
        """show_fixed has no effect on non-ruff tool formatters."""
        # Arrange
        tool_data: dict[str, Any] = {
            "issues": [
                {
                    "file": "main.py",
                    "line": 1,
                    "column": 0,
                    "severity": "error",
                    "message": "type error",
                    "code": "assignment",
                },
            ],
        }

        # Act
        result = OutputFormatter.format_tool_issues(
            "mypy",
            tool_data,
            Path(),
            show_fixed=True,
        )

        # Assert
        assert "Fixed by Ruff:" not in result
        assert "type error" in result


# ── format_at_level unit tests ── #


@pytest.mark.unit
class TestFormatAtLevel:
    """Verify OutputFormatter.format_at_level() maps levels to flags."""

    def test_quiet_returns_empty(self) -> None:
        """QUIET level produces no issue output."""
        issue = _make_ruff_issue()
        tool_data: dict[str, Any] = {"issues": [issue], "command": ["ruff"]}

        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.QUIET,
            Path(),
        )

        assert result == ""

    def test_normal_omits_metadata(self) -> None:
        """NORMAL level produces compact lines without metadata."""
        issue = _make_ruff_issue(
            fix={"applicability": "safe"},
            url="https://docs.astral.sh/ruff/rules/unused-import",
        )
        tool_data: dict[str, Any] = {"issues": [issue], "command": ["ruff"]}

        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.NORMAL,
            Path(),
        )

        assert "a.py:1:1: F401 unused import" in result
        assert "fixable" not in result
        assert "https://" not in result

    def test_detailed_includes_metadata(self) -> None:
        """DETAILED level includes fixable flag and URL."""
        issue = _make_ruff_issue(
            fix={"applicability": "safe"},
            url="https://docs.astral.sh/ruff/rules/unused-import",
        )
        tool_data: dict[str, Any] = {"issues": [issue], "command": ["ruff"]}

        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.DETAILED,
            Path(),
        )

        assert "fixable" in result
        assert "https://docs.astral.sh/ruff/rules/unused-import" in result

    def test_verbose_includes_fixed_items(self) -> None:
        """VERBOSE level includes fixed-by-Ruff section."""
        remaining = _make_ruff_issue(code="W291", message="trailing ws")
        fixed = _make_ruff_issue(code="F401", message="unused import")
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": [fixed, remaining],
            "fixed_count": 1,
            "command": ["ruff"],
        }

        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.VERBOSE,
            Path(),
        )

        assert "Fixed by Ruff:" in result
        assert "F401 unused import" in result

    def test_data_unchanged_after_multiple_calls(self) -> None:
        """tool_data is not mutated across calls at different levels."""
        issue = _make_ruff_issue()
        tool_data: dict[str, Any] = {"issues": [issue], "command": ["ruff"]}
        original_keys = set(tool_data.keys())
        original_issue_count = len(tool_data["issues"])

        OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.VERBOSE,
            Path(),
        )
        OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.NORMAL,
            Path(),
        )

        assert set(tool_data.keys()) == original_keys
        assert len(tool_data["issues"]) == original_issue_count


# ── Divergent logger level tests ── #


@pytest.mark.unit
class TestDivergentLoggerLevels:
    """Verify log_tool_output() routes correctly when levels differ."""

    def test_console_normal_file_verbose(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Console gets compact, file gets verbose with fixed items."""
        remaining = _make_ruff_issue(code="W291", message="trailing ws")
        fixed = _make_ruff_issue(code="F401", message="unused import")
        tool_data: dict[str, Any] = {
            "issues": [remaining],
            "initial_issues": [fixed, remaining],
            "fixed_count": 1,
            "command": ["ruff"],
        }

        file_buffer = io.StringIO()
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.VERBOSE, file_buffer)

        logger.log_tool_output("ruff_linter", tool_data, Path())

        console_output = capsys.readouterr().out
        file_output = file_buffer.getvalue()

        # Console: compact, no metadata, no fixed section.
        assert "W291" in console_output
        assert "fixable" not in console_output
        assert "Fixed by Ruff:" not in console_output

        # File: verbose with metadata and fixed section.
        assert "W291" in file_output
        assert "Fixed by Ruff:" in file_output
        assert "F401 unused import" in file_output

    def test_console_verbose_file_quiet(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Console gets verbose, file gets nothing."""
        issue = _make_ruff_issue()
        tool_data: dict[str, Any] = {
            "issues": [issue],
            "command": ["ruff"],
        }

        logger = _make_test_logger(LoggerLevel.VERBOSE, LoggerLevel.QUIET)

        logger.log_tool_output("ruff_linter", tool_data, Path())

        console_output = capsys.readouterr().out
        assert "a.py:1:1: F401 unused import" in console_output

    def test_console_quiet_file_detailed(self) -> None:
        """Console gets nothing, file gets detailed output."""
        issue = _make_ruff_issue(
            fix={"applicability": "safe"},
            url="https://docs.astral.sh/ruff/rules/unused-import",
        )
        tool_data: dict[str, Any] = {
            "issues": [issue],
            "command": ["ruff"],
        }

        file_buffer = io.StringIO()
        logger = _make_test_logger(LoggerLevel.QUIET, LoggerLevel.DETAILED, file_buffer)

        logger.log_tool_output("ruff_linter", tool_data, Path())

        file_output = file_buffer.getvalue()
        assert "fixable" in file_output
        assert "https://docs.astral.sh/ruff/rules/unused-import" in file_output


# ── Fatal error output formatting ── #


@pytest.mark.unit
class TestFatalErrorOutput:
    """Verify that fatal tool errors show Error: instead of Files:/Issues:."""

    def _make_logger(self) -> tuple[Any, io.StringIO]:
        """Create a real SCRLogger writing to a StringIO buffer."""
        buf = io.StringIO()
        logger = _make_test_logger(LoggerLevel.NORMAL, LoggerLevel.VERBOSE, buf)
        return logger, buf

    def test_fatal_error_shows_error_instead_of_files_and_issues(self) -> None:
        """Fatal error summary shows Error: instead of Files:/Issues:."""
        logger, buf = self._make_logger()

        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.82,
            files_processed=51,
            stdout=(
                'conftest.py: error: Duplicate module named "conftest"\nFound 1 error in 1 file\n'
            ),
            stderr="",
            tool_data={"command": ["mypy", "--strict", "src/main.py"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = result
        mypy_config = MypyConfig(strict_mode=True)

        _run_tool_safe(
            executor,
            "mypy",
            [],
            mypy_config,
            MagicMock(),
            Path(),
            logger,
        )

        log_output = buf.getvalue()
        assert "[mypy]" in log_output
        assert "Error:" in log_output
        assert "Duplicate module" in log_output
        assert "Files:" not in log_output
        assert "Issues:" not in log_output
        assert "Checked: strict type checking" in log_output
        # Result: should NOT appear on fatal errors.
        assert "Result:" not in log_output

    def test_fatal_error_multiline_captures_full_message(self) -> None:
        """Fatal error with wrapped output captures the full error message."""
        logger, buf = self._make_logger()

        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.55,
            files_processed=10,
            stdout=(
                "validators.py: error: Duplicate module named\n"
                '"ks_backend.ks_common.validators"\n'
                "Found 1 error in 1 file\n"
            ),
            stderr="",
            tool_data={"command": ["mypy", "--strict", "src/"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = result
        mypy_config = MypyConfig(strict_mode=True)

        _run_tool_safe(
            executor,
            "mypy",
            [],
            mypy_config,
            MagicMock(),
            Path(),
            logger,
        )

        log_output = buf.getvalue()
        assert "Duplicate module named" in log_output
        assert '"ks_backend.ks_common.validators"' in log_output
        # Continuation line should be indented to align under Error: content.
        assert '         "ks_backend.ks_common.validators"' in log_output

    def test_fatal_error_with_empty_output_shows_unknown(self) -> None:
        """Fatal error with no stdout/stderr shows 'unknown error'."""
        logger, buf = self._make_logger()

        result = ToolResult(
            tool="radon",
            success=False,
            exit_code=2,
            execution_time=0.1,
            files_processed=0,
            stdout="",
            stderr="",
            tool_data={"command": ["radon", "cc"]},
        )
        executor = MagicMock()
        executor.run_tool.return_value = result

        _run_tool_safe(
            executor,
            "radon",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        log_output = buf.getvalue()
        assert "Error: unknown error" in log_output

    def test_normal_run_with_issues_still_shows_files_and_issues(self) -> None:
        """Tool with issues_found > 0 still uses normal Files/Issues format."""
        logger, buf = self._make_logger()

        result = ToolResult(
            tool="ruff_linter",
            success=False,
            exit_code=1,
            execution_time=0.5,
            files_processed=3,
            stdout="",
            stderr="",
            issues_found=1,
            tool_data={"command": ["ruff", "check"]},
        )

        log_completed_result("ruff_linter", result, {}, logger, Path())

        log_output = buf.getvalue()
        assert "Files: 3" in log_output
        assert "Issues: 1" in log_output
        assert "Error:" not in log_output


@pytest.mark.unit
class TestGenerateErrorSummary:
    """Verify OutputFormatter.generate_error_summary format."""

    def test_format(self) -> None:
        """generate_error_summary produces [tool]\\n  Error:\\n  Time:."""
        result = OutputFormatter.generate_error_summary(
            "mypy",
            'Duplicate module named "conftest"',
            0.82,
        )
        assert result == ('[mypy]\n  Error: Duplicate module named "conftest"\n  Time: 0.82s')

    def test_multiline_error_indented(self) -> None:
        """generate_error_summary indents continuation lines."""
        error_msg = "conftest.py: error: Duplicate module\nconftest.py: note: See docs"
        result = OutputFormatter.generate_error_summary("mypy", error_msg, 0.5)
        expected = (
            "[mypy]\n"
            "  Error: conftest.py: error: Duplicate module\n"
            "         conftest.py: note: See docs\n"
            "  Time: 0.50s"
        )
        assert result == expected


@pytest.mark.unit
class TestExtractErrorMessage:
    """Verify _extract_error_message helper."""

    def test_skips_noise(self) -> None:
        """Helper skips blank lines and mypy summary noise."""
        raw = "\nconftest.py: error: Duplicate module\nFound 1 error in 1 file\n"
        assert _extract_error_message(raw) == "conftest.py: error: Duplicate module"

    def test_fallback_on_noise_only(self) -> None:
        """Returns 'unknown error' when only noise lines present."""
        assert _extract_error_message("Found 1 error\n") == "unknown error"
        assert _extract_error_message("") == "unknown error"

    def test_stderr_content(self) -> None:
        """Extracts error from stderr-like content."""
        raw = "bandit: config file error\nFound 1 error\n"
        assert _extract_error_message(raw) == "bandit: config file error"

    def test_multiline_error_joined(self) -> None:
        """Contiguous non-noise lines are joined with newlines."""
        raw = (
            "validators.py: error: Duplicate module named\n"
            '"ks_backend.ks_common.validators"\n'
            "Found 1 error in 1 file\n"
        )
        assert _extract_error_message(raw) == (
            'validators.py: error: Duplicate module named\n"ks_backend.ks_common.validators"'
        )

    def test_blank_line_stops_collection(self) -> None:
        """A blank line after content stops collection."""
        raw = "first error line\n\nunrelated line\n"
        assert _extract_error_message(raw) == "first error line"


@pytest.mark.unit
class TestCommandFlagsOnly:
    """Verify Command: line shows only flags, not executable or file paths."""

    def test_command_strips_executable_and_files(self) -> None:
        """Command debug line contains only flags."""
        result = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=1.0,
            files_processed=2,
            stdout="",
            stderr="",
            tool_data={
                "command": [
                    "mypy",
                    "--strict",
                    "--python-version=3.9",
                    "src/a.py",
                    "src/b.py",
                ],
            },
        )
        executor = MagicMock()
        executor.run_tool.return_value = result
        logger = MagicMock()
        logger.console_level = LoggerLevel.DETAILED
        logger.file_level = LoggerLevel.DETAILED

        _run_tool_safe(
            executor,
            "mypy",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        debug_calls = [call[0][0] for call in logger.debug.call_args_list]
        command_msgs = [msg for msg in debug_calls if "Command:" in msg]
        assert command_msgs
        cmd_line = command_msgs[0]
        assert "--strict" in cmd_line
        assert "--python-version=3.9" in cmd_line
        # Executable and file paths must be stripped.
        assert "mypy" not in cmd_line.split("Command: ")[1]
        assert "src/a.py" not in cmd_line
        assert "src/b.py" not in cmd_line


# ── _build_fatal_error_summary ── #


def _make_tool_result_for_summary(
    tool: str = "ruff_linter",
    stderr: str = "",
    stdout: str = "",
    execution_time: float = 0.1,
) -> object:
    """Create a failed ToolResult for fatal error summary testing."""
    return ToolResult(
        tool=tool,
        success=False,
        exit_code=1,
        execution_time=execution_time,
        files_processed=1,
        stdout=stdout,
        stderr=stderr,
        issues_found=0,
        issues_fixed=0,
    )


@pytest.mark.unit
class TestBuildFatalErrorSummary:
    """Test fatal error summary construction from tool output."""

    def test_uses_stderr_and_stdout(self) -> None:
        """Verify both stderr and stdout are used for error extraction."""
        # Arrange
        result = _make_tool_result_for_summary(
            stderr="Error: something broke",
            stdout="extra output",
        )

        # Act
        summary = _build_fatal_error_summary("ruff", result)

        # Assert
        assert "[ruff]" in summary
        assert "Error" in summary

    def test_empty_output_falls_back_to_unknown(self) -> None:
        """Verify 'unknown error' is used when both outputs are empty."""
        # Arrange
        result = _make_tool_result_for_summary(stderr="", stdout="")

        # Act
        summary = _build_fatal_error_summary("mypy", result)

        # Assert
        assert "unknown error" in summary

    def test_only_stderr_populated(self) -> None:
        """Verify summary works when only stderr has content."""
        # Arrange
        result = _make_tool_result_for_summary(
            stderr="fatal: cannot run",
            stdout="",
        )

        # Act
        summary = _build_fatal_error_summary("bandit", result)

        # Assert
        assert "[bandit]" in summary

    def test_only_stdout_populated(self) -> None:
        """Verify summary works when only stdout has content."""
        # Arrange
        result = _make_tool_result_for_summary(
            stderr="",
            stdout="Configuration error",
        )

        # Act
        summary = _build_fatal_error_summary("radon", result)

        # Assert
        assert "[radon]" in summary


# ── _log_verbose_command ── #


@pytest.mark.unit
class TestLogVerboseCommand:
    """Test verbose command and exit code logging."""

    def test_emits_flags_when_command_tokens_exist(self) -> None:
        """Verify command flags are logged when command tokens present."""
        # Arrange
        logger = MagicMock()
        result = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=0.5,
            files_processed=2,
            stdout="",
            stderr="",
            tool_data={"command": ["mypy", "--strict", "--output=json", "a.py", "b.py"]},
        )

        # Act
        _log_verbose_command(result, logger)

        # Assert
        debug_calls = [str(call) for call in logger.debug.call_args_list]
        command_call = [call for call in debug_calls if "Command:" in call]
        assert len(command_call) == 1
        assert "--strict" in command_call[0]
        assert "--output=json" in command_call[0]

    def test_omits_command_when_no_tokens(self) -> None:
        """Verify no command line is logged when command tokens are empty."""
        # Arrange
        logger = MagicMock()
        result = ToolResult(
            tool="ruff",
            success=True,
            exit_code=0,
            execution_time=0.1,
            files_processed=0,
            stdout="",
            stderr="",
            tool_data={},
        )

        # Act
        _log_verbose_command(result, logger)

        # Assert
        debug_calls = [str(call) for call in logger.debug.call_args_list]
        command_calls = [call for call in debug_calls if "Command:" in call]
        assert len(command_calls) == 0

    def test_always_emits_tool_code(self) -> None:
        """Verify Tool Code is always logged regardless of command tokens."""
        # Arrange
        logger = MagicMock()
        result = ToolResult(
            tool="ruff",
            success=True,
            exit_code=0,
            execution_time=0.1,
            files_processed=0,
            stdout="",
            stderr="",
            tool_data={},
        )

        # Act
        _log_verbose_command(result, logger)

        # Assert
        debug_calls = [str(call) for call in logger.debug.call_args_list]
        tool_code_calls = [call for call in debug_calls if "Tool Code:" in call]
        assert len(tool_code_calls) == 1


# ── _log_discovered_files ── #


@pytest.mark.unit
class TestLogDiscoveredFiles:
    """Test two-column discovered files display with optional MI ranks."""

    def test_renders_files_in_two_column_layout(self, tmp_path: Path) -> None:
        """Verify files are split across two columns."""
        # Arrange
        logger = MagicMock()
        root = tmp_path
        files = [root / "alpha.py", root / "beta.py", root / "gamma.py", root / "delta.py"]
        for file_path in files:
            file_path.touch()

        # Act
        _log_discovered_files(logger, files, root, None)

        # Assert
        header_calls = [str(call) for call in logger.header.call_args_list]
        assert any("Discovered 4 Python file(s)" in call for call in header_calls)
        # Two-column layout: 4 files -> 2 rows.
        file_lines = [call for call in header_calls if "Discovered" not in call]
        assert len(file_lines) == 2

    def test_appends_mi_rank_when_provided(self, tmp_path: Path) -> None:
        """Verify MI rank annotation appears after file name."""
        # Arrange
        logger = MagicMock()
        root = tmp_path
        file_path = root / "script.py"
        file_path.touch()
        mi_ranks = {"script.py": "C"}

        # Act
        _log_discovered_files(logger, [file_path], root, mi_ranks)

        # Assert
        header_calls = [str(call) for call in logger.header.call_args_list]
        assert any("script.py [C]" in call for call in header_calls)

    def test_omits_mi_rank_when_none(self, tmp_path: Path) -> None:
        """Verify no rank annotation when mi_ranks is None."""
        # Arrange
        logger = MagicMock()
        root = tmp_path
        file_path = root / "script.py"
        file_path.touch()

        # Act
        _log_discovered_files(logger, [file_path], root, None)

        # Assert
        header_calls = [str(call) for call in logger.header.call_args_list]
        assert any("script.py" in call for call in header_calls)
        assert not any("[" in call for call in header_calls if "Discovered" not in call)

    def test_single_file_no_second_column(self, tmp_path: Path) -> None:
        """Verify single file renders with one row and no second column."""
        # Arrange
        logger = MagicMock()
        root = tmp_path
        file_path = root / "only.py"
        file_path.touch()

        # Act
        _log_discovered_files(logger, [file_path], root, None)

        # Assert
        header_calls = [str(call) for call in logger.header.call_args_list]
        assert any("Discovered 1 Python file(s)" in call for call in header_calls)
        file_lines = [call for call in header_calls if "Discovered" not in call]
        assert len(file_lines) == 1
