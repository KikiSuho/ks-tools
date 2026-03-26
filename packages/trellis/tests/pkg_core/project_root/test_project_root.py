"""Tests for trellis.core.project_root module.

Covers find_project_root discovery, marker validation, depth limiting,
preference ordering, and symlink handling.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trellis.core.project_root import (
    DEFAULT_MARKERS,
    find_project_root,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_default_markers_combines_vcs_and_config() -> None:
    # Arrange
    expected_first = ".git"
    expected_config = "pyproject.toml"

    # Act
    markers = DEFAULT_MARKERS

    # Assert
    assert expected_first in markers
    assert expected_config in markers


# ---------------------------------------------------------------------------
# find_project_root — basic behavior
# ---------------------------------------------------------------------------


def test_finds_root_with_marker_file(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "pyproject.toml").touch()

    # Act
    result = find_project_root(start_path=tmp_path, markers=["pyproject.toml"])

    # Assert
    assert result == tmp_path


def test_finds_root_with_marker_directory(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()

    # Act
    result = find_project_root(start_path=tmp_path, markers=[".git"])

    # Assert
    assert result == tmp_path


def test_walks_up_to_parent(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()
    child_dir = tmp_path / "src" / "pkg"
    child_dir.mkdir(parents=True)

    # Act
    result = find_project_root(start_path=child_dir, markers=[".git"])

    # Assert
    assert result == tmp_path


def test_returns_none_when_no_marker_found(tmp_path: Path) -> None:
    # Arrange
    child_dir = tmp_path / "deep" / "nested"
    child_dir.mkdir(parents=True)

    # Act
    result = find_project_root(
        start_path=child_dir, markers=["nonexistent_marker"], max_depth=2
    )

    # Assert
    assert result is None


def test_starts_from_file_parent(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()
    test_file = tmp_path / "script.py"
    test_file.touch()

    # Act
    result = find_project_root(start_path=test_file, markers=[".git"])

    # Assert
    assert result == tmp_path


def test_respects_max_depth(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()
    deep_dir = tmp_path / "a" / "b" / "c"
    deep_dir.mkdir(parents=True)

    # Act
    result = find_project_root(start_path=deep_dir, markers=[".git"], max_depth=2)

    # Assert
    assert result is None


def test_max_depth_of_one_checks_start_only(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()

    # Act
    result = find_project_root(start_path=tmp_path, markers=[".git"], max_depth=1)

    # Assert
    assert result == tmp_path


def test_start_path_none_uses_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    # Act
    result = find_project_root(start_path=None, markers=[".git"])

    # Assert
    assert result == tmp_path


def test_follow_symlinks_resolves_marker(tmp_path: Path) -> None:
    # Arrange
    real_git = tmp_path / "real_git"
    real_git.mkdir()
    # Skip when OS does not support symlinks without elevation
    try:
        # Create a symlink marker to test follow_symlinks resolution
        (tmp_path / ".git").symlink_to(real_git)
    except OSError:
        # Abort test on platforms that require elevated privileges for symlinks
        pytest.skip("symlinks require elevated privileges on this platform")

    # Act
    result = find_project_root(
        start_path=tmp_path, markers=[".git"], follow_symlinks=True
    )

    # Assert
    assert result == tmp_path


# ---------------------------------------------------------------------------
# find_project_root — marker checking order
# ---------------------------------------------------------------------------


def test_first_marker_wins_at_same_level(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").touch()

    # Act
    result = find_project_root(
        start_path=tmp_path, markers=[".git", "pyproject.toml"]
    )

    # Assert
    assert result == tmp_path


# ---------------------------------------------------------------------------
# find_project_root — preference ordering
# ---------------------------------------------------------------------------


def test_preference_vcs_reorders_markers(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / ".git").mkdir()

    # Act
    result = find_project_root(
        start_path=tmp_path,
        markers=["pyproject.toml", ".git"],
        preference="vcs",
    )

    # Assert
    assert result == tmp_path


def test_preference_config_reorders_markers(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "pyproject.toml").touch()

    # Act
    result = find_project_root(
        start_path=tmp_path,
        markers=[".git", "pyproject.toml"],
        preference="config",
    )

    # Assert
    assert result == tmp_path


# ---------------------------------------------------------------------------
# find_project_root — validation errors
# ---------------------------------------------------------------------------


def test_invalid_preference_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="Invalid preference"):
        find_project_root(preference="invalid")  # type: ignore[arg-type]


def test_max_depth_zero_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="max_depth must be at least 1"):
        find_project_root(max_depth=0)


def test_max_depth_bool_raises_type_error() -> None:
    # Act / Assert
    with pytest.raises(TypeError, match="max_depth must be an integer"):
        find_project_root(max_depth=True)  # type: ignore[arg-type]


def test_markers_string_raises_type_error() -> None:
    # Act / Assert
    with pytest.raises(TypeError, match="markers must be a list, tuple, or None"):
        find_project_root(markers=".git")  # type: ignore[arg-type]


def test_markers_empty_list_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="markers must not be empty"):
        find_project_root(markers=[])


def test_markers_with_empty_string_raises_value_error() -> None:
    # Act / Assert
    with pytest.raises(ValueError, match="whitespace-only"):
        find_project_root(markers=["  "])


def test_markers_with_non_string_raises_type_error() -> None:
    # Act / Assert
    with pytest.raises(TypeError, match="markers must contain only strings"):
        find_project_root(markers=[123])  # type: ignore[list-item]


