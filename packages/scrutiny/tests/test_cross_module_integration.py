"""Cross-module integration tests for scrutiny pipeline.

Tests realistic multi-step workflows that exercise the dependency chains
between main.py and its direct imports (config, configs/resolver,
configs/dataclasses, execution/handlers, execution/services, output/logger).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.config import UserDefaults
from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.cli import parse_cli_to_dict, create_argument_parser
from scrutiny.core.enums import (
    ConfigTier,
    FrameworkSelection,
    LoggerLevel,
    LogLocation,
    SecurityTool,
)
from scrutiny.core.exceptions import (
    SCRProjectRootError,
    SCRSystemError,
    ExitCode,
)
from scrutiny.execution.results import ToolResult
from scrutiny.main import (
    _compute_mi_ranks,
    _create_logger,
    _resolve_log_root,
    _verify_tool_availability,
)
from scrutiny.output.header import (
    _format_header_normal,
    _format_header_verbose,
    _log_discovered_files,
)
from scrutiny.output.logger import SCRLogger, DeferredLogBuffer
from scrutiny.output.reporting import (
    _compute_result_totals,
    _format_tool_status_line,
    determine_exit_code,
)
from scrutiny.output.run_logging import _build_fatal_error_summary
from conftest import make_global_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_result(
    tool: str = "mypy",
    success: bool = True,
    exit_code: int = 0,
    issues_found: int = 0,
    issues_fixed: int = 0,
    execution_time: float = 1.0,
    error_code: int = 0,
) -> ToolResult:
    """Build a ToolResult with sensible defaults for testing."""
    return ToolResult(
        tool=tool,
        success=success,
        exit_code=exit_code,
        execution_time=execution_time,
        files_processed=3,
        stdout="",
        stderr="",
        issues_found=issues_found,
        issues_fixed=issues_fixed,
        error_code=error_code,
    )


# ---------------------------------------------------------------------------
# Integration: UserDefaults -> snapshot -> ConfigResolver -> GlobalConfig
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSnapshotToConfigResolution:
    """Integration tests for the config bootstrap pipeline."""

    def test_snapshot_feeds_resolver_produces_valid_config(self) -> None:
        """Snapshot created from UserDefaults produces a valid GlobalConfig via resolver."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.config_tier == UserDefaults.SCR_CONFIG_TIER
        assert config.python_version == UserDefaults.SCR_PYTHON_VERSION
        assert config.line_length == UserDefaults.SCR_LINE_LENGTH

    def test_cli_overrides_propagate_through_resolver(self) -> None:
        """CLI dict overrides flow through resolver into GlobalConfig fields."""
        snapshot = UserDefaults.to_frozen()
        cli_dict: dict[str, Any] = {
            "config_tier": ConfigTier.ESSENTIAL,
            "parallel": True,
            "check_only": True,
        }
        resolver = ConfigResolver(
            cli_args=cli_dict,
            pyproject_config={},
            context=None,
            tier=ConfigTier.ESSENTIAL,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.config_tier == ConfigTier.ESSENTIAL
        assert config.parallel is True
        assert config.check_only is True

    def test_context_detection_influences_enabled_tools(self) -> None:
        """Different ContextDetection values produce different enabled tool lists."""
        config = make_global_config(
            run_security=True,
            security_tool=SecurityTool.BANDIT,
            pipeline_security_tool=SecurityTool.RUFF,
        )
        ide_tools = config.get_enabled_tools(ContextDetection.IDE)
        ci_tools = config.get_enabled_tools(ContextDetection.CI)

        # Both should include core tools
        assert "ruff_formatter" in ide_tools
        # Security tool differs by context
        assert "bandit" in ide_tools
        assert "ruff_security" in ci_tools


# ---------------------------------------------------------------------------
# Integration: CLI parsing -> parse_cli_to_dict -> resolver
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCliToConfigChain:
    """Integration tests for CLI -> dict -> resolver chain."""

    def test_argparse_to_dict_to_resolver_round_trip(self) -> None:
        """Full chain: argparse args -> cli_dict -> resolver -> GlobalConfig."""
        parser = create_argument_parser()
        args = parser.parse_args(["--essential", "--no-parallel"])
        cli_dict = parse_cli_to_dict(args)

        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args=cli_dict,
            pyproject_config={},
            context=None,
            tier=cli_dict.get("config_tier", snapshot.scr_config_tier),
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.config_tier == ConfigTier.ESSENTIAL
        assert config.parallel is False

    def test_framework_flag_flows_through_chain(self) -> None:
        """The --framework flag produces a GlobalConfig with the correct framework."""
        parser = create_argument_parser()
        args = parser.parse_args(["--framework", "django"])
        cli_dict = parse_cli_to_dict(args)

        assert cli_dict["framework"] == FrameworkSelection.DJANGO


# ---------------------------------------------------------------------------
# Integration: tool execution -> result aggregation -> exit code
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutionToReportingChain:
    """Integration tests for tool results -> aggregation -> exit code."""

    def test_clean_results_produce_zero_exit_code(self) -> None:
        """All-clean tool results yield exit code 0."""
        results = [
            _make_tool_result(tool="ruff_formatter"),
            _make_tool_result(tool="mypy"),
            _make_tool_result(tool="radon"),
        ]
        totals = _compute_result_totals(results)
        exit_code = determine_exit_code(results)

        assert exit_code == 0
        assert totals.total_issues == 0
        assert totals.total_fixed == 0

    def test_issues_results_produce_exit_code_ten(self) -> None:
        """Results with issues but no crashes yield exit code 10."""
        results = [
            _make_tool_result(tool="ruff_linter", issues_found=5, issues_fixed=2),
            _make_tool_result(tool="mypy", issues_found=3),
        ]
        totals = _compute_result_totals(results)
        exit_code = determine_exit_code(results)

        expected_total_issues = 5 + 3
        expected_total_fixed = 2
        assert exit_code == ExitCode.ISSUES_FOUND
        assert totals.total_issues == expected_total_issues
        assert totals.total_fixed == expected_total_fixed

    def test_fatal_error_produces_exit_code_eleven(self) -> None:
        """A crashed tool yields exit code 11 regardless of issues in other tools."""
        results = [
            _make_tool_result(tool="ruff_linter", issues_found=2),
            _make_tool_result(
                tool="mypy",
                success=False,
                exit_code=2,
                error_code=ExitCode.TOOL_EXECUTION,
            ),
        ]
        exit_code = determine_exit_code(results)

        assert exit_code == ExitCode.TOOL_FAILURE

    def test_status_line_formatting_matches_result_state(self) -> None:
        """Status lines reflect pass, issues, and failure states correctly."""
        passed = _make_tool_result(tool="ruff_formatter")
        issues = _make_tool_result(tool="mypy", issues_found=3)
        failed = _make_tool_result(
            tool="bandit",
            success=False,
            exit_code=2,
            error_code=ExitCode.TOOL_EXECUTION,
        )

        assert "passed" in _format_tool_status_line(passed, 14)
        assert "3 issues" in _format_tool_status_line(issues, 14)
        assert "failed" in _format_tool_status_line(failed, 14)


# ---------------------------------------------------------------------------
# _format_header_verbose / _format_header_normal
# ---------------------------------------------------------------------------


class TestHeaderFormatting:
    """Tests for header output formatting functions."""

    def test_verbose_header_includes_all_settings(self) -> None:
        """Verbose header emits tier, context, security, parallel, files, timeout."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(
            framework=FrameworkSelection.DJANGO,
            pyproject_only=True,
        )
        context = ContextDetection.CLI

        _format_header_verbose(
            logger,
            config,
            context,
            file_count=10,
            column_width=35,
            pyproject_has_config=True,
        )

        # Collect all header calls
        header_texts = [call.args[0] for call in logger.header.call_args_list]
        combined = "\n".join(header_texts)

        assert "Tier:" in combined
        assert "Context:" in combined
        assert "Security:" in combined
        assert "Parallel:" in combined
        assert "Files:" in combined
        assert "Timeout:" in combined
        assert "Framework:" in combined
        assert "Mode:      pyproject" in combined

    def test_normal_header_omits_operational_details(self) -> None:
        """Normal header shows tier, context, security but not files/timeout."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()
        context = ContextDetection.CLI

        _format_header_normal(logger, config, context)

        header_texts = [call.args[0] for call in logger.header.call_args_list]
        combined = "\n".join(header_texts)

        assert "Tier:" in combined
        assert "Context:" in combined
        assert "Security:" in combined
        assert "Files:" not in combined
        assert "Timeout:" not in combined


# ---------------------------------------------------------------------------
# _log_discovered_files
# ---------------------------------------------------------------------------


class TestLogDiscoveredFiles:
    """Tests for the discovered-files listing function."""

    def test_renders_files_in_two_column_layout(self) -> None:
        """Files are rendered with file count and two-column layout."""
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")
        files = [root / "a.py", root / "b.py", root / "c.py"]

        _log_discovered_files(logger, files, root, mi_ranks=None)

        header_texts = [call.args[0] for call in logger.header.call_args_list]
        combined = "\n".join(header_texts)

        assert "Discovered 3 Python file(s)" in combined
        assert "a.py" in combined
        assert "b.py" in combined
        assert "c.py" in combined

    def test_annotates_files_with_mi_ranks(self) -> None:
        """Files with MI rank data are annotated with [rank] suffix."""
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")
        files = [root / "module.py"]
        mi_ranks = {"module.py": "C"}

        _log_discovered_files(logger, files, root, mi_ranks=mi_ranks)

        header_texts = [call.args[0] for call in logger.header.call_args_list]
        combined = "\n".join(header_texts)

        assert "module.py [C]" in combined


# ---------------------------------------------------------------------------
# _create_logger
# ---------------------------------------------------------------------------


class TestCreateLogger:
    """Tests for the logger creation fallback behavior."""

    def test_creates_console_only_logger_on_file_error(self, tmp_path: Path) -> None:
        """Falls back to console-only logging when file creation fails."""
        config = make_global_config(
            create_log=True,
            console_logger_level=LoggerLevel.NORMAL,
        )

        with patch(
            "scrutiny.main.SCRLogger",
            autospec=True,
        ) as mock_cls:
            from scrutiny.core.exceptions import SCRLoggerFileError

            # First call raises, second succeeds
            fallback_logger = MagicMock(spec=SCRLogger)
            mock_cls.side_effect = [
                SCRLoggerFileError("Permission denied"),
                fallback_logger,
            ]

            result = _create_logger(tmp_path, config)

            assert result is fallback_logger
            fallback_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_log_root
# ---------------------------------------------------------------------------


class TestResolveLogRoot:
    """Tests for log root resolution across LogLocation modes."""

    def test_current_dir_mode_returns_start_path(self, tmp_path: Path) -> None:
        """CURRENT_DIR mode always returns the start path directory."""
        config = make_global_config(log_location=LogLocation.CURRENT_DIR)
        result = _resolve_log_root(tmp_path, config)

        assert result == tmp_path.resolve()

    def test_hybrid_mode_falls_back_to_cwd(self, tmp_path: Path) -> None:
        """HYBRID mode returns start path when no project root is found."""
        config = make_global_config(log_location=LogLocation.HYBRID)

        with patch(
            "scrutiny.main.ProjectRootService.get_actual_project_root",
            autospec=True,
            side_effect=SCRProjectRootError("No markers"),
        ):
            DeferredLogBuffer.clear()
            result = _resolve_log_root(tmp_path, config)

        assert result == tmp_path.resolve()

    def test_project_root_mode_returns_none_on_missing_root(self, tmp_path: Path) -> None:
        """PROJECT_ROOT mode disables logging when no root is found."""
        config = make_global_config(log_location=LogLocation.PROJECT_ROOT)

        with patch(
            "scrutiny.main.ProjectRootService.get_actual_project_root",
            autospec=True,
            side_effect=SCRProjectRootError("No markers"),
        ):
            DeferredLogBuffer.clear()
            result = _resolve_log_root(tmp_path, config)

        assert result is None


# ---------------------------------------------------------------------------
# _compute_mi_ranks
# ---------------------------------------------------------------------------


class TestComputeMiRanks:
    """Tests for MI rank computation delegation."""

    def test_returns_none_when_radon_not_enabled(self) -> None:
        """Returns None when radon is not in the tool list."""
        result = _compute_mi_ranks(
            tool_names=["mypy", "ruff_linter"],
            discovered_files=[Path("/fake.py")],
            effective_root=Path("/"),
            global_config=make_global_config(),
        )

        assert result is None


# ---------------------------------------------------------------------------
# _verify_tool_availability
# ---------------------------------------------------------------------------


class TestVerifyToolAvailability:
    """Tests for pre-flight tool verification."""

    def test_raises_system_error_for_missing_tools(self) -> None:
        """Raises SCRSystemError listing all missing executables."""
        with (
            patch(
                "scrutiny.main.which",
                autospec=True,
                return_value=None,
            ),
            pytest.raises(SCRSystemError, match="Missing tools"),
        ):
            _verify_tool_availability(["mypy", "radon"])


# ---------------------------------------------------------------------------
# _build_fatal_error_summary
# ---------------------------------------------------------------------------


class TestBuildFatalErrorSummary:
    """Tests for fatal error summary formatting."""

    def test_extracts_error_from_combined_output(self) -> None:
        """Extracts meaningful error from combined stderr+stdout."""
        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.5,
            files_processed=1,
            stdout="",
            stderr="mypy: error: Cannot find implementation\n",
            error_code=ExitCode.TOOL_EXECUTION,
        )
        summary = _build_fatal_error_summary("mypy", result)

        assert "mypy" in summary
        assert "Cannot find implementation" in summary

    def test_handles_empty_output(self) -> None:
        """Produces 'unknown error' summary when output is empty."""
        result = ToolResult(
            tool="bandit",
            success=False,
            exit_code=2,
            execution_time=0.1,
            files_processed=0,
            stdout="",
            stderr="",
            error_code=ExitCode.TOOL_EXECUTION,
        )
        summary = _build_fatal_error_summary("bandit", result)

        assert "unknown error" in summary


# ---------------------------------------------------------------------------
# Cross-module: config -> resolver -> tool dispatch -> reporting
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConfigToDispatchToReportingChain:
    """End-to-end chain: snapshot -> resolver -> config -> tool names -> reporting."""

    def test_snapshot_to_config_to_tools_to_exit_code(self) -> None:
        """Full pipeline: UserDefaults -> resolver -> enabled tools -> result -> exit code."""
        # Arrange: build config from defaults
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={"run_mypy": False},
            pyproject_config={},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        # Act: get enabled tools
        tools = config.get_enabled_tools(ContextDetection.CLI)
        assert "mypy" not in tools

        # Act: simulate tool results and compute exit code
        results = [_make_tool_result(tool=t, success=True, issues_found=0) for t in tools[:2]]
        totals = _compute_result_totals(results)
        exit_code = determine_exit_code(results)

        # Assert
        assert exit_code == 0
        assert totals.total_issues == 0

    def test_cli_override_flows_through_resolver_to_config(self) -> None:
        """CLI args flow through resolver and override defaults in GlobalConfig."""
        # Arrange: CLI disables parallel
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={"parallel": False, "check_only": True},
            pyproject_config={},
            context=ContextDetection.CLI,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        # Assert: CLI overrides applied
        assert config.parallel is False
        assert config.check_only is True
