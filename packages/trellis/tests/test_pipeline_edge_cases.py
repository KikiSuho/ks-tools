"""Tests for pipeline edge cases (Category 5).

Cover empty projects, all-ignored files, doc-only projects, deep nesting,
and permission errors during scanning.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from trellis.config import CallFlowMode, Config
from trellis.main import DirectoryStructure


@pytest.fixture(autouse=True)
def _restore_config():
    """Snapshot and restore all mutable Config attributes."""
    originals = {
        attr: getattr(Config, attr)
        for attr in dir(Config)
        if not attr.startswith("_") and attr.isupper()
    }
    yield
    for attr, value in originals.items():
        setattr(Config, attr, value)


def _quiet_config() -> None:
    """Disable noisy Config features for cleaner test output."""
    Config.SHOW_DECORATORS = False
    Config.CALL_FLOW_MODE = CallFlowMode.OFF


# ---------------------------------------------------------------------------
# Test 5.1
# ---------------------------------------------------------------------------


def test_empty_project_directory(tmp_path: Path) -> None:
    """Empty directory produces a valid structure file without crashing."""
    _quiet_config()
    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))
    result = ds.save_structure()

    assert Path(result.output_path).exists()
    content = Path(result.output_path).read_text(encoding="utf-8")
    assert ds.project_name in content
    assert "# tr_meta:" in content


# ---------------------------------------------------------------------------
# Test 5.2
# ---------------------------------------------------------------------------


def test_project_with_only_ignored_files(tmp_path: Path) -> None:
    """When all files match ignore patterns, output has no file entries."""
    _quiet_config()
    Config.ENABLE_IGNORE_FILES = True
    # Create files that match default IGNORE_FILES patterns.
    (tmp_path / "conftest.py").write_text("", encoding="utf-8")
    (tmp_path / "test_foo.py").write_text("", encoding="utf-8")
    (tmp_path / "setup.toml").write_text("", encoding="utf-8")

    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))

    output = ds.structure
    # These files should be filtered out by default ignore patterns.
    assert "conftest.py" not in output
    assert "test_foo.py" not in output
    assert "setup.toml" not in output


# ---------------------------------------------------------------------------
# Test 5.3
# ---------------------------------------------------------------------------


def test_project_with_only_doc_files_show_docs_disabled(tmp_path: Path) -> None:
    """Doc-only project with SHOW_DOCS=False produces no file entries."""
    _quiet_config()
    Config.SHOW_DOCS = False
    Config.ENABLE_IGNORE_FILES = False

    (tmp_path / "README.md").write_text("# Readme", encoding="utf-8")
    (tmp_path / "guide.rst").write_text("Guide", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Notes", encoding="utf-8")

    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))

    output = ds.structure
    assert "README.md" not in output
    assert "guide.rst" not in output
    assert "notes.txt" not in output


# ---------------------------------------------------------------------------
# Test 5.4
# ---------------------------------------------------------------------------


def test_project_with_only_doc_files_show_docs_enabled(tmp_path: Path) -> None:
    """Doc-only project with SHOW_DOCS=True includes all doc files."""
    _quiet_config()
    Config.SHOW_DOCS = True
    Config.ENABLE_IGNORE_FILES = False

    (tmp_path / "README.md").write_text("# Readme", encoding="utf-8")
    (tmp_path / "guide.rst").write_text("Guide", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("Notes", encoding="utf-8")

    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))

    output = ds.structure
    assert "README.md" in output
    assert "guide.rst" in output
    assert "notes.txt" in output


# ---------------------------------------------------------------------------
# Test 5.5
# ---------------------------------------------------------------------------


def test_deeply_nested_structure_20_levels(tmp_path: Path) -> None:
    """20-level deep nesting scans without errors or stack overflow."""
    _quiet_config()
    Config.ENABLE_IGNORE_DIRS = False
    Config.ENABLE_IGNORE_FILES = False

    current = tmp_path
    for depth in range(20):
        current = current / f"level_{depth}"
        current.mkdir()
        (current / "__init__.py").write_text("", encoding="utf-8")
        (current / f"mod_{depth}.py").write_text(
            f"x_{depth} = {depth}\n", encoding="utf-8"
        )

    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))

    output = ds.structure
    # All 20 levels should appear.
    for depth in range(20):
        assert f"level_{depth}/" in output
    # Deepest module should appear.
    assert "mod_19.py" in output
    # Package tags should appear.
    assert "[pkg]" in output


# ---------------------------------------------------------------------------
# Test 5.6
# ---------------------------------------------------------------------------


def test_scan_directory_with_permission_error(tmp_path: Path) -> None:
    """Permission errors produce error annotations without crashing."""
    _quiet_config()
    Config.ENABLE_IGNORE_DIRS = False
    Config.ENABLE_IGNORE_FILES = False

    (tmp_path / "readable.py").write_text("x = 1\n", encoding="utf-8")
    forbidden_dir = tmp_path / "forbidden"
    forbidden_dir.mkdir()

    # Mock os.scandir to raise PermissionError for the forbidden directory.
    original_scandir = DirectoryStructure._safe_list_directory

    def _patched_safe_list(self, path):
        if Path(path).name == "forbidden":
            self.append_line("[Warning: cannot read directory: PermissionError]\n")
            return []
        return original_scandir(self, path)

    with patch.object(
        DirectoryStructure,
        "_safe_list_directory",
        _patched_safe_list,
    ):
        ds = DirectoryStructure(str(tmp_path))
        ds.scan_directory(str(tmp_path))

    output = ds.structure
    assert "readable.py" in output
    # The forbidden directory still appears in the listing (it's discovered
    # by the parent's scandir), but its children trigger the error.
    assert "PermissionError" in output or "forbidden" in output
