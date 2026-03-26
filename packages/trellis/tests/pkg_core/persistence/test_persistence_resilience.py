"""Tests for persistence layer I/O resilience and public API.

Verify that save_structure handles directory creation failures,
read errors, write failures, and change detection. Also covers
prepare_tree_content formatting.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from trellis.config import Config, build_filter_settings, build_tr_meta
from trellis.core.persistence import (
    PersistenceContext,
    SaveResult,
    WriteStatus,
    prepare_tree_content,
    save_structure,
)


def _make_ctx(root_dir: str, **overrides: object) -> PersistenceContext:
    """Build a minimal PersistenceContext for testing."""
    defaults: dict[str, object] = {
        "project_name": Path(root_dir).name,
        "root_dir": root_dir,
        "structure": "\u251c\u2500\u2500 main.py\n",
        "scanned_paths": frozenset({"main.py"}),
        "path_hierarchy": {"main.py": ()},
        "filter_settings": build_filter_settings(),
        "tr_meta": build_tr_meta(),
    }
    defaults.update(overrides)
    return PersistenceContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# prepare_tree_content
# ---------------------------------------------------------------------------


def test_prepare_tree_content_formats_root_and_structure() -> None:
    # Arrange
    project_name = "demo"
    structure = "\u251c\u2500\u2500 main.py\n"

    # Act
    result = prepare_tree_content(project_name, structure)

    # Assert
    assert result.startswith("demo/\n")
    assert "main.py" in result


def test_prepare_tree_content_strips_trailing_whitespace() -> None:
    # Arrange
    project_name = "demo"
    structure = "\u251c\u2500\u2500 main.py\n\n\n"

    # Act
    result = prepare_tree_content(project_name, structure)

    # Assert
    assert result.endswith("main.py\n")


# ---------------------------------------------------------------------------
# save_structure — first run
# ---------------------------------------------------------------------------


def test_save_structure_first_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    ctx = _make_ctx(str(tmp_path))

    # Act
    result = save_structure(ctx)

    # Assert
    assert result.changes is None
    assert result.write_status == WriteStatus.SUCCESS
    assert result.read_error == ""
    assert Path(result.output_path).exists()


# ---------------------------------------------------------------------------
# save_structure — second run with changes
# ---------------------------------------------------------------------------


def test_save_structure_second_run_detects_added_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    ctx_v1 = _make_ctx(str(tmp_path))
    save_structure(ctx_v1)
    ctx_v2 = _make_ctx(
        str(tmp_path),
        structure="\u251c\u2500\u2500 main.py\n\u2514\u2500\u2500 utils.py\n",
        scanned_paths=frozenset({"main.py", "utils.py"}),
        path_hierarchy={"main.py": (), "utils.py": ()},
    )

    # Act
    result = save_structure(ctx_v2)

    # Assert
    assert result.changes is not None
    assert result.changes.has_changes is True
    assert result.write_status == WriteStatus.SUCCESS


# ---------------------------------------------------------------------------
# save_structure — error paths
# ---------------------------------------------------------------------------


def test_save_structure_dir_create_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    ctx = _make_ctx(str(tmp_path))

    # Act
    with patch(
        "trellis.core.persistence.Path.mkdir",
        side_effect=PermissionError("read-only"),
    ):
        result = save_structure(ctx)

    # Assert
    assert result.write_status == WriteStatus.DIR_CREATE_FAILED
    assert result.output_path == ""


def test_save_structure_read_error_signals_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    ctx = _make_ctx(str(tmp_path))
    save_structure(ctx)
    real_open = Path.open

    def _mock_open(self, *args, **kwargs):
        """Raise PermissionError when reading the structure file."""
        if str(self).endswith("_structure.txt") and "r" in kwargs.get(
            "mode", args[0] if args else "r"
        ):
            raise PermissionError("locked")
        return real_open(self, *args, **kwargs)

    # Act
    with patch.object(Path, "open", _mock_open):
        result = save_structure(ctx)

    # Assert
    assert result.changes is None
    assert result.read_error != ""
    assert "PermissionError" in result.read_error


def test_save_structure_write_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    ctx = _make_ctx(str(tmp_path))

    # Act
    with patch(
        "trellis.core.persistence.atomic_write_text",
        return_value=False,
    ):
        result = save_structure(ctx)

    # Assert
    assert result.write_status == WriteStatus.WRITE_FAILED
