"""Tests for per-run log file behavior (Category 6).

Verify that per-run timestamped log files are correctly created,
each run produces its own file, and the content is well-formed.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from trellis.config import Config, FilterSettings, build_tr_meta
from trellis.tracking.comparator import (
    ApiChange,
    ApiEntry,
    StructureChanges,
)
from trellis.output.console import format_change_summary
from trellis.tracking.detector import append_tr_meta
from trellis.tracking.logger import log_structure_changes


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


# ---------------------------------------------------------------------------
# Test 6.1: Each run produces a separate log file
# ---------------------------------------------------------------------------


def test_separate_runs_produce_separate_log_files(tmp_path: Path) -> None:
    """Two runs with changes produce two separate timestamped log files."""
    changes1 = _make_changes(new_modules=["alpha.py"])
    changes2 = _make_changes(new_modules=["beta.py"])

    content1 = format_change_summary(changes1, "proj", "", 100)
    content2 = format_change_summary(changes2, "proj", "", 100)
    log_structure_changes(str(tmp_path), content1)
    time.sleep(1.1)  # ensure distinct timestamps
    log_structure_changes(str(tmp_path), content2)

    log_files = list(tmp_path.glob("trellis_*.txt"))
    assert len(log_files) == 2

    contents = [f.read_text(encoding="utf-8") for f in sorted(log_files)]
    assert "alpha.py" in contents[0]
    assert "beta.py" in contents[1]


# ---------------------------------------------------------------------------
# Test 6.2: No log file when no changes
# ---------------------------------------------------------------------------


def test_no_log_file_when_no_changes(tmp_path: Path) -> None:
    """No log file is created when has_changes is False."""
    changes = _make_changes(has_changes=False)

    # When there are no changes, the caller should not write a log.
    result = log_structure_changes(str(tmp_path), "")

    assert result == ""
    log_files = list(tmp_path.glob("trellis_*.txt"))
    assert log_files == []


# ---------------------------------------------------------------------------
# Test 6.3: Log file content is well-formed
# ---------------------------------------------------------------------------


def test_log_file_is_well_formed(tmp_path: Path) -> None:
    """Every non-blank line in the log should be a header, section label, or entry."""
    changes = _make_changes(
        api_changes=[ApiChange("config.py", "def build() -> Config", "def build() -> Settings")],
        new_api=[ApiEntry("validators.py", "def validate(data: dict) -> bool")],
        removed_api=[ApiEntry("utils.py", "def old_helper(x: int) -> str")],
        new_modules=["middleware/"],
        removed_modules=["legacy/"],
    )

    formatted = format_change_summary(changes, "proj", "", 100)
    log_path = log_structure_changes(str(tmp_path), formatted)

    content = Path(log_path).read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        is_banner = stripped.startswith("=")
        is_header = stripped.startswith("Structure Changes")
        is_meta = stripped.startswith(("Project:", "Log:", "Summary:"))
        is_section = stripped.endswith(":")
        is_indented = line.startswith("  ")  # entries, file groups, details
        assert is_banner or is_header or is_meta or is_section or is_indented, (
            f"Unexpected line in log file: {stripped!r}"
        )


# ---------------------------------------------------------------------------
# Test 6.4: Multiple changes in one run are all captured
# ---------------------------------------------------------------------------


def test_all_change_types_captured_in_single_log(tmp_path: Path) -> None:
    """A single run with mixed change types produces one file with all sections."""
    changes = _make_changes(
        api_changes=[ApiChange("handler.py", "def run()", "def run(limit: int)")],
        new_api=[ApiEntry("new_mod.py", "def new_func()")],
        removed_api=[ApiEntry("old_mod.py", "def old_func()")],
        new_modules=["pkg/"],
        removed_modules=["dead/"],
    )

    formatted = format_change_summary(changes, "proj", "", 100)
    log_path = log_structure_changes(str(tmp_path), formatted)

    content = Path(log_path).read_text(encoding="utf-8")
    assert "Updated API (1):" in content
    assert "New API (1):" in content
    assert "Removed API (1):" in content
    assert "New Modules (1):" in content
    assert "Removed Modules (1):" in content


# ---------------------------------------------------------------------------
# Test 6.5: Log filename contains timestamp
# ---------------------------------------------------------------------------


def test_log_filename_has_timestamp_format(tmp_path: Path) -> None:
    """Log filename follows trellis_YYYYMMDD_HHMMSS.txt pattern."""
    import re

    changes = _make_changes(new_modules=["utils.py"])

    formatted = format_change_summary(changes, "proj", "", 100)
    log_path = log_structure_changes(str(tmp_path), formatted)

    filename = Path(log_path).name
    assert re.match(r"trellis_\d{8}_\d{6}\.txt$", filename)
