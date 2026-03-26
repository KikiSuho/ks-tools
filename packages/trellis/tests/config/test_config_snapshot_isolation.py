"""Tests for Config snapshot isolation (Category 1).

Verify that FilterSettings and RenderSettings are true frozen snapshots --
mutating Config after snapshot creation has no effect on the frozen copy,
and build_tr_meta() reads live Config (not from any snapshot).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trellis.config import Config, build_filter_settings, build_tr_meta
from trellis.main import DirectoryStructure
from trellis.pyast.renderer import build_render_settings


# ---------------------------------------------------------------------------
# FilterSettings frozen after mutation
# ---------------------------------------------------------------------------


def test_filter_settings_frozen_after_config_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    original_show_docs = Config.SHOW_DOCS
    snapshot = build_filter_settings()

    # Act
    monkeypatch.setattr(Config, "SHOW_DOCS", not original_show_docs)

    # Assert
    assert snapshot.show_docs == original_show_docs


# ---------------------------------------------------------------------------
# RenderSettings frozen after mutation
# ---------------------------------------------------------------------------


def test_render_settings_frozen_after_config_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    original_show_types = Config.SHOW_TYPES
    snapshot = build_render_settings()

    # Act
    monkeypatch.setattr(Config, "SHOW_TYPES", not original_show_types)

    # Assert
    assert snapshot.show_types == original_show_types


# ---------------------------------------------------------------------------
# build_tr_meta reads live Config
# ---------------------------------------------------------------------------


def test_build_tr_meta_reads_live_config_not_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    meta_before = build_tr_meta()

    # Act
    monkeypatch.setattr(Config, "SHOW_DOCS", not Config.SHOW_DOCS)
    meta_after = build_tr_meta()

    # Assert
    assert meta_before != meta_after


# ---------------------------------------------------------------------------
# FilterSettings ignore_dirs decoupled from Config
# ---------------------------------------------------------------------------


def test_filter_settings_ignore_dirs_mutation_does_not_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    snapshot = build_filter_settings()
    original_snapshot_dirs = snapshot.ignore_dirs

    # Act
    monkeypatch.setattr(Config, "IGNORE_DIRS", frozenset())

    # Assert
    assert isinstance(snapshot.ignore_dirs, frozenset)
    assert snapshot.ignore_dirs == original_snapshot_dirs
    assert len(snapshot.ignore_dirs) > 0


# ---------------------------------------------------------------------------
# DirectoryStructure freezes settings at construction
# ---------------------------------------------------------------------------


def test_directory_structure_init_freezes_settings_at_construction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    original_enable = Config.ENABLE_IGNORE_DIRS
    ds = DirectoryStructure(str(tmp_path))

    # Act
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", not original_enable)

    # Assert
    assert ds._filter_settings.enable_ignore_dirs == original_enable
