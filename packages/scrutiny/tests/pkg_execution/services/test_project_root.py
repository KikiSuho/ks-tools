"""Tests for ProjectRootService and _resolve_log_root behaviour."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from scrutiny.core.enums import LogLocation, SearchDepth
from scrutiny.core.exceptions import SCRProjectRootError
from scrutiny.execution.services import ProjectRootService
from scrutiny.main import _resolve_log_root
from scrutiny.output.logger import DeferredLogBuffer
from conftest import make_global_config


# ── _marker_exists ── #


@pytest.mark.unit
class TestMarkerExists:
    """Test the _marker_exists staticmethod for project marker detection."""

    def test_existing_file_with_follow_symlinks(self, tmp_path: Path) -> None:
        """Return True for an existing file when follow_symlinks=True."""
        (tmp_path / ".git").mkdir()

        result = ProjectRootService._marker_exists(tmp_path, ".git", follow_symlinks=True)

        assert result is True

    def test_missing_file_with_follow_symlinks(self, tmp_path: Path) -> None:
        """Return False for a missing marker when follow_symlinks=True."""
        result = ProjectRootService._marker_exists(
            tmp_path,
            ".git",
            follow_symlinks=True,
        )

        assert result is False

    def test_existing_file_without_follow_symlinks(self, tmp_path: Path) -> None:
        """Return True for an existing file when follow_symlinks=False."""
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

        result = ProjectRootService._marker_exists(
            tmp_path,
            "pyproject.toml",
            follow_symlinks=False,
        )

        assert result is True

    def test_missing_file_without_follow_symlinks(self, tmp_path: Path) -> None:
        """Return False for a missing marker when follow_symlinks=False."""
        result = ProjectRootService._marker_exists(
            tmp_path,
            "pyproject.toml",
            follow_symlinks=False,
        )

        assert result is False

    def test_symlink_with_follow_true(self, tmp_path: Path) -> None:
        """Follow symlinks and return True when target exists."""
        # Mock Path.exists to simulate a symlink that resolves to a real target.
        candidate = tmp_path / ".git"
        with patch.object(type(candidate), "exists", return_value=True):
            result = ProjectRootService._marker_exists(
                tmp_path,
                ".git",
                follow_symlinks=True,
            )

        assert result is True

    def test_symlink_with_follow_false(self, tmp_path: Path) -> None:
        """Return True for symlink itself (via lstat) even without following."""
        # Mock Path.lstat to simulate a symlink detected without following.
        candidate = tmp_path / ".git"
        with patch.object(type(candidate), "lstat", return_value=object()):
            result = ProjectRootService._marker_exists(
                tmp_path,
                ".git",
                follow_symlinks=False,
            )

        assert result is True

    def test_permission_error_returns_false(self, tmp_path: Path) -> None:
        """Return False gracefully when OSError/PermissionError occurs."""
        # Use a non-existent parent directory to trigger OSError
        bogus_directory = tmp_path / "nonexistent_parent" / "child"

        result = ProjectRootService._marker_exists(
            bogus_directory,
            ".git",
            follow_symlinks=True,
        )

        assert result is False


# ── search_upward ── #


@pytest.mark.unit
class TestSearchUpward:
    """Test ProjectRootService.search_upward traversal logic."""

    def test_finds_root_with_git(self, tmp_path: Path) -> None:
        """Return directory containing .git when found."""
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "src" / "pkg"
        sub.mkdir(parents=True)

        result = ProjectRootService.search_upward(
            sub,
            max_depth=5,
            follow_symlinks=True,
        )

        assert result == tmp_path

    def test_finds_root_with_pyproject(self, tmp_path: Path) -> None:
        """Return directory containing pyproject.toml when found."""
        (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)

        result = ProjectRootService.search_upward(
            sub,
            max_depth=5,
            follow_symlinks=True,
        )

        assert result == tmp_path

    def test_raises_when_no_markers(self, tmp_path: Path) -> None:
        """Raise SCRProjectRootError when no markers are found."""
        sub = tmp_path / "lonely"
        sub.mkdir()

        with pytest.raises(
            SCRProjectRootError,
            match=r"No project markers found",
        ):
            ProjectRootService.search_upward(
                sub,
                max_depth=2,
                follow_symlinks=True,
            )

    def test_raises_when_max_depth_exhausted(self, tmp_path: Path) -> None:
        """Raise SCRProjectRootError when max_depth is exhausted before finding markers."""
        (tmp_path / ".git").mkdir()
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)

        # max_depth=2 means we only check 2 levels up from deep.
        with pytest.raises(
            SCRProjectRootError,
            match=r"No project markers found",
        ):
            ProjectRootService.search_upward(
                deep,
                max_depth=2,
                follow_symlinks=True,
            )


# ── _resolve_log_root ── #


@pytest.fixture(autouse=False)
def _clear_deferred_buffer() -> Iterator[None]:
    """Clear DeferredLogBuffer state before and after each test."""
    DeferredLogBuffer.clear()
    yield
    DeferredLogBuffer.clear()


@pytest.mark.unit
@pytest.mark.usefixtures("_clear_deferred_buffer")
class TestResolveLogRoot:
    """Test _resolve_log_root log placement resolution."""

    def test_current_dir_returns_start_path(self, tmp_path: Path) -> None:
        """CURRENT_DIR returns the invocation directory without upward search."""
        # Arrange
        config = make_global_config(log_location=LogLocation.CURRENT_DIR)

        # Act
        result = _resolve_log_root(tmp_path, config)  # noqa: SLF001

        # Assert
        assert result == tmp_path.resolve()

    def test_project_root_returns_actual_root(self, tmp_path: Path) -> None:
        """PROJECT_ROOT returns the discovered root when markers exist."""
        # Arrange
        (tmp_path / ".git").mkdir()
        sub_directory = tmp_path / "src" / "pkg"
        sub_directory.mkdir(parents=True)
        config = make_global_config(log_location=LogLocation.PROJECT_ROOT)

        # Act
        result = _resolve_log_root(sub_directory, config)  # noqa: SLF001

        # Assert
        assert result == tmp_path

    def test_project_root_no_markers_returns_none(self, tmp_path: Path) -> None:
        """PROJECT_ROOT returns None when no project markers are found."""
        # Arrange
        bare_directory = tmp_path / "no_markers"
        bare_directory.mkdir()
        config = make_global_config(
            log_location=LogLocation.PROJECT_ROOT,
            max_upward_search_depth=SearchDepth.SHALLOW,
        )

        # Act
        result = _resolve_log_root(bare_directory, config)  # noqa: SLF001

        # Assert
        assert result is None

    def test_project_root_no_markers_emits_message(self, tmp_path: Path) -> None:
        """PROJECT_ROOT emits a guidance message when no root is found."""
        # Arrange
        bare_directory = tmp_path / "no_markers"
        bare_directory.mkdir()
        config = make_global_config(
            log_location=LogLocation.PROJECT_ROOT,
            max_upward_search_depth=SearchDepth.SHALLOW,
        )

        # Act
        _resolve_log_root(bare_directory, config)  # noqa: SLF001

        # Assert
        messages = DeferredLogBuffer._messages  # noqa: SLF001
        assert len(messages) >= 1
        assert any("--log-location" in message for _, message in messages)

    def test_hybrid_returns_actual_root_when_found(self, tmp_path: Path) -> None:
        """HYBRID returns the discovered root when markers exist."""
        # Arrange
        (tmp_path / ".git").mkdir()
        sub_directory = tmp_path / "src"
        sub_directory.mkdir()
        config = make_global_config(log_location=LogLocation.HYBRID)

        # Act
        result = _resolve_log_root(sub_directory, config)  # noqa: SLF001

        # Assert
        assert result == tmp_path

    def test_hybrid_falls_back_to_current_dir(self, tmp_path: Path) -> None:
        """HYBRID falls back to current directory when no root is found."""
        # Arrange
        bare_directory = tmp_path / "no_markers"
        bare_directory.mkdir()
        config = make_global_config(
            log_location=LogLocation.HYBRID,
            max_upward_search_depth=SearchDepth.SHALLOW,
        )

        # Act
        result = _resolve_log_root(bare_directory, config)  # noqa: SLF001

        # Assert
        assert result == bare_directory.resolve()

    def test_hybrid_fallback_emits_warning(self, tmp_path: Path) -> None:
        """HYBRID emits a warning when falling back to current directory."""
        # Arrange
        bare_directory = tmp_path / "no_markers"
        bare_directory.mkdir()
        config = make_global_config(
            log_location=LogLocation.HYBRID,
            max_upward_search_depth=SearchDepth.SHALLOW,
        )

        # Act
        _resolve_log_root(bare_directory, config)  # noqa: SLF001

        # Assert
        messages = DeferredLogBuffer._messages  # noqa: SLF001
        assert len(messages) >= 1
        assert any("current directory" in message for _, message in messages)
