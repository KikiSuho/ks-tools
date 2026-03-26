"""Tests for trellis.output.console module.

Covers banner formatting, section rendering, summary line counts,
signature wrapping, and grouped output.
"""

from __future__ import annotations

from trellis.output.console import (
    format_change_summary,
)
from trellis.tracking.comparator import (
    ApiChange,
    ApiEntry,
    StructureChanges,
)

_MAX_WIDTH = 100


def _make_changes(**overrides: object) -> StructureChanges:
    """Build a StructureChanges with sensible defaults."""
    defaults: dict[str, object] = {
        "api_changes": [],
        "new_api": [],
        "removed_api": [],
        "new_packages": [],
        "removed_packages": [],
        "new_modules": [],
        "removed_modules": [],
        "new_files": [],
        "removed_files": [],
        "has_changes": True,
    }
    defaults.update(overrides)
    return StructureChanges(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# No changes
# ---------------------------------------------------------------------------


def test_format_no_changes_returns_short_message() -> None:
    # Arrange
    changes = _make_changes(has_changes=False)

    # Act
    result = format_change_summary(changes, "scout", "", _MAX_WIDTH)

    # Assert
    assert result == "No structure changes detected."


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------


def test_format_api_changes_section() -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[
            ApiChange("config.py", "def build() -> Config", "def build() -> Settings"),
        ],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Updated API (1):" in result
    assert "config.py" in result
    assert ">>" in result
    assert "() -> Settings" in result


def test_format_new_api_section() -> None:
    # Arrange
    changes = _make_changes(
        new_api=[ApiEntry("validators.py", "def validate(data: dict) -> bool  :10")],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "New API (1):" in result
    assert "validators.py:10" in result
    assert "def validate" in result
    assert "(data: dict) -> bool" in result


def test_format_removed_api_section() -> None:
    # Arrange
    changes = _make_changes(
        removed_api=[ApiEntry("utils.py", "def old_helper(x: int) -> str")],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Removed API (1):" in result
    assert "utils.py" in result
    assert "def old_helper" in result


def test_format_new_modules_section() -> None:
    # Arrange
    changes = _make_changes(new_modules=["middleware/", "middleware/auth.py"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "New Modules (2):" in result
    assert "  middleware/" in result
    assert "  middleware/auth.py" in result


def test_format_removed_modules_section() -> None:
    # Arrange
    changes = _make_changes(removed_modules=["legacy/"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Removed Modules (1):" in result
    assert "  legacy/" in result


def test_format_new_packages_section() -> None:
    # Arrange
    changes = _make_changes(new_packages=["middleware/", "plugins/"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "New Packages (2):" in result
    assert "  middleware/" in result
    assert "  plugins/" in result


def test_format_new_files_section() -> None:
    # Arrange
    changes = _make_changes(new_files=["data.csv", "README.md"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "New Files (2):" in result
    assert "  data.csv" in result
    assert "  README.md" in result


def test_format_removed_files_section() -> None:
    # Arrange
    changes = _make_changes(removed_files=["old_config.yml"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Removed Files (1):" in result
    assert "  old_config.yml" in result


# ---------------------------------------------------------------------------
# Omission of empty sections
# ---------------------------------------------------------------------------


def test_format_omits_empty_sections() -> None:
    # Arrange
    changes = _make_changes(
        new_api=[ApiEntry("new.py", "def func()")],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Updated API" not in result
    assert "Removed API" not in result
    assert "New Modules" not in result
    assert "Removed Modules" not in result
    assert "New API (1):" in result


# ---------------------------------------------------------------------------
# Summary line
# ---------------------------------------------------------------------------


def test_format_summary_line_counts() -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[
            ApiChange("a.py", "def f()", "def f(x)"),
            ApiChange("b.py", "def g()", "def g(y)"),
        ],
        new_api=[ApiEntry("c.py", "def h()")],
        removed_api=[ApiEntry("d.py", "def i()")],
        new_modules=["pkg/"],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "2 API updates" in result
    assert "1 new API" in result
    assert "1 removed" in result
    assert "1 new module" in result


def test_format_summary_line_singular() -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[ApiChange("a.py", "def f()", "def f(x)")],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "1 API update" in result
    assert "1 API updates" not in result


def test_format_summary_wraps_when_too_long() -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[ApiChange("a.py", "def f()", "def f(x)")],
        new_api=[ApiEntry("b.py", "def g()")],
        removed_api=[ApiEntry("c.py", "def h()")],
        new_packages=["pkg1/"],
        removed_packages=["pkg2/"],
        new_modules=["mod1.py"],
        removed_modules=["mod2.py"],
        new_files=["data.csv"],
        removed_files=["old.yml"],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", 60)

    # Assert
    summary_lines = [line for line in result.split("\n") if "\u00b7" in line]
    assert len(summary_lines) >= 2


# ---------------------------------------------------------------------------
# Banner structure
# ---------------------------------------------------------------------------


def test_format_banner_width_matches_config() -> None:
    # Arrange
    changes = _make_changes(new_modules=["pkg/"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    lines = result.split("\n")
    banner_line = lines[0]
    assert len(banner_line) == _MAX_WIDTH
    assert banner_line == "=" * _MAX_WIDTH


def test_format_header_contains_project_name() -> None:
    # Arrange
    changes = _make_changes(new_modules=["pkg/"])

    # Act
    result = format_change_summary(changes, "my_project", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Project:   my_project" in result


def test_format_header_omits_root() -> None:
    # Arrange
    changes = _make_changes(new_modules=["pkg/"])

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Root:" not in result


def test_format_header_contains_log_filename_only() -> None:
    # Arrange
    changes = _make_changes(new_modules=["pkg/"])
    log_path = "logs/structure_changes/20260318_143025.txt"

    # Act
    result = format_change_summary(changes, "scout", log_path, _MAX_WIDTH)

    # Assert
    assert "Log:       20260318_143025.txt" in result
    assert "logs/structure_changes/" not in result


def test_format_header_omits_log_when_empty() -> None:
    # Arrange
    changes = _make_changes(new_modules=["pkg/"])

    # Act
    result = format_change_summary(changes, "scout", "", _MAX_WIDTH)

    # Assert
    assert "Log:" not in result


# ---------------------------------------------------------------------------
# Grouped format
# ---------------------------------------------------------------------------


def test_format_api_changes_multiple_in_same_file() -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[
            ApiChange(
                "handlers.py",
                "def process(input)  :10",
                "def process(input, limit: int)  :42",
            ),
            ApiChange(
                "handlers.py",
                "def validate(data)  :50",
                "def validate(data, strict: bool)  :87",
            ),
        ],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "Updated API (2):" in result
    assert "handlers.py:42" in result
    assert "handlers.py:87" in result


def test_format_uses_double_arrow_separator() -> None:
    # Arrange
    changes = _make_changes(
        api_changes=[
            ApiChange("config.py", "def build() -> Config", "def build() -> Settings"),
        ],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert ">>" in result
    assert "() -> Settings" in result


def test_format_api_change_expands_long_signatures() -> None:
    # Arrange
    old_sig = (
        "def configure_pipeline(host: str, port: int, timeout: float, "
        "retries: int) -> Pipeline  :42"
    )
    new_sig = (
        "def configure_pipeline(host: str, port: int, timeout: float, "
        "retries: int, backoff: float) -> Pipeline  :42"
    )
    changes = _make_changes(
        api_changes=[ApiChange("pipeline.py", old_sig, new_sig)],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "pipeline.py:42  def configure_pipeline\n" in result
    assert ">>" in result
    assert "host: str" in result
    assert "backoff: float" in result


def test_format_api_change_wraps_at_line_width() -> None:
    # Arrange
    old_sig = (
        "def process(alpha: str, bravo: int, charlie: float, delta: bool, "
        "echo: list, foxtrot: dict) -> Result  :10"
    )
    new_sig = (
        "def process(alpha: str, bravo: int, charlie: float, delta: bool, "
        "echo: list, foxtrot: dict, golf: Path) -> Result  :10"
    )
    changes = _make_changes(
        api_changes=[ApiChange("handlers.py", old_sig, new_sig)],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    max_line_length = max(len(line) for line in result.split("\n"))
    assert max_line_length <= _MAX_WIDTH


def test_format_new_api_multiple_in_same_file() -> None:
    # Arrange
    changes = _make_changes(
        new_api=[
            ApiEntry("tracking/comparator.py", "class StructureChanges(NamedTuple)  :60"),
            ApiEntry("tracking/comparator.py", "def compare(old, new) -> StructureChanges  :204"),
        ],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "New API (2):" in result
    assert "tracking/comparator.py:60" in result
    assert "tracking/comparator.py:204" in result
    assert "class StructureChanges" in result
    assert "def compare" in result


def test_format_removed_api_strips_lineno() -> None:
    # Arrange
    changes = _make_changes(
        removed_api=[ApiEntry("utils.py", "def old_helper(x: int) -> str  :15")],
    )

    # Act
    result = format_change_summary(changes, "scout", "log.txt", _MAX_WIDTH)

    # Assert
    assert "def old_helper" in result
    assert ":15" not in result
