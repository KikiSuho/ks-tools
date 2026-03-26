"""Tests for SourceReader and OutputFormatter clean-pass / context methods."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from scrutiny.configs.dataclasses import (
    BanditConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.core.enums import LoggerLevel
from scrutiny.execution.issues import RuffIssue
from scrutiny.output.formatting import OutputFormatter, SourceReader


# ── Fixtures ── #


@pytest.fixture(autouse=True)
def _clear_source_cache() -> Iterator[None]:
    """Clear the SourceReader file cache before and after each test.

    Prevents leaked state between tests that rely on cached file reads.
    """
    SourceReader._source_cache.clear()
    yield
    SourceReader._source_cache.clear()


# ====================================================================== #
#  SourceReader.read_source_context                                       #
# ====================================================================== #


@pytest.mark.unit
class TestSourceReader:
    """Test SourceReader caching and context-window behaviour."""

    def test_read_source_context_basic(self, tmp_path: object) -> None:
        """Return five formatted lines around line 5 with context_lines=2."""
        # Arrange
        src = tmp_path / "sample.py"  # type: ignore[operator]
        src.write_text(
            "\n".join(f"line {line_number}" for line_number in range(1, 11)),
            encoding="utf-8",
        )

        # Act
        result = SourceReader.read_source_context(str(src), 5, context_lines=2)

        # Assert
        assert len(result) == 5
        assert "line 3" in result[0]
        assert "line 7" in result[-1]

    def test_read_source_context_caching(self, tmp_path: object) -> None:
        """Cache file contents after the first read."""
        # Arrange
        src = tmp_path / "cached.py"  # type: ignore[operator]
        src.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
        path_str = str(src)

        # Act
        SourceReader.read_source_context(path_str, 1, context_lines=0)
        SourceReader.read_source_context(path_str, 2, context_lines=0)

        # Assert
        assert path_str in SourceReader._source_cache

    def test_read_source_context_file_not_found(self) -> None:
        """Return empty list when the file does not exist."""
        # Arrange
        bogus_path = "/nonexistent/path/to/file.py"

        # Act
        result = SourceReader.read_source_context(bogus_path, 1)

        # Assert
        assert result == []

    def test_read_source_context_near_start(self, tmp_path: object) -> None:
        """Clamp window at the file start without negative indices."""
        # Arrange
        src = tmp_path / "start.py"  # type: ignore[operator]
        src.write_text(
            "\n".join(f"line {line_number}" for line_number in range(1, 11)),
            encoding="utf-8",
        )

        # Act
        result = SourceReader.read_source_context(str(src), 1, context_lines=2)

        # Assert — window covers lines 1..3 (start clamped at 0)
        assert len(result) == 3
        assert "line 1" in result[0]

    def test_read_source_context_near_end(self, tmp_path: object) -> None:
        """Clamp window at the file end for the last line."""
        # Arrange
        src = tmp_path / "end.py"  # type: ignore[operator]
        src.write_text(
            "\n".join(f"line {line_number}" for line_number in range(1, 6)),
            encoding="utf-8",
        )

        # Act
        result = SourceReader.read_source_context(str(src), 5, context_lines=2)

        # Assert — window covers lines 3..5 (end clamped at len)
        assert len(result) == 3
        assert "line 5" in result[-1]

    def test_read_source_context_line_number_format(self, tmp_path: object) -> None:
        """Match the expected ``'      {n:>4} | {content}'`` format."""
        # Arrange
        src = tmp_path / "fmt.py"  # type: ignore[operator]
        src.write_text("hello\n", encoding="utf-8")

        # Act
        result = SourceReader.read_source_context(str(src), 1, context_lines=0)

        # Assert
        assert len(result) == 1
        expected = f"      {1:>4} | hello"
        assert result[0] == expected


# ====================================================================== #
#  OutputFormatter.get_tool_context                                        #
# ====================================================================== #


@pytest.mark.unit
class TestGetToolContext:
    """Test OutputFormatter.get_tool_context for every recognised tool."""

    def test_ruff_linter_context(self) -> None:
        """Return non-empty checked and result descriptions for ruff_linter."""
        # Arrange
        ruff_cfg = RuffConfig()

        # Act
        checked, result = OutputFormatter.get_tool_context("ruff_linter", ruff_cfg)

        # Assert
        assert checked
        assert result
        assert "rule" in checked.lower()

    def test_ruff_formatter_context(self) -> None:
        """Return formatting-related description for ruff_formatter."""
        # Arrange
        ruff_cfg = RuffConfig()

        # Act
        checked, result = OutputFormatter.get_tool_context("ruff_formatter", ruff_cfg)

        # Assert
        assert "format" in checked.lower()
        assert result

    def test_mypy_context(self) -> None:
        """Return type checking description for mypy."""
        # Arrange
        mypy_cfg = MypyConfig(strict_mode=True)

        # Act
        checked, result = OutputFormatter.get_tool_context("mypy", mypy_cfg)

        # Assert
        assert "type" in checked.lower()
        assert "error" in result.lower()

    def test_radon_context(self) -> None:
        """Return complexity description for radon."""
        # Arrange
        radon_cfg = RadonConfig()

        # Act
        checked, result = OutputFormatter.get_tool_context("radon", radon_cfg)

        # Assert
        assert "complexity" in checked.lower()
        assert "threshold" in result.lower()

    def test_bandit_context(self) -> None:
        """Return security description for bandit."""
        # Arrange
        bandit_cfg = BanditConfig(severity="high", confidence="high")

        # Act
        checked, result = OutputFormatter.get_tool_context("bandit", bandit_cfg)

        # Assert
        assert "security" in checked.lower()
        assert result

    def test_unknown_tool_returns_empty(self) -> None:
        """Return empty strings for an unrecognised tool name."""
        # Arrange / Act
        checked, result = OutputFormatter.get_tool_context("unknown_tool", None)

        # Assert
        assert checked == ""
        assert result == ""


# ====================================================================== #
#  OutputFormatter.generate_summary                                        #
# ====================================================================== #


@pytest.mark.unit
class TestGenerateSummary:
    """Test standardized summary block generation."""

    def test_basic_summary_with_no_fixes(self) -> None:
        """Summary without fixes shows Issues count instead of breakdown."""
        # Arrange / Act
        summary = OutputFormatter.generate_summary(
            "ruff_linter",
            files_processed=10,
            issues_found=3,
        )

        # Assert
        assert "[ruff_linter]" in summary
        assert "Files: 10" in summary
        assert "Issues: 3" in summary
        assert "Fixed" not in summary

    def test_summary_with_fixes_shows_breakdown(self) -> None:
        """Summary with fixes shows Found/Fixed/Remaining breakdown."""
        # Arrange / Act
        summary = OutputFormatter.generate_summary(
            "ruff_linter",
            files_processed=10,
            issues_found=5,
            issues_fixed=3,
        )

        # Assert
        assert "Found: 5" in summary
        assert "Fixed: 3" in summary
        assert "Remaining: 2" in summary

    def test_summary_with_extra_metrics(self) -> None:
        """Extra metrics are appended to the summary."""
        # Arrange / Act
        summary = OutputFormatter.generate_summary(
            "radon",
            files_processed=5,
            issues_found=0,
            extra_metrics={"Avg Complexity": "A"},
        )

        # Assert
        assert "Avg Complexity: A" in summary

    def test_summary_includes_execution_time(self) -> None:
        """Execution time is formatted with two decimal places."""
        # Arrange / Act
        summary = OutputFormatter.generate_summary(
            "mypy",
            files_processed=1,
            issues_found=0,
            execution_time=1.234,
        )

        # Assert
        assert "Time: 1.23s" in summary


# ====================================================================== #
#  OutputFormatter.format_at_level                                         #
# ====================================================================== #


@pytest.mark.unit
class TestFormatAtLevel:
    """Test verbosity-level-aware issue formatting."""

    def _make_tool_data_with_issues(self) -> dict[str, object]:
        """Build minimal tool_data with one ruff issue for testing."""
        return {
            "issues": [
                RuffIssue(
                    {
                        "code": "F401",
                        "message": "unused import",
                        "location": {"row": 1, "column": 1},
                        "filename": "test.py",
                        "fix": None,
                        "url": "",
                    },
                ),
            ],
        }

    def test_quiet_returns_empty_string(self) -> None:
        """QUIET level suppresses all issue output."""
        # Arrange
        tool_data = self._make_tool_data_with_issues()

        # Act
        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.QUIET,
            Path(),
        )

        # Assert
        assert result == ""

    def test_normal_returns_basic_output(self) -> None:
        """NORMAL level returns basic issue output."""
        # Arrange
        tool_data = self._make_tool_data_with_issues()

        # Act
        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.NORMAL,
            Path(),
        )

        # Assert
        assert result != ""
        assert "F401" in result

    def test_detailed_includes_metadata(self) -> None:
        """DETAILED level includes metadata flags."""
        # Arrange
        tool_data = self._make_tool_data_with_issues()

        # Act
        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.DETAILED,
            Path(),
        )

        # Assert
        assert result != ""
        assert "F401" in result

    def test_verbose_returns_most_detail(self) -> None:
        """VERBOSE level returns the richest format."""
        # Arrange
        tool_data = self._make_tool_data_with_issues()

        # Act
        result = OutputFormatter.format_at_level(
            "ruff_linter",
            tool_data,
            LoggerLevel.VERBOSE,
            Path(),
        )

        # Assert
        assert result != ""
        assert "F401" in result


# ====================================================================== #
#  R-2: SourceReader cache staleness after file modification              #
# ====================================================================== #


@pytest.mark.unit
class TestSourceReaderCacheStaleness:
    """Test that SourceReader cache can become stale after file modification."""

    def test_cache_returns_stale_content_after_file_modification(
        self,
        tmp_path: Path,
    ) -> None:
        """After overwriting a file, the cache still returns old content."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line_v1\n", encoding="utf-8")

        # First read populates cache.
        result_v1 = SourceReader.read_source_context(str(test_file), 1, context_lines=0)
        assert any("line_v1" in line for line in result_v1)

        # Overwrite file.
        test_file.write_text("line_v2\n", encoding="utf-8")

        # Second read returns stale cached content.
        result_v2 = SourceReader.read_source_context(str(test_file), 1, context_lines=0)
        assert any("line_v1" in line for line in result_v2)

    def test_clear_cache_allows_fresh_read(
        self,
        tmp_path: Path,
    ) -> None:
        """After clear_cache(), SourceReader reads fresh file content."""
        test_file = tmp_path / "test.py"
        test_file.write_text("line_v1\n", encoding="utf-8")

        SourceReader.read_source_context(str(test_file), 1, context_lines=0)
        test_file.write_text("line_v2\n", encoding="utf-8")

        SourceReader.clear_cache()

        result = SourceReader.read_source_context(str(test_file), 1, context_lines=0)
        assert any("line_v2" in line for line in result)
