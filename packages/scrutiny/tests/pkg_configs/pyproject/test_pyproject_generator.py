"""Tests for PyProjectGenerator and related pyproject.toml functionality."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]


from scrutiny.config import UserDefaults
from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.configs.pyproject import PyProjectGenerator
from scrutiny.configs.resolver import ConfigResolver
from scrutiny.core.enums import ConfigTier, PythonVersion
from scrutiny.core.tool_data import (
    RUFF_IGNORE_RULES,
    RUFF_MYPY_OVERLAP,
    _build_effective_ignore_rules,
)
from scrutiny.output.logger import DeferredLogBuffer

from unittest.mock import MagicMock, patch



def _build_global_config() -> object:
    """Build a GlobalConfig with default values for testing."""
    return GlobalConfig()


def _build_gen_config(**overrides: object) -> object:
    """Build a GlobalConfig for generation testing."""
    return GlobalConfig(**overrides)


# ── _check_coverage_version ── #


@pytest.mark.unit
class TestCheckCoverageVersion:
    """Test coverage version check and deferred warnings."""

    def test_no_warning_when_coverage_sufficient(self) -> None:
        """Verify no warning is captured when coverage >= 7.2."""
        # Arrange
        DeferredLogBuffer.clear()
        mock_coverage = MagicMock()
        mock_coverage.__version__ = "7.6.1"

        # Act
        with patch.dict("sys.modules", {"coverage": mock_coverage}):
            PyProjectGenerator._check_coverage_version()

        # Assert
        messages = DeferredLogBuffer._messages
        warning_messages = [msg for msg in messages if msg[0] == "warning"]
        coverage_warnings = [msg for msg in warning_messages if "[COVERAGE]" in msg[1]]
        assert len(coverage_warnings) == 0

    def test_warning_when_coverage_below_7_2(self) -> None:
        """Verify warning is captured when coverage < 7.2."""
        # Arrange
        DeferredLogBuffer.clear()
        mock_coverage = MagicMock()
        mock_coverage.__version__ = "6.5.0"

        # Act
        with patch.dict("sys.modules", {"coverage": mock_coverage}):
            PyProjectGenerator._check_coverage_version()

        # Assert
        messages = DeferredLogBuffer._messages
        warning_messages = [msg for msg in messages if msg[0] == "warning"]
        coverage_warnings = [msg for msg in warning_messages if "[COVERAGE]" in msg[1]]
        assert len(coverage_warnings) == 1
        assert "exclude_also" in coverage_warnings[0][1]

    def test_warning_when_coverage_not_installed(self) -> None:
        """Verify warning is captured when coverage is not installed."""
        # Arrange
        DeferredLogBuffer.clear()

        # Act — simulate ImportError by removing coverage from sys.modules
        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def mock_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "coverage":
                raise ImportError("No module named 'coverage'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            PyProjectGenerator._check_coverage_version()

        # Assert
        messages = DeferredLogBuffer._messages
        warning_messages = [msg for msg in messages if msg[0] == "warning"]
        coverage_warnings = [msg for msg in warning_messages if "[COVERAGE]" in msg[1]]
        assert len(coverage_warnings) == 1
        assert "not installed" in coverage_warnings[0][1]


# ── _render_coverage_sections ── #


@pytest.mark.unit
class TestRenderCoverageSections:
    """Test coverage TOML section rendering helper."""

    def test_renders_run_and_report_sections(self) -> None:
        """Verify both run and report sections are rendered."""
        # Arrange
        coverage_settings = {
            "run": {"branch": True, "source": ["src"]},
            "report": {"show_missing": True},
        }

        # Act
        lines = PyProjectGenerator._render_coverage_sections(
            coverage_settings,
        )

        # Assert
        assert "[tool.coverage.run]" in lines
        assert "[tool.coverage.report]" in lines

    def test_list_values_render_as_toml_arrays(self) -> None:
        """Verify list values are rendered as TOML array syntax."""
        # Arrange
        coverage_settings = {
            "run": {"omit": ["tests/*", "docs/*"]},
            "report": {},
        }

        # Act
        lines = PyProjectGenerator._render_coverage_sections(
            coverage_settings,
        )

        # Assert
        omit_line = [line for line in lines if line.startswith("omit")]
        assert len(omit_line) == 1
        assert '["tests/*", "docs/*"]' in omit_line[0]

    def test_scalar_values_render_as_bare_values(self) -> None:
        """Verify non-list values are rendered without array syntax."""
        # Arrange
        coverage_settings = {
            "run": {"branch": True},
            "report": {"show_missing": True},
        }

        # Act
        lines = PyProjectGenerator._render_coverage_sections(
            coverage_settings,
        )

        # Assert
        assert "branch = True" in lines
        assert "show_missing = True" in lines


# ── _to_toml_array ── #


@pytest.mark.unit
class TestToTomlArray:
    """Test TOML array formatting helper."""

    def test_formats_tuple_as_toml_array(self) -> None:
        """Format a tuple of strings as a TOML array literal."""
        # Arrange
        items = ("E4", "E7", "E9", "F")

        # Act
        result = PyProjectGenerator._to_toml_array(items)

        # Assert
        assert result == '["E4", "E7", "E9", "F"]'

    def test_formats_empty_sequence(self) -> None:
        """Format an empty sequence as an empty TOML array."""
        # Arrange

        # Act
        result = PyProjectGenerator._to_toml_array(())

        # Assert
        assert result == "[]"

    def test_formats_single_item(self) -> None:
        """Format a single-item sequence correctly."""
        # Arrange

        # Act
        result = PyProjectGenerator._to_toml_array(["only"])

        # Assert
        assert result == '["only"]'


# ── _render_templates ── #


@pytest.mark.unit
class TestRenderTemplates:
    """Test TOML template rendering."""

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_produces_valid_toml(self) -> None:
        """Rendered template output should parse as valid TOML."""
        # Arrange
        params = _build_gen_config()

        # Act
        rendered = PyProjectGenerator._render_templates(params)

        # Assert
        parsed = tomllib.loads(rendered)
        assert "tool" in parsed
        assert "ruff" in parsed["tool"]
        assert "mypy" in parsed["tool"]

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_ruff_rules_are_lists(self) -> None:
        """Ruff select and ignore rules should parse as lists."""
        # Arrange
        params = _build_gen_config()

        # Act
        rendered = PyProjectGenerator._render_templates(params)
        parsed = tomllib.loads(rendered)

        # Assert
        lint = parsed["tool"]["ruff"]["lint"]
        assert isinstance(lint["select"], list)
        assert isinstance(lint["ignore"], list)


# ── _iter_sections ── #


@pytest.mark.unit
class TestIterSections:
    """Test splitting generated TOML into section pairs."""

    def test_splits_into_header_body_pairs(self) -> None:
        """Split TOML text into (header, body_lines) tuples."""
        # Arrange
        text = "[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n"

        # Act
        sections = PyProjectGenerator._iter_sections(text)

        # Assert
        assert len(sections) == 2
        assert sections[0][0] == "[tool.ruff]"
        assert sections[1][0] == "[tool.mypy]"

    def test_body_excludes_empty_lines(self) -> None:
        """Empty lines within sections are excluded from body."""
        # Arrange
        text = "[tool.ruff]\nline-length = 100\n\nfix = true\n"

        # Act
        sections = PyProjectGenerator._iter_sections(text)

        # Assert
        body = sections[0][1]
        assert len(body) == 2
        assert "line-length = 100" in body[0]
        assert "fix = true" in body[1]


# ── generate_or_merge ── #


@pytest.mark.unit
class TestGenerateOrMerge:
    """Test pyproject.toml creation, merging, and override."""

    def test_creates_new_file(self, tmp_path: Path) -> None:
        """Create a new pyproject.toml when none exists."""
        # Arrange
        params = _build_gen_config()

        # Act
        result = PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Assert
        assert result == "created"
        pyproject = tmp_path / "pyproject.toml"
        assert pyproject.exists()
        content = pyproject.read_text(encoding="utf-8")
        assert "[tool.ruff]" in content

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level override",
    )
    def test_override_replaces_managed_tool_sections(self, tmp_path: Path) -> None:
        """Override mode replace managed [tool.*] sections."""
        # Arrange
        params = _build_gen_config(override_config=True)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n\n[tool.ruff]\nline-length = 50\n',
            encoding="utf-8",
        )

        # Act
        result = PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Assert
        assert result == "updated"
        content = pyproject.read_text(encoding="utf-8")
        assert "[project]" in content
        parsed = tomllib.loads(content)
        assert parsed["tool"]["ruff"]["line-length"] != 50

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level override",
    )
    def test_preserves_non_tool_sections(self, tmp_path: Path) -> None:
        """Non-tool sections are preserved during override."""
        # Arrange
        params = _build_gen_config(override_config=True)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "my-project"\n\n[build-system]\nrequires = ["setuptools"]\n',
            encoding="utf-8",
        )

        # Act
        PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Assert
        content = pyproject.read_text(encoding="utf-8")
        assert "[project]" in content
        assert "[build-system]" in content

    def test_section_level_merge_adds_new_sections(self, tmp_path: Path) -> None:
        """Section-level merge adds entirely new tool sections."""
        # Arrange
        params = _build_gen_config(override_config=False)
        pyproject = tmp_path / "pyproject.toml"

        # Write a file with only [tool.ruff] - mypy section is missing.
        pyproject.write_text(
            "[tool.ruff]\nline-length = 100\n",
            encoding="utf-8",
        )

        # Force section-level fallback by patching tomli_w to None.
        import scrutiny.configs.pyproject as _pyproject_mod

        original_tomli_w = _pyproject_mod.tomli_w
        _pyproject_mod.tomli_w = None
        try:
            # Act
            result = PyProjectGenerator.generate_or_merge(tmp_path, params)
        finally:
            _pyproject_mod.tomli_w = original_tomli_w

        # Assert
        content = pyproject.read_text(encoding="utf-8")
        assert "[tool.mypy]" in content
        assert result == "updated"

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level merge",
    )
    def test_key_level_merge_adds_missing_keys(self, tmp_path: Path) -> None:
        """Key-level merge adds missing keys without overwriting existing."""
        # Arrange
        params = _build_gen_config(override_config=False)
        pyproject = tmp_path / "pyproject.toml"

        # Write with only line-length in [tool.ruff], no fix key.
        pyproject.write_text(
            "[tool.ruff]\nline-length = 80\n",
            encoding="utf-8",
        )

        # Act
        result = PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Assert
        assert result == "updated"
        content = pyproject.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)

        # Existing key should be preserved.
        assert parsed["tool"]["ruff"]["line-length"] == 80

        # New keys should be added.
        assert "fix" in parsed["tool"]["ruff"]

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level merge",
    )
    def test_key_level_merge_unchanged_when_all_keys_exist(self, tmp_path: Path) -> None:
        """Key-level merge returns unchanged when no new keys to add."""
        # Arrange
        params = _build_gen_config(override_config=False)

        # Generate once to get the full file.
        PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Act (merge again -- all keys already exist).
        result = PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Assert
        assert result == "unchanged"


# ── _deep_merge_tool_sections ── #


@pytest.mark.unit
class TestDeepMergeToolSections:
    """Test the recursive key-level merge helper."""

    def test_adds_new_section(self) -> None:
        """Add an entirely new tool section."""
        # Arrange
        existing: dict = {"tool": {"ruff": {"line-length": 100}}}
        generated: dict = {"tool": {"mypy": {"strict": True}}}

        # Act
        changed = PyProjectGenerator._deep_merge_tool_sections(
            existing,
            generated,
        )

        # Assert
        assert changed is True
        assert existing["tool"]["mypy"] == {"strict": True}

    def test_adds_missing_keys_to_existing_section(self) -> None:
        """Add missing keys without overwriting existing ones."""
        # Arrange
        existing: dict = {"tool": {"ruff": {"line-length": 80}}}
        generated: dict = {"tool": {"ruff": {"line-length": 100, "fix": True}}}

        # Act
        changed = PyProjectGenerator._deep_merge_tool_sections(
            existing,
            generated,
        )

        # Assert
        assert changed is True
        assert existing["tool"]["ruff"]["line-length"] == 80
        assert existing["tool"]["ruff"]["fix"] is True

    def test_no_change_when_all_keys_exist(self) -> None:
        """Return False when all generated keys already exist."""
        # Arrange
        existing: dict = {"tool": {"ruff": {"line-length": 80, "fix": True}}}
        generated: dict = {"tool": {"ruff": {"line-length": 100, "fix": False}}}

        # Act
        changed = PyProjectGenerator._deep_merge_tool_sections(
            existing,
            generated,
        )

        # Assert
        assert changed is False
        assert existing["tool"]["ruff"]["line-length"] == 80
        assert existing["tool"]["ruff"]["fix"] is True

    def test_creates_tool_section_when_missing(self) -> None:
        """Create the tool section when existing dict has none."""
        # Arrange
        existing: dict = {"project": {"name": "test"}}
        generated: dict = {"tool": {"ruff": {"fix": True}}}

        # Act
        changed = PyProjectGenerator._deep_merge_tool_sections(
            existing,
            generated,
        )

        # Assert
        assert changed is True
        assert existing["tool"]["ruff"]["fix"] is True

    def test_handles_nested_subsections(self) -> None:
        """Merge nested subsections like ruff -> lint."""
        # Arrange
        existing: dict = {"tool": {"ruff": {"line-length": 80, "lint": {"select": ["E4"]}}}}
        generated: dict = {"tool": {"ruff": {"lint": {"select": ["E4", "E7"], "ignore": ["W"]}}}}

        # Act
        changed = PyProjectGenerator._deep_merge_tool_sections(
            existing,
            generated,
        )

        # Assert
        assert changed is True
        # Existing key preserved.
        assert existing["tool"]["ruff"]["lint"]["select"] == ["E4"]
        # New key added.
        assert existing["tool"]["ruff"]["lint"]["ignore"] == ["W"]


# ── _to_toml_array multi-line formatting ── #


@pytest.mark.unit
class TestToTomlArrayMultiline:
    """Test multi-line TOML array formatting for long arrays."""

    def test_short_array_stays_inline(self) -> None:
        """Short array remains on a single line."""
        # Arrange
        items = ("E4", "E7", "E9")

        # Act
        result = PyProjectGenerator._to_toml_array(items)

        # Assert
        assert "\n" not in result
        assert result == '["E4", "E7", "E9"]'

    def test_long_array_becomes_multiline(self) -> None:
        """Array exceeding threshold formats with one item per line."""
        # Arrange
        items = (
            "E4",
            "E7",
            "E9",
            "F",
            "B",
            "A",
            "I",
            "N",
            "SIM",
            "C4",
            "RET",
            "PTH",
            "PERF",
            "ISC",
        )

        # Act
        result = PyProjectGenerator._to_toml_array(items)

        # Assert
        assert result.startswith("[\n")
        assert result.endswith(",\n]")
        assert '    "E4"' in result

    def test_custom_threshold_forces_multiline(self) -> None:
        """Custom max_inline_length threshold triggers multi-line."""
        # Arrange
        items = ("A", "B", "C")

        # Act
        result = PyProjectGenerator._to_toml_array(
            items,
            max_inline_length=5,
        )

        # Assert
        assert "\n" in result

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_multiline_array_parses_as_valid_toml(self) -> None:
        """Multi-line formatted array is valid TOML when embedded."""
        # Arrange
        items = tuple(f"RULE{idx}" for idx in range(20))

        # Act
        array_str = PyProjectGenerator._to_toml_array(items)
        toml_text = f"[tool.test]\nrules = {array_str}\n"
        parsed = tomllib.loads(toml_text)

        # Assert
        assert parsed["tool"]["test"]["rules"] == list(items)


# ── _override_key_level ── #


@pytest.mark.unit
class TestOverrideKeyLevel:
    """Test structured TOML override of managed sections."""

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level override",
    )
    def test_replaces_managed_preserves_unmanaged(self, tmp_path: Path) -> None:
        """Replace managed sections while keeping unmanaged ones intact."""
        # Arrange
        params = _build_gen_config()
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.ruff]\n"
            "line-length = 50\n"
            "\n"
            "[tool.pytest.ini_options]\n"
            'addopts = "-v"\n'
            "\n"
            "[tool.coverage.run]\n"
            "branch = true\n",
            encoding="utf-8",
        )
        existing_text = pyproject.read_text(encoding="utf-8")
        generated_content = PyProjectGenerator._render_templates(params)

        # Act
        result = PyProjectGenerator._override_key_level(
            pyproject,
            existing_text,
            generated_content,
        )

        # Assert
        assert result == "updated"
        content = pyproject.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
        # Managed section was replaced.
        assert parsed["tool"]["ruff"]["line-length"] != 50
        # Unmanaged sections preserved.
        assert "pytest" in parsed["tool"]
        assert "coverage" in parsed["tool"]

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level override",
    )
    def test_returns_unchanged_when_identical(self, tmp_path: Path) -> None:
        """Return unchanged when generated content matches existing."""
        # Arrange
        params = _build_gen_config()
        pyproject = tmp_path / "pyproject.toml"

        # Generate once to create the file.
        PyProjectGenerator.generate_or_merge(tmp_path, params)

        existing_text = pyproject.read_text(encoding="utf-8")
        generated_content = PyProjectGenerator._render_templates(params)

        # Act
        result = PyProjectGenerator._override_key_level(
            pyproject,
            existing_text,
            generated_content,
        )

        # Assert
        assert result == "unchanged"


# ── Override integration: generate_or_merge with override=True ── #


@pytest.mark.unit
class TestOverrideIntegration:
    """Test override behavior through generate_or_merge."""

    @pytest.mark.skipif(
        tomllib is None or tomli_w is None,
        reason="tomllib and tomli_w required for key-level override",
    )
    def test_override_preserves_unmanaged_tool_sections(
        self,
        tmp_path: Path,
    ) -> None:
        """Override with unmanaged sections present; verify they survive."""
        # Arrange
        params = _build_gen_config(override_config=True)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\n'
            "\n"
            "[tool.ruff]\nline-length = 50\n"
            "\n"
            "[tool.pytest.ini_options]\n"
            'addopts = "-v"\n'
            "\n"
            "[tool.coverage.run]\nbranch = true\n",
            encoding="utf-8",
        )

        # Act
        result = PyProjectGenerator.generate_or_merge(tmp_path, params)

        # Assert
        assert result == "updated"
        content = pyproject.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
        assert "pytest" in parsed["tool"]
        assert "coverage" in parsed["tool"]
        assert parsed["tool"]["ruff"]["line-length"] != 50

    def test_override_without_tomli_w_returns_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        """Override without tomli_w returns skipped and preserves file."""
        # Arrange
        params = _build_gen_config(override_config=True)
        pyproject = tmp_path / "pyproject.toml"
        original_content = (
            '[tool.ruff]\nline-length = 50\n\n[tool.pytest.ini_options]\naddopts = "-v"\n'
        )
        pyproject.write_text(original_content, encoding="utf-8")

        # Patch tomli_w to None to simulate missing dependency.
        import scrutiny.configs.pyproject as _pyproject_mod

        original_tomli_w = _pyproject_mod.tomli_w
        _pyproject_mod.tomli_w = None
        try:
            # Act
            result = PyProjectGenerator.generate_or_merge(tmp_path, params)
        finally:
            _pyproject_mod.tomli_w = original_tomli_w

        # Assert
        assert "skipped" in result
        assert pyproject.read_text(encoding="utf-8") == original_content


# ── Version-Gated Ignores ── #


@pytest.mark.unit
class TestVersionGatedIgnores:
    """Test version-aware ignore rule generation."""

    def test_py39_includes_up007_and_up045(self) -> None:
        """py39 target add UP007 and UP045 to effective ignore list."""
        result = _build_effective_ignore_rules(PythonVersion.PY39)
        assert "UP007" in result
        assert "UP045" in result

    def test_py310_excludes_up007_and_up045(self) -> None:
        """py310 target does NOT add UP007 and UP045."""
        result = _build_effective_ignore_rules(PythonVersion.PY310)
        assert "UP007" not in result
        assert "UP045" not in result

    def test_py311_excludes_up007_and_up045(self) -> None:
        """py311+ also excludes version-gated rules."""
        result = _build_effective_ignore_rules(PythonVersion.PY311)
        assert "UP007" not in result
        assert "UP045" not in result

    def test_unconditional_ignores_present_at_all_versions(self) -> None:
        """Unconditional ignores (TRY003, G004 etc.) present at all versions."""
        for version in PythonVersion:
            result = _build_effective_ignore_rules(version)
            assert "TRY003" in result
            assert "G004" in result

    def test_ruff_ignore_rules_does_not_contain_up007(self) -> None:
        """UP007 must NOT be in unconditional RUFF_IGNORE_RULES."""
        assert "UP007" not in RUFF_IGNORE_RULES
        assert "UP045" not in RUFF_IGNORE_RULES

    def test_ruff_ignore_rules_contains_expected_set(self) -> None:
        """RUFF_IGNORE_RULES contains only unconditional rules."""
        expected = {
            "TRY003", "TRY300", "TRY301", "TRY400",
            "G004", "RUF100",
            "D105", "D107", "D203", "D212",
        }
        assert set(RUFF_IGNORE_RULES) == expected


# ── Mypy Overlap ── #


@pytest.mark.unit
class TestMypyOverlap:
    """Test mypy overlap tracking."""

    def test_ruf013_in_mypy_overlap(self) -> None:
        """RUF013 must be tracked as a mypy overlap rule."""
        assert "RUF013" in RUFF_MYPY_OVERLAP


# ── GlobalConfig generation defaults ── #


@pytest.mark.unit
class TestGlobalConfigGenerationDefaults:
    """Test GlobalConfig defaults relevant to pyproject.toml generation."""

    def test_defaults_match_user_defaults(self) -> None:
        """GlobalConfig defaults match UserDefaults for generation fields."""
        config = GlobalConfig()
        assert config.config_tier == UserDefaults.SCR_CONFIG_TIER
        assert config.python_version == UserDefaults.SCR_PYTHON_VERSION
        assert config.line_length == UserDefaults.SCR_LINE_LENGTH

    def test_prelim_resolver_applies_cli_overrides(self) -> None:
        """ConfigResolver with empty pyproject applies CLI overrides."""
        cli_dict = {"config_tier": ConfigTier.ESSENTIAL}
        resolver = ConfigResolver(
            cli_args=cli_dict,
            pyproject_config={},
            context=None,
            tier=ConfigTier.ESSENTIAL,
        )
        config = resolver.build_global_config()
        assert config.config_tier == ConfigTier.ESSENTIAL
        assert config.framework == UserDefaults.RUFF_FRAMEWORK

    def test_prelim_resolver_empty_cli_uses_defaults(self) -> None:
        """ConfigResolver with empty CLI dict uses all UserDefaults."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            context=None,
            tier=UserDefaults.SCR_CONFIG_TIER,
        )
        config = resolver.build_global_config()
        assert config.config_tier == UserDefaults.SCR_CONFIG_TIER
        assert config.fix == UserDefaults.RUFF_FIX
        assert config.override_config == UserDefaults.SCR_OVERRIDE_CONFIG

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_render_templates_py39_includes_up007(self) -> None:
        """At py39, UP007 appears in the generated ignore list."""
        config = GlobalConfig(
            python_version=PythonVersion.PY39,
        )
        output = PyProjectGenerator._render_templates(config)
        assert "UP007" in output

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_render_templates_py310_excludes_up007(self) -> None:
        """At py310, UP007 is NOT in the generated ignore list."""
        config = GlobalConfig(
            python_version=PythonVersion.PY310,
        )
        output = PyProjectGenerator._render_templates(config)
        assert "UP007" not in output

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_render_templates_mypy_enabled_includes_ruf013(self) -> None:
        """When mypy is enabled, RUF013 appears in generated ignore list."""
        config = GlobalConfig(run_mypy=True)
        output = PyProjectGenerator._render_templates(config)
        assert "RUF013" in output

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_render_templates_mypy_disabled_excludes_ruf013(self) -> None:
        """When mypy is disabled, RUF013 is NOT in generated ignore list."""
        config = GlobalConfig(run_mypy=False)
        output = PyProjectGenerator._render_templates(config)
        assert "RUF013" not in output
