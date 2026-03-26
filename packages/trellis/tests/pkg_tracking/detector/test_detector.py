"""Tests for trellis.tracking.detector module.

Covers tr_meta formatting/parsing/splitting, structure change detection,
and structure path analysis.
"""

from __future__ import annotations

import pytest

from trellis.config import FilterSettings, build_tr_meta
from trellis.tracking.detector import (
    analyze_structure_paths,
    append_tr_meta,
    detect_structure_changes,
    format_tr_meta,
    parse_tr_meta_line,
    split_tree_and_meta,
)


def _make_settings(**overrides: object) -> FilterSettings:
    """Build a FilterSettings with sensible defaults."""
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
    """Accept all paths without filtering."""
    return False


# ---------------------------------------------------------------------------
# build_tr_meta / format_tr_meta
# ---------------------------------------------------------------------------


def test_build_tr_meta_starts_with_docs_flag() -> None:
    # Arrange
    expected_prefix = "D"

    # Act
    meta = build_tr_meta()

    # Assert
    assert meta.startswith(expected_prefix)


def test_format_tr_meta_includes_prefix() -> None:
    # Arrange
    meta = build_tr_meta()

    # Act
    result = format_tr_meta(meta)

    # Assert
    assert result.startswith("# tr_meta:")


# ---------------------------------------------------------------------------
# parse_tr_meta_line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, is_valid",
    [
        pytest.param("# tr_meta:D1I1F1T1@1C0", True, id="full-v2"),
        pytest.param("# tr_meta:D1I1F1", True, id="legacy-v1"),
        pytest.param("# tr_meta:INVALID", False, id="invalid"),
        pytest.param("not a meta line", False, id="no-prefix"),
        pytest.param("", False, id="empty"),
    ],
)
def test_parse_tr_meta_line_validity(line: str, is_valid: bool) -> None:
    # Arrange
    input_line = line

    # Act
    result = parse_tr_meta_line(input_line)

    # Assert
    assert (result is not None) == is_valid


def test_parse_tr_meta_line_extracts_values() -> None:
    # Arrange
    line = "# tr_meta:D1I0F1T0@1C1"

    # Act
    result = parse_tr_meta_line(line)

    # Assert
    assert result is not None
    assert "D1" in result
    assert "I0" in result
    assert "T0" in result
    assert "@1" in result
    assert "C1" in result


def test_parse_tr_meta_legacy_fills_defaults() -> None:
    # Arrange
    legacy_line = "# tr_meta:D1I1F1"

    # Act
    result = parse_tr_meta_line(legacy_line)

    # Assert
    assert result is not None
    assert "T1" in result
    assert "@1" in result
    assert "C0" in result


# ---------------------------------------------------------------------------
# append_tr_meta / split_tree_and_meta round-trip
# ---------------------------------------------------------------------------


def test_append_tr_meta_adds_footer() -> None:
    # Arrange
    tree_content = "myproject/\n├── src/\n"
    meta = build_tr_meta()

    # Act
    result = append_tr_meta(tree_content, meta)

    # Assert
    assert "# tr_meta:" in result
    assert result.startswith("myproject/")


def test_split_tree_and_meta_round_trip() -> None:
    # Arrange
    tree_content = "myproject/\n├── src/\n"
    combined = append_tr_meta(tree_content, build_tr_meta())

    # Act
    extracted_tree, meta_value, meta_status = split_tree_and_meta(combined, "myproject")

    # Assert
    assert meta_status == "valid"
    assert meta_value is not None
    assert "src/" in extracted_tree


def test_split_tree_and_meta_missing_footer() -> None:
    # Arrange
    content = "myproject/\n├── src/\n"

    # Act
    _tree, meta_value, meta_status = split_tree_and_meta(content, "myproject")

    # Assert
    assert meta_status == "missing"
    assert meta_value is None


def test_split_tree_and_meta_invalid_root() -> None:
    # Arrange
    content = "otherproject/\n├── src/\n"

    # Act
    tree, meta_value, meta_status = split_tree_and_meta(content, "myproject")

    # Assert
    assert meta_status == "invalid"
    assert tree == ""


def test_split_tree_and_meta_invalid_footer() -> None:
    # Arrange
    content = "myproject/\n├── src/\n\n\n# tr_meta:GARBAGE\n"

    # Act
    _tree, meta_value, meta_status = split_tree_and_meta(content, "myproject")

    # Assert
    assert meta_status == "invalid"
    assert meta_value is None


# ---------------------------------------------------------------------------
# analyze_structure_paths
# ---------------------------------------------------------------------------


def test_analyze_strips_line_count_annotation() -> None:
    # Arrange
    text = "myproject/\n├── main.py {150}\n└── utils.py {42}\n"

    # Act
    paths, _hierarchy = analyze_structure_paths(text)

    # Assert
    assert any(path.endswith("main.py") for path in paths)
    assert not any("{" in path for path in paths)


def test_analyze_extracts_file_paths() -> None:
    # Arrange
    text = "myproject/\n├── src/\n│   ├── main.py\n│   └── utils.py\n└── README.md\n"

    # Act
    paths, hierarchy = analyze_structure_paths(text)

    # Assert
    assert any("main.py" in path for path in paths)
    assert any("utils.py" in path for path in paths)
    assert any("README.md" in path for path in paths)


def test_analyze_extracts_directory_paths() -> None:
    # Arrange
    text = "myproject/\n├── src/\n│   └── main.py\n"

    # Act
    paths, hierarchy = analyze_structure_paths(text)

    # Assert
    assert any("src/" in path for path in paths)


def test_analyze_skips_code_elements() -> None:
    # Arrange
    text = (
        "myproject/\n"
        "├── main.py\n"
        "│   ├── def main()\n"
        "│   └── class Config\n"
    )

    # Act
    paths, _hierarchy = analyze_structure_paths(text)

    # Assert
    assert not any("def main" in path for path in paths)
    assert not any("class Config" in path for path in paths)


def test_analyze_builds_hierarchy_with_indented_children() -> None:
    # Arrange
    text = (
        "myproject/\n"
        "└── src/\n"
        "    ├── main.py\n"
        "    └── utils.py\n"
    )

    # Act
    paths, hierarchy = analyze_structure_paths(text)

    # Assert
    main_key = [path for path in paths if "main.py" in path][0]
    assert "src/" in main_key
    assert len(hierarchy[main_key]) > 0


def test_analyze_empty_text() -> None:
    # Arrange
    text = ""

    # Act
    paths, hierarchy = analyze_structure_paths(text)

    # Assert
    assert paths == set()
    assert hierarchy == {}


# ---------------------------------------------------------------------------
# detect_structure_changes
# ---------------------------------------------------------------------------


def test_detect_no_changes_when_identical() -> None:
    # Arrange
    content = "myproject/\n├── src/\n│   └── main.py\n"
    old = append_tr_meta(content, build_tr_meta())

    # Act
    added, deleted, has_changes = detect_structure_changes(
        content, old, "myproject", _no_filter, _make_settings()
    )

    # Assert
    assert has_changes is False
    assert added == []
    assert deleted == []


def test_detect_added_file() -> None:
    # Arrange
    old_tree = "myproject/\n├── main.py\n"
    old = append_tr_meta(old_tree, build_tr_meta())
    new_tree = "myproject/\n├── main.py\n└── utils.py\n"

    # Act
    added, deleted, has_changes = detect_structure_changes(
        new_tree, old, "myproject", _no_filter, _make_settings()
    )

    # Assert
    assert has_changes is True
    assert any("utils.py" in path for path in added)
    assert deleted == []


def test_detect_deleted_file() -> None:
    # Arrange
    old_tree = "myproject/\n├── main.py\n└── utils.py\n"
    old = append_tr_meta(old_tree, build_tr_meta())
    new_tree = "myproject/\n└── main.py\n"

    # Act
    added, deleted, has_changes = detect_structure_changes(
        new_tree, old, "myproject", _no_filter, _make_settings()
    )

    # Assert
    assert has_changes is True
    assert added == []
    assert any("utils.py" in path for path in deleted)


def test_detect_skips_when_logging_disabled() -> None:
    # Arrange
    settings = _make_settings(log_structure_changes=False)
    old = append_tr_meta("myproject/\n├── a.py\n", build_tr_meta())
    new_content = "myproject/\n├── b.py\n"

    # Act
    added, deleted, has_changes = detect_structure_changes(
        new_content, old, "myproject", _no_filter, settings
    )

    # Assert
    assert has_changes is False
    assert added == []
    assert deleted == []
