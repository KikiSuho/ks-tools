"""Handler-level suppression tests for pyproject-authoritative behavior.

Each build_command is exercised against a GlobalConfig carrying
``pyproject_native_pairs`` that mimics what the loader produces in
production.  When a native key is present, the handler must not emit the
corresponding scrutiny-built CLI flag; when ``cli_override_keys`` claims
the same scrutiny key, the flag must be emitted regardless.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scrutiny.configs.dataclasses import (
    BanditConfig,
    GlobalConfig,
    MypyConfig,
    RuffConfig,
)
from scrutiny.execution.handlers import (
    BanditHandler,
    MypyHandler,
    RuffFormatterHandler,
    RuffHandler,
)


def _global_with_pyproject(
    *pairs: tuple[str, str],
    cli_override_keys: frozenset[str] = frozenset(),
    is_pyproject_only: bool = False,
) -> GlobalConfig:
    """
    Build a GlobalConfig with explicit provenance state for handler tests.

    Parameters
    ----------
    *pairs : tuple[str, str]
        ``(pyproject_section, native_key)`` tuples representing native
        keys observed in a user's pyproject.toml (e.g. ``("ruff",
        "exclude")`` to simulate ``[tool.ruff] exclude = [...]``).
    cli_override_keys : frozenset[str]
        Scrutiny-internal keys the user explicitly passed on the CLI.
        Defaults to an empty set so tests assert the pyproject-owned path.
    is_pyproject_only : bool
        Whether ``--pyproject-only`` mode is active.

    Returns
    -------
    GlobalConfig
        Minimal configuration with provenance fields populated for
        ``should_emit`` resolution.

    """
    return GlobalConfig(
        cli_override_keys=cli_override_keys,
        pyproject_native_pairs=frozenset(pairs),
        pyproject_only=is_pyproject_only,
    )


# ====================================== #
#           RUFF HANDLER                 #
# ====================================== #


@pytest.mark.unit
class TestRuffHandlerPyprojectAware:
    """RuffHandler.build_command suppresses CLI flags covered by pyproject."""

    def test_line_length_omitted_when_pyproject_has_line_length(self) -> None:
        """--line-length is suppressed when [tool.ruff] line-length is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("ruff", "line-length"))
        ruff_config = RuffConfig(line_length=80)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert not any(token.startswith("--line-length=") for token in command)

    def test_line_length_emitted_when_cli_overrides_pyproject(self) -> None:
        """User's --line-length on scrutiny CLI wins over pyproject coverage."""
        # Arrange
        global_config = _global_with_pyproject(
            ("ruff", "line-length"),
            cli_override_keys=frozenset({"line_length"}),
        )
        ruff_config = RuffConfig(line_length=95)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert "--line-length=95" in command

    def test_select_omitted_when_pyproject_has_select(self) -> None:
        """--select is suppressed when [tool.ruff.lint] select is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("ruff.lint", "select"))
        ruff_config = RuffConfig(select_rules=("E", "F"))
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert not any(token.startswith("--select=") for token in command)

    def test_ignore_omitted_when_pyproject_has_ignore(self) -> None:
        """--ignore is suppressed when [tool.ruff.lint] ignore is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("ruff.lint", "ignore"))
        ruff_config = RuffConfig(ignore_rules=("E501",))
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert not any(token.startswith("--ignore=") for token in command)

    def test_exclude_flags_omitted_when_pyproject_has_exclude(self) -> None:
        """All --exclude tokens are suppressed when [tool.ruff] exclude is set."""
        # Arrange
        global_config = _global_with_pyproject(("ruff", "exclude"))
        ruff_config = RuffConfig(exclude_dirs=("tests",), exclude_files=("*_original.py",))
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert "--exclude" not in command

    def test_fix_omitted_when_pyproject_has_fix(self) -> None:
        """--fix is suppressed in fix_mode when [tool.ruff] fix is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("ruff", "fix"))
        ruff_config = RuffConfig(fix=True)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(), fix_mode=True,
        )

        # Assert
        assert "--fix" not in command

    def test_unsafe_fixes_omitted_when_pyproject_has_unsafe_fixes(self) -> None:
        """--unsafe-fixes is suppressed when pyproject owns unsafe-fixes."""
        # Arrange
        global_config = _global_with_pyproject(("ruff", "unsafe-fixes"))
        ruff_config = RuffConfig(unsafe_fixes=True)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(), fix_mode=True,
        )

        # Assert
        assert "--unsafe-fixes" not in command

    def test_no_cache_emits_in_pyproject_only_mode(self) -> None:
        """Operational flags with no pyproject equivalent survive pyproject_only mode."""
        # Arrange
        global_config = _global_with_pyproject(is_pyproject_only=True)
        ruff_config = RuffConfig(no_cache=True)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert - no_cache has no [tool.ruff] equivalent; pyproject_only must
        # not suppress it since it cannot shadow a user setting.
        assert "--no-cache" in command

    def test_pyproject_only_suppresses_every_flag_except_cli_and_operational(self) -> None:
        """pyproject_only=True suppresses non-CLI flags even when pyproject is empty."""
        # Arrange
        global_config = _global_with_pyproject(is_pyproject_only=True)
        ruff_config = RuffConfig(line_length=80, select_rules=("E",), ignore_rules=("F401",))
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert - config-shadowing flags are suppressed; the ruff subcommand,
        # the hardcoded --output-format=json, and the file list are the only
        # tokens that survive in this scenario.
        assert "--output-format=json" in command
        assert not any(token.startswith("--line-length=") for token in command)
        assert not any(token.startswith("--select=") for token in command)
        assert not any(token.startswith("--ignore=") for token in command)
        assert not any(token.startswith("--target-version=") for token in command)
        assert "--exclude" not in command


# ====================================== #
#       RUFF FORMATTER HANDLER           #
# ====================================== #


@pytest.mark.unit
class TestRuffFormatterHandlerPyprojectAware:
    """RuffFormatterHandler.build_command follows the same suppression rules."""

    def test_exclude_omitted_when_pyproject_has_exclude(self) -> None:
        """--exclude suppressed when [tool.ruff] exclude is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("ruff", "exclude"))
        ruff_config = RuffConfig(exclude_dirs=("tests",))
        handler = RuffFormatterHandler(tool_name="ruff_formatter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert "--exclude" not in command

    def test_line_length_omitted_when_pyproject_has_line_length(self) -> None:
        """--line-length suppressed when [tool.ruff] line-length is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("ruff", "line-length"))
        ruff_config = RuffConfig(line_length=80)
        handler = RuffFormatterHandler(tool_name="ruff_formatter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert
        assert not any(token.startswith("--line-length=") for token in command)


# ====================================== #
#           MYPY HANDLER                 #
# ====================================== #


@pytest.mark.unit
class TestMypyHandlerPyprojectAware:
    """MypyHandler.build_command suppresses flags covered by [tool.mypy]."""

    def test_strict_omitted_when_pyproject_has_strict(self) -> None:
        """--strict suppressed when [tool.mypy] strict is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("mypy", "strict"))
        mypy_config = MypyConfig(strict_mode=True)
        handler = MypyHandler(tool_name="mypy")

        # Act
        command = handler.build_command(
            [Path("sample.py")], mypy_config, global_config, Path.cwd(),
        )

        # Assert
        assert "--strict" not in command

    def test_python_version_omitted_when_pyproject_has_python_version(self) -> None:
        """--python-version suppressed when [tool.mypy] python_version is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("mypy", "python_version"))
        mypy_config = MypyConfig(python_version="3.11")
        handler = MypyHandler(tool_name="mypy")

        # Act
        command = handler.build_command(
            [Path("sample.py")], mypy_config, global_config, Path.cwd(),
        )

        # Assert
        assert not any(token.startswith("--python-version=") for token in command)

    def test_exclude_omitted_when_pyproject_has_exclude(self) -> None:
        """--exclude suppressed when [tool.mypy] exclude is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("mypy", "exclude"))
        mypy_config = MypyConfig(exclude_dirs=("tests",))
        handler = MypyHandler(tool_name="mypy")

        # Act
        command = handler.build_command(
            [Path("sample.py")], mypy_config, global_config, Path.cwd(),
        )

        # Assert
        assert "--exclude" not in command


# ====================================== #
#          BANDIT HANDLER                #
# ====================================== #


@pytest.mark.unit
class TestBanditHandlerPyprojectAware:
    """BanditHandler.build_command suppresses flags covered by [tool.bandit]."""

    def test_exclude_omitted_when_pyproject_has_exclude_dirs(self) -> None:
        """Exclude flags suppressed when [tool.bandit] exclude_dirs is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("bandit", "exclude_dirs"))
        bandit_config = BanditConfig(exclude_dirs=("tests",))
        handler = BanditHandler(tool_name="bandit")

        # Act
        command = handler.build_command(
            [Path("sample.py")], bandit_config, global_config, Path.cwd(),
        )

        # Assert - bandit's exclude flag uses -x={value}; suppress the whole family.
        assert not any(token.startswith("-x=") for token in command)

    def test_skip_tests_omitted_when_pyproject_has_skips(self) -> None:
        """-s={value} suppressed when [tool.bandit] skips is set natively."""
        # Arrange
        global_config = _global_with_pyproject(("bandit", "skips"))
        bandit_config = BanditConfig(skip_tests=("B101",))
        handler = BanditHandler(tool_name="bandit")

        # Act
        command = handler.build_command(
            [Path("sample.py")], bandit_config, global_config, Path.cwd(),
        )

        # Assert
        assert not any(token.startswith("-s=") for token in command)


# ====================================== #
#       DEFAULT BACKWARDS COMPAT         #
# ====================================== #


@pytest.mark.unit
class TestHandlerDefaultBackwardsCompatibility:
    """With empty provenance (cold start), handlers emit the full flag set."""

    def test_ruff_handler_default_emits_all_flags(self) -> None:
        """Empty pyproject_native_pairs means no suppression; flags match legacy output."""
        # Arrange
        global_config = GlobalConfig()
        ruff_config = RuffConfig(line_length=100, select_rules=("E", "F"))
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")], ruff_config, global_config, Path.cwd(),
        )

        # Assert - flags that were emitted before the refactor are still emitted.
        assert "--line-length=100" in command
        assert any(token.startswith("--select=") for token in command)
