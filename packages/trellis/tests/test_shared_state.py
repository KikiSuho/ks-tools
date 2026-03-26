"""Tests for shared state (_structure_lines reference) (Category 4).

Verify that the _structure_lines list shared by reference between
DirectoryStructure and AstRenderer works correctly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trellis.config import Config
from trellis.pyast.renderer import AstRenderer, build_render_settings
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


# ---------------------------------------------------------------------------
# Test 4.1
# ---------------------------------------------------------------------------


def test_renderer_appends_to_same_list_as_directory_structure(
    tmp_path: Path,
) -> None:
    """Manual append and renderer output both appear in ds.structure."""
    py_file = tmp_path / "hello.py"
    py_file.write_text("def greet():\n    pass\n", encoding="utf-8")

    ds = DirectoryStructure(str(tmp_path))
    ds.append_line("manual line\n")

    ds._renderer.render_python_structure(str(py_file), "", True)

    output = ds.structure
    assert "manual line" in output
    assert "def greet" in output
    # Manual line appears before rendered content.
    assert output.index("manual line") < output.index("def greet")


# ---------------------------------------------------------------------------
# Test 4.2
# ---------------------------------------------------------------------------


def test_structure_lines_ordering_dirs_then_ast(tmp_path: Path) -> None:
    """Directory line appears before file line, class after file."""
    subdir = tmp_path / "pkg"
    subdir.mkdir()
    (subdir / "__init__.py").write_text("", encoding="utf-8")
    (subdir / "models.py").write_text(
        "class User:\n    pass\n", encoding="utf-8"
    )

    Config.ENABLE_IGNORE_DIRS = False
    Config.ENABLE_IGNORE_FILES = False
    Config.SHOW_DECORATORS = False
    Config.CALL_FLOW_MODE = Config.CALL_FLOW_MODE.__class__("off")
    ds = DirectoryStructure(str(tmp_path))
    ds.scan_directory(str(tmp_path))

    output = ds.structure
    assert "pkg/" in output
    assert "models.py" in output
    assert "class User" in output

    pkg_pos = output.index("pkg/")
    models_pos = output.index("models.py")
    user_pos = output.index("class User")
    assert pkg_pos < models_pos < user_pos


# ---------------------------------------------------------------------------
# Test 4.3
# ---------------------------------------------------------------------------


def test_renderer_does_not_own_structure_lines(tmp_path: Path) -> None:
    """AstRenderer appends to the caller's list without replacing it."""
    shared_list: list[str] = []
    original_id = id(shared_list)

    settings = build_render_settings()
    renderer = AstRenderer(shared_list, False, False, False, settings)

    py_file = tmp_path / "sample.py"
    py_file.write_text("def foo():\n    pass\n", encoding="utf-8")
    renderer.render_python_structure(str(py_file), "", True)

    assert id(shared_list) == original_id
    assert len(shared_list) > 0
    assert any("def foo" in line for line in shared_list)
