"""Tests for config-aware change detection run-to-run (Category 3).

Verify that config changes between runs are correctly distinguished from
structural changes, and that LOG_CONFIG_ONLY_CHANGES controls whether
config-triggered diffs are logged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from trellis.config import (
    Config,
    build_tr_meta,
)
from trellis.core.persistence import (
    _resolve_with_elements,
    prepare_tree_content,
)
from trellis.main import DirectoryStructure
from trellis.tracking.comparator import StructureChanges
from trellis.tracking.detector import (
    append_tr_meta,
)


def _prepare(ds: DirectoryStructure) -> str:
    """Prepare tree content from a scanned DirectoryStructure."""
    return prepare_tree_content(ds.project_name, ds.structure)


def _resolve(
    ds: DirectoryStructure, tree_content: str, old_content: str
) -> Optional[StructureChanges]:
    """Resolve changes using the persistence-layer function.

    Parameters
    ----------
    ds : DirectoryStructure
        Scanner instance with current scan state.
    tree_content : str
        Current tree content string.
    old_content : str
        Previous tree content string to compare against.

    Returns
    -------
    Optional[StructureChanges]
        Detected changes, or None when changes are suppressed.
    """
    return _resolve_with_elements(
        tree_content,
        old_content,
        ds._filter_settings,
        ds._scanned_paths,
        ds._path_hierarchy,
        ds.project_name,
        ds._tr_meta,
    )


# ---------------------------------------------------------------------------
# Config-only change suppression
# ---------------------------------------------------------------------------


def test_config_change_only_suppressed_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "LOG_CONFIG_ONLY_CHANGES", False)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    ds1 = DirectoryStructure(str(tmp_path))
    ds1.scan_directory(str(tmp_path))
    tree_content_v1 = _prepare(ds1)
    old_content = append_tr_meta(tree_content_v1, build_tr_meta())
    monkeypatch.setattr(Config, "SHOW_DOCS", False)
    ds2 = DirectoryStructure(str(tmp_path))
    ds2.scan_directory(str(tmp_path))
    tree_content_v2 = _prepare(ds2)

    # Act
    result = _resolve(ds2, tree_content_v2, old_content)

    # Assert
    assert result is None


# ---------------------------------------------------------------------------
# Config change logged when enabled
# ---------------------------------------------------------------------------


def test_config_change_logged_when_log_config_only_changes_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "LOG_CONFIG_ONLY_CHANGES", True)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    ds1 = DirectoryStructure(str(tmp_path))
    ds1.scan_directory(str(tmp_path))
    tree_content_v1 = _prepare(ds1)
    old_content = append_tr_meta(tree_content_v1, build_tr_meta())
    monkeypatch.setattr(Config, "SHOW_DOCS", False)
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")
    ds2 = DirectoryStructure(str(tmp_path))
    ds2.scan_directory(str(tmp_path))
    tree_content_v2 = _prepare(ds2)

    # Act
    result = _resolve(ds2, tree_content_v2, old_content)

    # Assert
    assert result is not None
    assert result.has_changes is True


# ---------------------------------------------------------------------------
# Combined config + structural change suppression
# ---------------------------------------------------------------------------


def test_config_change_plus_structure_change_detects_structural_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "LOG_CONFIG_ONLY_CHANGES", False)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    ds1 = DirectoryStructure(str(tmp_path), show_types=True)
    ds1.scan_directory(str(tmp_path))
    tree_content_v1 = _prepare(ds1)
    old_content = append_tr_meta(tree_content_v1, build_tr_meta(show_types=True))
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")
    ds2 = DirectoryStructure(str(tmp_path), show_types=False)
    ds2.scan_directory(str(tmp_path))
    tree_content_v2 = _prepare(ds2)

    # Act
    result = _resolve(ds2, tree_content_v2, old_content)

    # Assert — structural changes are no longer suppressed when config also changed
    assert result is not None
    assert result.has_changes is True


# ---------------------------------------------------------------------------
# Normal run-to-run with no config change
# ---------------------------------------------------------------------------


def test_meta_status_valid_no_suppression(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    ds1 = DirectoryStructure(str(tmp_path))
    ds1.scan_directory(str(tmp_path))
    tree_content_v1 = _prepare(ds1)
    old_content = append_tr_meta(tree_content_v1, build_tr_meta())
    ds2 = DirectoryStructure(str(tmp_path))
    ds2.scan_directory(str(tmp_path))
    tree_content_v2 = _prepare(ds2)

    # Act
    result = _resolve(ds2, tree_content_v2, old_content)

    # Assert
    assert result is not None
    assert result.has_changes is False
