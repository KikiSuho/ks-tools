"""Tests for the platforms/ package; interface parity, data, and behavior."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from scrutiny.platforms import linux as plat_linux
from scrutiny.platforms import macos as plat_macos
from scrutiny.platforms import windows as plat_windows


_EXPECTED_EXPORTS: frozenset[str] = frozenset(
    {
        "IDE_ENV_VARS",
        "IDE_PROCESSES",
        "get_extra_search_dirs",
        "get_pathext",
        "get_subprocess_creation_flags",
        "get_subprocess_preexec_fn",
        "safe_rmtree",
        "terminate_process_tree",
    },
)

_ALL_PLATFORM_MODULES = pytest.mark.parametrize(
    "platform_module",
    [plat_windows, plat_linux, plat_macos],
    ids=["windows", "linux", "macos"],
)


# ====================================== #
#          INTERFACE PARITY              #
# ====================================== #


@pytest.mark.unit
class TestPlatformInterfaceParity:
    """Verify all three platform modules export identical public names."""

    def test_all_modules_export_same_names(self) -> None:
        """windows, linux, and macos __all__ lists must match exactly."""
        # Arrange
        win_exports = set(plat_windows.__all__)
        lin_exports = set(plat_linux.__all__)
        mac_exports = set(plat_macos.__all__)

        # Assert
        assert win_exports == lin_exports == mac_exports

    def test_exports_match_expected_set(self) -> None:
        """All modules export exactly the expected set of names."""
        # Arrange / Act
        win_exports = set(plat_windows.__all__)

        # Assert
        assert win_exports == _EXPECTED_EXPORTS


# ====================================== #
#            PLATFORM DATA               #
# ====================================== #


@pytest.mark.unit
class TestPlatformData:
    """Verify platform-specific data values are correct."""

    def test_windows_ide_processes_contain_exe_variants(self) -> None:
        """Windows IDE_PROCESSES must include .exe variants."""
        # Assert
        assert "code.exe" in plat_windows.IDE_PROCESSES
        assert "pycharm64.exe" in plat_windows.IDE_PROCESSES

    def test_linux_ide_processes_no_exe_variants(self) -> None:
        """Linux IDE_PROCESSES must not include .exe variants."""
        # Assert
        exe_names = {p for p in plat_linux.IDE_PROCESSES if p.endswith(".exe")}
        assert exe_names == set()

    def test_macos_ide_processes_no_exe_variants(self) -> None:
        """macOS IDE_PROCESSES must not include .exe variants."""
        # Assert
        exe_names = {p for p in plat_macos.IDE_PROCESSES if p.endswith(".exe")}
        assert exe_names == set()

    @_ALL_PLATFORM_MODULES
    def test_universal_editors_present(self, platform_module: object) -> None:
        """vim, nvim, emacs must be in all platform IDE_PROCESSES."""
        # Arrange
        processes: frozenset[str] = platform_module.IDE_PROCESSES  # type: ignore[union-attr]

        # Assert
        assert {"vim", "nvim", "emacs"}.issubset(processes)

    def test_macos_excludes_term_program_version(self) -> None:
        """macOS must NOT include TERM_PROGRAM_VERSION (false positive)."""
        # Assert
        assert "TERM_PROGRAM_VERSION" not in plat_macos.IDE_ENV_VARS

    def test_windows_excludes_term_program_version(self) -> None:
        """Windows must NOT include TERM_PROGRAM_VERSION."""
        # Assert
        assert "TERM_PROGRAM_VERSION" not in plat_windows.IDE_ENV_VARS

    def test_linux_excludes_term_program_version(self) -> None:
        """Linux must NOT include TERM_PROGRAM_VERSION."""
        # Assert
        assert "TERM_PROGRAM_VERSION" not in plat_linux.IDE_ENV_VARS

    @_ALL_PLATFORM_MODULES
    def test_terminal_emulator_present(self, platform_module: object) -> None:
        """TERMINAL_EMULATOR (JetBrains) must be in all platforms."""
        # Arrange
        env_vars: frozenset[str] = platform_module.IDE_ENV_VARS  # type: ignore[union-attr]

        # Assert
        assert "TERMINAL_EMULATOR" in env_vars

    @_ALL_PLATFORM_MODULES
    def test_vscode_git_ipc_handle_present(self, platform_module: object) -> None:
        """VSCODE_GIT_IPC_HANDLE must be in all platforms."""
        # Arrange
        env_vars: frozenset[str] = platform_module.IDE_ENV_VARS  # type: ignore[union-attr]

        # Assert
        assert "VSCODE_GIT_IPC_HANDLE" in env_vars

    def test_windows_pathext_includes_exe(self) -> None:
        """Windows get_pathext must include .EXE."""
        # Act
        result = plat_windows.get_pathext()

        # Assert
        assert ".EXE" in result or ".exe" in result

    def test_linux_pathext_is_empty_string(self) -> None:
        """Linux get_pathext must return [''] (no extension needed)."""
        # Act
        result = plat_linux.get_pathext()

        # Assert
        assert result == [""]

    def test_macos_pathext_is_empty_string(self) -> None:
        """macOS get_pathext must return [''] (no extension needed)."""
        # Act
        result = plat_macos.get_pathext()

        # Assert
        assert result == [""]

    def test_windows_extra_dirs_includes_scripts(self) -> None:
        """Windows get_extra_search_dirs must return Scripts/ dir."""
        # Act
        result = plat_windows.get_extra_search_dirs("/some/interp/dir")

        # Assert
        assert len(result) == 1
        assert "Scripts" in result[0]

    def test_linux_extra_dirs_empty(self) -> None:
        """Linux get_extra_search_dirs must return empty list."""
        # Act
        result = plat_linux.get_extra_search_dirs("/some/interp/dir")

        # Assert
        assert result == []

    def test_macos_extra_dirs_empty(self) -> None:
        """macOS get_extra_search_dirs must return empty list."""
        # Act
        result = plat_macos.get_extra_search_dirs("/some/interp/dir")

        # Assert
        assert result == []


# ====================================== #
#          SUBPROCESS FLAGS              #
# ====================================== #


@pytest.mark.unit
class TestSubprocessFlags:
    """Verify platform subprocess configuration values."""

    def test_windows_creation_flags_nonzero(self) -> None:
        """Windows must return a nonzero creation flag."""
        # Act
        result = plat_windows.get_subprocess_creation_flags()

        # Assert
        assert result != 0

    def test_linux_creation_flags_zero(self) -> None:
        """Linux must return 0 (no special flags)."""
        # Act
        result = plat_linux.get_subprocess_creation_flags()

        # Assert
        assert result == 0

    def test_macos_creation_flags_zero(self) -> None:
        """macOS must return 0 (no special flags)."""
        # Act
        result = plat_macos.get_subprocess_creation_flags()

        # Assert
        assert result == 0

    def test_windows_preexec_fn_is_none(self) -> None:
        """Windows must return None for preexec_fn."""
        # Act
        result = plat_windows.get_subprocess_preexec_fn()

        # Assert
        assert result is None

    def test_linux_preexec_fn_is_callable(self) -> None:
        """Linux must return a callable for preexec_fn."""
        # Arrange; provide a stand-in when os.setsid is unavailable (Windows).
        sentinel = lambda: None  # noqa: E731
        # Patch os.setsid if missing so the function under test can resolve it.
        if not hasattr(os, "setsid"):
            os.setsid = sentinel  # type: ignore[attr-defined]
        # Exercise the function and guarantee cleanup afterward.
        try:
            # Act
            result = plat_linux.get_subprocess_preexec_fn()

            # Assert
            assert callable(result)
        # finally: clean up the monkey-patch.
        finally:
            # Remove the stand-in only if it is still ours.
            if getattr(os, "setsid", None) is sentinel:
                del os.setsid  # type: ignore[attr-defined]

    def test_macos_preexec_fn_is_callable(self) -> None:
        """macOS must return a callable for preexec_fn."""
        # Arrange; provide a stand-in when os.setsid is unavailable (Windows).
        sentinel = lambda: None  # noqa: E731
        # Patch os.setsid if missing so the function under test can resolve it.
        if not hasattr(os, "setsid"):
            os.setsid = sentinel  # type: ignore[attr-defined]
        # Exercise the function and guarantee cleanup afterward.
        try:
            # Act
            result = plat_macos.get_subprocess_preexec_fn()

            # Assert
            assert callable(result)
        # finally: clean up the monkey-patch.
        finally:
            # Remove the stand-in only if it is still ours.
            if getattr(os, "setsid", None) is sentinel:
                del os.setsid  # type: ignore[attr-defined]


# ====================================== #
#            SAFE RMTREE                 #
# ====================================== #


@pytest.mark.unit
class TestSafeRmtree:
    """Verify safe_rmtree removes directories correctly."""

    def test_removes_normal_directory(self, tmp_path: Path) -> None:
        """safe_rmtree removes a directory with normal files."""
        # Arrange
        target = tmp_path / "cache_dir"
        target.mkdir()
        (target / "file.txt").write_text("data")

        # Act; use the current platform's safe_rmtree
        from scrutiny.platforms import safe_rmtree

        safe_rmtree(target)

        # Assert
        assert not target.exists()

    @pytest.mark.skipif(
        os.name != "nt",
        reason="read-only removal handling is Windows-specific",
    )
    def test_windows_removes_readonly_file(self, tmp_path: Path) -> None:
        """Windows safe_rmtree removes read-only files."""
        # Arrange
        target = tmp_path / "cache_dir"
        target.mkdir()
        readonly_file = target / "readonly.txt"
        readonly_file.write_text("locked")
        readonly_file.chmod(stat.S_IREAD)

        # Act
        plat_windows.safe_rmtree(target)

        # Assert
        assert not target.exists()

    def test_removes_nested_directories(self, tmp_path: Path) -> None:
        """safe_rmtree removes nested directory structures."""
        # Arrange
        target = tmp_path / "outer"
        inner = target / "inner" / "deep"
        inner.mkdir(parents=True)
        (inner / "file.py").write_text("content")

        # Act
        from scrutiny.platforms import safe_rmtree

        safe_rmtree(target)

        # Assert
        assert not target.exists()
