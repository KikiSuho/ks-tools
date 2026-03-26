"""Tests for trellis.tracking.comparator module.

Covers element comparison, change categorization, line number handling,
signature detail extraction, and edge cases for the structure diffing logic.
"""

from __future__ import annotations

from trellis.tracking.comparator import (
    ApiChange,
    ApiEntry,
    compare_structure_elements,
    extract_lineno,
    extract_signature_detail,
    strip_lineno,
)


# ---------------------------------------------------------------------------
# compare_structure_elements — core comparison
# ---------------------------------------------------------------------------


def test_no_changes_returns_empty() -> None:
    # Arrange
    elements = {"main.py": ["def run() -> None"]}

    # Act
    result = compare_structure_elements(elements, elements, [], [])

    # Assert
    assert result.api_changes == []
    assert result.new_api == []
    assert result.removed_api == []
    assert result.has_changes is False


def test_new_file_elements_categorized_as_new_api() -> None:
    # Arrange
    old: dict[str, list[str]] = {}
    new = {"utils.py": ["def helper() -> str"]}

    # Act
    result = compare_structure_elements(old, new, ["utils.py"], [])

    # Assert
    assert len(result.new_api) == 1
    assert result.new_api[0] == ApiEntry("utils.py", "def helper() -> str")
    assert result.has_changes is True


def test_removed_file_elements_categorized_as_removed_api() -> None:
    # Arrange
    old = {"utils.py": ["def helper() -> str"]}
    new: dict[str, list[str]] = {}

    # Act
    result = compare_structure_elements(old, new, [], ["utils.py"])

    # Assert
    assert len(result.removed_api) == 1
    assert result.removed_api[0] == ApiEntry("utils.py", "def helper() -> str")
    assert result.has_changes is True


def test_signature_change_detected() -> None:
    # Arrange
    old = {"handlers.py": ["def process(input)"]}
    new = {"handlers.py": ["def process(input, limit: int)"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert result.api_changes[0] == ApiChange(
        "handlers.py", "def process(input)", "def process(input, limit: int)"
    )


def test_return_type_change_detected() -> None:
    # Arrange
    old = {"config.py": ["def build() -> Config"]}
    new = {"config.py": ["def build() -> Settings"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert result.api_changes[0].old_signature == "def build() -> Config"
    assert result.api_changes[0].new_signature == "def build() -> Settings"


def test_new_function_in_existing_file() -> None:
    # Arrange
    old = {"main.py": ["def run() -> None"]}
    new = {"main.py": ["def run() -> None", "def stop() -> None"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.new_api) == 1
    assert result.new_api[0] == ApiEntry("main.py", "def stop() -> None")


def test_removed_function_from_existing_file() -> None:
    # Arrange
    old = {"main.py": ["def run() -> None", "def stop() -> None"]}
    new = {"main.py": ["def run() -> None"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.removed_api) == 1
    assert result.removed_api[0] == ApiEntry("main.py", "def stop() -> None")


def test_decorator_change_detected() -> None:
    # Arrange
    old = {"utils.py": ["def helper() -> None"]}
    new = {"utils.py": ["@staticmethod | def helper() -> None"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert result.api_changes[0].old_signature == "def helper() -> None"
    assert result.api_changes[0].new_signature == "@staticmethod | def helper() -> None"


def test_class_inheritance_change() -> None:
    # Arrange
    old = {"models.py": ["class Config"]}
    new = {"models.py": ["class Config(BaseConfig)"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert result.api_changes[0].old_signature == "class Config"
    assert result.api_changes[0].new_signature == "class Config(BaseConfig)"


def test_multiple_changes_across_files() -> None:
    # Arrange
    old = {
        "main.py": ["def run() -> None"],
        "utils.py": ["def helper() -> str", "def old_func() -> int"],
    }
    new = {
        "main.py": ["def run(verbose: bool) -> None"],
        "utils.py": ["def helper() -> str", "def new_func() -> int"],
    }

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert len(result.new_api) == 1
    assert len(result.removed_api) == 1
    assert result.has_changes is True


def test_async_def_signature_change_detected() -> None:
    # Arrange
    old = {"handlers.py": ["async def fetch(url: str) -> bytes"]}
    new = {"handlers.py": ["async def fetch(url: str, timeout: float) -> bytes"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert "timeout: float" in result.api_changes[0].new_signature


def test_name_collision_last_wins() -> None:
    # Arrange
    old = {"main.py": ["def run() -> None", "def run(x: int) -> None"]}
    new = {"main.py": ["def run(x: int, y: int) -> None"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert len(result.api_changes) == 1
    assert result.api_changes[0].old_signature == "def run(x: int) -> None"
    assert result.api_changes[0].new_signature == "def run(x: int, y: int) -> None"


def test_file_in_both_maps_and_added_paths_skips_diff() -> None:
    # Arrange
    old = {"utils.py": ["def helper() -> str"]}
    new = {"utils.py": ["def helper(x: int) -> str"]}

    # Act
    result = compare_structure_elements(old, new, ["utils.py"], [])

    # Assert
    assert result.api_changes == []
    assert len(result.new_api) == 1
    assert result.new_api[0].signature == "def helper(x: int) -> str"


# ---------------------------------------------------------------------------
# Path splitting
# ---------------------------------------------------------------------------


def test_has_changes_true_when_any_category_nonempty() -> None:
    # Arrange
    old: dict[str, list[str]] = {}
    new: dict[str, list[str]] = {}

    # Act
    result = compare_structure_elements(old, new, ["new_dir/"], [])

    # Assert
    assert result.has_changes is True
    assert result.new_packages == ["new_dir/"]


def test_has_changes_false_when_all_empty() -> None:
    # Arrange
    old: dict[str, list[str]] = {}
    new: dict[str, list[str]] = {}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert result.has_changes is False


def test_non_py_files_in_added_paths_become_new_files() -> None:
    # Arrange
    added = ["data.csv", "config.yml"]

    # Act
    result = compare_structure_elements({}, {}, added, [])

    # Assert
    assert result.new_api == []
    assert result.new_modules == []
    assert result.new_files == ["data.csv", "config.yml"]
    assert result.has_changes is True


def test_mixed_paths_split_into_packages_modules_and_files() -> None:
    # Arrange
    added = ["utils.py", "data.csv", "pkg/", "README.md"]

    # Act
    result = compare_structure_elements({}, {}, added, [])

    # Assert
    assert result.new_packages == ["pkg/"]
    assert result.new_modules == ["utils.py"]
    assert result.new_files == ["data.csv", "README.md"]


def test_nested_file_path_uses_full_path() -> None:
    # Arrange
    old = {"pkg/sub/module.py": ["def func() -> int"]}
    new = {"pkg/sub/module.py": ["def func(x: int) -> int"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert result.api_changes[0].file_path == "pkg/sub/module.py"


# ---------------------------------------------------------------------------
# strip_lineno
# ---------------------------------------------------------------------------


def test_strip_lineno_removes_suffix() -> None:
    # Arrange
    line = "def run() -> None  :42"

    # Act
    result = strip_lineno(line)

    # Assert
    assert result == "def run() -> None"


def test_strip_lineno_preserves_line_without_suffix() -> None:
    # Arrange
    line = "def run() -> None"

    # Act
    result = strip_lineno(line)

    # Assert
    assert result == "def run() -> None"


def test_strip_lineno_class_with_suffix() -> None:
    # Arrange
    line = "class Config(Base)  :10"

    # Act
    result = strip_lineno(line)

    # Assert
    assert result == "class Config(Base)"


def test_lineno_shift_only_not_detected_as_change() -> None:
    # Arrange
    old = {"main.py": ["def run() -> None  :10"]}
    new = {"main.py": ["def run() -> None  :25"]}

    # Act
    result = compare_structure_elements(old, new, [], [])

    # Assert
    assert result.api_changes == []
    assert result.has_changes is False


# ---------------------------------------------------------------------------
# extract_lineno
# ---------------------------------------------------------------------------


def test_extract_lineno_present() -> None:
    # Arrange
    line = "def run() -> None  :42"

    # Act
    result = extract_lineno(line)

    # Assert
    assert result == ":42"


def test_extract_lineno_absent() -> None:
    # Arrange
    line = "def run() -> None"

    # Act
    result = extract_lineno(line)

    # Assert
    assert result == ""


def test_extract_lineno_class() -> None:
    # Arrange
    line = "class Config  :10"

    # Act
    result = extract_lineno(line)

    # Assert
    assert result == ":10"


# ---------------------------------------------------------------------------
# extract_signature_detail
# ---------------------------------------------------------------------------


def test_extract_signature_detail_def_with_params() -> None:
    # Arrange
    line = "def process_data(input: str) -> int  :42"

    # Act
    result = extract_signature_detail(line)

    # Assert
    assert result == "(input: str) -> int"


def test_extract_signature_detail_class_with_inheritance() -> None:
    # Arrange
    line = "class Config(BaseConfig)  :10"

    # Act
    result = extract_signature_detail(line)

    # Assert
    assert result == "(BaseConfig)"


def test_extract_signature_detail_class_no_inheritance() -> None:
    # Arrange
    line = "class Config  :10"

    # Act
    result = extract_signature_detail(line)

    # Assert
    assert result == ""


def test_extract_signature_detail_decorated() -> None:
    # Arrange
    line = "@staticmethod | def helper()  :25"

    # Act
    result = extract_signature_detail(line)

    # Assert
    assert result == "()"


def test_extract_signature_detail_no_lineno() -> None:
    # Arrange
    line = "def run(verbose: bool) -> None"

    # Act
    result = extract_signature_detail(line)

    # Assert
    assert result == "(verbose: bool) -> None"
