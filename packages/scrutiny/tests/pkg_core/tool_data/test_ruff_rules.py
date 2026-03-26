"""Tests for Ruff rule composition and version-gated ignore logic."""

from __future__ import annotations

import pytest

from scrutiny.core.enums import ConfigTier, FrameworkSelection, PythonVersion
from scrutiny.core.tool_data import _build_effective_ignore_rules, build_ruff_rules


# ── _build_effective_ignore_rules ── #


@pytest.mark.unit
class TestBuildEffectiveIgnoreRules:
    """Test version-gated and unconditional ignore rule composition."""

    def test_py39_includes_version_gated_rules(self) -> None:
        """PY39 is below py310, so UP007/UP045 should be in the ignore list."""
        # Arrange / Act
        ignore_rules = _build_effective_ignore_rules(PythonVersion.PY39)

        # Assert
        assert "UP007" in ignore_rules
        assert "UP045" in ignore_rules

    def test_py313_excludes_version_gated_rules(self) -> None:
        """PY313 is above py310, so UP007/UP045 should NOT be ignored."""
        # Arrange / Act
        ignore_rules = _build_effective_ignore_rules(PythonVersion.PY313)

        # Assert
        assert "UP007" not in ignore_rules
        assert "UP045" not in ignore_rules

    def test_always_includes_unconditional_ignores(self) -> None:
        """TRY003 and other unconditional rules are always present."""
        # Arrange / Act
        ignore_rules = _build_effective_ignore_rules(PythonVersion.PY313)

        # Assert
        assert "TRY003" in ignore_rules
        assert "RUF100" in ignore_rules


# ── build_ruff_rules ── #


@pytest.mark.unit
class TestBuildRuffRules:
    """Test tier + framework + version + mypy rule composition."""

    def test_essential_tier_returns_essential_rules(self) -> None:
        """Essential tier should contain F (pyflakes) rules."""
        # Arrange / Act
        select_rules, _ignore_rules = build_ruff_rules(
            ConfigTier.ESSENTIAL,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            run_mypy=False,
        )

        # Assert
        assert "F" in select_rules
        assert "B" not in select_rules

    def test_strict_tier_includes_standard_and_strict_rules(self) -> None:
        """Strict tier should contain both standard (B, I) and strict (ARG) rules."""
        # Arrange / Act
        select_rules, _ignore_rules = build_ruff_rules(
            ConfigTier.STRICT,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            run_mypy=False,
        )

        # Assert
        assert "F" in select_rules
        assert "B" in select_rules
        assert "ARG" in select_rules

    def test_framework_rules_appended_when_django(self) -> None:
        """Django framework adds DJ rules to the select list."""
        # Arrange / Act
        select_rules, _ignore_rules = build_ruff_rules(
            ConfigTier.STANDARD,
            FrameworkSelection.DJANGO,
            PythonVersion.PY39,
            run_mypy=False,
        )

        # Assert
        assert "DJ" in select_rules

    def test_no_framework_rules_when_none(self) -> None:
        """No framework-specific rules when FrameworkSelection.NONE."""
        # Arrange / Act
        select_rules, _ignore_rules = build_ruff_rules(
            ConfigTier.STANDARD,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            run_mypy=False,
        )

        # Assert
        assert "DJ" not in select_rules
        assert "FAST" not in select_rules
        assert "PD" not in select_rules

    def test_mypy_overlap_rules_added_when_mypy_enabled(self) -> None:
        """When mypy runs, RUF013 should be in the ignore list."""
        # Arrange / Act
        _select_rules, ignore_rules = build_ruff_rules(
            ConfigTier.STRICT,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            run_mypy=True,
        )

        # Assert
        assert "RUF013" in ignore_rules

    def test_no_mypy_overlap_when_mypy_disabled(self) -> None:
        """Without mypy, RUF013 should NOT be in the ignore list."""
        # Arrange / Act
        _select_rules, ignore_rules = build_ruff_rules(
            ConfigTier.STRICT,
            FrameworkSelection.NONE,
            PythonVersion.PY39,
            run_mypy=False,
        )

        # Assert
        assert "RUF013" not in ignore_rules
