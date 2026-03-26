"""Tests for trellis.core.filters module.

Covers system file skipping, directory/file ignore predicates,
pattern matching, doc file filtering, and hierarchy-based filtering.
"""

from __future__ import annotations

import pytest

from trellis.config import FilterSettings
from trellis.core.filters import (
    directory_matches_pattern,
    is_docs_directory_visible,
    is_path_filtered_by_flags,
    is_path_in_ignored_hierarchy,
    is_special_case_item,
    matches_ignored_directory,
    matches_ignored_file,
    should_ignore_directory,
    should_ignore_file,
    should_skip_system_file,
)


def _make_settings(**overrides: object) -> FilterSettings:
    """Build a FilterSettings with sensible defaults, overridden by kwargs."""
    defaults: dict[str, object] = {
        "enable_ignore_dirs": True,
        "enable_ignore_files": True,
        "show_docs": True,
        "doc_extensions": frozenset({".md", ".txt", ".rst"}),
        "output_dir": "docs",
        "ignore_dirs": frozenset({"build", "tests"}),
        "ignore_files": frozenset({".gitignore", "*.yml"}),
        "log_dir": "logs/structure_changes",
        "log_structure_changes": True,
        "log_config_only_changes": False,
    }
    defaults.update(overrides)
    return FilterSettings(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# should_skip_system_file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename, is_expected_skipped",
    [
        pytest.param("__init__.py", True, id="init"),
        pytest.param("__main__.py", True, id="main"),
        pytest.param("py.typed", True, id="py-typed"),
        pytest.param("utils.py", False, id="regular-file"),
        pytest.param("__pycache__", False, id="pycache-dir"),
    ],
)
def test_should_skip_system_file(filename: str, is_expected_skipped: bool) -> None:
    # Arrange
    item = filename

    # Act
    result = should_skip_system_file(item)

    # Assert
    assert result == is_expected_skipped


# ---------------------------------------------------------------------------
# is_docs_directory_visible
# ---------------------------------------------------------------------------


def test_docs_directory_visible_when_show_docs_enabled() -> None:
    # Arrange
    settings = _make_settings(output_dir="docs", show_docs=True)

    # Act
    result = is_docs_directory_visible("docs", settings)

    # Assert
    assert result is True


def test_docs_directory_not_visible_when_show_docs_disabled() -> None:
    # Arrange
    settings = _make_settings(output_dir="docs", show_docs=False)

    # Act
    result = is_docs_directory_visible("docs", settings)

    # Assert
    assert result is False


def test_non_docs_directory_not_visible() -> None:
    # Arrange
    settings = _make_settings(output_dir="docs", show_docs=True)

    # Act
    result = is_docs_directory_visible("src", settings)

    # Assert
    assert result is False


# ---------------------------------------------------------------------------
# is_special_case_item
# ---------------------------------------------------------------------------


def test_special_case_docs_directory() -> None:
    # Arrange
    settings = _make_settings(output_dir="docs", show_docs=True)

    # Act
    result = is_special_case_item("docs", is_directory=True, settings=settings)

    # Assert
    assert result is True


def test_special_case_file_is_not_special() -> None:
    # Arrange
    settings = _make_settings(output_dir="docs", show_docs=True)

    # Act
    result = is_special_case_item("docs", is_directory=False, settings=settings)

    # Assert
    assert result is False


# ---------------------------------------------------------------------------
# should_ignore_directory
# ---------------------------------------------------------------------------


def test_ignore_directory_when_in_user_ignore_list() -> None:
    # Arrange
    settings = _make_settings(ignore_dirs=frozenset({"build"}))

    # Act
    result = should_ignore_directory("/project/build", settings)

    # Assert
    assert result is True


def test_do_not_ignore_directory_when_not_in_list() -> None:
    # Arrange
    settings = _make_settings(ignore_dirs=frozenset({"build"}))

    # Act
    result = should_ignore_directory("/project/src", settings)

    # Assert
    assert result is False


def test_ignore_dirs_disabled_skips_user_configured_dir() -> None:
    # Arrange
    settings = _make_settings(
        enable_ignore_dirs=False, ignore_dirs=frozenset({"build"})
    )

    # Act
    result = should_ignore_directory("/project/build", settings)

    # Assert
    assert result is False


def test_ignore_dirs_disabled_still_blocks_hard_ignore() -> None:
    # Arrange
    settings = _make_settings(enable_ignore_dirs=False, ignore_dirs=frozenset())

    # Act
    result = should_ignore_directory("/project/__pycache__", settings)

    # Assert
    assert result is True


# ---------------------------------------------------------------------------
# should_ignore_file
# ---------------------------------------------------------------------------


def test_ignore_file_matching_user_pattern() -> None:
    # Arrange
    settings = _make_settings(ignore_files=frozenset({".gitignore"}))

    # Act
    result = should_ignore_file("/project/.gitignore", settings)

    # Assert
    assert result is True


def test_do_not_ignore_file_not_matching() -> None:
    # Arrange
    settings = _make_settings(ignore_files=frozenset({".gitignore"}))

    # Act
    result = should_ignore_file("/project/module.py", settings)

    # Assert
    assert result is False


def test_ignore_files_disabled_skips_user_configured_pattern() -> None:
    # Arrange
    settings = _make_settings(
        enable_ignore_files=False, ignore_files=frozenset({".gitignore"})
    )

    # Act
    result = should_ignore_file("/project/.gitignore", settings)

    # Assert
    assert result is False


def test_ignore_files_disabled_still_blocks_hard_ignore() -> None:
    # Arrange
    settings = _make_settings(enable_ignore_files=False, ignore_files=frozenset())

    # Act
    result = should_ignore_file("/project/module.pyc", settings)

    # Assert
    assert result is True


def test_ignore_doc_file_when_show_docs_disabled() -> None:
    # Arrange
    settings = _make_settings(
        show_docs=False,
        doc_extensions=frozenset({".md"}),
        enable_ignore_files=False,
    )

    # Act
    result = should_ignore_file("/project/README.md", settings)

    # Assert
    assert result is True


def test_keep_doc_file_when_show_docs_enabled() -> None:
    # Arrange
    settings = _make_settings(
        show_docs=True,
        doc_extensions=frozenset({".md"}),
        enable_ignore_files=False,
    )

    # Act
    result = should_ignore_file("/project/README.md", settings)

    # Assert
    assert result is False


# ---------------------------------------------------------------------------
# matches_ignored_file
# ---------------------------------------------------------------------------


def test_matches_ignored_file_glob_pattern() -> None:
    # Arrange
    settings = _make_settings(ignore_files=frozenset({"test_*.py"}))

    # Act
    result = matches_ignored_file("/project/test_utils.py", settings)

    # Assert
    assert result is True


def test_matches_ignored_file_exact_name() -> None:
    # Arrange
    settings = _make_settings(ignore_files=frozenset({".gitignore"}))

    # Act
    result = matches_ignored_file("/project/.gitignore", settings)

    # Assert
    assert result is True


# ---------------------------------------------------------------------------
# directory_matches_pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dir_name, posix_path, pattern, is_expected_match",
    [
        pytest.param("__pycache__", "/project/__pycache__", "__pycache__", True, id="exact"),
        pytest.param("src", "/project/src", "__pycache__", False, id="no-match"),
        pytest.param("foo.egg-info", "/project/foo.egg-info", "*.egg-info", True, id="glob"),
        pytest.param(
            "build", "/project/docs/build", "docs/build", True, id="path-pattern"
        ),
    ],
)
def test_directory_matches_pattern(
    dir_name: str, posix_path: str, pattern: str, is_expected_match: bool
) -> None:
    # Arrange
    directory_name = dir_name
    normalized_posix = posix_path

    # Act
    result = directory_matches_pattern(directory_name, normalized_posix, pattern)

    # Assert
    assert result == is_expected_match


# ---------------------------------------------------------------------------
# matches_ignored_directory
# ---------------------------------------------------------------------------


def test_matches_ignored_directory_skips_docs_when_visible() -> None:
    # Arrange
    settings = _make_settings(
        ignore_dirs=frozenset({"docs"}), output_dir="docs", show_docs=True
    )

    # Act
    result = matches_ignored_directory("/project/docs", settings)

    # Assert
    assert result is False


def test_matches_ignored_directory_ignores_docs_when_hidden() -> None:
    # Arrange
    settings = _make_settings(
        ignore_dirs=frozenset({"docs"}), output_dir="docs", show_docs=False
    )

    # Act
    result = matches_ignored_directory("/project/docs", settings)

    # Assert
    assert result is True


def test_hard_ignore_dir_glob_matches_egg_info() -> None:
    # Arrange
    settings = _make_settings(enable_ignore_dirs=False, ignore_dirs=frozenset())

    # Act
    result = should_ignore_directory("/project/mypackage.egg-info", settings)

    # Assert
    assert result is True


# ---------------------------------------------------------------------------
# is_path_filtered_by_flags
# ---------------------------------------------------------------------------


def test_path_filtered_by_user_directory_ignore() -> None:
    # Arrange
    settings = _make_settings(ignore_dirs=frozenset({"build"}))

    # Act
    result = is_path_filtered_by_flags("build", settings)

    # Assert
    assert result is True


def test_path_filtered_by_hard_ignore_directory() -> None:
    # Arrange
    settings = _make_settings(enable_ignore_dirs=False, ignore_dirs=frozenset())

    # Act
    result = is_path_filtered_by_flags("__pycache__", settings)

    # Assert
    assert result is True


def test_path_filtered_by_user_file_ignore() -> None:
    # Arrange
    settings = _make_settings(ignore_files=frozenset({".gitignore"}))

    # Act
    result = is_path_filtered_by_flags(".gitignore", settings)

    # Assert
    assert result is True


def test_path_filtered_by_hard_ignore_file() -> None:
    # Arrange
    settings = _make_settings(enable_ignore_files=False, ignore_files=frozenset())

    # Act
    result = is_path_filtered_by_flags("module.pyc", settings)

    # Assert
    assert result is True


def test_path_not_filtered_when_clean() -> None:
    # Arrange
    settings = _make_settings()

    # Act
    result = is_path_filtered_by_flags("module.py", settings)

    # Assert
    assert result is False


def test_path_filtered_by_doc_extension_when_docs_hidden() -> None:
    # Arrange
    settings = _make_settings(
        show_docs=False,
        doc_extensions=frozenset({".md"}),
        enable_ignore_dirs=False,
        enable_ignore_files=False,
    )

    # Act
    result = is_path_filtered_by_flags("README.md", settings)

    # Assert
    assert result is True


# ---------------------------------------------------------------------------
# is_path_in_ignored_hierarchy
# ---------------------------------------------------------------------------


def test_path_in_ignored_hierarchy_self() -> None:
    # Arrange
    settings = _make_settings(ignore_dirs=frozenset({"tests"}))

    # Act
    result = is_path_in_ignored_hierarchy("tests", [], settings)

    # Assert
    assert result is True


def test_path_in_ignored_hierarchy_ancestor() -> None:
    # Arrange
    settings = _make_settings(ignore_dirs=frozenset({"tests"}))

    # Act
    result = is_path_in_ignored_hierarchy("conftest.py", ["tests"], settings)

    # Assert
    assert result is True


def test_path_not_in_ignored_hierarchy() -> None:
    # Arrange
    settings = _make_settings(ignore_dirs=frozenset({"tests"}))

    # Act
    result = is_path_in_ignored_hierarchy("module.py", ["src"], settings)

    # Assert
    assert result is False
