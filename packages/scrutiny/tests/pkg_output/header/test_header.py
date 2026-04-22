"""Tests for output/header.py: banner formatting, file listing, MI ranks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scrutiny.configs.resolver import ContextDetection
from scrutiny.core.enums import FrameworkSelection, LoggerLevel
from scrutiny.main import _compute_mi_ranks
from scrutiny.output.header import (
    _format_header_normal,
    _format_header_verbose,
    _log_discovered_files,
    print_header,
)
from scrutiny.output.logger import SCRLogger
from conftest import make_global_config

# ---------------------------------------------------------------------------
# print_header — delegation and conditional sections
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrintHeader:
    """Tests for the top-level print_header dispatcher."""

    def test_emits_banner_with_project_and_tools(self) -> None:
        """Header always includes project name and tool list."""
        logger = MagicMock(spec=SCRLogger)
        logger.console_level = LoggerLevel.NORMAL
        config = make_global_config()
        root = Path("/project")

        print_header(
            logger,
            config,
            ContextDetection.CLI,
            root,
            tool_names=["ruff_linter", "mypy"],
            file_count=5,
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        # Project label shows the last component of the root path.
        assert "Project:   project" in combined
        assert "Tools:" in combined
        assert "ruff_linter, mypy" in combined

    def test_gen_status_displayed_when_provided(self) -> None:
        """Generation status line appears when gen_status is not None."""
        logger = MagicMock(spec=SCRLogger)
        logger.console_level = LoggerLevel.NORMAL
        config = make_global_config()
        root = Path("/project")

        print_header(
            logger,
            config,
            ContextDetection.CLI,
            root,
            tool_names=["mypy"],
            file_count=1,
            gen_status="updated",
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "pyproject.toml updated" in combined

    def test_gen_status_omitted_when_none(self) -> None:
        """No generation status line when gen_status is None."""
        logger = MagicMock(spec=SCRLogger)
        logger.console_level = LoggerLevel.NORMAL
        config = make_global_config()
        root = Path("/project")

        print_header(
            logger,
            config,
            ContextDetection.CLI,
            root,
            tool_names=["mypy"],
            file_count=1,
            gen_status=None,
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Config:" not in combined

    def test_verbose_level_triggers_verbose_header(self) -> None:
        """Verbose logger level includes Files: and Timeout: lines."""
        logger = MagicMock(spec=SCRLogger)
        logger.console_level = LoggerLevel.VERBOSE
        config = make_global_config()
        root = Path("/project")

        print_header(
            logger,
            config,
            ContextDetection.CLI,
            root,
            tool_names=["mypy"],
            file_count=3,
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Files:" in combined
        assert "Timeout:" in combined

    def test_discovered_files_listed_when_flag_set(self) -> None:
        """Discovered files are emitted at the detail level when the flag is True."""
        # Arrange - discovered files listing flows through logger.detail so the
        # file log (default VERBOSE) always captures it while the terminal
        # surfaces it only at --detailed or --verbose.
        logger = MagicMock(spec=SCRLogger)
        logger.console_level = LoggerLevel.NORMAL
        config = make_global_config()
        root = Path("/project")
        files = [root / "a.py", root / "b.py"]

        # Act
        print_header(
            logger,
            config,
            ContextDetection.CLI,
            root,
            tool_names=["mypy"],
            file_count=2,
            discovered_files=files,
            log_discovered_files=True,
        )

        # Assert
        detail_texts = [str(c.args[0]) for c in logger.detail.call_args_list]
        combined = "\n".join(detail_texts)
        assert "Discovered 2 Python file(s)" in combined


# ---------------------------------------------------------------------------
# _format_header_verbose — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatHeaderVerboseEdgeCases:
    """Edge-case tests for verbose header formatting."""

    def test_cache_disabled_label(self) -> None:
        """No-cache config shows 'disabled' in cache label."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(no_cache=True)

        _format_header_verbose(
            logger,
            config,
            ContextDetection.CLI,
            file_count=5,
            column_width=35,
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "disabled" in combined

    def test_clear_cache_label(self) -> None:
        """Clear-cache config shows 'clear before run' in cache label."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(clear_cache=True)

        _format_header_verbose(
            logger,
            config,
            ContextDetection.CLI,
            file_count=5,
            column_width=35,
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "clear before run" in combined

    def test_framework_shows_none_when_unset(self) -> None:
        """Framework line shows 'none' when framework is NONE."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(framework=FrameworkSelection.NONE)

        _format_header_verbose(
            logger,
            config,
            ContextDetection.CLI,
            file_count=1,
            column_width=35,
        )

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Framework: none" in combined


# ---------------------------------------------------------------------------
# _format_header_normal — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatHeaderNormalEdgeCases:
    """Edge-case tests for normal header formatting."""

    def test_framework_shown_when_set(self) -> None:
        """Framework line shows the active framework."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(framework=FrameworkSelection.DJANGO)

        _format_header_normal(logger, config, ContextDetection.CLI)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Framework:" in combined
        assert "django" in combined

    def test_framework_shows_none_when_unset(self) -> None:
        """Framework line shows 'none' when framework is NONE."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(framework=FrameworkSelection.NONE)

        _format_header_normal(logger, config, ContextDetection.CLI)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Framework: none" in combined

    def test_mode_pyproject(self) -> None:
        """Mode shows 'pyproject' when pyproject_only and config found."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(pyproject_only=True)

        _format_header_normal(logger, config, ContextDetection.CLI, pyproject_has_config=True)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Mode:      pyproject" in combined

    def test_mode_standard(self) -> None:
        """Mode shows 'standard' when full chain and pyproject found."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(pyproject_only=False)

        _format_header_normal(logger, config, ContextDetection.CLI, pyproject_has_config=True)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Mode:      standard" in combined

    def test_mode_defaults_no_pyproject(self) -> None:
        """Mode shows 'defaults' when no pyproject tool config found."""
        logger = MagicMock(spec=SCRLogger)
        config = make_global_config(pyproject_only=True)

        _format_header_normal(logger, config, ContextDetection.CLI, pyproject_has_config=False)

        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        combined = "\n".join(header_texts)
        assert "Mode:      defaults" in combined


# ---------------------------------------------------------------------------
# _log_discovered_files — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLogDiscoveredFilesEdgeCases:
    """Edge-case tests for the discovered-files listing."""

    def test_single_file_renders_one_row(self) -> None:
        """A single file produces exactly one row plus the count line."""
        # Arrange
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")
        files = [root / "single.py"]

        # Act
        _log_discovered_files(logger, files, root, mi_ranks=None)

        # Assert
        detail_texts = [str(c.args[0]) for c in logger.detail.call_args_list]
        combined = "\n".join(detail_texts)
        assert "Discovered 1 Python file(s)" in combined
        assert "single.py" in combined

    def test_odd_file_count_balanced_columns(self) -> None:
        """Odd number of files produces balanced two-column layout."""
        # Arrange
        logger = MagicMock(spec=SCRLogger)
        root = Path("/project")
        files = [root / f"mod{index}.py" for index in range(3)]

        # Act
        _log_discovered_files(logger, files, root, mi_ranks=None)

        # Assert
        detail_texts = [str(c.args[0]) for c in logger.detail.call_args_list]
        combined = "\n".join(detail_texts)
        assert "mod0.py" in combined
        assert "mod1.py" in combined
        assert "mod2.py" in combined


# ---------------------------------------------------------------------------
# _compute_mi_ranks — edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeMiRanksEdgeCases:
    """Edge-case tests for MI rank computation."""

    def test_returns_none_without_radon(self) -> None:
        """Returns None when radon is not in tool_names."""
        result = _compute_mi_ranks(
            tool_names=["mypy", "ruff_linter"],
            discovered_files=[Path("/fake.py")],
            effective_root=Path("/"),
            global_config=make_global_config(),
        )
        assert result is None

    @pytest.mark.parametrize(
        "tool_list",
        [
            pytest.param(["ruff_linter"], id="single_non_radon"),
            pytest.param([], id="empty_list"),
        ],
    )
    def test_returns_none_for_non_radon_lists(self, tool_list: list[str]) -> None:
        """Returns None for any tool list that does not include radon."""
        result = _compute_mi_ranks(
            tool_names=tool_list,
            discovered_files=[],
            effective_root=Path("/"),
            global_config=make_global_config(),
        )
        assert result is None


# ---------------------------------------------------------------------------
# Integration: print_header end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPrintHeaderIntegration:
    """Integration test for the full header rendering workflow."""

    def _run_verbose_header(self) -> str:
        """Run print_header with verbose config and return combined output."""
        logger = MagicMock(spec=SCRLogger)
        logger.console_level = LoggerLevel.VERBOSE
        config = make_global_config(
            framework=FrameworkSelection.DJANGO,
            pyproject_only=True,
            run_security=True,
        )
        root = Path("/project")
        files = [root / "app.py", root / "models.py"]

        print_header(
            logger,
            config,
            ContextDetection.IDE,
            root,
            tool_names=["ruff_linter", "mypy", "bandit"],
            file_count=2,
            discovered_files=files,
            log_discovered_files=True,
            gen_status="created",
            pyproject_has_config=True,
        )

        # Concatenate both header-level banner text and detail-level file
        # listing so integration tests can assert on the full rendered run
        # output regardless of the log method used internally.
        header_texts = [str(c.args[0]) for c in logger.header.call_args_list]
        detail_texts = [str(c.args[0]) for c in logger.detail.call_args_list]
        return "\n".join((*header_texts, *detail_texts))

    def test_verbose_header_includes_banner(self) -> None:
        """Full verbose header includes banner with project name."""
        combined = self._run_verbose_header()
        assert "Code Quality Analysis" in combined
        assert "Project:   project" in combined

    def test_verbose_header_includes_details(self) -> None:
        """Full verbose header includes tier, files, timeout."""
        combined = self._run_verbose_header()
        assert "Tier:" in combined
        assert "Files:" in combined
        assert "Timeout:" in combined

    def test_verbose_header_includes_conditional_sections(self) -> None:
        """Full verbose header includes framework, mode, and gen_status."""
        combined = self._run_verbose_header()
        assert "django" in combined.lower()
        assert "Mode:      pyproject" in combined
        assert "pyproject.toml created" in combined

    def test_verbose_header_includes_discovered_files(self) -> None:
        """Full verbose header includes discovered file listing."""
        combined = self._run_verbose_header()
        assert "Discovered 2 Python file(s)" in combined
        assert "app.py" in combined
