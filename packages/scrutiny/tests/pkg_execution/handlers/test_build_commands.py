"""Tests for build_command output across all 5 handler classes.

Verifies that each handler produces the correct CLI tokens given specific
tool and global configurations.  Covers boolean flags, valued flags,
exclusion styles, fix modes, and file path placement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scrutiny.configs.dataclasses import (
    BanditConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.execution.handlers import (
    BanditHandler,
    MypyHandler,
    RadonCCHandler,
    RuffFormatterHandler,
    RuffHandler,
)
from conftest import make_global_config

# Shared test constants
DUMMY_FILES = [Path("src/app.py"), Path("src/utils.py")]
EFFECTIVE_ROOT = Path("/project")


# ── Helpers ── #


def _find_valued_flag(command: list[str], flag: str) -> str:
    """Return the value following *flag* in a command list.

    Parameters
    ----------
    command : list[str]
        Command token list.
    flag : str
        Flag token to locate (e.g. ``"--line-length"``).

    Returns
    -------
    str
        The token immediately after *flag*.

    Raises
    ------
    ValueError
        If *flag* is not found in *command*.
    """
    idx = command.index(flag)
    return command[idx + 1]


# ====================================== #
#          RuffHandler                    #
# ====================================== #


class TestRuffHandlerBuildCommand:
    """Verify RuffHandler.build_command produces correct ruff check tokens."""

    def _build(
        self,
        ruff_config: RuffConfig | None = None,
        files: list[Path] | None = None,
        fix_mode: bool = False,
    ) -> list[str]:
        """Build a ruff check command with sensible defaults."""
        handler = RuffHandler(60, tool_name="ruff_linter")
        return handler.build_command(
            files or DUMMY_FILES,
            ruff_config or RuffConfig(),
            make_global_config(),
            EFFECTIVE_ROOT,
            fix_mode=fix_mode,
        )

    def test_default_starts_with_ruff_check(self) -> None:
        """Default command starts with 'ruff check'."""
        command = self._build()
        assert command[:2] == ["ruff", "check"]

    def test_default_includes_json_output_format(self) -> None:
        """Check mode includes --output-format=json."""
        command = self._build(fix_mode=False)
        assert "--output-format=json" in command

    def test_fix_mode_includes_fix_flag(self) -> None:
        """Fix mode adds --fix."""
        command = self._build(fix_mode=True)
        assert "--fix" in command

    def test_fix_mode_excludes_output_format(self) -> None:
        """Fix mode omits --output-format (raw output, not JSON)."""
        command = self._build(fix_mode=True)
        assert not any(token.startswith("--output-format") for token in command)

    def test_unsafe_fixes_only_in_fix_mode(self) -> None:
        """--unsafe-fixes appears only when fix_mode=True and config enables it."""
        config = RuffConfig(unsafe_fixes=True)

        command_fix = self._build(ruff_config=config, fix_mode=True)
        command_check = self._build(ruff_config=config, fix_mode=False)

        assert "--unsafe-fixes" in command_fix
        assert "--unsafe-fixes" not in command_check

    def test_line_length_flag(self) -> None:
        """Line length is emitted as --line-length=<value>."""
        config = RuffConfig(line_length=120)
        command = self._build(ruff_config=config)
        assert "--line-length=120" in command

    def test_target_version_flag(self) -> None:
        """Target version is emitted as --target-version=<value>."""
        config = RuffConfig(target_version="py312")
        command = self._build(ruff_config=config)
        assert "--target-version=py312" in command

    def test_select_rules_comma_joined(self) -> None:
        """Select rules are comma-joined into a single --select flag."""
        config = RuffConfig(select_rules=("E", "W", "F"))
        command = self._build(ruff_config=config)
        assert "--select=E,W,F" in command

    def test_ignore_rules_comma_joined(self) -> None:
        """Ignore rules are comma-joined into a single --ignore flag."""
        config = RuffConfig(ignore_rules=("E501", "W291"))
        command = self._build(ruff_config=config)
        assert "--ignore=E501,W291" in command

    def test_no_cache_flag(self) -> None:
        """--no-cache appears when config enables it."""
        config = RuffConfig(no_cache=True)
        command = self._build(ruff_config=config)
        assert "--no-cache" in command

    def test_no_cache_absent_by_default(self) -> None:
        """--no-cache is absent when config disables it."""
        config = RuffConfig(no_cache=False)
        command = self._build(ruff_config=config)
        assert "--no-cache" not in command

    def test_exclusions_use_exclude_literal(self) -> None:
        """Ruff exclusions use '--exclude <pattern>' pairs."""
        config = RuffConfig(exclude_dirs=("vendor/",), exclude_files=("gen_*.py",))
        command = self._build(ruff_config=config)

        # Find all --exclude flags and their values
        exclusion_values = []
        for idx, token in enumerate(command):
            if token == "--exclude" and idx + 1 < len(command):
                exclusion_values.append(command[idx + 1])

        assert "vendor/" in exclusion_values
        assert "gen_*.py" in exclusion_values

    def test_files_appended_at_end(self) -> None:
        """File paths are the last tokens in the command."""
        files = [Path("a.py"), Path("b.py")]
        command = self._build(files=files)
        assert command[-2:] == ["a.py", "b.py"]

    def test_empty_select_rules_omits_flag(self) -> None:
        """Empty select_rules omits --select entirely."""
        config = RuffConfig(select_rules=())
        command = self._build(ruff_config=config)
        assert not any(token.startswith("--select") for token in command)

    def test_empty_ignore_rules_omits_flag(self) -> None:
        """Empty ignore_rules omits --ignore entirely."""
        config = RuffConfig(ignore_rules=())
        command = self._build(ruff_config=config)
        assert not any(token.startswith("--ignore") for token in command)


# ====================================== #
#       RuffFormatterHandler              #
# ====================================== #


class TestRuffFormatterHandlerBuildCommand:
    """Verify RuffFormatterHandler.build_command produces ruff format tokens."""

    def _build(
        self,
        ruff_config: RuffConfig | None = None,
        global_config_overrides: dict | None = None,
        files: list[Path] | None = None,
    ) -> list[str]:
        """Build a ruff format command with sensible defaults."""
        handler = RuffFormatterHandler(60, tool_name="ruff_formatter")
        return handler.build_command(
            files or DUMMY_FILES,
            ruff_config or RuffConfig(),
            make_global_config(**(global_config_overrides or {})),
            EFFECTIVE_ROOT,
        )

    def test_default_starts_with_ruff_format(self) -> None:
        """Default command starts with 'ruff format'."""
        command = self._build()
        assert command[:2] == ["ruff", "format"]

    def test_check_only_adds_check_flag(self) -> None:
        """check_only=True adds --check."""
        command = self._build(global_config_overrides={"check_only": True})
        assert "--check" in command

    def test_check_flag_absent_by_default(self) -> None:
        """--check is absent when check_only is False."""
        command = self._build(global_config_overrides={"check_only": False})
        assert "--check" not in command

    def test_line_length_flag(self) -> None:
        """Line length is emitted correctly."""
        config = RuffConfig(line_length=80)
        command = self._build(ruff_config=config)
        assert "--line-length=80" in command

    def test_target_version_flag(self) -> None:
        """Target version is emitted correctly."""
        config = RuffConfig(target_version="py39")
        command = self._build(ruff_config=config)
        assert "--target-version=py39" in command

    def test_exclusions_use_exclude_literal(self) -> None:
        """Formatter exclusions use '--exclude <pattern>' pairs."""
        config = RuffConfig(exclude_dirs=("vendor/",), exclude_files=())
        command = self._build(ruff_config=config)

        idx = command.index("--exclude")
        assert command[idx + 1] == "vendor/"

    def test_files_appended_at_end(self) -> None:
        """File paths are the last tokens."""
        files = [Path("x.py")]
        command = self._build(files=files)
        assert command[-1] == "x.py"

    def test_no_json_output_format(self) -> None:
        """Formatter does not emit --output-format (only linter does)."""
        command = self._build()
        assert not any(token.startswith("--output-format") for token in command)


# ====================================== #
#          MypyHandler                    #
# ====================================== #


class TestMypyHandlerBuildCommand:
    """Verify MypyHandler.build_command produces correct mypy tokens.

    Note: --no-incremental tests already exist in test_exclusion_architecture.py.
    This class covers the remaining flag variations.
    """

    def _build(
        self,
        mypy_config: MypyConfig | None = None,
        global_config_overrides: dict | None = None,
        files: list[Path] | None = None,
    ) -> list[str]:
        """Build a mypy command with sensible defaults."""
        handler = MypyHandler(60, tool_name="mypy")
        return handler.build_command(
            files or DUMMY_FILES,
            mypy_config or MypyConfig(),
            make_global_config(**(global_config_overrides or {})),
            EFFECTIVE_ROOT,
        )

    def test_starts_with_mypy(self) -> None:
        """Command starts with 'mypy'."""
        command = self._build()
        assert command[0] == "mypy"

    def test_json_output_always_present(self) -> None:
        """--output=json is always emitted."""
        command = self._build()
        assert "--output=json" in command

    def test_all_default_boolean_flags_present(self) -> None:
        """Default MypyConfig enables 6 boolean flags (not strict, not disallow_any)."""
        config = MypyConfig()
        command = self._build(mypy_config=config)

        # Default enabled flags
        assert "--warn-unreachable" in command
        assert "--ignore-missing-imports" in command
        assert "--disable-error-code=import-untyped" in command
        assert "--show-column-numbers" in command
        assert "--show-error-codes" in command

        # Default disabled flags
        assert "--strict" not in command
        assert "--disallow-untyped-globals" not in command
        assert "--disallow-any-explicit" not in command

    def test_strict_mode_all_flags_present(self) -> None:
        """Strict config includes --strict and all boolean flags."""
        config = MypyConfig(
            strict_mode=True,
            warn_unreachable=True,
            disallow_untyped_globals=True,
            disallow_any_explicit=True,
            ignore_missing_imports=True,
            disable_error_code_import_untyped=True,
            show_column_numbers=True,
            show_error_codes=True,
        )
        command = self._build(mypy_config=config)

        assert "--strict" in command
        assert "--warn-unreachable" in command
        assert "--disallow-untyped-globals" in command
        assert "--disallow-any-explicit" in command
        assert "--ignore-missing-imports" in command
        assert "--disable-error-code=import-untyped" in command
        assert "--show-column-numbers" in command
        assert "--show-error-codes" in command

    @pytest.mark.parametrize(
        ("field_name", "expected_flag"),
        [
            pytest.param("strict_mode", "--strict", id="strict"),
            pytest.param("warn_unreachable", "--warn-unreachable", id="warn_unreachable"),
            pytest.param(
                "disallow_untyped_globals",
                "--disallow-untyped-globals",
                id="disallow_untyped_globals",
            ),
            pytest.param(
                "disallow_any_explicit", "--disallow-any-explicit", id="disallow_any_explicit"
            ),
            pytest.param(
                "ignore_missing_imports", "--ignore-missing-imports", id="ignore_missing_imports"
            ),
            pytest.param(
                "disable_error_code_import_untyped",
                "--disable-error-code=import-untyped",
                id="disable_error_code",
            ),
            pytest.param("show_column_numbers", "--show-column-numbers", id="show_column_numbers"),
            pytest.param("show_error_codes", "--show-error-codes", id="show_error_codes"),
        ],
    )
    def test_individual_flag_disabled(self, field_name: str, expected_flag: str) -> None:
        """Disabling a single boolean field omits its CLI flag."""
        # Start with all flags enabled, disable the one under test
        all_enabled = {
            "strict_mode": True,
            "warn_unreachable": True,
            "disallow_untyped_globals": True,
            "disallow_any_explicit": True,
            "ignore_missing_imports": True,
            "disable_error_code_import_untyped": True,
            "show_column_numbers": True,
            "show_error_codes": True,
        }
        all_enabled[field_name] = False
        config = MypyConfig(**all_enabled)
        command = self._build(mypy_config=config)

        assert expected_flag not in command

    def test_python_version_flag(self) -> None:
        """Python version is emitted as --python-version=<value>."""
        config = MypyConfig(python_version="3.12")
        command = self._build(mypy_config=config)
        assert "--python-version=3.12" in command

    def test_exclusions_use_exclude_literal(self) -> None:
        """Mypy exclusions use '--exclude <pattern>' pairs."""
        config = MypyConfig(exclude_dirs=("migrations/",), exclude_files=())
        command = self._build(mypy_config=config)

        idx = command.index("--exclude")
        assert command[idx + 1] == "migrations/"

    def test_files_appended_at_end(self) -> None:
        """File paths are the last tokens."""
        files = [Path("mod.py")]
        command = self._build(files=files)
        assert command[-1] == "mod.py"


# ====================================== #
#          RadonCCHandler                 #
# ====================================== #


class TestRadonCCHandlerBuildCommand:
    """Verify RadonCCHandler.build_command produces correct radon cc tokens."""

    def _build(
        self,
        radon_config: RadonConfig | None = None,
        files: list[Path] | None = None,
    ) -> list[str]:
        """Build a radon cc command with sensible defaults."""
        handler = RadonCCHandler(60, tool_name="radon")
        return handler.build_command(
            files or DUMMY_FILES,
            radon_config or RadonConfig(exclude_dirs=(), exclude_files=()),
            make_global_config(),
            EFFECTIVE_ROOT,
        )

    def test_default_starts_with_radon_cc(self) -> None:
        """Default command starts with 'radon cc'."""
        command = self._build()
        assert command[:2] == ["radon", "cc"]

    def test_json_output_flag(self) -> None:
        """-j is present when json_output=True."""
        config = RadonConfig(json_output=True, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert "-j" in command

    def test_json_output_absent_when_disabled(self) -> None:
        """-j is absent when json_output=False."""
        config = RadonConfig(json_output=False, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert "-j" not in command

    def test_show_average_flag(self) -> None:
        """-a is present when show_average=True."""
        config = RadonConfig(show_average=True, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert "-a" in command

    def test_show_average_absent_when_disabled(self) -> None:
        """-a is absent when show_average=False."""
        config = RadonConfig(show_average=False, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert "-a" not in command

    def test_show_closures_flag(self) -> None:
        """--show-closures is present when show_closures=True."""
        config = RadonConfig(show_closures=True, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert "--show-closures" in command

    def test_show_closures_absent_when_disabled(self) -> None:
        """--show-closures is absent when show_closures=False."""
        config = RadonConfig(show_closures=False, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert "--show-closures" not in command

    @pytest.mark.parametrize(
        "grade",
        [
            pytest.param("A", id="grade_A"),
            pytest.param("B", id="grade_B"),
            pytest.param("C", id="grade_C"),
            pytest.param("D", id="grade_D"),
        ],
    )
    def test_minimum_complexity_flag(self, grade: str) -> None:
        """Minimum complexity is emitted as -n=<grade> (flag-map style)."""
        config = RadonConfig(minimum_complexity=grade, exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert f"-n={grade}" in command

    def test_exclusions_use_flag_map_style(self) -> None:
        """Radon exclusions use '-e=<pattern>' (NOT --exclude literal)."""
        config = RadonConfig(exclude_dirs=("test/", "vendor/"), exclude_files=("test_*.py",))
        command = self._build(radon_config=config)

        assert "-e=test/" in command
        assert "-e=vendor/" in command
        assert "-e=test_*.py" in command
        # Must NOT use --exclude literal style
        assert "--exclude" not in command

    def test_files_appended_at_end(self) -> None:
        """File paths are the last tokens."""
        files = [Path("mod.py")]
        config = RadonConfig(exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config, files=files)
        assert command[-1] == "mod.py"

    def test_no_exclusions_produces_no_exclude_flags(self) -> None:
        """Empty exclusions produce no -e flags."""
        config = RadonConfig(exclude_dirs=(), exclude_files=())
        command = self._build(radon_config=config)
        assert not any(token.startswith("-e=") for token in command)


# ====================================== #
#          BanditHandler                  #
# ====================================== #


class TestBanditHandlerBuildCommand:
    """Verify BanditHandler.build_command produces correct bandit tokens."""

    def _build(
        self,
        bandit_config: BanditConfig | None = None,
        files: list[Path] | None = None,
    ) -> list[str]:
        """Build a bandit command with sensible defaults."""
        handler = BanditHandler(60, tool_name="bandit")
        return handler.build_command(
            files or DUMMY_FILES,
            bandit_config or BanditConfig(),
            make_global_config(),
            EFFECTIVE_ROOT,
        )

    def test_default_starts_with_bandit(self) -> None:
        """Default command starts with 'bandit'."""
        command = self._build()
        assert command[0] == "bandit"

    def test_json_format_flag(self) -> None:
        """JSON format is emitted via flag map template (-f=json)."""
        command = self._build()
        assert "-f=json" in command

    def test_severity_flag(self) -> None:
        """Severity threshold is emitted as --severity-level=<value>."""
        config = BanditConfig(severity="high")
        command = self._build(bandit_config=config)
        assert "--severity-level=high" in command

    def test_confidence_flag(self) -> None:
        """Confidence threshold is emitted as --confidence-level=<value>."""
        config = BanditConfig(confidence="low")
        command = self._build(bandit_config=config)
        assert "--confidence-level=low" in command

    @pytest.mark.parametrize(
        ("severity", "confidence"),
        [
            pytest.param("low", "low", id="low_low"),
            pytest.param("medium", "medium", id="medium_medium"),
            pytest.param("high", "high", id="high_high"),
        ],
    )
    def test_severity_confidence_combinations(self, severity: str, confidence: str) -> None:
        """Various severity/confidence combos produce correct flags."""
        config = BanditConfig(severity=severity, confidence=confidence)
        command = self._build(bandit_config=config)
        assert f"--severity-level={severity}" in command
        assert f"--confidence-level={confidence}" in command

    def test_quiet_mode_flag(self) -> None:
        """-q is present when quiet=True."""
        config = BanditConfig(quiet=True)
        command = self._build(bandit_config=config)
        assert "-q" in command

    def test_quiet_absent_when_disabled(self) -> None:
        """-q is absent when quiet=False."""
        config = BanditConfig(quiet=False)
        command = self._build(bandit_config=config)
        assert "-q" not in command

    def test_skip_tests_comma_joined(self) -> None:
        """Skip tests are comma-joined into -s=<value>."""
        config = BanditConfig(skip_tests=("B101", "B601"))
        command = self._build(bandit_config=config)
        assert "-s=B101,B601" in command

    def test_empty_skip_tests_omits_flag(self) -> None:
        """Empty skip_tests omits -s entirely."""
        config = BanditConfig(skip_tests=())
        command = self._build(bandit_config=config)
        assert not any(token.startswith("-s=") for token in command)

    def test_exclusions_use_flag_map_style(self) -> None:
        """Bandit exclusions use '-x=<pattern>' (NOT --exclude literal)."""
        config = BanditConfig(exclude_dirs=("test/",), exclude_files=("conftest.py",))
        command = self._build(bandit_config=config)

        assert "-x=test/" in command
        assert "-x=conftest.py" in command
        # Must NOT use --exclude literal style
        assert "--exclude" not in command

    def test_files_appended_at_end(self) -> None:
        """File paths are the last tokens."""
        files = [Path("sec.py")]
        command = self._build(files=files)
        assert command[-1] == "sec.py"

    def test_no_exclusions_produces_no_exclude_flags(self) -> None:
        """Empty exclusions produce no -x flags."""
        config = BanditConfig(exclude_dirs=(), exclude_files=())
        command = self._build(bandit_config=config)
        assert not any(token.startswith("-x=") for token in command)

    def test_format_fallback_when_template_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to ['-f', 'json'] when flag map lacks 'format' key."""
        from scrutiny.core.tool_data import BANDIT_CLI_FLAGS
        from scrutiny.execution import handlers

        patched_flags = {k: v for k, v in BANDIT_CLI_FLAGS.items() if k != "format"}
        monkeypatch.setattr(handlers, "BANDIT_CLI_FLAGS", patched_flags)

        command = self._build()
        # Fallback: literal -f json as separate tokens
        idx = command.index("-f")
        assert command[idx + 1] == "json"
