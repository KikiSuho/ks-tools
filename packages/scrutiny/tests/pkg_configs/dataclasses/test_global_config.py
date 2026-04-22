"""Tests for GlobalConfig business logic methods."""

from __future__ import annotations

import pytest

from scrutiny.configs.resolver import ContextDetection
from scrutiny.core.enums import SecurityTool
from conftest import make_global_config


# ── GlobalConfig.get_enabled_tools ── #


@pytest.mark.unit
class TestGetEnabledTools:
    """Test tool list generation from GlobalConfig run flags."""

    def test_all_tools_enabled_returns_full_list(self) -> None:
        """Verify all five tools appear when every run flag is explicitly True."""
        # Arrange - scrutiny ships with ruff_formatter off by default, so the
        # test must opt in explicitly to assert the full-list behavior.
        expected_tool_count = 5
        global_config = make_global_config(run_ruff_formatter=True)

        # Act
        tools = global_config.get_enabled_tools(ContextDetection.CLI)

        # Assert
        assert "ruff_formatter" in tools
        assert "ruff_linter" in tools
        assert "mypy" in tools
        assert "radon" in tools
        assert len(tools) == expected_tool_count

    def test_disabled_ruff_omits_formatter_and_linter(self) -> None:
        """Verify disabling ruff removes both formatter and linter."""
        # Arrange
        global_config = make_global_config(
            run_ruff_formatter=False,
            run_ruff_linter=False,
        )

        # Act
        tools = global_config.get_enabled_tools(ContextDetection.CLI)

        # Assert
        assert "ruff_formatter" not in tools
        assert "ruff_linter" not in tools

    def test_disabled_mypy_omits_mypy(self) -> None:
        """Verify disabling mypy removes it from the tool list."""
        # Arrange
        global_config = make_global_config(run_mypy=False)

        # Act
        tools = global_config.get_enabled_tools(ContextDetection.CLI)

        # Assert
        assert "mypy" not in tools

    @pytest.mark.parametrize(
        "context",
        [
            pytest.param(ContextDetection.CI, id="ci_context"),
            pytest.param(ContextDetection.PRECOMMIT, id="precommit_context"),
        ],
    )
    def test_pipeline_context_uses_pipeline_security_tool(
        self,
        context: object,
    ) -> None:
        """Verify CI/PRECOMMIT contexts use the pipeline security tool."""
        # Arrange
        global_config = make_global_config(
            security_tool=SecurityTool.BANDIT,
            pipeline_security_tool=SecurityTool.RUFF,
        )

        # Act
        tools = global_config.get_enabled_tools(context)

        # Assert
        assert "ruff_security" in tools
        assert "bandit" not in tools

    def test_all_disabled_returns_empty_list(self) -> None:
        """Verify empty list when all run flags are False."""
        # Arrange
        global_config = make_global_config(
            run_ruff_formatter=False,
            run_ruff_linter=False,
            run_mypy=False,
            run_radon=False,
            run_security=False,
        )

        # Act
        tools = global_config.get_enabled_tools(ContextDetection.CLI)

        # Assert
        assert tools == []


# ── GlobalConfig.get_active_security_tool ── #


@pytest.mark.unit
class TestGetActiveSecurityTool:
    """Test security tool selection by execution context."""

    @pytest.mark.parametrize(
        "context",
        [
            pytest.param(ContextDetection.CI, id="ci_context"),
            pytest.param(ContextDetection.PRECOMMIT, id="precommit_context"),
        ],
    )
    def test_returns_pipeline_tool_for_pipeline_contexts(
        self,
        context: object,
    ) -> None:
        """Verify pipeline contexts return the pipeline security tool."""
        # Arrange
        global_config = make_global_config(
            security_tool=SecurityTool.BANDIT,
            pipeline_security_tool=SecurityTool.RUFF,
        )

        # Act
        result = global_config.get_active_security_tool(context)

        # Assert
        assert result == SecurityTool.RUFF

    @pytest.mark.parametrize(
        "context",
        [
            pytest.param(ContextDetection.CLI, id="cli_context"),
            pytest.param(ContextDetection.IDE, id="ide_context"),
        ],
    )
    def test_returns_default_tool_for_local_contexts(
        self,
        context: object,
    ) -> None:
        """Verify CLI/IDE contexts return the default security tool."""
        # Arrange
        global_config = make_global_config(
            security_tool=SecurityTool.BANDIT,
            pipeline_security_tool=SecurityTool.RUFF,
        )

        # Act
        result = global_config.get_active_security_tool(context)

        # Assert
        assert result == SecurityTool.BANDIT


# ── GlobalConfig.effective_fix ── #


@pytest.mark.unit
class TestEffectiveFix:
    """Test the effective_fix property combining fix and check_only flags."""

    @pytest.mark.parametrize(
        ("fix", "check_only", "expected"),
        [
            pytest.param(True, False, True, id="fix_enabled_check_off"),
            pytest.param(True, True, False, id="fix_enabled_check_on"),
            pytest.param(False, False, False, id="fix_disabled_check_off"),
            pytest.param(False, True, False, id="fix_disabled_check_on"),
        ],
    )
    def test_effective_fix_combinations(
        self,
        fix: bool,
        check_only: bool,
        expected: bool,
    ) -> None:
        """Verify fix x check_only yields the correct effective_fix value."""
        # Arrange
        global_config = make_global_config(fix=fix, check_only=check_only)

        # Act / Assert
        assert global_config.effective_fix is expected
