"""Tests for the change logging lifecycle across multiple generate runs.

Covers the end-to-end interaction between change detection
(``change_detector``) and change logging (``change_logger``), verifying
correct behavior across first runs, repeated runs with changes, runs
with identical structures, and duplicate entry prevention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trellis.config import FilterSettings, build_tr_meta
from trellis.tracking.comparator import (
    StructureChanges,
    compare_structure_elements,
)
from trellis.tracking.detector import (
    analyze_structure_elements,
    append_tr_meta,
    detect_structure_changes,
    split_tree_and_meta,
)
from trellis.tracking.logger import log_structure_changes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: object) -> FilterSettings:
    """Build a FilterSettings with sensible defaults for lifecycle tests."""
    defaults: dict[str, object] = {
        "enable_ignore_dirs": False,
        "enable_ignore_files": False,
        "show_docs": True,
        "doc_extensions": frozenset({".md"}),
        "output_dir": "docs",
        "ignore_dirs": frozenset(),
        "ignore_files": frozenset(),
        "log_dir": "logs/structure_changes",
        "log_structure_changes": True,
        "log_config_only_changes": False,
    }
    defaults.update(overrides)
    return FilterSettings(**defaults)  # type: ignore[arg-type]


def _no_filter(path: str, ancestry: list[str]) -> bool:
    """Path filter that never excludes anything."""
    return False


def _build_tree(*file_names: str, project: str = "myproject") -> str:
    """Build a minimal tree structure text from file names.

    Parameters
    ----------
    *file_names : str
        File names to include at the top level.
    project : str
        Project root name.

    Returns
    -------
    str
        A tree-formatted string with connectors.
    """
    lines = [f"{project}/"]
    for index, name in enumerate(sorted(file_names)):
        connector = "└── " if index == len(file_names) - 1 else "├── "
        lines.append(f"{connector}{name}")
    return "\n".join(lines) + "\n"


class _RunResult:
    """Lightweight result from a simulated generate run."""

    def __init__(self, has_changes: bool, change_entries: list[str]) -> None:
        self.has_changes = has_changes
        self.change_entries = change_entries


def _simulate_generate_run(
    output_path: Path,
    logs_dir: Path,
    tree_content: str,
    project_name: str,
) -> tuple[_RunResult, StructureChanges | None]:
    """Simulate what ``save_structure`` does for a single run.

    Parameters
    ----------
    output_path : Path
        Path to the structure output file.
    logs_dir : Path
        Directory for change log files.
    tree_content : str
        The tree content (without tr_meta) for this run.
    project_name : str
        Name of the project.

    Returns
    -------
    tuple[_RunResult, StructureChanges | None]
        The path-level change result and element-level changes.
    """
    from trellis.output.console import format_change_summary

    new_content = append_tr_meta(tree_content, build_tr_meta())

    if not output_path.exists():
        output_path.write_text(new_content, encoding="utf-8")
        return _RunResult(has_changes=False, change_entries=[]), None

    old_content = output_path.read_text(encoding="utf-8")

    # Path-level detection.
    added, deleted, has_changes = detect_structure_changes(
        tree_content, old_content, project_name, _no_filter, _make_settings()
    )

    change_entries = [f"+ {p} added" for p in added] + [f"- {p} deleted" for p in deleted]

    # Element-level detection.
    old_tree, _, _ = split_tree_and_meta(old_content, project_name)
    old_elements = analyze_structure_elements(old_tree)
    new_elements = analyze_structure_elements(tree_content)
    structure_changes = compare_structure_elements(
        old_elements, new_elements, added, deleted
    )

    output_path.write_text(new_content, encoding="utf-8")

    if structure_changes.has_changes:
        content = format_change_summary(
            structure_changes, project_name, "", 100
        )
        log_structure_changes(str(logs_dir), content)

    return _RunResult(has_changes=has_changes, change_entries=change_entries), structure_changes


# ---------------------------------------------------------------------------
# Gap 1: First run produces no log file
# ---------------------------------------------------------------------------


class TestFirstRunNoLogFile:
    """When the output structure file does not exist yet (first run),

    generate writes the file and returns without creating a log file.
    """

    def test_first_run_writes_structure_file(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        tree = _build_tree("main.py", "utils.py")

        _simulate_generate_run(output_path, logs_dir, tree, "myproject")

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "main.py" in content

    def test_first_run_creates_no_log_files(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        tree = _build_tree("main.py", "utils.py")

        _simulate_generate_run(output_path, logs_dir, tree, "myproject")

        log_files = list(logs_dir.glob("trellis_*.txt"))
        assert log_files == [], "First run should not create any log files"

    def test_first_run_returns_no_changes(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        tree = _build_tree("main.py")

        result, structure_changes = _simulate_generate_run(
            output_path, logs_dir, tree, "myproject"
        )

        assert result.has_changes is False
        assert result.change_entries == []
        assert structure_changes is None


# ---------------------------------------------------------------------------
# Gap 2: Second run detects and logs changes
# ---------------------------------------------------------------------------


class TestSecondRunDetectsChanges:
    """When the structure file already exists and the structure has changed,

    generate detects the diff and writes log entries.
    """

    def test_added_file_is_logged(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        tree_v1 = _build_tree("main.py")
        _simulate_generate_run(output_path, logs_dir, tree_v1, "myproject")

        tree_v2 = _build_tree("main.py", "utils.py")
        result, structure_changes = _simulate_generate_run(
            output_path, logs_dir, tree_v2, "myproject"
        )

        assert result.has_changes is True
        assert any("utils.py" in entry for entry in result.change_entries)

        log_files = list(logs_dir.glob("trellis_*.txt"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text(encoding="utf-8")
        assert "utils.py" in log_content

    def test_deleted_file_is_logged(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        tree_v1 = _build_tree("main.py", "utils.py")
        _simulate_generate_run(output_path, logs_dir, tree_v1, "myproject")

        tree_v2 = _build_tree("main.py")
        result, structure_changes = _simulate_generate_run(
            output_path, logs_dir, tree_v2, "myproject"
        )

        assert result.has_changes is True
        assert any("utils.py" in entry for entry in result.change_entries)

        log_files = list(logs_dir.glob("trellis_*.txt"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text(encoding="utf-8")
        assert "utils.py" in log_content

    def test_mixed_adds_and_deletes_logged(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        tree_v1 = _build_tree("alpha.py", "beta.py")
        _simulate_generate_run(output_path, logs_dir, tree_v1, "myproject")

        tree_v2 = _build_tree("beta.py", "gamma.py")
        result, structure_changes = _simulate_generate_run(
            output_path, logs_dir, tree_v2, "myproject"
        )

        assert result.has_changes is True
        log_files = list(logs_dir.glob("trellis_*.txt"))
        assert len(log_files) == 1
        log_content = log_files[0].read_text(encoding="utf-8")
        assert "gamma.py" in log_content
        assert "alpha.py" in log_content


# ---------------------------------------------------------------------------
# Gap 3: No new log when structure is unchanged
# ---------------------------------------------------------------------------


class TestNoLogWhenNoChanges:
    """A second run with identical structure produces no log entries and

    no new log file content.
    """

    def test_identical_structure_produces_no_log_file(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        tree = _build_tree("main.py", "utils.py")

        # Run 1: first run.
        _simulate_generate_run(output_path, logs_dir, tree, "myproject")

        # Run 2: identical structure.
        result, structure_changes = _simulate_generate_run(
            output_path, logs_dir, tree, "myproject"
        )

        assert result.has_changes is False
        assert result.change_entries == []

        log_files = list(logs_dir.glob("trellis_*.txt"))
        assert log_files == [], (
            "No log file should be created when structure is unchanged"
        )

    def test_no_changes_after_previous_changes_preserves_log_count(
        self, tmp_path: Path
    ) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # Run 1: initial.
        tree_v1 = _build_tree("main.py")
        _simulate_generate_run(output_path, logs_dir, tree_v1, "myproject")

        # Run 2: add a file (creates log).
        tree_v2 = _build_tree("main.py", "utils.py")
        _simulate_generate_run(output_path, logs_dir, tree_v2, "myproject")

        log_count_after_change = len(list(logs_dir.glob("trellis_*.txt")))
        assert log_count_after_change == 1

        # Run 3: identical to v2 -- no new changes.
        result, _ = _simulate_generate_run(
            output_path, logs_dir, tree_v2, "myproject"
        )

        assert result.has_changes is False
        log_count_after_no_change = len(list(logs_dir.glob("trellis_*.txt")))
        assert log_count_after_no_change == log_count_after_change

    def test_detect_structure_changes_returns_empty_for_identical(self) -> None:
        """Direct test of detect_structure_changes with identical content."""
        tree = _build_tree("main.py", "utils.py")
        old_content = append_tr_meta(tree, build_tr_meta())

        added, deleted, has_changes = detect_structure_changes(
            tree, old_content, "myproject", _no_filter, _make_settings()
        )

        assert has_changes is False
        assert added == []
        assert deleted == []


# ---------------------------------------------------------------------------
# Gap 4: Multiple runs produce separate per-run log files
# ---------------------------------------------------------------------------


class TestMultipleRunsAccumulate:
    """Multiple runs with different changes produce separate per-run log files."""

    def test_three_changes_produce_three_log_files(self, tmp_path: Path) -> None:
        output_path = tmp_path / "docs" / "mytrellis.txt"
        output_path.parent.mkdir(parents=True)
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # Run 1: initial (no log).
        tree_v1 = _build_tree("main.py")
        _simulate_generate_run(output_path, logs_dir, tree_v1, "myproject")

        # Run 2: add utils.py.
        import time

        tree_v2 = _build_tree("main.py", "utils.py")
        _simulate_generate_run(output_path, logs_dir, tree_v2, "myproject")
        time.sleep(1.1)  # ensure distinct timestamps

        # Run 3: add config.py.
        tree_v3 = _build_tree("main.py", "utils.py", "config.py")
        _simulate_generate_run(output_path, logs_dir, tree_v3, "myproject")
        time.sleep(1.1)

        # Run 4: remove main.py.
        tree_v4 = _build_tree("utils.py", "config.py")
        _simulate_generate_run(output_path, logs_dir, tree_v4, "myproject")

        log_files = list(logs_dir.glob("trellis_*.txt"))
        assert len(log_files) == 3

        # Collect all log content.
        all_content = "\n".join(
            f.read_text(encoding="utf-8") for f in log_files
        )
        assert "utils.py" in all_content
        assert "config.py" in all_content
        assert "main.py" in all_content
