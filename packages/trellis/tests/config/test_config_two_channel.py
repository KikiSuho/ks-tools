"""Tests for the Config two-channel encoding fix.

Verify that DirectoryStructure forwards caller-supplied visibility settings
to build_tr_meta() rather than reading stale Config class defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trellis.config import Config, build_tr_meta
from trellis.main import DirectoryStructure


def test_tr_meta_encodes_show_private_from_constructor(tmp_path: Path) -> None:
    # Arrange
    ds = DirectoryStructure(str(tmp_path), show_private=True)

    # Act
    result = ds._tr_meta

    # Assert
    assert "V1" in result


def test_tr_meta_encodes_show_dunder_from_constructor(tmp_path: Path) -> None:
    # Arrange
    ds = DirectoryStructure(str(tmp_path), show_dunder=True)

    # Act
    result = ds._tr_meta

    # Assert
    assert "U1" in result


def test_tr_meta_encodes_show_mangled_from_constructor(tmp_path: Path) -> None:
    # Arrange
    ds = DirectoryStructure(str(tmp_path), show_mangled=True)

    # Act
    result = ds._tr_meta

    # Assert
    assert "S1" in result


def test_tr_meta_encodes_all_visibility_overrides(tmp_path: Path) -> None:
    # Arrange
    ds = DirectoryStructure(
        str(tmp_path),
        show_private=True,
        show_mangled=True,
        show_dunder=True,
    )

    # Act
    result = ds._tr_meta

    # Assert
    assert "V1" in result
    assert "U1" in result
    assert "S1" in result


def test_tr_meta_defaults_match_config_defaults(tmp_path: Path) -> None:
    # Arrange
    ds = DirectoryStructure(str(tmp_path))

    # Act
    result = ds._tr_meta

    # Assert
    assert f"V{int(Config.SHOW_PRIVATE)}" in result
    assert f"U{int(Config.SHOW_DUNDER)}" in result
    assert f"S{int(Config.SHOW_MANGLED)}" in result


def test_build_tr_meta_explicit_param_overrides_config() -> None:
    # Arrange
    meta_with_private = build_tr_meta(show_private=True)
    meta_without_private = build_tr_meta(show_private=False)

    # Act / Assert
    assert "V1" in meta_with_private
    assert "V0" in meta_without_private


def test_build_tr_meta_explicit_param_ignores_config_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "SHOW_PRIVATE", False)

    # Act
    meta = build_tr_meta(show_private=True)

    # Assert
    assert "V1" in meta
