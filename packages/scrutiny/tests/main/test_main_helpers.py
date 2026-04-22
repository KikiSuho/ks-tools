"""Tests for main() helper functions: orchestration, path resolution, doctor."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.configs.resolver import ContextDetection
from scrutiny.core.cli import run_doctor
from scrutiny.core.enums import FrameworkSelection
from scrutiny.core.exceptions import SCRSystemError, SCRUserInputError
from scrutiny.main import (
    _determine_tool_names,
    _dispatch_tool_execution,
    _resolve_start_path,
    _show_effective_config,
    _verify_tool_availability,
)
from scrutiny.output.logger import SCRLogger
from conftest import make_global_config

# ── _resolve_start_path ── #


def _make_args(**kwargs: object) -> argparse.Namespace:
    """Create a minimal argparse.Namespace for _resolve_start_path tests."""
    defaults: dict[str, object] = {"paths": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
class TestResolveStartPath:
    """Test CLI path resolution for the analysis root."""

    def test_returns_cwd_when_no_paths(self) -> None:
        """Verify Path.cwd() is returned when no paths are provided."""
        # Arrange
        args = _make_args()

        # Act
        result = _resolve_start_path(args)

        # Assert
        assert result == Path.cwd()

    def test_returns_directory_when_directory_provided(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify directory path is returned unchanged."""
        # Arrange
        args = _make_args(paths=[tmp_path])

        # Act
        result = _resolve_start_path(args)

        # Assert
        assert result == tmp_path

    def test_returns_parent_when_file_provided(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify parent directory is returned when a file path is given."""
        # Arrange
        file_path = tmp_path / "script.py"
        file_path.touch()
        args = _make_args(paths=[file_path])

        # Act
        result = _resolve_start_path(args)

        # Assert
        assert result == tmp_path

    def test_raises_for_nonexistent_path(self, tmp_path: Path) -> None:
        """Verify SCRUserInputError for a path that does not exist."""
        # Arrange
        missing = tmp_path / "nonexistent"
        args = _make_args(paths=[missing])

        # Act / Assert
        with pytest.raises(SCRUserInputError, match="does not exist"):
            _resolve_start_path(args)

    def test_validates_all_paths_before_returning(
        self,
        tmp_path: Path,
    ) -> None:
        """Verify all paths are validated, not just the first."""
        # Arrange
        valid_dir = tmp_path / "valid"
        valid_dir.mkdir()
        missing = tmp_path / "missing"
        args = _make_args(paths=[valid_dir, missing])

        # Act / Assert
        with pytest.raises(SCRUserInputError, match="does not exist"):
            _resolve_start_path(args)


# ── _determine_tool_names ── #


def _make_tool_args(**kwargs: object) -> argparse.Namespace:
    """Create a minimal argparse.Namespace for _determine_tool_names tests."""
    defaults: dict[str, object] = {"tools": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
class TestDetermineToolNames:
    """Test tool name resolution from CLI arguments and GlobalConfig."""

    def test_explicit_ruff_expands_to_formatter_and_linter(self) -> None:
        """Verify --tool ruff expands to both ruff_formatter and ruff_linter."""
        # Arrange
        args = _make_tool_args(tools=["ruff"])
        global_config = make_global_config()
        context = ContextDetection.CLI

        # Act
        tool_names = _determine_tool_names(args, global_config, context)

        # Assert
        assert "ruff_formatter" in tool_names
        assert "ruff_linter" in tool_names

    def test_explicit_mypy_returns_single_entry(self) -> None:
        """Verify --tool mypy returns just mypy."""
        # Arrange
        args = _make_tool_args(tools=["mypy"])
        global_config = make_global_config()
        context = ContextDetection.CLI

        # Act
        tool_names = _determine_tool_names(args, global_config, context)

        # Assert
        assert tool_names == ["mypy"]

    def test_explicit_radon_returns_single_entry(self) -> None:
        """Verify --tool radon returns just radon."""
        # Arrange
        args = _make_tool_args(tools=["radon"])
        global_config = make_global_config()
        context = ContextDetection.CLI

        # Act
        tool_names = _determine_tool_names(args, global_config, context)

        # Assert
        assert tool_names == ["radon"]

    def test_no_explicit_tools_delegates_to_global_config(self) -> None:
        """Verify no --tool falls back to get_enabled_tools."""
        # Arrange
        args = _make_tool_args()
        global_config = make_global_config(run_ruff_formatter=True)
        context = ContextDetection.CLI

        # Act
        tool_names = _determine_tool_names(args, global_config, context)

        # Assert
        assert len(tool_names) >= 1
        assert "ruff_formatter" in tool_names

    def test_explicit_tool_bypasses_run_flag(self) -> None:
        """An explicit --tool request runs the tool even when run_X is False."""
        # Arrange
        args = _make_tool_args(tools=["ruff_formatter"])
        global_config = make_global_config(run_ruff_formatter=False)
        context = ContextDetection.CLI

        # Act
        tool_names = _determine_tool_names(args, global_config, context)

        # Assert - explicit CLI intent overrides the off-by-default toggle.
        assert tool_names == ["ruff_formatter"]

    def test_explicit_ruff_alias_bypasses_run_flags(self) -> None:
        """--tool ruff expands to both capabilities regardless of run_* defaults."""
        # Arrange
        args = _make_tool_args(tools=["ruff"])
        global_config = make_global_config(
            run_ruff_formatter=False,
            run_ruff_linter=False,
        )
        context = ContextDetection.CLI

        # Act
        tool_names = _determine_tool_names(args, global_config, context)

        # Assert - both formatter and linter run when the alias is requested.
        assert "ruff_formatter" in tool_names
        assert "ruff_linter" in tool_names


# ── run_doctor ── #


@pytest.mark.unit
class TestRunDoctor:
    """Test run_doctor tool availability checks and install guidance."""

    def test_missing_tool_prints_install_guidance(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify install instructions appear when a tool is missing."""

        # Arrange; bandit is missing, others are found but version fails gracefully
        def which_side_effect(name: str) -> str | None:
            # Return None for bandit to simulate it being missing
            if name == "bandit":
                return None
            return f"/usr/bin/{name}"

        # Act; patch on the module object directly to avoid stale sys.modules reference
        with (
            patch("scrutiny.core.cli.which", side_effect=which_side_effect),
            patch("subprocess.run", side_effect=OSError("no binary")),
        ):
            run_doctor()

        # Assert
        captured = capsys.readouterr().out
        assert "Install missing tools: pip install bandit | conda install bandit" in captured

    def test_all_tools_found_prints_no_install_guidance(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify no install instructions when all tools are available."""
        # Arrange / Act
        with (
            patch("scrutiny.core.cli.which", return_value="/usr/bin/tool"),
            patch("subprocess.run", side_effect=OSError("no binary")),
        ):
            run_doctor()

        # Assert
        captured = capsys.readouterr().out
        assert "Install missing tools" not in captured

    def test_multiple_missing_tools_listed_together(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Verify all missing tools appear in a single install instruction."""

        # Arrange; ruff and mypy missing
        def which_side_effect(name: str) -> str | None:
            # Return None for ruff and mypy to simulate both being missing
            if name in ("ruff", "mypy"):
                return None
            return f"/usr/bin/{name}"

        # Act
        with (
            patch("scrutiny.core.cli.which", side_effect=which_side_effect),
            patch("subprocess.run", side_effect=OSError("no binary")),
        ):
            run_doctor()

        # Assert
        captured = capsys.readouterr().out
        assert "pip install ruff mypy" in captured
        assert "conda install ruff mypy" in captured


# ── _show_effective_config ── #


@pytest.mark.unit
class TestShowEffectiveConfig:
    """Tests for the --show-config diagnostic output."""

    def _make_mock_logger(self) -> MagicMock:
        """Create a mock SCRLogger with log_info configured."""
        logger = MagicMock(spec=SCRLogger)
        logger.get_log_info.return_value = {
            "console_level": "NORMAL",
            "file_level": "NORMAL",
            "log_file_path": None,
        }
        return logger

    def test_returns_zero_always(self) -> None:
        """Show-config mode always returns exit code 0."""
        # Arrange
        logger = self._make_mock_logger()
        config = make_global_config()
        context = ContextDetection.CLI
        root = Path("/project")

        # Act
        result = _show_effective_config(logger, config, context, root, None)

        # Assert
        assert result == 0

    def test_logs_tier_and_python_version(self) -> None:
        """Config display includes tier and python version."""
        # Arrange
        logger = self._make_mock_logger()
        config = make_global_config()
        context = ContextDetection.CLI

        # Act
        _show_effective_config(logger, config, context, Path("/proj"), None)

        # Assert
        status_calls = [str(call.args[0]) for call in logger.status.call_args_list]
        combined = "\n".join(status_calls)
        assert "Tier:" in combined
        assert "Python:" in combined

    def test_displays_framework_when_set(self) -> None:
        """Framework line appears when framework is not NONE."""
        # Arrange
        logger = self._make_mock_logger()
        config = make_global_config(framework=FrameworkSelection.DJANGO)

        # Act
        _show_effective_config(
            logger,
            config,
            ContextDetection.CLI,
            Path("/proj"),
            None,
        )

        # Assert
        status_calls = [str(call.args[0]) for call in logger.status.call_args_list]
        combined = "\n".join(status_calls)
        assert "Framework:" in combined

    def test_displays_pyproject_path_when_provided(self) -> None:
        """Pyproject.toml path is shown when not None."""
        # Arrange
        logger = self._make_mock_logger()
        config = make_global_config()
        pyproject = Path("/project/pyproject.toml")

        # Act
        _show_effective_config(
            logger,
            config,
            ContextDetection.CLI,
            Path("/proj"),
            pyproject,
        )

        # Assert
        status_calls = [str(call.args[0]) for call in logger.status.call_args_list]
        combined = "\n".join(status_calls)
        assert "pyproject.toml" in combined


# ── _verify_tool_availability edge cases ── #


@pytest.mark.unit
class TestVerifyToolAvailability:
    """Tests for pre-flight tool verification."""

    def test_raises_for_missing_tool(self) -> None:
        """Raises SCRSystemError listing all missing executables."""
        with (
            patch(
                "scrutiny.main.which",
                autospec=True,
                return_value=None,
            ),
            pytest.raises(SCRSystemError, match="Missing tools"),
        ):
            _verify_tool_availability(["mypy"])

    def test_passes_when_all_tools_found(self) -> None:
        """No exception when all tools are available."""
        with patch(
            "scrutiny.main.which",
            autospec=True,
            return_value="/usr/bin/tool",
        ):
            _verify_tool_availability(["mypy", "ruff_linter"])

    def test_radon_also_checks_radon_mi(self) -> None:
        """When radon is in tool_names, radon_mi is also checked."""
        checked: list[str] = []

        def which_side_effect(name: str) -> str:
            checked.append(name)
            return f"/usr/bin/{name}"

        with patch(
            "scrutiny.main.which",
            autospec=True,
            side_effect=which_side_effect,
        ):
            _verify_tool_availability(["radon"])

        # The radon executable should be checked (radon_mi maps to radon)
        assert "radon" in checked

    def test_deduplicates_executable_checks(self) -> None:
        """Does not check the same executable twice."""
        check_count: dict[str, int] = {}

        def which_side_effect(name: str) -> str:
            check_count[name] = check_count.get(name, 0) + 1
            return f"/usr/bin/{name}"

        with patch(
            "scrutiny.main.which",
            autospec=True,
            side_effect=which_side_effect,
        ):
            _verify_tool_availability(["ruff_formatter", "ruff_linter"])

        # ruff_formatter and ruff_linter both use the "ruff" executable
        assert check_count.get("ruff", 0) == 1


# ── _dispatch_tool_execution ── #


@pytest.mark.unit
class TestDispatchToolExecution:
    """Tests for parallel vs sequential execution dispatch."""

    def test_sequential_when_parallel_disabled(self) -> None:
        """Uses sequential execution when parallel is False."""
        config = make_global_config(parallel=False)
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")

        with patch(
            "scrutiny.main._execute_tools_sequential",
            autospec=True,
            return_value=[],
        ) as mock_seq:
            _dispatch_tool_execution(
                ["mypy"],
                config,
                [],
                {},
                root,
                logger,
            )
            mock_seq.assert_called_once()

    def test_sequential_when_single_tool(self) -> None:
        """Uses sequential execution when only one tool is queued."""
        config = make_global_config(parallel=True)
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")

        with patch(
            "scrutiny.main._execute_tools_sequential",
            autospec=True,
            return_value=[],
        ) as mock_seq:
            _dispatch_tool_execution(
                ["mypy"],
                config,
                [],
                {},
                root,
                logger,
            )
            mock_seq.assert_called_once()

    def test_parallel_when_enabled_with_multiple_tools(self) -> None:
        """Uses parallel execution when parallel=True and multiple tools."""
        config = make_global_config(parallel=True)
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")

        with patch(
            "scrutiny.main._execute_tools_parallel",
            autospec=True,
            return_value=[],
        ) as mock_par:
            _dispatch_tool_execution(
                ["mypy", "radon"],
                config,
                [],
                {},
                root,
                logger,
            )
            mock_par.assert_called_once()


# ── _determine_tool_names edge cases ── #


@pytest.mark.unit
class TestDetermineToolNamesEdgeCases:
    """Edge-case tests for tool name resolution."""

    def test_explicit_bandit_returns_bandit(self) -> None:
        """Explicit --tool bandit returns just bandit."""
        # Arrange
        args = _make_tool_args(tools=["bandit"])
        config = make_global_config()

        # Act
        result = _determine_tool_names(args, config, ContextDetection.CLI)

        # Assert
        assert result == ["bandit"]

    def test_explicit_ruff_security_returns_ruff_security(self) -> None:
        """Explicit --tool ruff_security returns just ruff_security."""
        # Arrange
        args = _make_tool_args(tools=["ruff_security"])
        config = make_global_config()

        # Act
        result = _determine_tool_names(args, config, ContextDetection.CLI)

        # Assert
        assert result == ["ruff_security"]

    def test_default_config_omits_ruff_formatter_from_enabled_list(self) -> None:
        """Default global config runs the linter but not the formatter."""
        # Arrange - with no --tool argument, tool selection follows run_* defaults.
        args = _make_tool_args()
        config = make_global_config()

        # Act
        result = _determine_tool_names(args, config, ContextDetection.CLI)

        # Assert - ruff_formatter is off by default so it must not appear;
        # read-only analyzers still run.
        assert "ruff_formatter" not in result
        assert "ruff_linter" in result


# ── Integration/lifecycle: main.py orchestration ── #


@pytest.mark.integration
class TestMainOrchestrationLifecycle:
    """Integration test for main.py orchestration helpers."""

    def test_show_config_returns_zero_with_real_logger(
        self,
        tmp_path: Path,
    ) -> None:
        """Full show-config flow: create logger, show config, verify exit 0."""
        config = make_global_config(create_log=False)
        logger = SCRLogger(tmp_path, config)
        context = ContextDetection.CLI

        result = _show_effective_config(
            logger,
            config,
            context,
            tmp_path,
            None,
        )

        assert result == 0
        logger.close()


# ── R-3: Logger handle leak ── #


@pytest.mark.unit
class TestLoggerHandleLeak:
    """Test that SCRLogger file handles are properly managed."""

    def test_logger_handle_closed_in_context_manager(self, tmp_path: Path) -> None:
        """SCRLogger closes its file handle when used as a context manager."""
        config = make_global_config(create_log=True, log_dir="logs/")
        logger = SCRLogger(tmp_path, config)
        # File handle is deferred until __enter__.
        assert logger.log_file is None
        assert logger.log_path is not None

        with logger:
            assert logger.log_file is not None
            log_file_ref = logger.log_file  # Capture before __exit__ sets it to None.
            assert not log_file_ref.closed

        # __exit__ closes and then sets log_file to None.
        assert log_file_ref.closed

    def test_logger_handle_not_opened_without_context_manager(
        self,
        tmp_path: Path,
    ) -> None:
        """SCRLogger does not open a file handle without entering context manager."""
        config = make_global_config(create_log=True, log_dir="logs/")
        logger = SCRLogger(tmp_path, config)
        # File handle is deferred; no leak possible without `with`.
        assert logger.log_file is None
        assert logger.log_path is not None
        logger.close()
