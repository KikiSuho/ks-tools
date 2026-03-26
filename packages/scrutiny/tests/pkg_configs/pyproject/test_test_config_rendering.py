"""Tests for _render_test_config(), get_test_config_tier(), and test config CLI flags."""

from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.configs.pyproject import PyProjectGenerator
from scrutiny.core.enums import ConfigTier
from scrutiny.core.tool_data import get_test_config_tier
from scrutiny.core.cli import parse_cli_to_dict, create_argument_parser
from scrutiny.output.logger import DeferredLogBuffer


# ── get_test_config_tier ── #


@pytest.mark.unit
class TestGetTestConfigTier:
    """Test ConfigTier-to-test-tier mapping."""

    def test_essential_maps_to_relaxed(self) -> None:
        """ESSENTIAL tier maps to 'relaxed' test settings."""
        assert get_test_config_tier(ConfigTier.ESSENTIAL) == "relaxed"

    def test_standard_maps_to_relaxed(self) -> None:
        """STANDARD tier maps to 'relaxed' test settings."""
        assert get_test_config_tier(ConfigTier.STANDARD) == "relaxed"

    def test_strict_maps_to_strict(self) -> None:
        """STRICT tier maps to 'strict' test settings."""
        assert get_test_config_tier(ConfigTier.STRICT) == "strict"

    def test_insane_maps_to_strict(self) -> None:
        """INSANE tier maps to 'strict' test settings."""
        assert get_test_config_tier(ConfigTier.INSANE) == "strict"


# ── _render_test_config: relaxed vs strict ── #


@pytest.mark.unit
class TestRenderTestConfigTiers:
    """Test _render_test_config tier-dependent output."""

    def test_relaxed_tier_omits_xfail_strict(self) -> None:
        """Relaxed tier (ESSENTIAL) does not include xfail_strict."""
        config = GlobalConfig(
            config_tier=ConfigTier.ESSENTIAL,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "xfail_strict" not in joined

    def test_relaxed_tier_omits_filterwarnings(self) -> None:
        """Relaxed tier (STANDARD) does not include filterwarnings."""
        config = GlobalConfig(
            config_tier=ConfigTier.STANDARD,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "filterwarnings" not in joined

    def test_strict_tier_includes_xfail_strict(self) -> None:
        """Strict tier (STRICT) includes xfail_strict = true."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "xfail_strict = true" in joined

    def test_strict_tier_includes_filterwarnings(self) -> None:
        """Strict tier (INSANE) includes filterwarnings."""
        config = GlobalConfig(
            config_tier=ConfigTier.INSANE,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "filterwarnings" in joined

    def test_strict_tier_includes_strict_markers(self) -> None:
        """Strict tier addopts include --strict-markers."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "--strict-markers" in joined

    def test_relaxed_tier_omits_strict_markers(self) -> None:
        """Relaxed tier addopts do NOT include --strict-markers."""
        config = GlobalConfig(
            config_tier=ConfigTier.ESSENTIAL,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "--strict-markers" not in joined


# ── _render_test_config: plugin merging ── #


@pytest.mark.unit
class TestRenderTestConfigPlugins:
    """Test plugin flag effects on rendered test config."""

    def test_plugins_disabled_omits_required_plugins(self) -> None:
        """Without --include-test-plugins, no required_plugins line."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
            include_test_plugins=False,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "required_plugins" not in joined

    def test_plugins_enabled_includes_required_plugins(self) -> None:
        """With --include-test-plugins, required_plugins appears."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
            include_test_plugins=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "required_plugins" in joined
        assert "pytest-cov" in joined
        assert "pytest-xdist" in joined

    def test_plugins_enabled_adds_cov_addopts(self) -> None:
        """Plugin addopts include --cov and -n auto."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
            include_test_plugins=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "--cov" in joined
        assert "-n auto" in joined

    def test_plugins_disabled_omits_cov_addopts(self) -> None:
        """Without plugins, --cov does NOT appear in addopts."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
            include_test_plugins=False,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "--cov" not in joined


# ── _render_test_config: TOML core ── #


@pytest.mark.unit
class TestRenderTestConfigStructure:
    """Test structural correctness of rendered test config TOML."""

    def test_contains_pytest_section_header(self) -> None:
        """Output contains [tool.pytest.ini_options] header."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)

        assert "[tool.pytest.ini_options]" in lines

    def test_contains_coverage_run_header(self) -> None:
        """Output contains [tool.coverage.run] header."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)

        assert "[tool.coverage.run]" in lines

    def test_contains_coverage_report_header(self) -> None:
        """Output contains [tool.coverage.report] header."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)

        assert "[tool.coverage.report]" in lines

    def test_coverage_uses_exclude_also(self) -> None:
        """Coverage report section uses exclude_also, not exclude_lines."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "exclude_also" in joined
        assert "exclude_lines" not in joined

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_output_parses_as_valid_toml(self) -> None:
        """Rendered output is valid TOML when joined."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
            include_test_plugins=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        toml_text = "\n".join(lines)
        parsed = tomllib.loads(toml_text)

        assert "tool" in parsed
        assert "pytest" in parsed["tool"]
        assert "coverage" in parsed["tool"]

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_relaxed_output_parses_as_valid_toml(self) -> None:
        """Relaxed-tier rendered output is also valid TOML."""
        config = GlobalConfig(
            config_tier=ConfigTier.ESSENTIAL,
            include_test_config=True,
            include_test_plugins=False,
        )

        lines = PyProjectGenerator._render_test_config(config)
        toml_text = "\n".join(lines)
        parsed = tomllib.loads(toml_text)

        assert "tool" in parsed
        assert "ini_options" in parsed["tool"]["pytest"]

    def test_contains_minversion(self) -> None:
        """Output includes minversion setting."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "minversion" in joined

    def test_contains_markers(self) -> None:
        """Output includes markers definition."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        lines = PyProjectGenerator._render_test_config(config)
        joined = "\n".join(lines)

        assert "markers" in joined
        assert "unit" in joined.lower()


# ── _render_test_config: coverage version warning ── #


@pytest.mark.unit
class TestRenderTestConfigCoverageWarning:
    """Test coverage version check and deferred warning emission."""

    def test_old_coverage_emits_warning(self) -> None:
        """Coverage < 7.2 triggers a deferred warning about exclude_also."""
        # Arrange
        DeferredLogBuffer._messages.clear()
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        # Act — mock coverage.__version__ as 6.5
        mock_module = type("MockCoverage", (), {"__version__": "6.5"})()
        with patch.dict("sys.modules", {"coverage": mock_module}):
            PyProjectGenerator._render_test_config(config)

        # Assert
        warnings = [entry for entry in DeferredLogBuffer._messages if entry[0] == "warning"]
        warning_messages = [entry[1] for entry in warnings]
        assert any("exclude_also" in msg for msg in warning_messages)

    def test_missing_coverage_emits_warning(self) -> None:
        """Missing coverage package triggers a deferred warning."""
        # Arrange
        DeferredLogBuffer._messages.clear()
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
        )

        # Act — mock ImportError for coverage
        with patch.dict("sys.modules", {"coverage": None}):
            PyProjectGenerator._render_test_config(config)

        # Assert
        warnings = [entry for entry in DeferredLogBuffer._messages if entry[0] == "warning"]
        warning_messages = [entry[1] for entry in warnings]
        assert any("not installed" in msg for msg in warning_messages)


# ── _render_templates integration with include_test_config ── #


@pytest.mark.unit
class TestRenderTemplatesTestConfig:
    """Test _render_templates conditional call to _render_test_config."""

    def test_include_test_config_false_omits_pytest_section(self) -> None:
        """Default include_test_config=False omits [tool.pytest.ini_options]."""
        config = GlobalConfig(include_test_config=False)

        output = PyProjectGenerator._render_templates(config)

        assert "[tool.pytest.ini_options]" not in output

    def test_include_test_config_true_adds_pytest_section(self) -> None:
        """include_test_config=True adds [tool.pytest.ini_options]."""
        config = GlobalConfig(include_test_config=True)

        output = PyProjectGenerator._render_templates(config)

        assert "[tool.pytest.ini_options]" in output
        assert "[tool.coverage.run]" in output

    @pytest.mark.skipif(tomllib is None, reason="tomllib not available")
    def test_full_render_with_test_config_parses(self) -> None:
        """Full _render_templates with test config produces valid TOML."""
        config = GlobalConfig(
            config_tier=ConfigTier.STRICT,
            include_test_config=True,
            include_test_plugins=True,
        )

        output = PyProjectGenerator._render_templates(config)
        parsed = tomllib.loads(output)

        assert "ruff" in parsed["tool"]
        assert "pytest" in parsed["tool"]
        assert "coverage" in parsed["tool"]


# ── CLI flags: --include-test-config / --include-test-plugins ── #


@pytest.mark.unit
class TestTestConfigCLIFlags:
    """Test CLI parser and parse_cli_to_dict for test config flags."""

    def test_include_test_config_flag_accepted(self) -> None:
        """Parser accepts --include-test-config without error."""
        parser = create_argument_parser()

        args = parser.parse_args(["--include-test-config"])

        assert args.include_test_config is True

    def test_include_test_plugins_flag_accepted(self) -> None:
        """Parser accepts --include-test-plugins without error."""
        parser = create_argument_parser()

        args = parser.parse_args(["--include-test-plugins"])

        assert args.include_test_plugins is True

    def test_include_test_config_default_none(self) -> None:
        """include_test_config defaults to None when not passed."""
        parser = create_argument_parser()

        args = parser.parse_args([])

        assert args.include_test_config is None

    def test_include_test_plugins_default_none(self) -> None:
        """include_test_plugins defaults to None when not passed."""
        parser = create_argument_parser()

        args = parser.parse_args([])

        assert args.include_test_plugins is None

    def test_parse_cli_includes_test_config_when_set(self) -> None:
        """parse_cli_to_dict includes include_test_config=True when flag is set."""
        parser = create_argument_parser()
        args = parser.parse_args(["--include-test-config"])

        result = parse_cli_to_dict(args)

        assert result["include_test_config"] is True

    def test_parse_cli_includes_test_plugins_when_set(self) -> None:
        """parse_cli_to_dict includes include_test_plugins=True when flag is set."""
        parser = create_argument_parser()
        args = parser.parse_args(["--include-test-plugins"])

        result = parse_cli_to_dict(args)

        assert result["include_test_plugins"] is True

    def test_parse_cli_omits_test_config_when_unset(self) -> None:
        """parse_cli_to_dict omits include_test_config when flag is not set."""
        parser = create_argument_parser()
        args = parser.parse_args([])

        result = parse_cli_to_dict(args)

        assert "include_test_config" not in result

    def test_parse_cli_omits_test_plugins_when_unset(self) -> None:
        """parse_cli_to_dict omits include_test_plugins when flag is not set."""
        parser = create_argument_parser()
        args = parser.parse_args([])

        result = parse_cli_to_dict(args)

        assert "include_test_plugins" not in result
