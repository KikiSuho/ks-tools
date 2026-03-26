"""Tests for main.py orchestration: tool execution, config loading, bootstrap."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.core.enums import (
    LogLocation,
)
from scrutiny.core.exceptions import (
    SCRConfigurationError,
    SCRError,
    SCRSystemError,
    SCRTimeoutError,
)
from scrutiny.execution.handlers import ToolExecutor
from scrutiny.execution.results import ToolResult
from scrutiny.main import (
    _build_preliminary_config,
    _create_logger,
    _dispatch_tool_execution,
    _execute_tools_parallel,
    _execute_tools_sequential,
    _load_pyproject_config,
    _resolve_log_root,
    _run_config_generation,
    _run_tool_safe,
)
from scrutiny.output.logger import SCRLogger, DeferredLogBuffer
from conftest import make_global_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPECTED_SEQUENTIAL_COUNT = 2
_EXPECTED_PARALLEL_ALL_COUNT = 4
_EXPECTED_PARALLEL_READONLY_COUNT = 3
_EXPECTED_DISPATCH_SEQ_COUNT = 2
_EXPECTED_DISPATCH_PAR_COUNT = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_result(
    tool: str = "mypy",
    success: bool = True,
    exit_code: int = 0,
    issues_found: int = 0,
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
        error_code=error_code,
    )


def _make_side_effect_fn(
    order_tracker: list[str] | None = None,
) -> Any:
    """Create a _run_tool_safe side_effect that tracks call order."""

    def side_effect(*_args: object, **_kwargs: object) -> ToolResult:
        tool_name = str(_args[1])
        # Record the tool name when an order tracker is provided
        if order_tracker is not None:
            order_tracker.append(tool_name)
        return _make_tool_result(tool=tool_name)

    return side_effect


# ---------------------------------------------------------------------------
# _run_tool_safe
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunToolSafe:
    """Tests for _run_tool_safe: error handling around tool execution."""

    def test_returns_result_on_success(self) -> None:
        """Successful tool execution returns the ToolResult from the executor."""
        # Arrange
        expected = _make_tool_result(tool="ruff_linter")
        executor = MagicMock(spec=ToolExecutor)
        executor.run_tool.return_value = expected
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()

        # Act
        result = _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            None,
            config,
            Path("/root"),
            logger,
        )

        # Assert
        assert result.tool == "ruff_linter"
        assert result.success is True

    def test_returns_failure_result_on_scr_error(self) -> None:
        """SCRError from executor produces a synthetic failure ToolResult."""
        # Arrange
        executor = MagicMock(spec=ToolExecutor)
        executor.run_tool.side_effect = SCRTimeoutError("mypy", "tool timed out", 120)
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()

        # Act
        result = _run_tool_safe(
            executor,
            "mypy",
            [],
            None,
            config,
            Path("/root"),
            logger,
        )

        # Assert
        assert result.success is False
        assert result.tool == "mypy"
        assert "timed out" in result.stderr
        logger.error.assert_called_once()

    def test_logs_completed_result_on_success(self) -> None:
        """Successful execution triggers log_completed_result."""
        # Arrange
        expected = _make_tool_result(tool="bandit")
        executor = MagicMock(spec=ToolExecutor)
        executor.run_tool.return_value = expected
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()

        # Act
        with patch(
            "scrutiny.main.log_completed_result",
            autospec=True,
        ) as mock_log:
            _run_tool_safe(
                executor,
                "bandit",
                [],
                None,
                config,
                Path("/root"),
                logger,
            )
            mock_log.assert_called_once()

    def test_error_code_from_scr_error_propagates_to_result(self) -> None:
        """The SCRError exit_code is captured in the result error_code field."""
        # Arrange
        executor = MagicMock(spec=ToolExecutor)
        error = SCRSystemError("missing binary")
        executor.run_tool.side_effect = error
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()

        # Act
        result = _run_tool_safe(
            executor,
            "mypy",
            [],
            None,
            config,
            Path("/root"),
            logger,
        )

        # Assert
        assert result.error_code == error.exit_code


# ---------------------------------------------------------------------------
# _load_pyproject_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadPyprojectConfig:
    """Tests for pyproject.toml discovery and parsing."""

    def test_returns_empty_when_no_pyproject_found(self, tmp_path: Path) -> None:
        """Returns empty dict and None when no pyproject.toml exists."""
        # Act
        mapped, path = _load_pyproject_config(tmp_path)

        # Assert
        assert mapped == {}
        assert path is None

    def test_returns_mapped_config_when_pyproject_exists(self, tmp_path: Path) -> None:
        """Returns mapped configuration when pyproject.toml is found."""
        # Arrange
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.scrutiny]\nconfig_tier = "strict"\n',
            encoding="utf-8",
        )

        # Act
        mapped, path = _load_pyproject_config(tmp_path)

        # Assert
        assert path is not None
        assert isinstance(mapped, dict)

    def test_captures_warning_on_config_error(self, tmp_path: Path) -> None:
        """Logs warning via DeferredLogBuffer when pyproject parsing fails."""
        # Arrange
        DeferredLogBuffer.clear()
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.scrutiny]\n", encoding="utf-8")

        with patch(
            "scrutiny.main.PyProjectLoader.load_from_path",
            autospec=True,
            side_effect=SCRConfigurationError("bad toml"),
        ):
            # Act
            mapped, _path = _load_pyproject_config(tmp_path)

        # Assert - still returns results (no crash), warning was captured
        assert isinstance(mapped, dict)


# ---------------------------------------------------------------------------
# _execute_tools_sequential
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteToolsSequential:
    """Tests for sequential tool execution."""

    def test_runs_all_tools_in_order(self) -> None:
        """All tools run sequentially and results are returned in order."""
        # Arrange
        expected_results = [
            _make_tool_result(tool="ruff_linter"),
            _make_tool_result(tool="mypy"),
        ]
        config = make_global_config()
        logger = MagicMock(spec=SCRLogger)
        call_count = 0

        def side_effect(*_args: object, **_kwargs: object) -> ToolResult:
            nonlocal call_count
            result = expected_results[call_count]
            call_count += 1
            return result

        # Act
        with patch(
            "scrutiny.main._run_tool_safe",
            autospec=True,
            side_effect=side_effect,
        ):
            actual = _execute_tools_sequential(
                ["ruff_linter", "mypy"],
                MagicMock(spec=ToolExecutor),
                [],
                {},
                config,
                Path("/root"),
                logger,
            )

        # Assert
        assert len(actual) == _EXPECTED_SEQUENTIAL_COUNT
        assert actual[0].tool == "ruff_linter"
        assert actual[1].tool == "mypy"


# ---------------------------------------------------------------------------
# _execute_tools_parallel
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExecuteToolsParallel:
    """Tests for parallel tool execution strategy."""

    def test_runs_sequential_tools_first(self) -> None:
        """Ruff formatter/linter run sequentially before parallel batch."""
        # Arrange
        config = make_global_config()
        logger = MagicMock(spec=SCRLogger)
        call_order: list[str] = []

        # Act
        with patch(
            "scrutiny.main._run_tool_safe",
            autospec=True,
            side_effect=_make_side_effect_fn(call_order),
        ):
            results = _execute_tools_parallel(
                ["ruff_formatter", "ruff_linter", "mypy", "radon"],
                MagicMock(spec=ToolExecutor),
                [],
                {},
                config,
                Path("/root"),
                logger,
            )

        # Assert - ruff tools should be first two in order
        assert call_order[0] == "ruff_formatter"
        assert call_order[1] == "ruff_linter"
        assert len(results) == _EXPECTED_PARALLEL_ALL_COUNT

    def test_parallel_batch_completes(self) -> None:
        """Read-only analyzers in the parallel batch all produce results."""
        # Arrange
        config = make_global_config()
        logger = MagicMock(spec=SCRLogger)

        # Act
        with patch(
            "scrutiny.main._run_tool_safe",
            autospec=True,
            side_effect=_make_side_effect_fn(),
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

        # Assert
        assert len(results) == _EXPECTED_PARALLEL_READONLY_COUNT
        tool_names = {r.tool for r in results}
        assert tool_names == {"mypy", "radon", "bandit"}


# ---------------------------------------------------------------------------
# _run_config_generation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunConfigGeneration:
    """Tests for pyproject.toml generation dispatch."""

    def test_returns_none_when_generation_disabled(self) -> None:
        """Returns None when generate_config is False."""
        # Arrange
        config = make_global_config(generate_config=False)

        # Act
        result = _run_config_generation(Path("/start"), config)

        # Assert
        assert result is None

    def test_calls_generator_when_enabled(self) -> None:
        """Delegates to PyProjectGenerator when generation is enabled."""
        # Arrange
        config = make_global_config(generate_config=True)

        with (
            patch(
                "scrutiny.main.ProjectRootService.get_project_root",
                autospec=True,
                return_value=Path("/project"),
            ),
            patch(
                "scrutiny.main.ProjectRootService.get_actual_project_root",
                autospec=True,
                return_value=Path("/project"),
            ),
            patch(
                "scrutiny.main.PyProjectGenerator.generate_or_merge",
                autospec=True,
                return_value="created",
            ) as mock_gen,
        ):
            # Act
            result = _run_config_generation(Path("/start"), config)

        # Assert
        assert result == "created"
        mock_gen.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_log_root: additional edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveLogRootEdgeCases:
    """Edge-case tests for log root resolution."""

    def test_file_path_uses_parent_for_current_dir_mode(self, tmp_path: Path) -> None:
        """When start_path is a file, uses its parent directory."""
        # Arrange
        file_path = tmp_path / "script.py"
        file_path.touch()
        config = make_global_config(log_location=LogLocation.CURRENT_DIR)

        # Act
        result = _resolve_log_root(file_path, config)

        # Assert
        assert result == tmp_path.resolve()

    def test_project_root_mode_returns_root_when_found(self, tmp_path: Path) -> None:
        """PROJECT_ROOT mode returns the actual project root."""
        # Arrange
        config = make_global_config(log_location=LogLocation.PROJECT_ROOT)

        with patch(
            "scrutiny.main.ProjectRootService.get_actual_project_root",
            autospec=True,
            return_value=tmp_path,
        ):
            # Act
            result = _resolve_log_root(tmp_path, config)

        # Assert
        assert result == tmp_path


# ---------------------------------------------------------------------------
# _build_preliminary_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildPreliminaryConfig:
    """Tests for preliminary config construction before pyproject generation."""

    def test_returns_none_when_no_generation(self) -> None:
        """Returns None when generate_config defaults to False."""
        # Arrange
        from scrutiny.config import UserDefaults

        snapshot = UserDefaults.to_frozen()
        cli_dict: dict[str, Any] = {}
        tier = snapshot.scr_config_tier

        # Act
        with patch(
            "scrutiny.main._run_config_generation",
            autospec=True,
            return_value=None,
        ) as mock_gen:
            result = _build_preliminary_config(Path("/start"), cli_dict, snapshot, tier)

        # Assert
        assert result is None
        mock_gen.assert_called_once()

    def test_passes_empty_pyproject_to_resolver(self) -> None:
        """Preliminary resolver uses empty pyproject config."""
        # Arrange
        from scrutiny.config import UserDefaults

        snapshot = UserDefaults.to_frozen()
        cli_dict: dict[str, Any] = {"generate_config": True}
        tier = snapshot.scr_config_tier

        # Act
        with (
            patch(
                "scrutiny.main._run_config_generation",
                autospec=True,
                return_value="created",
            ),
            patch(
                "scrutiny.main.ConfigResolver",
                autospec=True,
            ) as mock_resolver_cls,
        ):
            mock_resolver = MagicMock()  # spec omitted: autospec on ConfigResolver class binding fails
            mock_resolver.build_global_config.return_value = make_global_config(
                generate_config=True,
            )
            mock_resolver_cls.return_value = mock_resolver
            _build_preliminary_config(Path("/start"), cli_dict, snapshot, tier)

        # Assert - pyproject_config should be empty dict
        call_kwargs = mock_resolver_cls.call_args
        assert call_kwargs.kwargs.get("pyproject_config") == {} or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == {}
        )


# ---------------------------------------------------------------------------
# _create_logger: additional edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateLoggerEdgeCases:
    """Edge-case tests for logger creation fallback."""

    def test_returns_working_logger_on_success(self, tmp_path: Path) -> None:
        """Returns logger directly when file creation succeeds."""
        # Arrange
        config = make_global_config(create_log=False)

        # Act
        logger = _create_logger(tmp_path, config)

        # Assert
        assert isinstance(logger, SCRLogger)
        logger.close()


# ---------------------------------------------------------------------------
# Integration: _execute_tools_sequential lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestExecutionLifecycle:
    """Integration test for tool dispatch and result collection."""

    def test_dispatch_sequential_produces_ordered_results(self) -> None:
        """Sequential dispatch returns results in tool order."""
        # Arrange
        config = make_global_config(parallel=False)
        logger = MagicMock(spec=SCRLogger)

        # Act
        with patch(
            "scrutiny.main._run_tool_safe",
            autospec=True,
            side_effect=_make_side_effect_fn(),
        ):
            results = _dispatch_tool_execution(
                ["ruff_linter", "mypy"],
                config,
                [],
                {},
                Path("/root"),
                logger,
            )

        # Assert
        assert len(results) == _EXPECTED_DISPATCH_SEQ_COUNT

    def test_dispatch_parallel_with_mixed_tools(self) -> None:
        """Parallel dispatch handles both sequential and parallel tools."""
        # Arrange
        config = make_global_config(parallel=True)
        logger = MagicMock(spec=SCRLogger)

        # Act
        with patch(
            "scrutiny.main._run_tool_safe",
            autospec=True,
            side_effect=_make_side_effect_fn(),
        ):
            results = _dispatch_tool_execution(
                ["ruff_formatter", "mypy", "radon"],
                config,
                [],
                {},
                Path("/root"),
                logger,
            )

        # Assert
        assert len(results) == _EXPECTED_DISPATCH_PAR_COUNT
        tool_names = {r.tool for r in results}
        assert "ruff_formatter" in tool_names
        assert "mypy" in tool_names
        assert "radon" in tool_names


# ---------------------------------------------------------------------------
# Edge cases: _run_tool_safe with different error types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunToolSafeEdgeCases:
    """Parametrized edge cases for _run_tool_safe error handling."""

    @pytest.mark.parametrize(
        ("error_cls", "error_msg"),
        [
            pytest.param(SCRSystemError, "missing binary", id="system"),
            pytest.param(SCRConfigurationError, "bad config", id="config"),
        ],
    )
    def test_different_scr_error_types_produce_failure_results(
        self,
        error_cls: type[SCRError],
        error_msg: str,
    ) -> None:
        """Different SCRError subclasses all produce failure ToolResults."""
        # Arrange
        executor = MagicMock(spec=ToolExecutor)
        executor.run_tool.side_effect = error_cls(error_msg)
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config()

        # Act
        result = _run_tool_safe(
            executor,
            "mypy",
            [],
            None,
            config,
            Path("/root"),
            logger,
        )

        # Assert
        assert result.success is False
        assert error_msg in result.stderr


# ---------------------------------------------------------------------------
# Coverage gap: _run_tool_safe with unexpected Exception wrapped by @handle_errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_tool_safe_unexpected_exception_produces_failure() -> None:
    """Unexpected exceptions are wrapped by @handle_errors into SCRUnexpectedError and caught."""
    # Arrange
    executor = MagicMock(spec=ToolExecutor)
    executor.run_tool.side_effect = RuntimeError("segfault in C extension")
    logger = MagicMock(spec=SCRLogger)
    config = make_global_config()

    # Act
    result = _run_tool_safe(
        executor,
        "mypy",
        [],
        None,
        config,
        Path("/root"),
        logger,
    )

    # Assert
    assert result.success is False
    assert "segfault" in result.stderr
    from scrutiny.core.exceptions import ExitCode

    assert result.error_code == ExitCode.UNEXPECTED


# ---------------------------------------------------------------------------
# Coverage gap: _resolve_log_root edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_log_root_hybrid_falls_back_to_cwd(tmp_path: Path) -> None:
    """HYBRID mode falls back to CWD when no project root is found."""
    # Arrange
    from scrutiny.core.exceptions import SCRProjectRootError

    config = make_global_config(log_location=LogLocation.HYBRID)
    DeferredLogBuffer.clear()

    with patch(
        "scrutiny.main.ProjectRootService.get_actual_project_root",
        autospec=True,
        side_effect=SCRProjectRootError("no root"),
    ):
        # Act
        result = _resolve_log_root(tmp_path, config)

    # Assert
    assert result == tmp_path.resolve()


@pytest.mark.unit
def test_resolve_log_root_project_root_disables_when_not_found(tmp_path: Path) -> None:
    """PROJECT_ROOT mode returns None (disables logging) when no root is found."""
    # Arrange
    from scrutiny.core.exceptions import SCRProjectRootError

    config = make_global_config(log_location=LogLocation.PROJECT_ROOT)
    DeferredLogBuffer.clear()

    with patch(
        "scrutiny.main.ProjectRootService.get_actual_project_root",
        autospec=True,
        side_effect=SCRProjectRootError("no root"),
    ):
        # Act
        result = _resolve_log_root(tmp_path, config)

    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# Coverage gap: _compute_mi_ranks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compute_mi_ranks_returns_none_when_radon_not_enabled() -> None:
    """Returns None when radon is not in the tool list."""
    # Arrange
    from scrutiny.main import _compute_mi_ranks

    config = make_global_config()

    # Act
    result = _compute_mi_ranks(["mypy", "ruff_linter"], [], Path("/root"), config)

    # Assert
    assert result is None
