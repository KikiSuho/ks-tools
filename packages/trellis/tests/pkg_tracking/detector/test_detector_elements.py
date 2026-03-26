"""Tests for analyze_structure_elements in detector module.

Covers element extraction from tree text, decorator grouping,
file context tracking, and edge cases.
"""

from __future__ import annotations

from trellis.tracking.detector import analyze_structure_elements


# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------


def test_empty_structure_returns_empty_dict() -> None:
    # Arrange
    tree = ""

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert result == {}


def test_single_file_with_functions() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── main.py\n"
        "    ├── def hello(name: str) -> None\n"
        "    └── def goodbye() -> None\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "main.py" in result
    assert result["main.py"] == [
        "def hello(name: str) -> None",
        "def goodbye() -> None",
    ]


def test_nested_class_methods() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── models.py\n"
        "    ├── class User\n"
        "    │   ├── def __init__(self, name: str)\n"
        "    │   └── def save(self) -> None\n"
        "    └── class Admin(User)\n"
        "        └── def promote(self) -> None\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "models.py" in result
    elements = result["models.py"]
    assert "class User" in elements
    assert "def __init__(self, name: str)" in elements
    assert "def save(self) -> None" in elements
    assert "class Admin(User)" in elements
    assert "def promote(self) -> None" in elements


# ---------------------------------------------------------------------------
# Decorator grouping
# ---------------------------------------------------------------------------


def test_decorator_grouping() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── utils.py\n"
        "    └── @staticmethod\n"
        "        └── def helper() -> None\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert result["utils.py"] == ["@staticmethod | def helper() -> None"]


def test_multi_decorator_grouping() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── views.py\n"
        "    ├── @app.route('/api')\n"
        "    ├── @login_required\n"
        "    └── def index() -> Response\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert result["views.py"] == [
        "@app.route('/api') | @login_required | def index() -> Response"
    ]


# ---------------------------------------------------------------------------
# File type filtering
# ---------------------------------------------------------------------------


def test_directories_not_included_in_elements() -> None:
    # Arrange
    tree = (
        "project/\n"
        "├── src/\n"
        "│   └── main.py\n"
        "│       └── def run() -> None\n"
        "└── tests/\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "src/" not in result
    assert "tests/" not in result
    assert "src/main.py" in result


def test_non_python_files_ignored() -> None:
    # Arrange
    tree = (
        "project/\n"
        "├── README.md\n"
        "├── config.txt\n"
        "└── main.py\n"
        "    └── def run() -> None\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "README.md" not in result
    assert "config.txt" not in result
    assert "main.py" in result


# ---------------------------------------------------------------------------
# Async functions
# ---------------------------------------------------------------------------


def test_async_functions_captured() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── handlers.py\n"
        "    ├── async def fetch(url: str) -> bytes\n"
        "    └── def sync_fetch(url: str) -> bytes\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "async def fetch(url: str) -> bytes" in result["handlers.py"]
    assert "def sync_fetch(url: str) -> bytes" in result["handlers.py"]


# ---------------------------------------------------------------------------
# Indentation and file context
# ---------------------------------------------------------------------------


def test_indentation_resets_file_context() -> None:
    # Arrange
    tree = (
        "project/\n"
        "├── alpha.py\n"
        "│   └── def foo() -> None\n"
        "└── beta.py\n"
        "    └── def bar() -> None\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert result["alpha.py"] == ["def foo() -> None"]
    assert result["beta.py"] == ["def bar() -> None"]


def test_nested_directory_file_paths() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── pkg/\n"
        "    └── sub/\n"
        "        └── module.py\n"
        "            └── def deep_func() -> int\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "pkg/sub/module.py" in result
    assert result["pkg/sub/module.py"] == ["def deep_func() -> int"]


# ---------------------------------------------------------------------------
# Line number annotations
# ---------------------------------------------------------------------------


def test_lineno_preserved_in_elements() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── main.py {150}\n"
        "    ├── def hello(name: str) -> None  :5\n"
        "    └── def goodbye() -> None  :20\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert result["main.py"] == [
        "def hello(name: str) -> None  :5",
        "def goodbye() -> None  :20",
    ]


def test_file_line_count_stripped_from_path() -> None:
    # Arrange
    tree = (
        "project/\n"
        "└── main.py {150}\n"
        "    └── def run() -> None  :1\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "main.py" in result
    assert "main.py {150}" not in result


# ---------------------------------------------------------------------------
# File tracking edge case
# ---------------------------------------------------------------------------


def test_file_with_no_elements_still_tracked() -> None:
    # Arrange
    tree = (
        "project/\n"
        "├── empty.py\n"
        "└── has_func.py\n"
        "    └── def run() -> None\n"
    )

    # Act
    result = analyze_structure_elements(tree)

    # Assert
    assert "empty.py" in result
    assert result["empty.py"] == []
    assert result["has_func.py"] == ["def run() -> None"]
