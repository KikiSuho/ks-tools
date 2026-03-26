"""Tests for PyProjectLoader: find, load, extract, and key-mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from scrutiny.configs.pyproject import PyProjectLoader
from scrutiny.core.exceptions import SCRConfigurationError


# ── find_pyproject_toml ── #


@pytest.mark.unit
class TestFindPyprojectToml:
    """Test upward search for pyproject.toml."""

    def test_finds_in_start_directory(self, tmp_path: Path) -> None:
        """Find pyproject.toml when it exists in the start directory."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\n", encoding="utf-8")

        result = PyProjectLoader.find_pyproject_toml(tmp_path)

        assert result == pyproject

    def test_finds_in_parent_directory(self, tmp_path: Path) -> None:
        """Find pyproject.toml in a parent directory."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\n", encoding="utf-8")
        child = tmp_path / "src" / "app"
        child.mkdir(parents=True)

        result = PyProjectLoader.find_pyproject_toml(child)

        assert result == pyproject

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        """Return None when pyproject.toml does not exist."""
        child = tmp_path / "deep" / "nested"
        child.mkdir(parents=True)

        result = PyProjectLoader.find_pyproject_toml(child, max_depth=2)

        assert result is None

    def test_respects_max_depth(self, tmp_path: Path) -> None:
        """Stop searching after max_depth parent directories."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\n", encoding="utf-8")
        deep = tmp_path / "a" / "b" / "c" / "d" / "e" / "f"
        deep.mkdir(parents=True)

        # max_depth=2 means search at most 2 parents; file is 6 levels up
        result = PyProjectLoader.find_pyproject_toml(deep, max_depth=2)

        assert result is None

    def test_accepts_file_path_as_start(self, tmp_path: Path) -> None:
        """Accept a file path and search from its parent directory."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\n", encoding="utf-8")
        source_file = tmp_path / "app.py"
        source_file.write_text("x = 1\n", encoding="utf-8")

        result = PyProjectLoader.find_pyproject_toml(source_file)

        assert result == pyproject


# ── load_from_path ── #


@pytest.mark.unit
class TestLoadFromPath:
    """Test parsing pyproject.toml from a file path."""

    def test_loads_valid_toml(self, tmp_path: Path) -> None:
        """Parse a valid TOML file and return dict."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n\n[tool.ruff]\nline-length = 100\n',
            encoding="utf-8",
        )

        data = PyProjectLoader.load_from_path(pyproject)

        assert data["project"]["name"] == "test"
        assert data["tool"]["ruff"]["line-length"] == 100

    def test_raises_on_nonexistent_file(self, tmp_path: Path) -> None:
        """Raise SCRConfigurationError for missing file."""
        missing = tmp_path / "nonexistent.toml"

        with pytest.raises(SCRConfigurationError, match="not found"):
            PyProjectLoader.load_from_path(missing)

    def test_raises_on_invalid_toml(self, tmp_path: Path) -> None:
        """Raise SCRConfigurationError for malformed TOML."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[invalid\n", encoding="utf-8")

        with pytest.raises(SCRConfigurationError, match="Failed to parse"):
            PyProjectLoader.load_from_path(pyproject)


# ── extract_tool_config ── #


@pytest.mark.unit
class TestExtractToolConfig:
    """Test tool section extraction from parsed TOML data."""

    def test_extracts_flat_tool_section(self) -> None:
        """Extract a flat tool section like [tool.ruff]."""
        data = {"tool": {"ruff": {"line-length": 100, "fix": True}}}

        result = PyProjectLoader.extract_tool_config(data, "ruff")

        assert result == {"line-length": 100, "fix": True}

    def test_extracts_dotted_tool_section(self) -> None:
        """Extract a nested section like [tool.ruff.lint]."""
        data = {"tool": {"ruff": {"lint": {"select": ["E", "F"]}}}}

        result = PyProjectLoader.extract_tool_config(data, "ruff.lint")

        assert result == {"select": ["E", "F"]}

    def test_returns_empty_dict_when_tool_missing(self) -> None:
        """Return empty dict when tool section does not exist."""
        data = {"tool": {"ruff": {"fix": True}}}

        result = PyProjectLoader.extract_tool_config(data, "mypy")

        assert result == {}

    def test_returns_empty_dict_when_no_tool_section(self) -> None:
        """Return empty dict when there is no [tool] section at all."""
        data = {"project": {"name": "test"}}

        result = PyProjectLoader.extract_tool_config(data, "ruff")

        assert result == {}

    def test_returns_empty_dict_for_non_dict_leaf(self) -> None:
        """Return empty dict when the leaf value is not a dict."""
        data = {"tool": {"ruff": {"line-length": 100}}}

        # "ruff.line-length" resolves to 100 (an int), not a dict
        result = PyProjectLoader.extract_tool_config(data, "ruff.line-length")

        assert result == {}


# ── map_to_internal_keys ── #


@pytest.mark.unit
class TestMapToInternalKeys:
    """Test TOML native key to internal key mapping."""

    def test_maps_ruff_keys(self) -> None:
        """Map ruff native keys to internal equivalents."""
        native = {"line-length": 100, "target-version": "py39", "fix": True}

        result = PyProjectLoader.map_to_internal_keys("ruff", native)

        assert result == {
            "line_length": 100,
            "python_version": "py39",
            "fix": True,
        }

    def test_maps_ruff_lint_keys(self) -> None:
        """Map ruff.lint native keys to internal equivalents."""
        native = {"select": ["E", "F"], "ignore": ["W"]}

        result = PyProjectLoader.map_to_internal_keys("ruff.lint", native)

        assert result == {"select_rules": ["E", "F"], "ignore_rules": ["W"]}

    def test_ignores_unknown_native_keys(self) -> None:
        """Silently ignore native keys not in PYPROJECT_KEY_MAP."""
        native = {"line-length": 100, "unknown-key": "value"}

        result = PyProjectLoader.map_to_internal_keys("ruff", native)

        assert "unknown-key" not in result
        assert "unknown_key" not in result
        assert result == {"line_length": 100}

    def test_unknown_tool_returns_empty(self) -> None:
        """Return empty dict for a tool with no key mapping."""
        native = {"some_key": "value"}

        result = PyProjectLoader.map_to_internal_keys("unknown_tool", native)

        assert result == {}

    def test_maps_mypy_keys(self) -> None:
        """Map mypy native keys to internal equivalents."""
        native = {"strict": True, "python_version": "3.9"}

        result = PyProjectLoader.map_to_internal_keys("mypy", native)

        assert result == {
            "strict_mode": True,
            "python_version_dotted": "3.9",
        }
