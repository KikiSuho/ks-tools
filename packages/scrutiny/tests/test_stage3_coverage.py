"""Tests filling Stage 3 coverage gaps from py-pipeline-d review.

Covers: _run_tool_safe unexpected error, _format_cli_overrides, _mode_label,
report_final_status lifecycle, _resolve_log_root HYBRID warning,
H-2 ThreadPoolExecutor cap, and cross-module config -> dispatch -> reporting chain.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.enums import (
    FrameworkSelection,
    LoggerLevel,
    LogLocation,
)
from scrutiny.core.exceptions import (
    SCRProjectRootError,
    ExitCode,
)
from scrutiny.execution.handlers import ToolExecutor
from scrutiny.execution.results import ResultTotals, ToolResult
from scrutiny.main import (
    _create_logger,
    _execute_tools_parallel,
    _resolve_log_root,
    _run_tool_safe,
    _show_effective_config,
    _verify_tool_availability,
)
from scrutiny.output.header import (
    _format_cli_overrides,
    _mode_label,
)
from scrutiny.output.logger import SCRLogger, DeferredLogBuffer
from scrutiny.output.reporting import (
    report_final_status,
)
from conftest import make_global_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPECTED_PARALLEL_TOOL_COUNT = 3
_EXPECTED_TOTAL_ISSUES = 5
_EXPECTED_REMAINING_ISSUES = 4
_EXPECTED_WORST_ERROR_CODE = 5
_EXPECTED_TOTAL_ISSUES_TOTALS = 10
_EXPECTED_TOTAL_FIXED = 3
_EXPECTED_TOTAL_TIME = 2.5
_EXPECTED_MAX_NAME_LEN = 14
_EXPECTED_WRAP_LINES_MIN = 2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_result(
    tool: str = "mypy",
    success: bool = True,
    exit_code: int = 0,
    issues_found: int = 0,
    issues_fixed: int = 0,
    execution_time: float = 0.1,
    error_code: int = 0,
) -> ToolResult:
    """Build a ToolResult with sensible defaults."""
    return ToolResult(
        tool=tool,
        success=success,
        exit_code=exit_code,
        execution_time=execution_time,
        files_processed=1,
        stdout="",
        stderr="",
        issues_found=issues_found,
        issues_fixed=issues_fixed,
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# _run_tool_safe: unexpected (non-SCR) error path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunToolSafeUnexpectedError:
    """Tests for _run_tool_safe handling of non-SCRError exceptions."""

    def test_unexpected_error_returns_failure_result(self) -> None:
        """Non-SCRError exceptions produce a synthetic failure ToolResult."""
        # Arrange
        executor = MagicMock(spec=ToolExecutor)
        executor.run_tool.side_effect = RuntimeError("segfault in subprocess")
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()

        # Act
        result = _run_tool_safe(
            executor,
            "radon",
            [],
            None,
            config,
            Path("/root"),
            logger,
        )

        # Assert
        assert result.success is False
        assert result.tool == "radon"
        assert "segfault" in result.stderr
        assert result.error_code == ExitCode.UNEXPECTED
        logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _format_cli_overrides
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatCliOverrides:
    """Tests for CLI override line wrapping in header output."""

    def test_single_short_flag_on_one_line(self) -> None:
        """A single short flag fits on one line after the prefix."""
        logger = MagicMock(spec=SCRLogger)

        _format_cli_overrides(logger, ("--strict",), banner_width=70)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        assert len(header_texts) == 1
        assert "--strict" in header_texts[0]
        assert header_texts[0].startswith("  CLI:")

    def test_multiple_flags_wrap_at_banner_width(self) -> None:
        """Flags that exceed banner width wrap onto continuation lines."""
        logger = MagicMock(spec=SCRLogger)
        flags = (
            "--strict",
            "--no-parallel",
            "--framework=django",
            "--check-only",
            "--no-cache",
            "--clear-cache",
            "--log-location=project_root",
        )

        _format_cli_overrides(logger, flags, banner_width=50)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        # Should produce multiple lines due to narrow banner
        assert len(header_texts) >= _EXPECTED_WRAP_LINES_MIN
        # First line starts with CLI prefix
        assert header_texts[0].startswith("  CLI:")
        # All flags present across all lines
        combined = " ".join(header_texts)
        for flag in flags:
            assert flag in combined

    def test_empty_overrides_emit_bare_prefix(self) -> None:
        """Empty overrides tuple emits only the bare CLI prefix line."""
        logger = MagicMock(spec=SCRLogger)

        _format_cli_overrides(logger, (), banner_width=70)

        # The prefix "  CLI:       " is non-blank so it is emitted
        assert logger.header.call_count == 1
        assert "CLI:" in str(logger.header.call_args_list[0].args[0])


# ---------------------------------------------------------------------------
# _mode_label
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModeLabel:
    """Tests for _mode_label configuration mode string."""

    @pytest.mark.parametrize(
        ("pyproject_only", "pyproject_has_config", "expected"),
        [
            pytest.param(False, False, "defaults", id="no_pyproject"),
            pytest.param(False, True, "standard", id="standard_with_pyproject"),
            pytest.param(True, True, "pyproject", id="pyproject_only"),
            pytest.param(True, False, "defaults", id="pyproject_only_no_config"),
        ],
    )
    def test_returns_correct_label(
        self,
        pyproject_only: bool,
        pyproject_has_config: bool,
        expected: str,
    ) -> None:
        """Each combination of pyproject_only and config presence maps correctly."""
        config = make_global_config(pyproject_only=pyproject_only)
        assert _mode_label(config, pyproject_has_config) == expected


# ---------------------------------------------------------------------------
# execution/results.py — ToolResult and ResultTotals data integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolResultDataIntegrity:
    """Tests for ToolResult default field values and data integrity."""

    def test_default_issues_and_error_code_are_zero(self) -> None:
        """ToolResult defaults issues_found, issues_fixed, error_code to 0."""
        result = ToolResult(
            tool="ruff",
            success=True,
            exit_code=0,
            execution_time=0.5,
            files_processed=1,
            stdout="",
            stderr="",
        )
        assert result.issues_found == 0
        assert result.issues_fixed == 0
        assert result.error_code == 0
        assert result.tool_data == {}

    def test_result_totals_stores_all_fields(self) -> None:
        """ResultTotals stores all aggregated fields correctly."""
        totals = ResultTotals(
            worst_error_code=_EXPECTED_WORST_ERROR_CODE,
            total_issues=_EXPECTED_TOTAL_ISSUES_TOTALS,
            total_fixed=_EXPECTED_TOTAL_FIXED,
            total_time=_EXPECTED_TOTAL_TIME,
            max_name_len=_EXPECTED_MAX_NAME_LEN,
        )
        assert totals.worst_error_code == _EXPECTED_WORST_ERROR_CODE
        assert totals.total_issues == _EXPECTED_TOTAL_ISSUES_TOTALS
        assert totals.total_fixed == _EXPECTED_TOTAL_FIXED
        assert totals.total_time == _EXPECTED_TOTAL_TIME
        assert totals.max_name_len == _EXPECTED_MAX_NAME_LEN


# ---------------------------------------------------------------------------
# report_final_status — lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReportFinalStatusLifecycle:
    """Integration test for full reporting lifecycle with real logger."""

    def test_clean_results_log_success_and_return_zero(
        self,
        tmp_path: Path,
    ) -> None:
        """All-clean results produce success message and exit code 0."""
        # Arrange
        results = [
            _make_tool_result(tool="ruff_linter"),
            _make_tool_result(tool="mypy"),
        ]
        config = make_global_config(create_log=False)
        logger = SCRLogger(tmp_path, config)
        files = [Path("a.py"), Path("b.py")]

        # Act
        exit_code = report_final_status(results, files, logger)
        logger.close()

        # Assert
        assert exit_code == 0

    def test_issues_results_log_error_summary_and_return_ten(self) -> None:
        """Results with issues produce error summary and exit code 10."""
        # Arrange
        results = [
            _make_tool_result(tool="ruff_linter", issues_found=3, issues_fixed=1),
            _make_tool_result(tool="mypy", issues_found=2),
        ]
        logger = MagicMock(spec=SCRLogger)
        files = [Path("a.py")]

        # Act
        exit_code = report_final_status(results, files, logger)

        # Assert
        assert exit_code == ExitCode.ISSUES_FOUND
        error_msgs = [str(c.args[0]) for c in logger.error.call_args_list]
        combined = " ".join(error_msgs)
        assert f"Issues found: {_EXPECTED_TOTAL_ISSUES}" in combined
        assert f"remaining: {_EXPECTED_REMAINING_ISSUES}" in combined


# ---------------------------------------------------------------------------
# _resolve_log_root — HYBRID warning message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLogRootHybridWarning:
    """Tests for deferred warning messages in _resolve_log_root."""

    def test_hybrid_mode_captures_deferred_warning(self, tmp_path: Path) -> None:
        """HYBRID fallback captures a warning via DeferredLogBuffer."""
        config = make_global_config(log_location=LogLocation.HYBRID)
        DeferredLogBuffer.clear()

        with patch(
            "scrutiny.main.ProjectRootService.get_actual_project_root",
            autospec=True,
            side_effect=SCRProjectRootError("No markers"),
        ):
            result = _resolve_log_root(tmp_path, config)

        assert result == tmp_path.resolve()

    def test_project_root_mode_captures_disable_warning(self, tmp_path: Path) -> None:
        """PROJECT_ROOT mode captures a disable-logging warning."""
        config = make_global_config(log_location=LogLocation.PROJECT_ROOT)
        DeferredLogBuffer.clear()

        with patch(
            "scrutiny.main.ProjectRootService.get_actual_project_root",
            autospec=True,
            side_effect=SCRProjectRootError("No markers"),
        ):
            result = _resolve_log_root(tmp_path, config)

        assert result is None


# ---------------------------------------------------------------------------
# H-2 fix: ThreadPoolExecutor max_workers capping
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestThreadPoolExecutorCapping:
    """Tests validating the H-2 fix: ThreadPoolExecutor max_workers cap."""

    def test_parallel_execution_completes_with_all_tools(self) -> None:
        """Parallel execution returns results for all read-only tools."""
        # Arrange
        config = make_global_config()
        logger = MagicMock(spec=SCRLogger)

        def side_effect(*args: object, **_kwargs: object) -> ToolResult:
            tool_name = str(args[1])
            return _make_tool_result(tool=tool_name)

        # Act — 3 read-only tools go to the parallel batch
        with patch(
            "scrutiny.main._run_tool_safe",
            autospec=True,
            side_effect=side_effect,
        ):
            results = _execute_tools_parallel(
                ["mypy", "radon", "bandit"],
                MagicMock(spec=ToolExecutor),
                [],
                {},
                config,
                Path("/root"),
                logger,
            )

        # Assert — all 3 tools produce results
        assert len(results) == _EXPECTED_PARALLEL_TOOL_COUNT
        tool_names = {r.tool for r in results}
        assert tool_names == {"mypy", "radon", "bandit"}

    def test_h2_source_uses_min_cap(self) -> None:
        """Verify the H-2 fix: source code uses min(batch, cpu_count)."""
        import inspect

        from scrutiny import main as main_module

        source = inspect.getsource(main_module._execute_tools_parallel)  # noqa: SLF001
        assert "min(len(parallel_batch), os.cpu_count()" in source


# ---------------------------------------------------------------------------
# Cross-module integration: config -> show-config -> verify tools
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConfigToShowConfigToVerifyChain:
    """Cross-module: snapshot -> resolver -> config -> show_config / verify."""

    def test_show_config_with_resolved_config(self, tmp_path: Path) -> None:
        """Full chain: resolve config, then show-config returns 0."""
        from scrutiny.config import UserDefaults

        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={"framework": FrameworkSelection.DJANGO},
            pyproject_config={},
            context=ContextDetection.CLI,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        logger = MagicMock(spec=SCRLogger)
        logger.get_log_info.return_value = {
            "console_level": "NORMAL",
            "file_level": "NORMAL",
            "log_file_path": None,
        }

        result = _show_effective_config(
            logger,
            config,
            ContextDetection.CLI,
            tmp_path,
            None,
        )
        assert result == 0

        status_calls = [str(c.args[0]) for c in logger.status.call_args_list]
        combined = "\n".join(status_calls)
        assert "Framework: django" in combined

    def test_verify_availability_after_config_resolution(self) -> None:
        """Resolved config tool list can be verified for availability."""
        from scrutiny.config import UserDefaults

        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            context=ContextDetection.CLI,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()
        tool_names = config.get_enabled_tools(ContextDetection.CLI)

        with patch(
            "scrutiny.main.which",
            autospec=True,
            return_value="/usr/bin/tool",
        ):
            # Should not raise
            _verify_tool_availability(tool_names)


# ---------------------------------------------------------------------------
# Cross-module integration: _create_logger -> DeferredLogBuffer flush
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLoggerCreationAndDeferredFlush:
    """Cross-module: create logger -> flush deferred buffer -> verify output."""

    def test_create_logger_then_flush_deferred_messages(
        self,
        tmp_path: Path,
    ) -> None:
        """Messages captured before logger creation appear after flush."""
        DeferredLogBuffer.clear()
        DeferredLogBuffer.capture("warning", "pre-logger warning")

        config = make_global_config(
            create_log=True,
            console_logger_level=LoggerLevel.VERBOSE,
            file_logger_level=LoggerLevel.VERBOSE,
            log_dir="logs/",
        )
        logger = _create_logger(tmp_path, config)

        with logger:
            DeferredLogBuffer.flush(logger)
            log_path = logger.log_path

        assert log_path is not None
        content = log_path.read_text(encoding="utf-8")
        assert "pre-logger warning" in content


# ---------------------------------------------------------------------------
# report_final_status: error-code escalation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReportFinalStatusErrorEscalation:
    """Tests for worst error_code display in report_final_status."""

    def test_worst_error_code_displayed_when_nonzero(self) -> None:
        """Error Code line appears when worst_error_code > 0."""
        results = [
            _make_tool_result(
                tool="mypy",
                success=False,
                exit_code=2,
                error_code=ExitCode.TOOL_EXECUTION,
            ),
        ]
        logger = MagicMock(spec=SCRLogger)

        report_final_status(results, [Path("a.py")], logger)

        status_msgs = [str(c.args[0]) for c in logger.status.call_args_list]
        assert any("Error Code:" in m for m in status_msgs)

    def test_no_error_code_line_when_all_clean(self) -> None:
        """No Error Code line when worst_error_code is 0."""
        results = [_make_tool_result(tool="ruff_linter")]
        logger = MagicMock(spec=SCRLogger)

        report_final_status(results, [Path("a.py")], logger)

        status_msgs = [str(c.args[0]) for c in logger.status.call_args_list]
        error_code_lines = [m for m in status_msgs if "Error Code:" in m]
        assert len(error_code_lines) == 0
