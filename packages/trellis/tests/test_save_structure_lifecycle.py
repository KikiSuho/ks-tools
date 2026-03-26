"""Tests for save_structure end-to-end lifecycle (Category 7).

Verify the full save_structure path including first-run, second-run with
changes, no-change runs, custom output dirs, and file overwrite behavior.
"""

from __future__ import annotations

from pathlib import Path

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
    Config.ENABLE_IGNORE_DIRS = False
    Config.ENABLE_IGNORE_FILES = False


# ---------------------------------------------------------------------------
# Test 7.1
# ---------------------------------------------------------------------------


def test_save_structure_first_run_no_prior_file(tmp_path: Path) -> None:
    """First run creates output file with tr_meta, no log file."""
    _quiet_config()
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))
    result = ds.save_structure()

    assert Path(result.output_path).exists()
    content = Path(result.output_path).read_text(encoding="utf-8")
    assert "# tr_meta:" in content

    logs_dir = Path(tmp_path) / Config.LOG_DIR
    log_files = list(logs_dir.glob("trellis_*.txt"))
    assert log_files == []


# ---------------------------------------------------------------------------
# Test 7.2
# ---------------------------------------------------------------------------


def test_save_structure_second_run_with_file_added(tmp_path: Path) -> None:
    """Adding a file between runs detects the change in SaveResult."""
    _quiet_config()
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

    ds1 = DirectoryStructure(str(tmp_path))
    ds1.scan_directory(str(tmp_path))
    ds1.save_structure()

    # Add a new file.
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")

    ds2 = DirectoryStructure(str(tmp_path))
    ds2.scan_directory(str(tmp_path))
    result = ds2.save_structure()

    # save_structure detects changes; log writing is the caller's job.
    assert result.changes is not None
    assert result.changes.has_changes is True
    assert result.logs_dir != ""


# ---------------------------------------------------------------------------
# Test 7.3
# ---------------------------------------------------------------------------


def test_save_structure_second_run_no_changes(tmp_path: Path) -> None:
    """Identical runs produce no changes on second pass.

    Uses the simulation helper to avoid side effects from save_structure
    creating output directories within the scanned path.
    """
    from trellis.tracking.detector import (
        append_tr_meta,
        detect_structure_changes,
    )
    from trellis.config import FilterSettings, build_tr_meta

    def _make_settings_local() -> FilterSettings:
        return FilterSettings(
            enable_ignore_dirs=False, enable_ignore_files=False,
            show_docs=True, doc_extensions=frozenset({".md"}),
            output_dir="docs", ignore_dirs=frozenset(),
            ignore_files=frozenset(), log_dir="logs/structure_changes",
            log_structure_changes=True, log_config_only_changes=False,
        )

    def _no_filter(path: str, ancestry: list[str]) -> bool:
        return False

    output_path = tmp_path / "docs" / "proj_structure.txt"
    output_path.parent.mkdir(parents=True)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    tree = "proj/\n└── main.py\n"
    new_content = append_tr_meta(tree, build_tr_meta())

    # Run 1: first run.
    output_path.write_text(new_content, encoding="utf-8")

    # Run 2: identical structure.
    old_content = output_path.read_text(encoding="utf-8")
    added, deleted, has_changes = detect_structure_changes(
        tree, old_content, "proj", _no_filter, _make_settings_local()
    )

    assert has_changes is False
    assert added == []
    assert deleted == []

    log_files = list(logs_dir.glob("trellis_*.txt"))
    assert log_files == []


# ---------------------------------------------------------------------------
# Test 7.4
# ---------------------------------------------------------------------------


def test_save_structure_uses_config_output_dir_and_log_dir(
    tmp_path: Path,
) -> None:
    """Custom OUTPUT_DIR and LOG_DIR are respected."""
    _quiet_config()
    Config.OUTPUT_DIR = "custom_docs"
    Config.LOG_DIR = "custom_logs"

    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))
    result = ds.save_structure()

    assert "custom_docs" in result.output_path
    assert (tmp_path / "custom_docs").is_dir()
    assert (tmp_path / "custom_logs").is_dir()


# ---------------------------------------------------------------------------
# Test 7.5
# ---------------------------------------------------------------------------


def test_save_structure_overwrites_existing_file_completely(
    tmp_path: Path,
) -> None:
    """Structure file is fully overwritten, not appended."""
    _quiet_config()
    # Run 1: three files.
    (tmp_path / "alpha.py").write_text("a = 1\n", encoding="utf-8")
    (tmp_path / "beta.py").write_text("b = 2\n", encoding="utf-8")
    (tmp_path / "gamma.py").write_text("g = 3\n", encoding="utf-8")

    ds1 = DirectoryStructure(str(tmp_path))
    ds1.scan_directory(str(tmp_path))
    result1 = ds1.save_structure()

    # Remove two files.
    (tmp_path / "beta.py").unlink()
    (tmp_path / "gamma.py").unlink()

    # Run 2: only alpha.py remains.
    ds2 = DirectoryStructure(str(tmp_path))
    ds2.scan_directory(str(tmp_path))
    ds2.save_structure()

    content = Path(result1.output_path).read_text(encoding="utf-8")
    assert "alpha.py" in content
    assert "beta.py" not in content
    assert "gamma.py" not in content
