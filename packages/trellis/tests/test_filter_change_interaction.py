"""Tests for filter settings interaction with change detection (Category 8).

Verify that ignore filtering correctly suppresses additions and deletions
of filtered paths in change detection.
"""

from __future__ import annotations

import pytest

from trellis.config import Config, FilterSettings, build_tr_meta
from trellis.tracking.detector import (
    append_tr_meta,
    detect_structure_changes,
)
from trellis.core.filters import is_path_in_ignored_hierarchy


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


def _make_settings(**overrides: object) -> FilterSettings:
    """Build a FilterSettings with sensible defaults."""
    defaults: dict[str, object] = {
        "enable_ignore_dirs": False,
        "enable_ignore_files": False,
        "show_docs": True,
        "doc_extensions": frozenset({".md", ".txt", ".rst"}),
        "output_dir": "docs",
        "ignore_dirs": frozenset(),
        "ignore_files": frozenset(),
        "log_dir": "logs/structure_changes",
        "log_structure_changes": True,
        "log_config_only_changes": False,
    }
    defaults.update(overrides)
    return FilterSettings(**defaults)  # type: ignore[arg-type]


def _path_filter_with_settings(settings: FilterSettings):
    """Return a path_filter callable that uses the given settings."""
    def _filter(path: str, ancestry: list[str]) -> bool:
        return is_path_in_ignored_hierarchy(path, ancestry, settings)
    return _filter


# ---------------------------------------------------------------------------
# Test 8.1
# ---------------------------------------------------------------------------


def test_ignored_file_addition_not_detected_as_change() -> None:
    """Adding a file matching ignore patterns is invisible to detection."""
    settings = _make_settings(
        enable_ignore_files=True,
        ignore_files=frozenset({"conftest.py"}),
    )
    path_filter = _path_filter_with_settings(settings)

    old_tree = "myproject/\n└── main.py\n"
    old_content = append_tr_meta(old_tree, build_tr_meta())

    new_tree = "myproject/\n├── conftest.py\n└── main.py\n"

    added, deleted, has_changes = detect_structure_changes(
        new_tree, old_content, "myproject", path_filter, settings
    )

    assert has_changes is False
    assert added == []
    assert deleted == []


# ---------------------------------------------------------------------------
# Test 8.2
# ---------------------------------------------------------------------------


def test_ignored_directory_removal_not_detected_as_change() -> None:
    """Removing a user-configured ignored directory is invisible to detection."""
    settings = _make_settings(
        enable_ignore_dirs=True,
        ignore_dirs=frozenset({"build"}),
    )
    path_filter = _path_filter_with_settings(settings)

    old_tree = "myproject/\n├── build/\n└── src/\n"
    old_content = append_tr_meta(old_tree, build_tr_meta())

    new_tree = "myproject/\n└── src/\n"

    added, deleted, has_changes = detect_structure_changes(
        new_tree, old_content, "myproject", path_filter, settings
    )

    assert has_changes is False
    assert added == []
    assert deleted == []


def test_hard_ignored_directory_invisible_even_with_flags_off() -> None:
    """Hard-ignored dirs are filtered regardless of enable_ignore_dirs flag."""
    settings = _make_settings(
        enable_ignore_dirs=False,
        enable_ignore_files=False,
        ignore_dirs=frozenset(),
    )
    path_filter = _path_filter_with_settings(settings)

    old_tree = "myproject/\n├── __pycache__/\n└── src/\n"
    old_content = append_tr_meta(old_tree, build_tr_meta())

    new_tree = "myproject/\n└── src/\n"

    added, deleted, has_changes = detect_structure_changes(
        new_tree, old_content, "myproject", path_filter, settings
    )

    assert has_changes is False
    assert added == []
    assert deleted == []


# ---------------------------------------------------------------------------
# Test 8.3
# ---------------------------------------------------------------------------


def test_doc_file_change_ignored_when_show_docs_false() -> None:
    """Adding a doc file is invisible when show_docs=False."""
    settings = _make_settings(
        show_docs=False,
        doc_extensions=frozenset({".md"}),
    )
    path_filter = _path_filter_with_settings(settings)

    old_tree = "myproject/\n└── main.py\n"
    old_content = append_tr_meta(old_tree, build_tr_meta())

    new_tree = "myproject/\n├── README.md\n└── main.py\n"

    added, deleted, has_changes = detect_structure_changes(
        new_tree, old_content, "myproject", path_filter, settings
    )

    assert has_changes is False
    assert added == []
    assert deleted == []
