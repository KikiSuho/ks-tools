"""Tests for ToolExecutor handler dispatch and _append_source_context."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from scrutiny.core.exceptions import SCRConfigurationError
from scrutiny.execution.handlers import ToolExecutor
from scrutiny.output.formatting import OutputFormatter, SourceReader


@pytest.fixture(autouse=True)
def _clear_source_cache() -> Iterator[None]:
    """Clear the SourceReader file cache before and after each test."""
    SourceReader._source_cache.clear()
    yield
    SourceReader._source_cache.clear()


# ── ToolExecutor._get_handler ── #


@pytest.mark.unit
class TestToolExecutorGetHandler:
    """Test handler creation and caching in ToolExecutor."""

    @pytest.mark.parametrize(
        "tool_name",
        [
            pytest.param("ruff_formatter", id="ruff_formatter"),
            pytest.param("ruff_linter", id="ruff_linter"),
            pytest.param("mypy", id="mypy"),
            pytest.param("radon", id="radon"),
            pytest.param("bandit", id="bandit"),
            pytest.param("ruff_security", id="ruff_security"),
        ],
    )
    def test_returns_handler_for_known_tool(self, tool_name: str) -> None:
        """Return a handler instance for each recognized tool name."""
        executor = ToolExecutor(timeout=60)

        handler = executor._get_handler(tool_name)

        assert handler is not None

    def test_raises_for_unknown_tool(self) -> None:
        """Raise SCRConfigurationError for an unrecognized tool name."""
        executor = ToolExecutor(timeout=60)

        with pytest.raises(SCRConfigurationError, match="No handler for tool"):
            executor._get_handler("nonexistent_tool")

    def test_caches_handler_on_second_call(self) -> None:
        """Return the same handler instance on repeated calls."""
        executor = ToolExecutor(timeout=60)

        first = executor._get_handler("mypy")
        second = executor._get_handler("mypy")

        assert first is second

    def test_different_tools_get_different_handlers(self) -> None:
        """Different tool names produce different handler instances."""
        executor = ToolExecutor(timeout=60)

        ruff_handler = executor._get_handler("ruff_linter")
        mypy_handler = executor._get_handler("mypy")

        assert ruff_handler is not mypy_handler


# ── OutputFormatter._append_source_context ── #


@pytest.mark.unit
class TestAppendSourceContext:
    """Test source context appending with file-based and embedded sources."""

    def test_appends_from_file(self, tmp_path: object) -> None:
        """Append source lines read from a file."""
        # Arrange
        src = tmp_path / "sample.py"  # type: ignore[operator]
        src.write_text("line1\nline2\nline3\n", encoding="utf-8")
        lines: list[str] = []

        # Act
        OutputFormatter._append_source_context(
            lines,
            str(src),
            line_number=2,
            context_lines=0,
        )

        # Assert
        assert len(lines) == 1
        assert "line2" in lines[0]

    def test_appends_embedded_source(self) -> None:
        """Use embedded source code instead of reading from disk."""
        lines: list[str] = []
        embedded = "import pickle\npickle.loads(data)\n"

        OutputFormatter._append_source_context(
            lines,
            "nonexistent.py",
            line_number=1,
            embedded_source=embedded,
        )

        assert len(lines) == 2
        assert "import pickle" in lines[0]
        assert "pickle.loads" in lines[1]

    def test_embedded_source_strips_trailing_newline(self) -> None:
        """Embedded source with trailing newline does not add an empty line."""
        lines: list[str] = []
        embedded = "single line\n"

        OutputFormatter._append_source_context(
            lines,
            "any.py",
            line_number=1,
            embedded_source=embedded,
        )

        assert len(lines) == 1
        assert "single line" in lines[0]

    def test_no_source_context_for_missing_file(self) -> None:
        """No lines appended when file does not exist and no embedded source."""
        lines: list[str] = []

        OutputFormatter._append_source_context(
            lines,
            "/nonexistent/path/to/file.py",
            line_number=1,
        )

        assert lines == []
