"""Tests filling coverage gaps identified by py-test-review-d.

Covers missing integration/lifecycle, edge-case, and error-path tests
across: core/enums.py, config.py, output/logger.py, output/formatting.py,
execution/services.py, core/tool_data.py, and cross-module workflows.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scrutiny.config import UserDefaults, UserDefaultsSnapshot
from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.enums import (
    ConfigSource,
    ConfigTier,
    FrameworkSelection,
    LoggerLevel,
    PythonVersion,
    SearchDepth,
)
from scrutiny.core.exceptions import (
    SCRProjectRootError,
    SCRSystemError,
    SCRUnexpectedError,
    ExitCode,
    handle_errors,
)
from scrutiny.core.tool_data import (
    build_ruff_rules,
    get_test_config_tier,
)
from scrutiny.execution.results import ToolResult
from scrutiny.execution.services import (
    FileDiscoveryService,
    ProjectRootService,
    clear_tool_caches,
)
from scrutiny.core.cli import parse_cli_to_dict, create_argument_parser
from scrutiny.output.reporting import determine_exit_code
from scrutiny.output.formatting import OutputFormatter, SourceReader
from scrutiny.output.logger import SCRLogger, DeferredLogBuffer
from conftest import make_global_config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_shared_state() -> Iterator[None]:
    """Clear class-level mutable state before and after each test."""
    DeferredLogBuffer.clear()
    SourceReader._source_cache.clear()  # noqa: SLF001
    yield
    DeferredLogBuffer.clear()
    SourceReader._source_cache.clear()  # noqa: SLF001


# ---------------------------------------------------------------------------
# core/enums.py — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPythonVersionToDotted:
    """Edge-case tests for PythonVersion.to_dotted conversion."""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            pytest.param(PythonVersion.PY39, "3.9", id="py39"),
            pytest.param(PythonVersion.PY310, "3.10", id="py310"),
            pytest.param(PythonVersion.PY311, "3.11", id="py311"),
            pytest.param(PythonVersion.PY312, "3.12", id="py312"),
            pytest.param(PythonVersion.PY313, "3.13", id="py313"),
        ],
    )
    def test_converts_compact_format_to_dotted(
        self,
        version: PythonVersion,
        expected: str,
    ) -> None:
        """Each PythonVersion member produces the correct dotted string."""
        assert version.to_dotted == expected


@pytest.mark.unit
class TestConfigSourceStr:
    """Edge-case tests for ConfigSource.__str__."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            pytest.param(ConfigSource.CLI, "cli", id="cli"),
            pytest.param(ConfigSource.PYPROJECT, "pyproject.toml", id="pyproject"),
            pytest.param(ConfigSource.CONTEXT, "context_detection", id="context"),
            pytest.param(ConfigSource.SCRIPT, "script_config", id="script"),
            pytest.param(ConfigSource.TOOL_DEFAULT, "tool_default", id="tool_default"),
        ],
    )
    def test_str_returns_value(
        self,
        source: ConfigSource,
        expected: str,
    ) -> None:
        """ConfigSource.__str__ returns the enum value string."""
        assert str(source) == expected


# ---------------------------------------------------------------------------
# config.py — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUserDefaultsSnapshotEdgeCases:
    """Edge-case tests for UserDefaultsSnapshot creation and immutability."""

    def test_snapshot_with_overridden_defaults_preserves_types(self) -> None:
        """Snapshot from modified UserDefaults preserves enum types."""
        original_tier = UserDefaults.SCR_CONFIG_TIER
        try:
            UserDefaults.SCR_CONFIG_TIER = ConfigTier.ESSENTIAL
            snapshot = UserDefaults.to_frozen()
            assert snapshot.scr_config_tier == ConfigTier.ESSENTIAL
            assert isinstance(snapshot.scr_config_tier, ConfigTier)
        finally:
            UserDefaults.SCR_CONFIG_TIER = original_tier

    def test_snapshot_default_construction_matches_user_defaults(self) -> None:
        """Direct UserDefaultsSnapshot() matches UserDefaults.to_frozen()."""
        direct = UserDefaultsSnapshot()
        frozen = UserDefaults.to_frozen()
        assert direct == frozen


# ---------------------------------------------------------------------------
# core/tool_data.py — edge cases for build_ruff_rules
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildRuffRulesEdgeCases:
    """Edge-case tests for ruff rule composition."""

    @pytest.mark.parametrize(
        "framework",
        [
            pytest.param(FrameworkSelection.DJANGO, id="django"),
            pytest.param(FrameworkSelection.FASTAPI, id="fastapi"),
            pytest.param(FrameworkSelection.AIRFLOW, id="airflow"),
            pytest.param(FrameworkSelection.NUMPY, id="numpy"),
            pytest.param(FrameworkSelection.PANDAS, id="pandas"),
        ],
    )
    def test_framework_rules_extend_select(self, framework: FrameworkSelection) -> None:
        """Non-NONE frameworks add rules to the select tuple."""
        base_select, _ = build_ruff_rules(
            ConfigTier.STRICT,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            True,
        )
        fw_select, _ = build_ruff_rules(
            ConfigTier.STRICT,
            framework,
            PythonVersion.PY39,
            True,
        )
        assert len(fw_select) > len(base_select)

    def test_mypy_overlap_added_when_mypy_enabled(self) -> None:
        """Enabling mypy adds overlap ignore rules."""
        _, ignore_with = build_ruff_rules(
            ConfigTier.STRICT,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            True,
        )
        _, ignore_without = build_ruff_rules(
            ConfigTier.STRICT,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            False,
        )
        assert len(ignore_with) >= len(ignore_without)

    @pytest.mark.parametrize(
        ("tier", "expected_label"),
        [
            pytest.param(ConfigTier.ESSENTIAL, "relaxed", id="essential"),
            pytest.param(ConfigTier.STANDARD, "relaxed", id="standard"),
            pytest.param(ConfigTier.STRICT, "strict", id="strict"),
            pytest.param(ConfigTier.INSANE, "strict", id="insane"),
        ],
    )
    def test_get_test_config_tier_mapping(
        self,
        tier: ConfigTier,
        expected_label: str,
    ) -> None:
        """get_test_config_tier maps each tier to its test label."""
        assert get_test_config_tier(tier) == expected_label


# ---------------------------------------------------------------------------
# output/formatting.py — edge cases + integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSourceReaderEdgeCases:
    """Edge-case tests for SourceReader."""

    def test_clear_cache_removes_entries(self, tmp_path: Path) -> None:
        """clear_cache empties the internal cache dict."""
        src = tmp_path / "cached.py"
        src.write_text("line1\nline2\n", encoding="utf-8")
        SourceReader.read_source_context(str(src), 1)
        assert str(src) in SourceReader._source_cache  # noqa: SLF001

        SourceReader.clear_cache()
        assert len(SourceReader._source_cache) == 0  # noqa: SLF001

    def test_zero_context_lines_returns_single_line(self, tmp_path: Path) -> None:
        """context_lines=0 returns exactly the target line."""
        src = tmp_path / "single.py"
        src.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        result = SourceReader.read_source_context(str(src), 2, context_lines=0)
        assert len(result) == 1
        assert "beta" in result[0]


@pytest.mark.integration
class TestOutputFormatterLifecycle:
    """Integration test for OutputFormatter read-format-display workflow."""

    def test_read_then_format_issue_workflow(self, tmp_path: Path) -> None:
        """Realistic workflow: read source, then format a ruff issue over it."""
        src = tmp_path / "target.py"
        src.write_text("import os\nimport sys\nprint('hello')\n", encoding="utf-8")

        context = SourceReader.read_source_context(str(src), 1, context_lines=1)
        assert len(context) >= 1
        assert "import os" in context[0]

        summary = OutputFormatter.generate_summary(
            "ruff_linter",
            files_processed=1,
            issues_found=1,
        )
        assert "Issues: 1" in summary


# ---------------------------------------------------------------------------
# output/logger.py — integration/lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSCRLoggerLifecycle:
    """Integration test for SCRLogger create-use-close lifecycle."""

    def test_context_manager_creates_and_closes_log(self, tmp_path: Path) -> None:
        """SCRLogger context manager opens and closes the log file."""
        config = make_global_config(
            create_log=True,
            console_logger_level=LoggerLevel.VERBOSE,
            file_logger_level=LoggerLevel.VERBOSE,
            log_dir="logs/",
        )
        with SCRLogger(tmp_path, config) as logger:
            assert logger.log_file is not None
            logger.status("test status")
            logger.warning("test warning")
            logger.error("test error")
            log_path = logger.log_path

        assert logger.log_file is None
        assert log_path is not None
        content = log_path.read_text(encoding="utf-8")
        assert "test status" in content
        assert "test warning" in content
        assert "test error" in content

    def test_no_log_file_when_disabled(self, tmp_path: Path) -> None:
        """SCRLogger with create_log=False does not open a file."""
        config = make_global_config(create_log=False)
        logger = SCRLogger(tmp_path, config)
        assert logger.log_file is None
        assert logger.log_path is None
        logger.close()

    def test_get_log_info_returns_config_snapshot(self, tmp_path: Path) -> None:
        """get_log_info returns a dictionary with expected keys."""
        config = make_global_config(create_log=False)
        logger = SCRLogger(tmp_path, config)
        info = logger.get_log_info()
        assert "console_level" in info
        assert "file_level" in info
        assert "log_file_enabled" in info
        assert info["log_file_enabled"] is False
        logger.close()


# ---------------------------------------------------------------------------
# execution/services.py — integration/lifecycle + edge cases
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFileDiscoveryLifecycle:
    """Integration test for file discovery with exclusions workflow."""

    def test_discover_filter_sort_workflow(self, tmp_path: Path) -> None:
        """Full workflow: create files, discover, verify exclusions and sorting."""
        # Arrange
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("# app")
        (tmp_path / "src" / "utils.py").write_text("# utils")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cached.py").write_text("# cached")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("# test")

        config = make_global_config(
            exclude_dirs=("__pycache__",),
            exclude_files=(),
        )

        # Act
        result = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert
        names = [p.name for p in result]
        assert "cached.py" not in names
        assert "app.py" in names
        assert "utils.py" in names
        # Files are sorted by full path, verify ordering is consistent
        paths_str = [str(p) for p in result]
        assert paths_str == sorted(paths_str)


@pytest.mark.unit
class TestClearToolCachesEdgeCases:
    """Edge-case tests for clear_tool_caches."""

    def test_clears_mypy_cache_directory(self, tmp_path: Path) -> None:
        """Removes .mypy_cache directory when present."""
        cache_dir = tmp_path / ".mypy_cache"
        cache_dir.mkdir()
        (cache_dir / "data.json").write_text("{}")

        logger = MagicMock(spec=SCRLogger)
        clear_tool_caches(tmp_path, logger)

        assert not cache_dir.exists()

    def test_reports_no_caches_when_empty(self, tmp_path: Path) -> None:
        """Logs informational message when no cache directories exist."""
        logger = MagicMock(spec=SCRLogger)
        clear_tool_caches(tmp_path, logger)

        logger.info.assert_called()
        info_texts = [call.args[0] for call in logger.info.call_args_list]
        assert any("No cache" in t for t in info_texts)


@pytest.mark.unit
class TestProjectRootServiceEdgeCases:
    """Edge-case tests for ProjectRootService."""

    def test_raises_when_no_markers_found(self, tmp_path: Path) -> None:
        """Raises SCRProjectRootError when no project markers exist."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        config = make_global_config(
            current_dir_as_root=False,
            max_upward_search_depth=SearchDepth.SHALLOW,
        )
        with pytest.raises(SCRProjectRootError, match="No project markers"):
            ProjectRootService.get_actual_project_root(empty_dir, config)

    def test_finds_pyproject_marker(self, tmp_path: Path) -> None:
        """Finds project root via pyproject.toml marker."""
        (tmp_path / "pyproject.toml").write_text("[tool]")
        sub = tmp_path / "src" / "pkg"
        sub.mkdir(parents=True)
        config = make_global_config(
            current_dir_as_root=False,
            max_upward_search_depth=SearchDepth.SHALLOW,
        )
        result = ProjectRootService.get_actual_project_root(sub, config)
        assert result == tmp_path


# ---------------------------------------------------------------------------
# core/exceptions.py — handle_errors edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleErrorsDecorator:
    """Edge-case tests for the handle_errors decorator."""

    def test_passes_cq_errors_through_unchanged(self) -> None:
        """SCRError subclasses propagate without wrapping."""

        @handle_errors
        def raises_system() -> None:
            raise SCRSystemError("missing tool")

        with pytest.raises(SCRSystemError, match="missing tool"):
            raises_system()

    def test_wraps_non_cq_errors(self) -> None:
        """Non-SCRError exceptions are wrapped in SCRUnexpectedError."""

        @handle_errors
        def raises_value() -> None:
            raise ValueError("bad value")

        with pytest.raises(SCRUnexpectedError, match="bad value"):
            raises_value()

    def test_preserves_original_error_as_cause(self) -> None:
        """Wrapped error preserves the original exception as __cause__."""

        @handle_errors
        def raises_runtime() -> None:
            raise RuntimeError("crash")

        with pytest.raises(SCRUnexpectedError) as exc_info:
            raises_runtime()
        assert isinstance(exc_info.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# Cross-module integration: CLI -> config -> tool dispatch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCliToDispatchIntegration:
    """Cross-module integration: parse CLI, resolve config, mock dispatch."""

    def test_cli_to_config_to_tool_names_workflow(self) -> None:
        """Full pipeline: CLI args -> parse -> resolve -> tool name list."""
        parser = create_argument_parser()
        args = parser.parse_args(["--strict", "--no-mypy"])
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

        tools = config.get_enabled_tools(ContextDetection.CLI)
        assert "mypy" not in tools
        assert config.config_tier == ConfigTier.STRICT
        assert "ruff_formatter" in tools

    def test_exit_code_from_mixed_tool_results(self) -> None:
        """Exit code reflects issues when no tools crashed."""
        results = [
            ToolResult(
                tool="ruff_linter",
                success=True,
                exit_code=0,
                execution_time=0.5,
                files_processed=5,
                stdout="",
                stderr="",
                issues_found=3,
                issues_fixed=1,
                error_code=0,
            ),
            ToolResult(
                tool="mypy",
                success=True,
                exit_code=0,
                execution_time=0.8,
                files_processed=5,
                stdout="",
                stderr="",
                issues_found=0,
                issues_fixed=0,
                error_code=0,
            ),
        ]
        exit_code = determine_exit_code(results)
        assert exit_code == ExitCode.ISSUES_FOUND


@pytest.mark.integration
class TestDeferredLogBufferToLoggerIntegration:
    """Cross-module: DeferredLogBuffer captures, then flushes to SCRLogger."""

    def test_capture_then_flush_to_real_logger(self, tmp_path: Path) -> None:
        """Messages captured before logger exists appear after flush."""
        DeferredLogBuffer.capture("warning", "early warning")
        DeferredLogBuffer.capture("error", "early error")

        config = make_global_config(
            create_log=True,
            console_logger_level=LoggerLevel.VERBOSE,
            file_logger_level=LoggerLevel.VERBOSE,
            log_dir="logs/",
        )
        with SCRLogger(tmp_path, config) as logger:
            DeferredLogBuffer.flush(logger)
            log_path = logger.log_path

        assert log_path is not None
        content = log_path.read_text(encoding="utf-8")
        assert "early warning" in content
        assert "early error" in content
