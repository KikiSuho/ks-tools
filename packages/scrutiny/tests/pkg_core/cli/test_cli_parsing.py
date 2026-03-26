"""Tests for CLI argument parsing via create_argument_parser and parse_cli_to_dict."""

from __future__ import annotations

from pathlib import Path

import pytest

from scrutiny.core.enums import (
    ConfigTier,
    FrameworkSelection,
    LoggerLevel,
    LogLocation,
    SecurityTool,
)
from scrutiny.core.cli import parse_cli_to_dict, create_argument_parser


# ── create_argument_parser ── #


@pytest.mark.unit
class TestCreateArgumentParser:
    """Test argparse parser construction and basic flag behaviour."""

    def test_default_args_no_tier(self) -> None:
        """Return None for config_tier when no tier flag is provided."""
        parser = create_argument_parser()

        args = parser.parse_args([])

        assert args.config_tier is None

    def test_essential_flag(self) -> None:
        """Set config_tier to ESSENTIAL when --essential is passed."""
        parser = create_argument_parser()

        args = parser.parse_args(["--essential"])

        assert args.config_tier is ConfigTier.ESSENTIAL

    def test_strict_flag(self) -> None:
        """Set config_tier to STRICT when --strict is passed."""
        parser = create_argument_parser()

        args = parser.parse_args(["--strict"])

        assert args.config_tier is ConfigTier.STRICT

    def test_check_only_flag(self) -> None:
        """Set check_only to True when --check-only is passed."""
        parser = create_argument_parser()

        args = parser.parse_args(["--check-only"])

        assert args.check_only is True

    def test_paths_positional(self) -> None:
        """Collect positional arguments as Path objects."""
        parser = create_argument_parser()

        args = parser.parse_args(["src", "tests/unit"])

        assert args.paths == [Path("src"), Path("tests/unit")]


# ── parse_cli_to_dict ── #


@pytest.mark.unit
class TestParseCLIToDict:
    """Test conversion of parsed CLI namespace to configuration dict."""

    def test_empty_args_returns_empty_dict(self) -> None:
        """Produce an empty dict when no flags are provided."""
        parser = create_argument_parser()
        args = parser.parse_args([])

        result = parse_cli_to_dict(args)

        assert result == {}

    def test_tier_included_when_set(self) -> None:
        """Include config_tier in dict when a tier flag is provided."""
        parser = create_argument_parser()
        args = parser.parse_args(["--strict"])

        result = parse_cli_to_dict(args)

        assert result["config_tier"] is ConfigTier.STRICT

    def test_no_ruff_disables_both_tools(self) -> None:
        """Disable both ruff formatter and linter when --no-ruff is passed."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-ruff"])

        result = parse_cli_to_dict(args)

        assert result["run_ruff_formatter"] is False
        assert result["run_ruff_linter"] is False

    def test_no_mypy_disables_mypy(self) -> None:
        """Disable mypy when --no-mypy is passed."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-mypy"])

        result = parse_cli_to_dict(args)

        assert result["run_mypy"] is False

    def test_no_parallel_sets_false(self) -> None:
        """Set parallel to False when --no-parallel is passed."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-parallel"])

        result = parse_cli_to_dict(args)

        assert result["parallel"] is False

    def test_no_log_sets_false(self) -> None:
        """Set create_log to False when --no-log is passed."""
        parser = create_argument_parser()
        args = parser.parse_args(["--no-log"])

        result = parse_cli_to_dict(args)

        assert result["create_log"] is False

    def test_exclude_dir_accumulation(self) -> None:
        """Accumulate multiple --exclude-dir values into a tuple."""
        parser = create_argument_parser()
        args = parser.parse_args(["--exclude-dir", "foo", "--exclude-dir", "bar"])

        result = parse_cli_to_dict(args)

        assert result["exclude_dirs"] == ("foo", "bar")

    def test_security_tool_enum_conversion(self) -> None:
        """Convert --security-tool string to SecurityTool enum."""
        parser = create_argument_parser()
        args = parser.parse_args(["--security-tool", "bandit"])

        result = parse_cli_to_dict(args)

        assert result["security_tool"] is SecurityTool.BANDIT

    def test_framework_enum_conversion(self) -> None:
        """Convert --framework string to FrameworkSelection enum."""
        parser = create_argument_parser()
        args = parser.parse_args(["--framework", "django"])

        result = parse_cli_to_dict(args)

        assert result["framework"] is FrameworkSelection.DJANGO

    @pytest.mark.parametrize(
        "cli_flag,expected_level",
        [
            ("-q", "QUIET"),
            ("-v", "VERBOSE"),
            ("--detailed", "DETAILED"),
        ],
    )
    def test_verbosity_flag_maps_to_logger_level(
        self,
        cli_flag: str,
        expected_level: str,
    ) -> None:
        """Map verbosity flags to the corresponding LoggerLevel enum member."""
        parser = create_argument_parser()
        args = parser.parse_args([cli_flag])

        result = parse_cli_to_dict(args)

        assert result["console_logger_level"] is getattr(LoggerLevel, expected_level)

    def test_clear_cache_flag(self) -> None:
        """Set clear_cache to True when --clear-cache is passed."""
        parser = create_argument_parser()
        args = parser.parse_args(["--clear-cache"])

        result = parse_cli_to_dict(args)

        assert result["clear_cache"] is True

    def test_clear_cache_absent_by_default(self) -> None:
        """Omit clear_cache from dict when --clear-cache is not passed."""
        parser = create_argument_parser()
        args = parser.parse_args([])

        result = parse_cli_to_dict(args)

        assert "clear_cache" not in result

    def test_log_location_enum_conversion(self) -> None:
        """Convert --log-location string to LogLocation enum."""
        parser = create_argument_parser()
        args = parser.parse_args(["--log-location", "current_dir"])

        result = parse_cli_to_dict(args)

        assert result["log_location"] is LogLocation.CURRENT_DIR

    def test_log_location_absent_by_default(self) -> None:
        """Omit log_location from dict when --log-location is not passed."""
        parser = create_argument_parser()
        args = parser.parse_args([])

        result = parse_cli_to_dict(args)

        assert "log_location" not in result
