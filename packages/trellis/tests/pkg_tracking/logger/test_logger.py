"""Tests for trellis.tracking.logger module.

Covers per-run timestamped log file creation, content matching
console format, and atomic write behavior.
"""

from __future__ import annotations

from pathlib import Path

from trellis.output.console import format_change_summary
from trellis.tracking.comparator import (
    ApiChange,
    ApiEntry,
    StructureChanges,
)
from trellis.tracking.logger import log_structure_changes

_PROJECT = "myproject"
_MAX_LINE_WIDTH = 100


def _make_changes(**overrides: object) -> StructureChanges:
    """Build a StructureChanges with sensible defaults."""
    defaults: dict[str, object] = {
        "api_changes": [],
        "new_api": [],
        "removed_api": [],
        "new_packages": [],
        "removed_packages": [],
        "new_modules": [],
        "removed_modules": [],
        "new_files": [],
        "removed_files": [],
        "has_changes": True,
    }
    defaults.update(overrides)
    return StructureChanges(**defaults)  # type: ignore[arg-type]


def _log_changes(tmp_path: Path, changes: StructureChanges) -> str:
    """Format changes and write to a log file."""
    # Return early when changes indicate nothing to log
    if not changes.has_changes:
        return log_structure_changes(str(tmp_path), "")
    content = format_change_summary(changes, _PROJECT, "", _MAX_LINE_WIDTH)
    return log_structure_changes(str(tmp_path), content)


# ---------------------------------------------------------------------------
# log_structure_changes
# ---------------------------------------------------------------------------


def test_log_creates_timestamped_file(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["utils.py"])

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    assert log_path != ""
    assert Path(log_path).exists()
    assert "trellis_" in Path(log_path).name


def test_log_returns_file_path(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["utils.py"])

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    assert str(tmp_path) in log_path
    assert log_path.endswith(".txt")


def test_log_returns_empty_string_for_no_changes(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(has_changes=False)

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    assert log_path == ""
    log_files = list(tmp_path.glob("trellis_*.txt"))
    assert log_files == []


def test_log_contains_api_changes_section(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[ApiChange("config.py", "def build() -> Config", "def build() -> Settings")],
    )

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "Updated API (1):" in content
    assert "config.py" in content
    assert ">>" in content


def test_log_contains_new_api_section(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(
        new_api=[ApiEntry("validators.py", "def validate(data: dict) -> bool  :10")],
    )

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "New API (1):" in content
    assert "validators.py:10" in content


def test_log_contains_removed_api_section(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(
        removed_api=[ApiEntry("utils.py", "def old_helper(x: int) -> str")],
    )

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "Removed API (1):" in content
    assert "utils.py" in content


def test_log_contains_new_modules_section(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["middleware/", "middleware/auth.py"])

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "New Modules (2):" in content
    assert "  middleware/" in content


def test_log_contains_removed_modules_section(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(removed_modules=["legacy/", "legacy/old.py"])

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "Removed Modules (2):" in content
    assert "  legacy/" in content


def test_log_omits_empty_sections(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["utils.py"])

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "Updated API" not in content
    assert "New API" not in content
    assert "Removed API" not in content
    assert "Removed Modules" not in content
    assert "New Modules (1):" in content


def test_log_matches_console_banner_format(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["utils.py"])

    # Act
    log_path = _log_changes(tmp_path, changes)

    # Assert
    content = Path(log_path).read_text(encoding="utf-8")
    assert "=" * _MAX_LINE_WIDTH in content
    assert "Structure Changes" in content
    assert f"Project:   {_PROJECT}" in content
    assert "Root:" not in content
    assert "Summary:" in content


def test_log_header_contains_log_path_when_provided(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["utils.py"])
    content = format_change_summary(changes, _PROJECT, "my_log.txt", _MAX_LINE_WIDTH)

    # Act
    log_path = log_structure_changes(str(tmp_path), content)

    # Assert
    file_content = Path(log_path).read_text(encoding="utf-8")
    assert "Log:" in file_content
    assert "my_log.txt" in file_content


def test_log_atomic_write_no_tmp_file_remains(tmp_path: Path) -> None:
    # Arrange
    changes = _make_changes(new_modules=["utils.py"])

    # Act
    _log_changes(tmp_path, changes)

    # Assert
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == []
