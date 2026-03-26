"""Tests for FileDiscoveryService file discovery with exclusion logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from scrutiny.execution.services import FileDiscoveryService
from conftest import make_global_config


# ── FileDiscoveryService.discover_files() ── #


@pytest.mark.unit
class TestFileDiscovery:
    """Test recursive Python file discovery with exclusions."""

    def test_discovers_python_files_in_directory(self, tmp_path: Path) -> None:
        """Verify .py files are found recursively."""
        # Arrange
        (tmp_path / "main.py").write_text("# main")
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "module.py").write_text("# module")

        config = make_global_config()

        # Act
        result = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert
        filenames = [path.name for path in result]
        assert "main.py" in filenames
        assert "module.py" in filenames

    def test_excludes_specified_directories(self, tmp_path: Path) -> None:
        """Verify excluded directories are skipped during traversal."""
        # Arrange
        included = tmp_path / "src"
        included.mkdir()
        (included / "app.py").write_text("# app")
        excluded = tmp_path / "__pycache__"
        excluded.mkdir()
        (excluded / "cached.py").write_text("# cached")

        config = make_global_config(exclude_dirs=("__pycache__",))

        # Act
        result = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert
        filenames = [path.name for path in result]
        assert "app.py" in filenames
        assert "cached.py" not in filenames

    def test_excludes_specified_files(self, tmp_path: Path) -> None:
        """Verify excluded file names are skipped during traversal."""
        # Arrange
        (tmp_path / "keep.py").write_text("# keep")
        (tmp_path / "conftest.py").write_text("# conftest")

        config = make_global_config(exclude_files=("conftest.py",))

        # Act
        result = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert
        filenames = [path.name for path in result]
        assert "keep.py" in filenames
        assert "conftest.py" not in filenames

    def test_directly_provided_files_bypass_exclusions(self, tmp_path: Path) -> None:
        """Verify files passed directly are included regardless of exclusions."""
        # Arrange
        target = tmp_path / "special.py"
        target.write_text("# special")

        config = make_global_config(exclude_files=("special.py",))

        # Act
        result = FileDiscoveryService.discover_files([target], config)

        # Assert
        assert len(result) == 1
        assert result[0].name == "special.py"

    def test_returns_empty_for_empty_directory(self, tmp_path: Path) -> None:
        """Verify empty list when directory contains no Python files."""
        config = make_global_config()
        result = FileDiscoveryService.discover_files([tmp_path], config)
        assert result == []

    def test_returns_sorted_deduplicated_results(self, tmp_path: Path) -> None:
        """Verify results are sorted and deduplicated."""
        # Arrange
        (tmp_path / "b.py").write_text("# b")
        (tmp_path / "a.py").write_text("# a")

        config = make_global_config()

        # Act — pass the directory twice to test deduplication.
        result = FileDiscoveryService.discover_files(
            [tmp_path, tmp_path],
            config,
        )

        # Assert
        filenames = [path.name for path in result]
        assert filenames == sorted(filenames)
        assert len(filenames) == len(set(filenames))

    def test_ignores_non_python_files(self, tmp_path: Path) -> None:
        """Verify non-.py files are skipped."""
        # Arrange
        (tmp_path / "readme.md").write_text("# readme")
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "script.py").write_text("# script")

        config = make_global_config()

        # Act
        result = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert
        assert len(result) == 1
        assert result[0].name == "script.py"
