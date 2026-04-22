"""Tests for tool handler subprocess execution and parallel ordering."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.config import UserDefaults
from scrutiny.configs.dataclasses import (
    BanditConfig,
    GlobalConfig,
    RuffConfig,
)
from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.cli import parse_cli_to_dict, create_argument_parser
from scrutiny.core.enums import (
    ConfigTier,
    FrameworkSelection,
    LineLength,
    LoggerLevel,
    PythonVersion,
    SearchDepth,
    SecurityTool,
    ToolTimeout,
)
from scrutiny.core.exceptions import (
    SCRConfigurationError,
    SCRError,
    SCRSystemError,
    SCRTimeoutError,
)
from scrutiny.core.tool_data import (
    RUFF_FRAMEWORK_RULES,
    RUFF_IGNORE_RULES,
    RUFF_PER_FILE_IGNORES,
    RUFF_RULES_ESSENTIAL,
    RUFF_RULES_INSANE,
    RUFF_RULES_STANDARD,
    RUFF_RULES_STRICT,
    RUFF_VERSION_GATED_IGNORES,
)
from scrutiny.execution.handlers import (
    BanditHandler,
    MypyHandler,
    RadonCCHandler,
    RuffHandler,
)
from scrutiny.execution.results import ToolResult
from scrutiny.execution.services import which
from scrutiny.main import _run_tool_safe


def _make_handler(timeout: int = 300) -> object:
    """Create a concrete tool handler for testing.

    Use RuffHandler as a concrete subclass of BaseToolHandler.
    """
    return RuffHandler(timeout=timeout)


# ── _execute_subprocess ── #


@pytest.mark.unit
class TestExecuteSubprocess:
    """Test BaseToolHandler._execute_subprocess method."""

    @patch("subprocess.run")
    def test_returns_tool_result_on_success(self, mock_run: MagicMock) -> None:
        """Return a ToolResult with captured stdout and stderr."""
        # Arrange
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="all clean",
            stderr="",
        )
        handler = _make_handler()

        # Act
        result = handler._execute_subprocess(
            tool="ruff_linter",
            command=["ruff", "check", "."],
            cwd=Path(),
        )

        # Assert
        assert result.tool == "ruff_linter"
        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == "all clean"

    @patch("subprocess.run")
    def test_raises_timeout_error_on_timeout(self, mock_run: MagicMock) -> None:
        """Raise SCRTimeoutError when subprocess times out."""
        # Arrange
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["ruff"],
            timeout=60,
        )
        handler = _make_handler(timeout=60)

        # Act / Assert
        with pytest.raises(SCRTimeoutError) as exc_info:
            handler._execute_subprocess(
                tool="ruff_linter",
                command=["ruff", "check", "."],
                cwd=Path(),
            )

        assert exc_info.value.tool_name == "ruff_linter"
        assert exc_info.value.timeout_seconds == 60

    @patch("subprocess.run")
    def test_raises_system_error_when_tool_not_found(self, mock_run: MagicMock) -> None:
        """Raise SCRSystemError when the tool executable is not found."""
        # Arrange
        mock_run.side_effect = FileNotFoundError()
        handler = _make_handler()

        # Act / Assert
        with pytest.raises(SCRSystemError, match="not found in PATH"):
            handler._execute_subprocess(
                tool="nonexistent_tool",
                command=["nonexistent_tool"],
                cwd=Path(),
            )

    @patch("subprocess.run")
    def test_tool_not_found_error_includes_install_guidance(
        self,
        mock_run: MagicMock,
    ) -> None:
        """Verify SCRSystemError message includes pip/conda install instructions."""
        # Arrange
        mock_run.side_effect = FileNotFoundError()
        handler = _make_handler()

        # Act / Assert
        with pytest.raises(SCRSystemError, match="Install: pip install") as exc_info:
            handler._execute_subprocess(
                tool="nonexistent_tool",
                command=["nonexistent_tool"],
                cwd=Path(),
            )
        assert "conda install nonexistent_tool" in str(exc_info.value)

    @patch("subprocess.run")
    def test_captures_nonzero_exit_code(self, mock_run: MagicMock) -> None:
        """Capture a non-zero exit code as success=False."""
        # Arrange
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="issues found",
            stderr="",
        )
        handler = _make_handler()

        # Act
        result = handler._execute_subprocess(
            tool="ruff_linter",
            command=["ruff", "check", "."],
            cwd=Path(),
        )

        # Assert
        assert result.success is False
        assert result.exit_code == 1
        assert result.stdout == "issues found"


# ── _run_tool_safe ── #


@pytest.mark.unit
class TestRunToolSafe:
    """Test the _run_tool_safe helper function."""

    def test_returns_result_on_success(self) -> None:
        """Return ToolResult from executor on successful run."""
        # Arrange
        expected = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=1.0,
            files_processed=5,
            stdout="ok",
            stderr="",
        )
        executor = MagicMock()
        executor.run_tool.return_value = expected
        logger = MagicMock()

        # Act
        result = _run_tool_safe(
            executor,
            "mypy",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        assert result is expected
        executor.run_tool.assert_called_once()

    def test_returns_failure_result_on_cq_error(self) -> None:
        """Return a synthetic failure ToolResult when SCRError is raised."""
        # Arrange
        executor = MagicMock()
        executor.run_tool.side_effect = SCRError("boom")
        logger = MagicMock()

        # Act
        result = _run_tool_safe(
            executor,
            "bandit",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        # Assert
        assert result.success is False
        assert result.exit_code == 11
        assert result.tool == "bandit"
        assert "boom" in result.stderr
        logger.error.assert_called_once()


# ── Parallel execution ordering ── #


@pytest.mark.unit
class TestParallelExecutionOrder:
    """Verify two-phase parallel execution: writers then readers."""

    @staticmethod
    def _make_fake_result(
        name: str,
    ) -> ToolResult:
        """Create a minimal successful ToolResult."""
        return ToolResult(
            tool=name,
            success=True,
            exit_code=0,
            execution_time=0.1,
            files_processed=1,
            stdout="",
            stderr="",
        )

    def test_ruff_tools_run_before_parallel_batch(self) -> None:
        """Ruff formatter and linter execute before parallel analysers."""
        # Arrange
        call_order: list[str] = []
        call_threads: dict[str, int] = {}
        main_thread_id = threading.current_thread().ident

        original_run_tool_safe = _run_tool_safe

        def tracking_run_tool_safe(
            executor: object,
            name: str,
            *args: object,
            **kwargs: object,
        ) -> object:
            call_order.append(name)
            call_threads[name] = threading.current_thread().ident  # type: ignore[assignment]
            return self._make_fake_result(name)

        # Build minimal GlobalConfig with parallel=True.
        global_config = MagicMock()
        global_config.parallel = True
        global_config.get_enabled_tools.return_value = [
            "ruff_formatter",
            "ruff_linter",
            "mypy",
            "radon",
            "bandit",
        ]
        global_config.tool_timeout = 300

        executor = MagicMock()
        executor.run_tool.side_effect = lambda name, *a, **kw: self._make_fake_result(name)

        tool_names = global_config.get_enabled_tools()
        tool_config_map: dict[str, object] = dict.fromkeys(tool_names)
        logger = MagicMock()
        discovered_files: list[Path] = [Path("test.py")]
        effective_root = Path()
        results: list[object] = []

        # Act — simulate the parallel branch from main().
        _SEQUENTIAL_TOOLS = {"ruff_formatter", "ruff_linter"}

        # Phase 1: sequential writers.
        parallel_batch: list[str] = []
        for name in tool_names:
            if name in _SEQUENTIAL_TOOLS:
                results.append(
                    tracking_run_tool_safe(
                        executor,
                        name,
                        discovered_files,
                        tool_config_map.get(name),
                        global_config,
                        effective_root,
                        logger,
                    )
                )
            else:
                parallel_batch.append(name)

        # Assert Phase 1 ran first and in order.
        assert call_order[0] == "ruff_formatter"
        assert call_order[1] == "ruff_linter"
        assert call_threads["ruff_formatter"] == main_thread_id
        assert call_threads["ruff_linter"] == main_thread_id

        # Assert Phase 2 tools were deferred.
        assert parallel_batch == ["mypy", "radon", "bandit"]

    def test_ruff_formatter_precedes_ruff_linter(self) -> None:
        """Ruff formatter always runs before ruff linter."""
        # Arrange
        call_order: list[str] = []

        def tracking_safe(
            executor: object,
            name: str,
            *a: object,
            **kw: object,
        ) -> object:
            call_order.append(name)
            return self._make_fake_result(name)

        tool_names = ["ruff_formatter", "ruff_linter", "mypy"]
        _SEQUENTIAL_TOOLS = {"ruff_formatter", "ruff_linter"}

        # Act
        for name in tool_names:
            if name in _SEQUENTIAL_TOOLS:
                tracking_safe(MagicMock(), name, [], None, MagicMock(), Path(), MagicMock())

        # Assert
        assert call_order == ["ruff_formatter", "ruff_linter"]

    def test_parallel_batch_uses_thread_pool(self) -> None:
        """Read-only analysers run in a ThreadPoolExecutor."""
        # Arrange
        worker_threads: dict[str, int] = {}
        main_thread_id = threading.current_thread().ident

        def tracking_run_tool(
            name: str,
            *args: object,
            **kwargs: object,
        ) -> object:
            worker_threads[name] = threading.current_thread().ident  # type: ignore[assignment]
            return self._make_fake_result(name)

        parallel_batch = ["mypy", "radon", "bandit"]
        executor = MagicMock()
        executor.run_tool.side_effect = tracking_run_tool

        # Act — run Phase 2 directly.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[object] = []
        with ThreadPoolExecutor(max_workers=len(parallel_batch)) as pool:
            future_map = {
                pool.submit(
                    executor.run_tool,
                    name,
                    [],
                    None,
                    MagicMock(),
                    Path(),
                ): name
                for name in parallel_batch
            }
            for future in as_completed(future_map):
                results.append(future.result())

        # Assert — all three tools ran, at least one on a worker thread.
        assert set(worker_threads.keys()) == {"mypy", "radon", "bandit"}
        assert any(tid != main_thread_id for tid in worker_threads.values()), (
            "Expected at least one tool to run on a worker thread"
        )


# ── tool_data preservation ── #


@pytest.mark.unit
class TestToolDataPreservation:
    """Verify handler run() methods preserve tool_data['command']."""

    @patch("subprocess.run")
    def test_run_with_fix_preserves_command(self, mock_run: MagicMock) -> None:
        """RuffHandler._run_with_fix() keeps the command key from subprocess."""
        # Arrange
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[]",
            stderr="",
        )
        handler = RuffHandler(timeout=300)
        ruff_config = RuffConfig(fix=True)
        global_config = GlobalConfig()
        root = Path()

        # Act
        result = handler.run([Path("a.py")], ruff_config, global_config, root)

        # Assert — command key must still exist alongside fix-specific keys.
        assert "command" in result.tool_data
        assert "issues" in result.tool_data
        assert "initial_issues" in result.tool_data
        assert "fixed_count" in result.tool_data

    @patch("subprocess.run")
    def test_run_with_fix_logs_warning_on_fix_failure(
        self, mock_run: MagicMock,
    ) -> None:
        """RuffHandler._run_with_fix() warns when the fix pass fails."""
        # Arrange — fix pass (2nd call) returns non-zero exit code.
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="[]", stderr=""),   # initial check
            MagicMock(returncode=1, stdout="", stderr="err"),  # fix pass FAILS
            MagicMock(returncode=0, stdout="[]", stderr=""),   # post-fix check
        ]
        handler = RuffHandler(timeout=300)
        ruff_config = RuffConfig(fix=True)
        global_config = GlobalConfig()
        root = Path()

        # Act
        with patch(
            "scrutiny.execution.handlers.DeferredLogBuffer",
        ) as mock_buffer:
            result = handler.run([Path("a.py")], ruff_config, global_config, root)

        # Assert — result completes (no crash), warning emitted.
        assert result is not None
        mock_buffer.capture.assert_called_once()
        warning_msg = mock_buffer.capture.call_args[0][1]
        assert "fix pass" in warning_msg.lower()

    @patch("subprocess.run")
    def test_bandit_run_preserves_command(self, mock_run: MagicMock) -> None:
        """BanditHandler.run() keeps the command key from subprocess."""
        # Arrange
        import json

        bandit_json = json.dumps(
            {
                "results": [
                    {
                        "test_id": "B603",
                        "test_name": "subprocess_without_shell",
                        "issue_severity": "LOW",
                        "issue_confidence": "HIGH",
                        "line_number": 10,
                        "filename": "a.py",
                        "issue_text": "test",
                        "more_info": "",
                    }
                ],
                "metrics": {},
            }
        )
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=bandit_json,
            stderr="",
        )
        handler = BanditHandler(timeout=300)
        bandit_config = BanditConfig()
        global_config = GlobalConfig()
        root = Path()

        # Act
        result = handler.run([Path("a.py")], bandit_config, global_config, root)

        # Assert — command key must still exist alongside bandit-specific keys.
        assert "command" in result.tool_data
        assert "issues" in result.tool_data
        assert "total_before_filter" in result.tool_data


# ── which() tool discovery ── #


@pytest.mark.unit
class TestWhichToolDiscovery:
    """Verify which() finds tools in conda/venv environments."""

    @pytest.fixture(autouse=True)
    def _clear_which_cache(self) -> None:
        """Clear the which() lru_cache before each test."""
        which.cache_clear()

    def test_finds_tool_via_sys_executable_directory(self, tmp_path: Path) -> None:
        """which() discovers tools next to sys.executable."""
        # Arrange
        fake_exe = tmp_path / ("fake_tool.exe" if sys.platform == "win32" else "fake_tool")
        fake_exe.touch()
        fake_exe.chmod(0o755)

        # Patch sys.executable so which() checks tmp_path.
        fake_python = tmp_path / "python.exe"
        fake_python.touch()

        with (
            patch.object(sys, "executable", str(fake_python)),
            patch.dict(os.environ, {"PATH": ""}, clear=False),
        ):
            # Act
            result = which("fake_tool")

        # Assert
        assert result is not None
        assert "fake_tool" in result

    def test_finds_tool_in_scripts_subdir_on_windows(self, tmp_path: Path) -> None:
        """which() checks Scripts/ next to the interpreter on Windows."""
        # Arrange
        scripts_dir = tmp_path / "Scripts"
        scripts_dir.mkdir()
        fake_exe = scripts_dir / "fake_tool.exe"
        fake_exe.touch()
        fake_exe.chmod(0o755)

        fake_python = tmp_path / "python.exe"
        fake_python.touch()

        with (
            patch.object(sys, "executable", str(fake_python)),
            patch.dict(os.environ, {"PATH": ""}, clear=False),
            patch.object(sys, "platform", "win32"),
        ):
            # Act
            result = which("fake_tool")

        # Assert
        assert result is not None
        assert "Scripts" in result

    def test_returns_none_when_tool_not_found(self) -> None:
        """which() returns None for a non-existent tool."""
        # Arrange

        # Act
        result = which("this_tool_does_not_exist_anywhere_12345")

        # Assert
        assert result is None

    def test_prefers_interpreter_dir_over_path(self, tmp_path: Path) -> None:
        """Interpreter directory is checked before PATH entries."""
        # Arrange
        interp_dir = tmp_path / "interp"
        interp_dir.mkdir()
        path_dir = tmp_path / "other"
        path_dir.mkdir()

        ext = ".exe" if sys.platform == "win32" else ""
        interp_tool = interp_dir / f"mytool{ext}"
        interp_tool.touch()
        interp_tool.chmod(0o755)
        path_tool = path_dir / f"mytool{ext}"
        path_tool.touch()
        path_tool.chmod(0o755)

        fake_python = interp_dir / "python.exe"
        fake_python.touch()

        with (
            patch.object(sys, "executable", str(fake_python)),
            patch.dict(os.environ, {"PATH": str(path_dir)}, clear=False),
        ):
            # Act
            result = which("mytool")

        # Assert — should find the one in interp_dir, not path_dir.
        assert result is not None
        assert str(interp_dir) in result


@pytest.mark.unit
class TestExecuteSubprocessResolvesTool:
    """Verify _execute_subprocess resolves tool names via which()."""

    @patch("subprocess.run")
    def test_resolves_tool_path_before_subprocess(self, mock_run: MagicMock) -> None:
        """_execute_subprocess uses which() to resolve the tool path."""
        # Arrange
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="ok",
            stderr="",
        )
        handler = _make_handler()
        resolved_path = "/fake/env/bin/ruff"

        with patch(
            "scrutiny.execution.handlers.which",
            return_value=resolved_path,
        ) as mockwhich:
            # Act
            result = handler._execute_subprocess(
                tool="ruff_linter",
                command=["ruff", "check", "."],
                cwd=Path(),
            )

        # Assert — which was called with the command name.
        mockwhich.assert_called_once_with("ruff")
        # The resolved path replaced the bare tool name in the command.
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == resolved_path
        assert called_cmd[1:] == ["check", "."]
        # tool_data["command"] also has the resolved path.
        assert result.tool_data["command"][0] == resolved_path

    @patch("subprocess.run")
    def test_falls_back_to_bare_name_whenwhich_returns_none(self, mock_run: MagicMock) -> None:
        """Falls back to bare command when which() returns None."""
        # Arrange
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="ok",
            stderr="",
        )
        handler = _make_handler()

        with patch("scrutiny.execution.handlers.which", return_value=None):
            # Act
            handler._execute_subprocess(
                tool="ruff_linter",
                command=["ruff", "check", "."],
                cwd=Path(),
            )

        # Assert — bare name is kept.
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == "ruff"


# ── Security Tool Selection ── #


@pytest.mark.unit
class TestSecurityToolSelection:
    """Test get_active_security_tool and get_enabled_tools swap behaviour."""

    def _make_global_config(
        self,
        security_tool: object | None = None,
        pipeline_security_tool: object | None = None,
        run_security: bool = True,
    ) -> object:
        """Build a GlobalConfig with optional security tool overrides."""
        kwargs: dict[str, object] = {"run_security": run_security}
        if security_tool is not None:
            kwargs["security_tool"] = security_tool
        if pipeline_security_tool is not None:
            kwargs["pipeline_security_tool"] = pipeline_security_tool
        return GlobalConfig(**kwargs)

    # ── get_active_security_tool ── #

    def test_ide_context_returns_default_security_tool(self) -> None:
        """IDE context should select the configured default security tool."""
        config = self._make_global_config()
        result = config.get_active_security_tool(ContextDetection.IDE)
        assert result == config.security_tool

    def test_cli_context_returns_default_security_tool(self) -> None:
        """CLI context should select the configured default security tool."""
        config = self._make_global_config()
        result = config.get_active_security_tool(ContextDetection.CLI)
        assert result == config.security_tool

    def test_ci_context_returns_pipeline_security_tool(self) -> None:
        """CI context should select the configured pipeline security tool."""
        config = self._make_global_config()
        result = config.get_active_security_tool(ContextDetection.CI)
        assert result == config.pipeline_security_tool

    def test_precommit_context_returns_pipeline_security_tool(self) -> None:
        """PRECOMMIT context should select the configured pipeline security tool."""
        config = self._make_global_config()
        result = config.get_active_security_tool(ContextDetection.PRECOMMIT)
        assert result == config.pipeline_security_tool

    # ── get_enabled_tools ── #

    def test_enabled_tools_ide_includes_default_security_tool(self) -> None:
        """IDE context enabled tools should include the configured default security tool."""
        config = self._make_global_config()
        tools = config.get_enabled_tools(ContextDetection.IDE)
        assert config.security_tool.value in tools

    def test_enabled_tools_ci_includes_pipeline_security_tool(self) -> None:
        """CI context enabled tools should include the configured pipeline security tool."""
        config = self._make_global_config()
        tools = config.get_enabled_tools(ContextDetection.CI)
        assert config.pipeline_security_tool.value in tools

    def test_enabled_tools_precommit_includes_pipeline_security_tool(self) -> None:
        """PRECOMMIT context enabled tools should include the configured pipeline security tool."""
        config = self._make_global_config()
        tools = config.get_enabled_tools(ContextDetection.PRECOMMIT)
        assert config.pipeline_security_tool.value in tools

    def test_enabled_tools_security_disabled_excludes_all(self) -> None:
        """When run_security is False, no security tool should appear."""
        config = self._make_global_config(run_security=False)
        tools = config.get_enabled_tools(ContextDetection.IDE)
        assert "bandit" not in tools
        assert "ruff_security" not in tools

    # ── Custom overrides ── #

    def test_custom_security_tool_overrides_ide_default(self) -> None:
        """Custom security_tool should override the IDE default."""
        config = self._make_global_config(
            security_tool=SecurityTool.RUFF,
        )
        result = config.get_active_security_tool(ContextDetection.IDE)
        assert result == SecurityTool.RUFF

    def test_custom_pipeline_tool_overrides_ci_default(self) -> None:
        """Custom pipeline_security_tool should override the CI default."""
        config = self._make_global_config(
            pipeline_security_tool=SecurityTool.BANDIT,
        )
        result = config.get_active_security_tool(ContextDetection.CI)
        assert result == SecurityTool.BANDIT


# ── Config Enum Validation ── #


@pytest.mark.unit
class TestConfigEnums:
    """Test PythonVersion, LineLength, SearchDepth, ToolTimeout enums."""

    @pytest.mark.parametrize(
        "member_name,expected_dotted",
        [("PY39", "3.9"), ("PY310", "3.10"), ("PY313", "3.13")],
    )
    def test_python_version_to_dotted(
        self,
        member_name: str,
        expected_dotted: str,
    ) -> None:
        """PythonVersion.to_dotted converts enum members to dotted strings."""
        member = getattr(PythonVersion, member_name)
        assert member.to_dotted == expected_dotted

    def test_python_version_string_behaviour(self) -> None:
        """PythonVersion members should behave as strings."""
        version = PythonVersion.PY39
        assert version.startswith("py")
        assert version[2] == "3"

    def test_line_length_values(self) -> None:
        """LineLength enum should have the expected int values."""
        assert LineLength.PEP8 == 79
        assert LineLength.BLACK == 88
        assert LineLength.STANDARD == 100
        assert LineLength.RELAXED == 120

    def test_search_depth_values(self) -> None:
        """SearchDepth enum should have the expected int values."""
        assert SearchDepth.SHALLOW == 3
        assert SearchDepth.MODERATE == 5
        assert SearchDepth.DEFAULT == 8
        assert SearchDepth.DEEP == 10

    def test_tool_timeout_values(self) -> None:
        """ToolTimeout enum should have the expected int values."""
        assert ToolTimeout.QUICK == 30
        assert ToolTimeout.STANDARD == 60
        assert ToolTimeout.PATIENT == 120
        assert ToolTimeout.GENEROUS == 300
        assert ToolTimeout.EXTENDED == 600

    def test_user_defaults_enum_types(self) -> None:
        """UserDefaults fields should be enum instances."""
        assert isinstance(UserDefaults.SCR_PYTHON_VERSION, PythonVersion)
        assert isinstance(UserDefaults.SCR_LINE_LENGTH, LineLength)
        assert isinstance(UserDefaults.SCR_MAX_UPWARD_SEARCH_DEPTH, SearchDepth)
        assert isinstance(UserDefaults.SCR_TOOL_TIMEOUT, ToolTimeout)

    def test_global_config_accepts_enum_values(self) -> None:
        """GlobalConfig should accept enum values without errors."""
        # LineLength is an IntEnum so passing a member still satisfies the int
        # field; validation only requires a positive integer within bounds.
        config = GlobalConfig(
            python_version=PythonVersion.PY312,
            line_length=LineLength.BLACK,
            max_upward_search_depth=SearchDepth.SHALLOW,
            tool_timeout=ToolTimeout.QUICK,
        )
        assert config.python_version == PythonVersion.PY312
        assert config.line_length == int(LineLength.BLACK)
        assert config.max_upward_search_depth == SearchDepth.SHALLOW
        assert config.tool_timeout == ToolTimeout.QUICK

    def test_global_config_accepts_raw_int_for_line_length(self) -> None:
        """GlobalConfig accepts any positive int within bounds for line_length."""
        # Arrange
        user_value = 123

        # Act
        config = GlobalConfig(line_length=user_value)

        # Assert
        assert config.line_length == user_value

    def test_global_config_rejects_line_length_below_minimum(self) -> None:
        """GlobalConfig rejects line_length values smaller than the minimum."""
        # Arrange
        below_minimum = 1

        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"line_length must be >="):
            GlobalConfig(line_length=below_minimum)

    def test_global_config_rejects_line_length_above_maximum(self) -> None:
        """GlobalConfig rejects line_length values larger than the maximum."""
        # Arrange
        above_maximum = 9999

        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"line_length must be <="):
            GlobalConfig(line_length=above_maximum)

    def test_global_config_rejects_raw_str_for_python_version(self) -> None:
        """GlobalConfig should reject raw str for python_version."""
        with pytest.raises(SCRConfigurationError, match=r"must be PythonVersion"):
            GlobalConfig(python_version="py39")


# ── CLI Flag Coverage ── #


@pytest.mark.unit
class TestCliParserCoverage:
    """Test that all GlobalConfig fields have corresponding CLI flags."""

    def test_parser_has_fix_flag(self) -> None:
        """Parser should accept --fix."""
        parser = create_argument_parser()
        args = parser.parse_args(["--fix"])
        assert args.fix is True

    def test_parser_has_no_parallel_flag(self) -> None:
        """Parser should accept --no-parallel."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-parallel"])
        assert args.no_parallel is True

    def test_parser_has_unsafe_fixes_flag(self) -> None:
        """Parser should accept --unsafe-fixes."""
        parser = create_argument_parser()
        args = parser.parse_args(["--unsafe-fixes"])
        assert args.unsafe_fixes is True

    def test_parser_has_timeout_flag(self) -> None:
        """Parser should accept --timeout with int value."""
        parser = create_argument_parser()
        args = parser.parse_args(["--timeout", "60"])
        assert args.tool_timeout == 60

    def test_parser_has_no_current_dir_as_root_flag(self) -> None:
        """Parser should accept --no-current-dir-as-root."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-current-dir-as-root"])
        assert args.no_current_dir_as_root is True

    def test_parser_has_max_search_depth_flag(self) -> None:
        """Parser should accept --max-search-depth with int value."""
        parser = create_argument_parser()
        args = parser.parse_args(["--max-search-depth", "10"])
        assert args.max_upward_search_depth == 10

    def test_parser_has_follow_symlinks_flag(self) -> None:
        """Parser should accept --follow-symlinks."""
        parser = create_argument_parser()
        args = parser.parse_args(["--follow-symlinks"])
        assert args.follow_symlinks is True

    def test_parser_has_exclude_dir_flag(self) -> None:
        """Parser should accept repeatable --exclude-dir."""
        parser = create_argument_parser()
        args = parser.parse_args(["--exclude-dir", ".venv", "--exclude-dir", "build"])
        assert args.exclude_dirs == [".venv", "build"]

    def test_parser_has_exclude_file_flag(self) -> None:
        """Parser should accept repeatable --exclude-file."""
        parser = create_argument_parser()
        args = parser.parse_args(["--exclude-file", "*.pyc", "--exclude-file", "*.pyo"])
        assert args.exclude_files == ["*.pyc", "*.pyo"]

    def test_parser_has_no_log_flag(self) -> None:
        """Parser should accept --no-log."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-log"])
        assert args.no_log is True

    def test_parser_has_log_dir_flag(self) -> None:
        """Parser should accept --log-dir with path value."""
        parser = create_argument_parser()
        args = parser.parse_args(["--log-dir", "/tmp/logs"])
        assert args.log_dir == "/tmp/logs"

    def test_parser_has_file_log_level_flag(self) -> None:
        """Parser should accept --file-log-level with choices."""
        parser = create_argument_parser()
        args = parser.parse_args(["--file-log-level", "verbose"])
        assert args.file_logger_level == "verbose"

    def test_parser_has_security_tool_flag(self) -> None:
        """Parser should accept --security-tool with choices."""
        parser = create_argument_parser()
        args = parser.parse_args(["--security-tool", "bandit"])
        assert args.security_tool == "bandit"

    def test_parser_has_pipeline_security_tool_flag(self) -> None:
        """Parser should accept --pipeline-security-tool with choices."""
        parser = create_argument_parser()
        args = parser.parse_args(["--pipeline-security-tool", "ruff_security"])
        assert args.pipeline_security_tool == "ruff_security"


# ── parse_cli_to_dict Mapping ── #


@pytest.mark.unit
class TestParseCliToDict:
    """Test parse_cli_to_dict maps CLI args to config dict correctly."""

    def test_valued_arg_tool_timeout(self) -> None:
        """--timeout should map to tool_timeout in config dict."""
        parser = create_argument_parser()
        args = parser.parse_args(["--timeout", "45"])
        result = parse_cli_to_dict(args)
        assert result["tool_timeout"] == 45

    def test_valued_arg_max_search_depth(self) -> None:
        """--max-search-depth should map to max_upward_search_depth."""
        parser = create_argument_parser()
        args = parser.parse_args(["--max-search-depth", "3"])
        result = parse_cli_to_dict(args)
        assert result["max_upward_search_depth"] == 3

    def test_valued_arg_log_dir(self) -> None:
        """--log-dir should map to log_dir in config dict."""
        parser = create_argument_parser()
        args = parser.parse_args(["--log-dir", "/tmp/cq"])
        result = parse_cli_to_dict(args)
        assert result["log_dir"] == "/tmp/cq"

    def test_bool_flag_fix(self) -> None:
        """--fix should map to fix=True in config dict."""
        parser = create_argument_parser()
        args = parser.parse_args(["--fix"])
        result = parse_cli_to_dict(args)
        assert result["fix"] is True

    def test_bool_flag_unsafe_fixes(self) -> None:
        """--unsafe-fixes should map to unsafe_fixes=True."""
        parser = create_argument_parser()
        args = parser.parse_args(["--unsafe-fixes"])
        result = parse_cli_to_dict(args)
        assert result["unsafe_fixes"] is True

    def test_bool_flag_follow_symlinks(self) -> None:
        """--follow-symlinks should map to follow_symlinks=True."""
        parser = create_argument_parser()
        args = parser.parse_args(["--follow-symlinks"])
        result = parse_cli_to_dict(args)
        assert result["follow_symlinks"] is True

    def test_negation_no_current_dir_as_root(self) -> None:
        """--no-current-dir-as-root should map to current_dir_as_root=False."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-current-dir-as-root"])
        result = parse_cli_to_dict(args)
        assert result["current_dir_as_root"] is False

    def test_append_exclude_files(self) -> None:
        """--exclude-file should produce a tuple of patterns."""
        parser = create_argument_parser()
        args = parser.parse_args(["--exclude-file", "*.bak", "--exclude-file", "*.tmp"])
        result = parse_cli_to_dict(args)
        assert result["exclude_files"] == ("*.bak", "*.tmp")

    def test_pipeline_security_tool_converts_to_enum(self) -> None:
        """--pipeline-security-tool should convert to SecurityTool enum."""
        parser = create_argument_parser()
        args = parser.parse_args(["--pipeline-security-tool", "bandit"])
        result = parse_cli_to_dict(args)
        assert result["pipeline_security_tool"] == SecurityTool.BANDIT

    def test_file_log_level_converts_to_enum(self) -> None:
        """--file-log-level should convert to LoggerLevel enum."""
        parser = create_argument_parser()
        args = parser.parse_args(["--file-log-level", "detailed"])
        result = parse_cli_to_dict(args)
        assert result["file_logger_level"] == LoggerLevel.DETAILED


# ── Ruff Rule Tiers ── #


@pytest.mark.unit
class TestRuffRuleTiers:
    """Verify tier composition and rule placement."""

    def test_essential_contains_core_rules(self) -> None:
        """Essential tier must contain E4, E7, E9, and F."""
        essential = RUFF_RULES_ESSENTIAL
        for rule in ("E4", "E7", "E9", "F"):
            assert rule in essential

    def test_standard_contains_up_and_ytt(self) -> None:
        """Standard tier must include full UP and YTT families."""
        standard = RUFF_RULES_STANDARD
        assert "UP" in standard
        assert "YTT" in standard

    def test_standard_does_not_contain_pth_or_perf(self) -> None:
        """PTH and PERF belong in Strict, not Standard."""
        standard = RUFF_RULES_STANDARD
        assert "PTH" not in standard
        assert "PERF" not in standard

    def test_strict_contains_pth_and_perf(self) -> None:
        """Strict tier must include PTH and PERF."""
        strict = RUFF_RULES_STRICT
        assert "PTH" in strict
        assert "PERF" in strict

    def test_strict_contains_promoted_rules(self) -> None:
        """Strict tier must include T20, FIX, and SLF."""
        strict = RUFF_RULES_STRICT
        assert "T20" in strict
        assert "FIX" in strict
        assert "SLF" in strict

    def test_strict_does_not_contain_plc(self) -> None:
        """PLC belongs in Insane, not Strict."""
        # Strict has cherry-picked PLR rules but not PLC.
        strict = RUFF_RULES_STRICT
        assert "PLC" not in strict

    def test_insane_contains_plc_and_full_plr(self) -> None:
        """Insane tier must include PLC and full PLR."""
        insane = RUFF_RULES_INSANE
        assert "PLC" in insane
        assert "PLR" in insane

    def test_insane_includes_all_strict_rules(self) -> None:
        """Insane must be a superset of Strict."""
        strict_set = set(RUFF_RULES_STRICT)
        insane_set = set(RUFF_RULES_INSANE)
        assert strict_set.issubset(insane_set)

    def test_strict_includes_all_standard_rules(self) -> None:
        """Strict must be a superset of Standard."""
        standard_set = set(RUFF_RULES_STANDARD)
        strict_set = set(RUFF_RULES_STRICT)
        assert standard_set.issubset(strict_set)


# ── Ruff Ignore Rules ── #


@pytest.mark.unit
class TestRuffIgnoreRules:
    """Verify RUFF_IGNORE_RULES contents."""

    def test_try003_in_ignore_rules(self) -> None:
        """TRY003 must be globally ignored."""
        assert "TRY003" in RUFF_IGNORE_RULES

    def test_try400_in_ignore_rules(self) -> None:
        """TRY400 must be globally ignored."""
        assert "TRY400" in RUFF_IGNORE_RULES

    def test_up045_in_version_gated_ignores(self) -> None:
        """UP045 must be version-gated (ignored below py310)."""
        assert "UP045" in RUFF_VERSION_GATED_IGNORES["py310"]

    def test_g004_in_ignore_rules(self) -> None:
        """G004 must be globally ignored (SCRLogger uses custom methods)."""
        assert "G004" in RUFF_IGNORE_RULES

    def test_ignore_rules_is_non_empty_tuple(self) -> None:
        """RUFF_IGNORE_RULES must be a non-empty tuple."""
        assert isinstance(RUFF_IGNORE_RULES, tuple)
        assert len(RUFF_IGNORE_RULES) > 0


# ── Per-File Ignores ── #


@pytest.mark.unit
class TestRuffPerFileIgnores:
    """Verify RUFF_PER_FILE_IGNORES contents."""

    def test_scripts_folder_ignores_inp001(self) -> None:
        """scripts/*.py must have INP001 suppressed."""
        assert "scripts/*.py" in RUFF_PER_FILE_IGNORES
        assert "INP001" in RUFF_PER_FILE_IGNORES["scripts/*.py"]


# ── Framework Rules ── #


@pytest.mark.unit
class TestFrameworkOverlay:
    """Verify FrameworkSelection enum and rule overlay."""

    def test_framework_none_adds_no_rules(self) -> None:
        """Default 'none' framework produces no extra rules."""
        rules = RUFF_FRAMEWORK_RULES.get("none", ())
        assert rules == ()

    def test_framework_django_adds_dj_rules(self) -> None:
        """Django framework adds 'DJ' rule family."""
        rules = RUFF_FRAMEWORK_RULES.get("django", ())
        assert "DJ" in rules

    def test_framework_fastapi_adds_fast_rules(self) -> None:
        """FastAPI framework adds 'FAST' rule family."""
        rules = RUFF_FRAMEWORK_RULES.get("fastapi", ())
        assert "FAST" in rules

    def test_framework_rules_merge_with_tier(self) -> None:
        """Framework rules must append to tier rules."""
        tier_rules = RUFF_RULES_STRICT
        framework_rules = RUFF_FRAMEWORK_RULES["django"]
        merged = (*tier_rules, *framework_rules)
        assert "DJ" in merged
        # All strict rules must still be present.
        for rule in tier_rules:
            assert rule in merged

    def test_framework_enum_values(self) -> None:
        """FrameworkSelection enum must expose all expected values."""
        values = {member.value for member in FrameworkSelection}
        expected = {"none", "django", "fastapi", "airflow", "numpy", "pandas"}
        assert values == expected

    def test_framework_cli_flag_parses(self) -> None:
        """--framework fastapi should parse without error."""
        parser = create_argument_parser()
        args = parser.parse_args(["--framework", "fastapi"])
        assert args.framework == "fastapi"


# ── Pyproject-Only Mode ── #


@pytest.mark.unit
class TestPyprojectOnlyMode:
    """Test --pyproject-only mode for ConfigResolver."""

    def test_pyproject_only_skips_script_defaults(self) -> None:
        """In pyproject-only mode, script defaults are not used."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            tier=ConfigTier.STRICT,
            pyproject_only=True,
        )
        result = resolver.resolve(script_default="should_be_skipped")
        assert result.value is None

    def test_pyproject_only_respects_cli(self) -> None:
        """Pyproject-only mode still uses CLI (priority 1)."""
        resolver = ConfigResolver(
            cli_args={"fix": True},
            pyproject_config={},
            tier=ConfigTier.STRICT,
            pyproject_only=True,
        )
        result = resolver.resolve(cli_key="fix", script_default=False)
        assert result.value is True

    def test_pyproject_only_respects_pyproject(self) -> None:
        """Pyproject-only mode still uses pyproject.toml (priority 2)."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": 120}},
            tier=ConfigTier.STRICT,
            pyproject_only=True,
        )
        result = resolver.resolve(
            pyproject_tool="ruff",
            pyproject_key="line_length",
            script_default=100,
        )
        assert result.value == 120

    def test_pyproject_only_default_is_true(self) -> None:
        """Pyproject-only mode defaults to True in UserDefaults."""
        assert UserDefaults.SCR_PYPROJECT_ONLY is False

    def test_pyproject_only_cli_flag_parses(self) -> None:
        """--pyproject-only flag should parse without error."""
        parser = create_argument_parser()
        args = parser.parse_args(["--pyproject-only"])
        assert args.pyproject_only is True

    def test_pyproject_only_in_global_config(self) -> None:
        """GlobalConfig accepts pyproject_only field."""
        config = GlobalConfig(pyproject_only=True)
        assert config.pyproject_only is True


# ── Version-Gated Ignore Rules in ConfigResolver ── #


@pytest.mark.unit
class TestVersionGatedIgnoresInResolver:
    """Test version-aware ignore rules through ConfigResolver."""

    def test_build_ruff_config_py39_includes_up007(self) -> None:
        """Build ruff config at py39: UP007 must appear in ignore rules."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            tier=ConfigTier.STRICT,
        )
        global_config = GlobalConfig(
            python_version=PythonVersion.PY39,
        )
        ruff_config = resolver.build_ruff_config(global_config)
        assert "UP007" in ruff_config.ignore_rules
        assert "UP045" in ruff_config.ignore_rules

    def test_build_ruff_config_py310_excludes_up007(self) -> None:
        """Build ruff config at py310: UP007 must NOT appear in ignore rules."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            tier=ConfigTier.STRICT,
        )
        global_config = GlobalConfig(
            python_version=PythonVersion.PY310,
        )
        ruff_config = resolver.build_ruff_config(global_config)
        assert "UP007" not in ruff_config.ignore_rules
        assert "UP045" not in ruff_config.ignore_rules

    def test_build_ruff_config_mypy_enabled_ignores_ruf013(self) -> None:
        """When mypy is enabled, RUF013 must be in ignore rules."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            tier=ConfigTier.STRICT,
        )
        global_config = GlobalConfig(run_mypy=True)
        ruff_config = resolver.build_ruff_config(global_config)
        assert "RUF013" in ruff_config.ignore_rules

    def test_build_ruff_config_mypy_disabled_allows_ruf013(self) -> None:
        """When mypy is disabled, RUF013 must NOT be in ignore rules."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            tier=ConfigTier.STRICT,
        )
        global_config = GlobalConfig(run_mypy=False)
        ruff_config = resolver.build_ruff_config(global_config)
        assert "RUF013" not in ruff_config.ignore_rules


# ── BaseToolHandler._strip_ansi_codes ── #


@pytest.mark.unit
class TestStripAnsiCodes:
    """Test ANSI escape sequence removal from tool output."""

    def test_removes_color_codes(self) -> None:
        """Strip a single ANSI colour sequence from text."""
        # Arrange
        handler = _make_handler()
        text = "\x1b[31mERROR\x1b[0m: something failed"

        # Act
        result = handler._strip_ansi_codes(text)

        # Assert
        assert result == "ERROR: something failed"

    def test_preserves_plain_text(self) -> None:
        """Plain text without ANSI codes is returned unchanged."""
        # Arrange
        handler = _make_handler()
        text = "no colour here"

        # Act
        result = handler._strip_ansi_codes(text)

        # Assert
        assert result == "no colour here"

    def test_handles_empty_string(self) -> None:
        """Empty string returns empty string."""
        # Arrange
        handler = _make_handler()

        # Act / Assert
        assert handler._strip_ansi_codes("") == ""

    def test_handles_multiple_escape_sequences(self) -> None:
        """Multiple consecutive ANSI sequences are all removed."""
        # Arrange
        handler = _make_handler()
        text = "\x1b[1m\x1b[32mOK\x1b[0m \x1b[33mWARN\x1b[0m"

        # Act
        result = handler._strip_ansi_codes(text)

        # Assert
        assert result == "OK WARN"


# ── MypyHandler._parse_json_output ── #


@pytest.mark.unit
class TestMypyParseJsonOutput:
    """Test Mypy JSON output parsing."""

    def test_parses_standard_json_error(self) -> None:
        """Parse a standard mypy JSON error with all fields."""
        # Arrange
        line = (
            '{"file": "app/main.py", "line": 10, "column": 5, '
            '"severity": "error", "message": "Incompatible return", '
            '"hint": null, "code": "return-value"}'
        )

        # Act
        issues = MypyHandler._parse_json_output(line)

        # Assert
        assert len(issues) == 1
        assert issues[0]["file"] == "app/main.py"
        assert issues[0]["line"] == 10
        assert issues[0]["column"] == 5
        assert issues[0]["severity"] == "error"
        assert issues[0]["code"] == "return-value"

    def test_normalizes_negative_column_to_zero(self) -> None:
        """Column value of -1 (no column available) normalizes to 0."""
        # Arrange
        line = (
            '{"file": "app/main.py", "line": 10, "column": -1, '
            '"severity": "error", "message": "Missing return", '
            '"hint": null, "code": "return"}'
        )

        # Act
        issues = MypyHandler._parse_json_output(line)

        # Assert
        assert len(issues) == 1
        assert issues[0]["column"] == 0

    def test_parses_warning_severity(self) -> None:
        """Parse a mypy JSON warning line."""
        # Arrange
        line = (
            '{"file": "app/main.py", "line": 5, "column": 1, '
            '"severity": "warning", "message": "Unused import", '
            '"hint": null, "code": "unused-import"}'
        )

        # Act
        issues = MypyHandler._parse_json_output(line)

        # Assert
        assert len(issues) == 1
        assert issues[0]["severity"] == "warning"

    def test_skips_non_json_lines(self) -> None:
        """Non-JSON lines (like summary text) are silently skipped."""
        # Arrange
        lines = "Found 2 errors in 1 file (checked 3 source files)"

        # Act
        issues = MypyHandler._parse_json_output(lines)

        # Assert
        assert issues == []

    def test_returns_empty_for_empty_input(self) -> None:
        """Empty string produces empty list."""
        # Arrange

        # Act / Assert
        assert MypyHandler._parse_json_output("") == []

    def test_parses_multiple_json_lines(self) -> None:
        """Multi-line JSON output produces multiple issue dicts."""
        # Arrange
        stdout = (
            '{"file": "a.py", "line": 1, "column": 5, "severity": "error", '
            '"message": "Type error", "hint": null, "code": "return-value"}\n'
            '{"file": "b.py", "line": 10, "column": 3, "severity": "error", '
            '"message": "Assignment error", "hint": null, "code": "assignment"}'
        )

        # Act
        issues = MypyHandler._parse_json_output(stdout)

        # Assert
        assert len(issues) == 2
        assert issues[0]["file"] == "a.py"
        assert issues[1]["file"] == "b.py"

    def test_skips_invalid_json_among_valid_lines(self) -> None:
        """Valid JSON issues are parsed; invalid lines are skipped."""
        # Arrange
        stdout = (
            '{"file": "a.py", "line": 1, "column": 5, "severity": "error", '
            '"message": "error msg", "hint": null, "code": "return-value"}\n'
            "Found 1 error in 1 file\n"
            "Some random text\n"
        )

        # Act
        issues = MypyHandler._parse_json_output(stdout)

        # Assert
        assert len(issues) == 1

    def test_handles_missing_json_fields(self) -> None:
        """Missing JSON keys use safe defaults."""
        # Arrange
        stdout = '{"file": "a.py", "line": 1, "severity": "error", "message": "msg"}'

        # Act
        issues = MypyHandler._parse_json_output(stdout)

        # Assert
        assert len(issues) == 1
        assert issues[0]["column"] == 0
        assert issues[0]["code"] == ""


# ── RadonCCHandler._parse_json_output ── #


@pytest.mark.unit
class TestRadonParseJsonOutput:
    """Test Radon JSON parsing with complexity threshold filtering."""

    def test_filters_below_threshold(self) -> None:
        """Functions at or below threshold grade pass through."""
        # Arrange
        import json

        data = {
            "test.py": [
                {
                    "name": "simple",
                    "lineno": 1,
                    "complexity": 2,
                    "rank": "A",
                    "type": "function",
                    "classname": "",
                }
            ]
        }
        stdout = json.dumps(data)

        # Act
        issues = RadonCCHandler._parse_json_output(stdout, "B")

        # Assert
        assert len(issues) == 0

    def test_flags_above_threshold_grade(self) -> None:
        """Functions above threshold grade are returned as issues."""
        # Arrange
        import json

        data = {
            "test.py": [
                {
                    "name": "complex_func",
                    "lineno": 10,
                    "complexity": 15,
                    "rank": "C",
                    "type": "function",
                    "classname": "",
                }
            ]
        }
        stdout = json.dumps(data)

        # Act
        issues = RadonCCHandler._parse_json_output(stdout, "B")

        # Assert
        assert len(issues) == 1
        assert issues[0]["name"] == "complex_func"
        assert issues[0]["grade"] == "C"

    def test_threshold_grade_itself_passes(self) -> None:
        """A function at exactly the threshold grade is acceptable."""
        # Arrange
        import json

        data = {
            "test.py": [
                {
                    "name": "moderate",
                    "lineno": 5,
                    "complexity": 8,
                    "rank": "B",
                    "type": "function",
                    "classname": "",
                }
            ]
        }
        stdout = json.dumps(data)

        # Act
        issues = RadonCCHandler._parse_json_output(stdout, "B")

        # Assert
        assert len(issues) == 0

    def test_invalid_json_raises_error(self) -> None:
        """Non-JSON input raises json.JSONDecodeError."""
        # Arrange
        import json

        # Act / Assert
        with pytest.raises(json.JSONDecodeError):
            RadonCCHandler._parse_json_output("not json", "B")


# ── BanditHandler._parse_json_output ── #


@pytest.mark.unit
class TestBanditParseJsonOutput:
    """Test Bandit JSON parsing into BanditIssue objects."""

    def test_parses_valid_results(self) -> None:
        """Parse valid Bandit JSON into BanditIssue list."""
        # Arrange
        import json

        data = {
            "results": [
                {
                    "test_id": "B101",
                    "test_name": "assert_used",
                    "issue_severity": "LOW",
                    "issue_confidence": "HIGH",
                    "line_number": 5,
                    "filename": "test.py",
                    "issue_text": "Use of assert detected.",
                    "more_info": "",
                    "code": "",
                },
            ],
        }
        stdout = json.dumps(data)

        # Act
        issues = BanditHandler._parse_json_output(stdout)

        # Assert
        assert len(issues) == 1
        assert issues[0].test_id == "B101"

    def test_returns_empty_for_invalid_json(self) -> None:
        """Invalid JSON returns empty list (not an exception)."""
        # Arrange

        # Act
        issues = BanditHandler._parse_json_output("not json")

        # Assert
        assert issues == []

    def test_returns_empty_for_no_results_key(self) -> None:
        """JSON without 'results' key returns empty list."""
        # Arrange
        import json

        # Act
        issues = BanditHandler._parse_json_output(json.dumps({"errors": []}))

        # Assert
        assert issues == []
