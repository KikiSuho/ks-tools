"""Tests for ConfigResolver five-level priority chain and config builders."""

from __future__ import annotations

import pytest

from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.enums import (
    ConfigSource,
    ConfigTier,
    FrameworkSelection,
    PythonVersion,
)
from scrutiny.core.exceptions import SCRUserInputError
from scrutiny.core.tool_data import RUFF_MYPY_OVERLAP, RUFF_RULES_ESSENTIAL
from conftest import make_global_config


# ── ConfigResolver.resolve() priority chain ── #


@pytest.mark.unit
class TestConfigResolverResolve:
    """Test the five-level priority chain in ConfigResolver.resolve()."""

    def test_cli_takes_highest_priority(self) -> None:
        """Verify CLI value wins over all other sources."""
        resolver = ConfigResolver(
            cli_args={"line_length": 120},
            pyproject_config={"ruff": {"line_length": 88}},
            context=ContextDetection.IDE,
            tier=ConfigTier.STRICT,
        )
        result = resolver.resolve(
            cli_key="line_length",
            pyproject_tool="ruff",
            pyproject_key="line_length",
            script_default=100,
            tool_default=79,
        )
        assert result.value == 120
        assert result.source == ConfigSource.CLI

    def test_pyproject_overrides_script_default(self) -> None:
        """Verify pyproject.toml value wins over script and tool defaults."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": 88}},
        )
        result = resolver.resolve(
            cli_key="line_length",
            pyproject_tool="ruff",
            pyproject_key="line_length",
            script_default=100,
            tool_default=79,
        )
        assert result.value == 88
        assert result.source == ConfigSource.PYPROJECT

    def test_context_overrides_script_default(self) -> None:
        """Verify context value wins over script and tool defaults."""
        resolver = ConfigResolver(cli_args={})
        result = resolver.resolve(
            context_value="ci_value",
            script_default="script_value",
            tool_default="tool_value",
        )
        assert result.value == "ci_value"
        assert result.source == ConfigSource.CONTEXT

    def test_script_default_overrides_tool_default(self) -> None:
        """Verify script default wins over tool default."""
        resolver = ConfigResolver(cli_args={})
        result = resolver.resolve(
            script_default="from_script",
            tool_default="from_tool",
        )
        assert result.value == "from_script"
        assert result.source == ConfigSource.SCRIPT

    def test_tool_default_used_as_fallback(self) -> None:
        """Verify tool default is used when all higher sources are empty."""
        resolver = ConfigResolver(cli_args={})
        result = resolver.resolve(tool_default="fallback")
        assert result.value == "fallback"
        assert result.source == ConfigSource.TOOL_DEFAULT

    def test_returns_none_when_all_sources_empty(self) -> None:
        """Verify None is returned when no source provides a value."""
        resolver = ConfigResolver(cli_args={})
        result = resolver.resolve()
        assert result.value is None
        assert result.source == ConfigSource.TOOL_DEFAULT

    def test_pyproject_only_skips_script_default_but_uses_tool_default(self) -> None:
        """Verify pyproject-only mode skips priority 4 but uses tool_default as safety net."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_only=True,
        )
        result = resolver.resolve(
            script_default="should_be_skipped",
            tool_default="safety_net",
        )
        assert result.value == "safety_net"
        assert result.source == ConfigSource.TOOL_DEFAULT

    def test_pyproject_only_returns_none_without_tool_default(self) -> None:
        """Verify pyproject-only mode returns None when no tool_default is provided."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_only=True,
        )
        result = resolver.resolve(
            script_default="should_be_skipped",
        )
        assert result.value is None

    def test_pyproject_only_still_uses_cli(self) -> None:
        """Verify CLI still wins in pyproject-only mode."""
        resolver = ConfigResolver(
            cli_args={"key": "cli_value"},
            pyproject_only=True,
        )
        result = resolver.resolve(cli_key="key")
        assert result.value == "cli_value"
        assert result.source == ConfigSource.CLI

    def test_coerces_list_to_tuple_from_pyproject(self) -> None:
        """Verify TOML lists are coerced to tuples for frozen dataclasses."""
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff.lint": {"select_rules": ["E", "F", "W"]}},
        )
        result = resolver.resolve(
            pyproject_tool="ruff.lint",
            pyproject_key="select_rules",
        )
        assert result.value == ("E", "F", "W")
        assert isinstance(result.value, tuple)


# ── ConfigResolver._resolve_from_pyproject() ── #


@pytest.mark.unit
class TestResolveFromPyproject:
    """Test pyproject.toml lookup helper for the priority chain."""

    def test_returns_value_when_key_exists(self) -> None:
        """Verify value is returned when tool section contains the key."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": 88}},
        )

        # Act
        result = resolver._resolve_from_pyproject("ruff", "line_length")

        # Assert
        assert result is not None
        assert result.value == 88
        assert result.source == ConfigSource.PYPROJECT

    def test_coerces_list_to_tuple(self) -> None:
        """Verify TOML lists are coerced to tuples for frozen dataclasses."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff.lint": {"select": ["E", "F", "W"]}},
        )

        # Act
        result = resolver._resolve_from_pyproject("ruff.lint", "select")

        # Assert
        assert result is not None
        assert result.value == ("E", "F", "W")
        assert isinstance(result.value, tuple)

    def test_returns_none_when_tool_is_none(self) -> None:
        """Verify None is returned when pyproject_tool is None."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": 88}},
        )

        # Act
        result = resolver._resolve_from_pyproject(None, "line_length")

        # Assert
        assert result is None

    def test_returns_none_when_key_is_none(self) -> None:
        """Verify None is returned when pyproject_key is None."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": 88}},
        )

        # Act
        result = resolver._resolve_from_pyproject("ruff", None)

        # Assert
        assert result is None

    def test_returns_none_when_key_not_in_section(self) -> None:
        """Verify None is returned when key does not exist in tool section."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": 88}},
        )

        # Act
        result = resolver._resolve_from_pyproject("ruff", "nonexistent_key")

        # Assert
        assert result is None

    def test_returns_none_when_tool_section_missing(self) -> None:
        """Verify None is returned when tool section does not exist."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
        )

        # Act
        result = resolver._resolve_from_pyproject("ruff", "line_length")

        # Assert
        assert result is None

    def test_preserves_non_list_values(self) -> None:
        """Verify non-list values are returned unchanged."""
        # Arrange
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"mypy": {"strict": True}},
        )

        # Act
        result = resolver._resolve_from_pyproject("mypy", "strict")

        # Assert
        assert result is not None
        assert result.value is True
        assert not isinstance(result.value, tuple)


# ── ConfigResolver.build_ruff_config() ── #


@pytest.mark.unit
class TestConfigResolverBuildRuffConfig:
    """Test RuffConfig construction with tier rules and overlays."""

    def test_uses_tier_rules(self) -> None:
        """Verify select_rules match the configured tier."""
        global_config = make_global_config(
            config_tier=ConfigTier.ESSENTIAL,
        )
        resolver = ConfigResolver(cli_args={})
        ruff_config = resolver.build_ruff_config(global_config)
        assert ruff_config.select_rules == RUFF_RULES_ESSENTIAL

    def test_appends_framework_rules(self) -> None:
        """Verify framework overlay appends rules to the tier set."""
        global_config = make_global_config(
            config_tier=ConfigTier.STRICT,
            framework=FrameworkSelection.DJANGO,
        )
        resolver = ConfigResolver(cli_args={})
        ruff_config = resolver.build_ruff_config(global_config)
        # Django adds "DJ" to the rule set.
        assert "DJ" in ruff_config.select_rules

    def test_adds_mypy_overlap_when_mypy_enabled(self) -> None:
        """Verify mypy overlap ignores are included when mypy is enabled."""
        global_config = make_global_config(run_mypy=True)
        resolver = ConfigResolver(cli_args={})
        ruff_config = resolver.build_ruff_config(global_config)
        for overlap_rule in RUFF_MYPY_OVERLAP:
            assert overlap_rule in ruff_config.ignore_rules

    def test_no_mypy_overlap_when_mypy_disabled(self) -> None:
        """Verify mypy overlap ignores are excluded when mypy is disabled."""
        global_config = make_global_config(run_mypy=False)
        resolver = ConfigResolver(cli_args={})
        ruff_config = resolver.build_ruff_config(global_config)
        for overlap_rule in RUFF_MYPY_OVERLAP:
            assert overlap_rule not in ruff_config.ignore_rules

    def test_version_gated_ignores_for_py39(self) -> None:
        """Verify py310-gated ignores are added when targeting py39."""
        global_config = make_global_config(
            python_version=PythonVersion.PY39,
        )
        resolver = ConfigResolver(cli_args={})
        ruff_config = resolver.build_ruff_config(global_config)
        # UP007 is gated at py310, so should be ignored for py39.
        assert "UP007" in ruff_config.ignore_rules

    def test_no_version_gated_ignores_for_py310_plus(self) -> None:
        """Verify py310-gated ignores are NOT added when targeting py310+."""
        global_config = make_global_config(
            python_version=PythonVersion.PY310,
        )
        resolver = ConfigResolver(cli_args={})
        ruff_config = resolver.build_ruff_config(global_config)
        # UP007 is gated at py310, so should NOT be ignored for py310.
        assert "UP007" not in ruff_config.ignore_rules


# ── Context-aware check_only ── #


@pytest.mark.unit
class TestContextCheckOnly:
    """Test check_only auto-enable via ContextHandling."""

    def test_ci_context_enables_check_only(self) -> None:
        """Verify CI context auto-enables check_only."""
        resolver = ConfigResolver(
            cli_args={},
            context=ContextDetection.CI,
        )
        global_config = resolver.build_global_config()
        assert global_config.check_only is True

    def test_precommit_context_enables_check_only(self) -> None:
        """Verify pre-commit context auto-enables check_only."""
        resolver = ConfigResolver(
            cli_args={},
            context=ContextDetection.PRECOMMIT,
        )
        global_config = resolver.build_global_config()
        assert global_config.check_only is True

    def test_cli_context_uses_default_check_only(self) -> None:
        """Verify CLI context falls back to UserDefaults for check_only."""
        resolver = ConfigResolver(
            cli_args={},
            context=ContextDetection.CLI,
        )
        global_config = resolver.build_global_config()
        assert global_config.check_only is False


# ── R-1: Falsy CLI value resolution ── #


@pytest.mark.unit
class TestResolveFalsyCliValues:
    """Test that falsy CLI values (False, 0) are honored, not dropped."""

    def test_false_cli_value_is_honored(self) -> None:
        """CLI value of False must win over script/tool defaults."""
        resolver = ConfigResolver(
            cli_args={"check_only": False},
            tier=ConfigTier.STRICT,
        )
        result = resolver.resolve(
            cli_key="check_only",
            script_default=True,
            tool_default=True,
        )
        assert result.value is False
        assert result.source == ConfigSource.CLI

    def test_negation_flag_parallel_false_is_honored(self) -> None:
        """--no-parallel sets parallel=False in cli_dict; resolver must honor it."""
        resolver = ConfigResolver(
            cli_args={"parallel": False},
            tier=ConfigTier.STRICT,
        )
        result = resolver.resolve(
            cli_key="parallel",
            script_default=True,
            tool_default=True,
        )
        assert result.value is False
        assert result.source == ConfigSource.CLI

    def test_none_cli_value_is_correctly_skipped(self) -> None:
        """None in cli_args means 'not provided' — must fall through."""
        resolver = ConfigResolver(
            cli_args={"check_only": None},
            tier=ConfigTier.STRICT,
        )
        result = resolver.resolve(
            cli_key="check_only",
            script_default=True,
            tool_default=True,
        )
        assert result.value is True
        assert result.source == ConfigSource.SCRIPT

    def test_absent_cli_key_falls_through(self) -> None:
        """A key absent from cli_args falls through to lower priorities."""
        resolver = ConfigResolver(
            cli_args={},
            tier=ConfigTier.STRICT,
        )
        result = resolver.resolve(
            cli_key="parallel",
            script_default=True,
            tool_default=True,
        )
        assert result.value is True
        assert result.source == ConfigSource.SCRIPT
