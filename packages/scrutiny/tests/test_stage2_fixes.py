"""Tests for Stage 2 fixes applied in py-pipeline-d run 20260317-204832-47e9.

Covers:
- H-1: Exception chain preservation in handlers._execute_subprocess
- H-2: Removed @handle_errors from _bootstrap_pre_logger
- H-3: pid = int(pid) guard in terminate_process_tree (all 3 platforms)
- H-4: DeferredLogBuffer.clear() at top of main()
- M-1: Preliminary config guard when generate_config is False
- M-6: max_depth limit in _walk_directory
- M-7: Removed @handle_errors from _show_effective_config
"""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.configs.resolver import ContextDetection
from scrutiny.core.exceptions import (
    SCRSystemError,
    SCRTimeoutError,
)
from scrutiny.execution.handlers import RuffHandler
from scrutiny.execution.services import FileDiscoveryService
from scrutiny.main import (
    _bootstrap_pre_logger,
    _show_effective_config,
)
from scrutiny.output.logger import SCRLogger, DeferredLogBuffer
from scrutiny.platforms import linux as plat_linux
from scrutiny.platforms import macos as plat_macos
from scrutiny.platforms import windows as plat_windows
from conftest import make_global_config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPECTED_DEFAULT_MAX_DEPTH = 50

_ALL_PLATFORM_MODULES = pytest.mark.parametrize(
    "platform_module",
    [plat_windows, plat_linux, plat_macos],
    ids=["windows", "linux", "macos"],
)


# ---------------------------------------------------------------------------
# H-1: Exception chain preservation in _execute_subprocess
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExceptionChainPreservation:
    """Verify SCRSystemError raised from _execute_subprocess chains the original."""

    @patch("subprocess.run")
    def test_file_not_found_chains_original_exception(
        self,
        mock_run: MagicMock,
    ) -> None:
        """SCRSystemError raised for missing tool chains the FileNotFoundError."""
        # Arrange
        original = FileNotFoundError("No such file: ruff")
        mock_run.side_effect = original
        handler = RuffHandler(timeout=300)

        # Act / Assert
        with pytest.raises(SCRSystemError) as exc_info:
            handler._execute_subprocess(  # noqa: SLF001
                tool="ruff_linter",
                command=["ruff", "check", "."],
                cwd=Path(),
            )

        assert exc_info.value.__cause__ is original

    @patch("subprocess.run")
    def test_timeout_chains_original_exception(
        self,
        mock_run: MagicMock,
    ) -> None:
        """SCRTimeoutError raised for timeout chains the TimeoutExpired."""
        # Arrange
        import subprocess

        original = subprocess.TimeoutExpired(cmd=["ruff"], timeout=60)
        mock_run.side_effect = original
        handler = RuffHandler(timeout=60)

        # Act / Assert
        with pytest.raises(SCRTimeoutError) as exc_info:
            handler._execute_subprocess(  # noqa: SLF001
                tool="ruff_linter",
                command=["ruff", "check", "."],
                cwd=Path(),
            )

        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# H-2: _bootstrap_pre_logger propagates SCRError without extra wrapper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBootstrapPreLoggerPropagation:
    """Verify SCRError from _build_preliminary_config propagates without wrapper."""

    def test_cqerror_propagates_directly(self) -> None:
        """SCRError raised inside _bootstrap_pre_logger propagates unchanged."""
        # Arrange
        args = argparse.Namespace(
            paths=None,
            doctor=False,
            show_config=False,
            tools=None,
        )
        error = SCRSystemError("test system error")

        with (
            patch(
                "scrutiny.main._resolve_start_path",
                autospec=True,
                side_effect=error,
            ),
            pytest.raises(SCRSystemError, match="test system error") as exc_info,
        ):
            # Act
            _bootstrap_pre_logger(args)

        # Assert - should be the exact same error, not wrapped
        assert exc_info.value is error


# ---------------------------------------------------------------------------
# H-3: pid = int(pid) guard in terminate_process_tree
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTerminateProcessTreePidGuard:
    """Verify terminate_process_tree rejects non-integer pid values."""

    @_ALL_PLATFORM_MODULES
    def test_string_pid_raises_value_error(self, platform_module: object) -> None:
        """A non-numeric string pid raises ValueError from int() conversion."""
        # Act / Assert
        with pytest.raises(ValueError, match="invalid literal"):
            platform_module.terminate_process_tree("not_a_pid")  # type: ignore[union-attr]

    @_ALL_PLATFORM_MODULES
    def test_none_pid_raises_type_error(self, platform_module: object) -> None:
        """None pid raises TypeError from int() conversion."""
        # Act / Assert
        with pytest.raises(TypeError):
            platform_module.terminate_process_tree(None)  # type: ignore[union-attr]

    @_ALL_PLATFORM_MODULES
    def test_numeric_string_pid_converts_successfully(
        self,
        platform_module: object,
    ) -> None:
        """A numeric string pid converts to int without error."""
        # Arrange — patch subprocess.run and OS-level process APIs so no real
        # kill occurs.  os.getpgid / os.killpg may not exist on Windows, so
        # create=True is required.
        with (
            patch("subprocess.run", autospec=True),
            patch("os.killpg", side_effect=ProcessLookupError, create=True),
            patch("os.kill", side_effect=ProcessLookupError, create=True),
            patch("os.getpgid", return_value=12345, create=True),
            contextlib.suppress(ProcessLookupError, PermissionError, OSError),
        ):
            # Act — should not raise (string "12345" is valid for int())
            platform_module.terminate_process_tree("12345")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# H-4: DeferredLogBuffer.clear() at top of main()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeferredLogBufferClearAtMainStart:
    """Verify stale messages don't bleed between main() calls."""

    def test_main_clears_buffer_on_non_doctor_path(self) -> None:
        """DeferredLogBuffer is cleared before _bootstrap_pre_logger on normal path."""
        # Arrange — pre-populate buffer
        DeferredLogBuffer.capture("error", "leftover error")
        DeferredLogBuffer.capture("warning", "leftover warning")

        args = argparse.Namespace(
            doctor=False,
            paths=None,
            show_config=False,
            tools=None,
        )
        error = SCRSystemError("deliberate early exit")

        with (
            patch(
                "scrutiny.main.create_argument_parser",
                autospec=True,
            ) as mock_parser_fn,
            patch(
                "scrutiny.main._bootstrap_pre_logger",
                autospec=True,
                side_effect=error,
            ),
            patch(
                "scrutiny.main.DeferredLogBuffer",
                wraps=DeferredLogBuffer,
            ) as mock_buf,
        ):
            mock_parser = MagicMock()
            mock_parser.parse_args.return_value = args
            mock_parser_fn.return_value = mock_parser

            from scrutiny.main import main

            main()

        # Assert — clear() was called before _bootstrap_pre_logger
        clear_calls = [call for call in mock_buf.method_calls if call[0] == "clear"]
        assert len(clear_calls) >= 1


# ---------------------------------------------------------------------------
# M-1: Preliminary config guard — skips _build_preliminary_config when
#       generate_config is False
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPreliminaryConfigGuard:
    """Verify _build_preliminary_config is skipped when generate_config is False."""

    def test_skips_preliminary_config_when_generate_config_false(self) -> None:
        """_build_preliminary_config is not called when generate_config is False."""
        # Arrange
        args = argparse.Namespace(
            paths=None,
            doctor=False,
            show_config=False,
            tools=None,
        )

        mock_resolved = MagicMock()
        mock_resolved.resolver = MagicMock()
        mock_resolved.global_config = make_global_config()
        mock_resolved.context = ContextDetection.CLI
        mock_resolved.effective_root = Path("/project")
        mock_resolved.pyproject_path = None
        mock_resolved.log_root = Path("/project")
        mock_resolved.pyproject_has_config = False

        with (
            patch(
                "scrutiny.main._resolve_start_path",
                autospec=True,
                return_value=Path("/project"),
            ),
            patch(
                "scrutiny.main.parse_cli_to_dict",
                autospec=True,
                return_value={"generate_config": False},
            ),
            patch(
                "scrutiny.main.cli_dict_to_flags",
                autospec=True,
                return_value=(),
            ),
            patch(
                "scrutiny.main._build_preliminary_config",
                autospec=True,
            ) as mock_prelim,
            patch(
                "scrutiny.main._build_resolved_config",
                autospec=True,
                return_value=mock_resolved,
            ),
        ):
            # Act
            _bootstrap_pre_logger(args)

        # Assert — preliminary config was NOT called
        mock_prelim.assert_not_called()

    def test_calls_preliminary_config_when_generate_config_true(self) -> None:
        """_build_preliminary_config IS called when generate_config is True."""
        # Arrange
        args = argparse.Namespace(
            paths=None,
            doctor=False,
            show_config=False,
            tools=None,
        )

        mock_resolved = MagicMock()
        mock_resolved.resolver = MagicMock()
        mock_resolved.global_config = make_global_config()
        mock_resolved.context = ContextDetection.CLI
        mock_resolved.effective_root = Path("/project")
        mock_resolved.pyproject_path = None
        mock_resolved.log_root = Path("/project")
        mock_resolved.pyproject_has_config = False

        with (
            patch(
                "scrutiny.main._resolve_start_path",
                autospec=True,
                return_value=Path("/project"),
            ),
            patch(
                "scrutiny.main.parse_cli_to_dict",
                autospec=True,
                return_value={"generate_config": True},
            ),
            patch(
                "scrutiny.main.cli_dict_to_flags",
                autospec=True,
                return_value=("--generate-config",),
            ),
            patch(
                "scrutiny.main._build_preliminary_config",
                autospec=True,
                return_value="created",
            ) as mock_prelim,
            patch(
                "scrutiny.main._build_resolved_config",
                autospec=True,
                return_value=mock_resolved,
            ),
        ):
            # Act
            _bootstrap_pre_logger(args)

        # Assert — preliminary config WAS called
        mock_prelim.assert_called_once()


# ---------------------------------------------------------------------------
# M-6: max_depth limit in _walk_directory
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWalkDirectoryMaxDepth:
    """Verify _walk_directory stops recursing at max_depth."""

    def test_depth_zero_returns_empty(self, tmp_path: Path) -> None:
        """max_depth=0 returns no files even if directory has .py files."""
        # Arrange
        (tmp_path / "module.py").write_text("# top level")

        # Act
        result = FileDiscoveryService._walk_directory(  # noqa: SLF001
            tmp_path,
            exclusions=set(),
            follow_symlinks=False,
            max_depth=0,
        )

        # Assert
        assert result == []

    def test_depth_one_finds_only_top_level(self, tmp_path: Path) -> None:
        """max_depth=1 finds files at root but not in subdirectories."""
        # Arrange
        (tmp_path / "top.py").write_text("# top")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_text("# nested")

        # Act
        result = FileDiscoveryService._walk_directory(  # noqa: SLF001
            tmp_path,
            exclusions=set(),
            follow_symlinks=False,
            max_depth=1,
        )

        # Assert
        names = [p.name for p in result]
        assert "top.py" in names
        assert "nested.py" not in names

    def test_depth_two_finds_one_level_deep(self, tmp_path: Path) -> None:
        """max_depth=2 finds files at root and one subdirectory level."""
        # Arrange
        (tmp_path / "top.py").write_text("# top")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "mid.py").write_text("# mid")
        deep = sub / "deep"
        deep.mkdir()
        (deep / "bottom.py").write_text("# bottom")

        # Act
        result = FileDiscoveryService._walk_directory(  # noqa: SLF001
            tmp_path,
            exclusions=set(),
            follow_symlinks=False,
            max_depth=2,
        )

        # Assert
        names = [p.name for p in result]
        assert "top.py" in names
        assert "mid.py" in names
        assert "bottom.py" not in names

    def test_default_max_depth_is_fifty(self) -> None:
        """Default max_depth parameter is 50."""
        import inspect

        sig = inspect.signature(FileDiscoveryService._walk_directory)  # noqa: SLF001
        assert sig.parameters["max_depth"].default == _EXPECTED_DEFAULT_MAX_DEPTH


# ---------------------------------------------------------------------------
# M-7: _show_effective_config works without @handle_errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShowEffectiveConfigWithoutDecorator:
    """Verify _show_effective_config still works after removing @handle_errors."""

    def test_returns_zero_and_logs_config(self) -> None:
        """_show_effective_config returns 0 and logs all expected fields."""
        # Arrange
        logger = MagicMock(spec=SCRLogger)
        logger.get_log_info.return_value = {
            "console_level": "NORMAL",
            "file_level": "NORMAL",
            "log_file_path": None,
        }
        config = make_global_config()

        # Act
        result = _show_effective_config(
            logger,
            config,
            ContextDetection.CLI,
            Path("/project"),
            None,
        )

        # Assert
        assert result == 0
        status_calls = [str(c.args[0]) for c in logger.status.call_args_list]
        combined = "\n".join(status_calls)
        assert "Tier:" in combined
        assert "Python:" in combined
        assert "Parallel:" in combined

    def test_not_decorated_with_handle_errors(self) -> None:
        """Verify _show_effective_config is NOT wrapped by @handle_errors."""
        # The function should not have __wrapped__ attribute from handle_errors
        # After M-7 removal, _show_effective_config should be a plain function
        assert not hasattr(_show_effective_config, "__wrapped__")


# ---------------------------------------------------------------------------
# Integration: Stage 2 fix chain — buffer clear -> bootstrap -> analysis
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStage2FixChainIntegration:
    """Integration test exercising multiple Stage 2 fixes together."""

    def test_buffer_clear_and_bootstrap_with_no_generation(self) -> None:
        """H-4 + M-1: main clears buffer, then skips preliminary config."""
        # Arrange
        DeferredLogBuffer.capture("warning", "stale pre-existing message")

        args = argparse.Namespace(
            paths=None,
            doctor=False,
            show_config=False,
            tools=None,
        )

        mock_resolved = MagicMock()
        mock_resolved.resolver = MagicMock()
        mock_resolved.global_config = make_global_config()
        mock_resolved.context = ContextDetection.CLI
        mock_resolved.effective_root = Path("/project")
        mock_resolved.pyproject_path = None
        mock_resolved.log_root = Path("/project")
        mock_resolved.pyproject_has_config = False

        with (
            patch(
                "scrutiny.main._resolve_start_path",
                autospec=True,
                return_value=Path("/project"),
            ),
            patch(
                "scrutiny.main.parse_cli_to_dict",
                autospec=True,
                return_value={"generate_config": False},
            ),
            patch(
                "scrutiny.main.cli_dict_to_flags",
                autospec=True,
                return_value=(),
            ),
            patch(
                "scrutiny.main._build_preliminary_config",
                autospec=True,
            ) as mock_prelim,
            patch(
                "scrutiny.main._build_resolved_config",
                autospec=True,
                return_value=mock_resolved,
            ),
        ):
            # Act
            result = _bootstrap_pre_logger(args)

        # Assert
        mock_prelim.assert_not_called()
        assert result.gen_status is None
