"""Regression tests for pyproject.toml authoritative priority chain.

Each test corresponds to a real bug reproduced during the refactor that
restored pyproject.toml as the authoritative source when the user has not
provided an explicit scrutiny CLI override.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pytest

from scrutiny.configs.pyproject import PyProjectLoader
from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.enums import ConfigTier, FrameworkSelection
from scrutiny.core.tool_data import PYPROJECT_KEY_MAP, PYPROJECT_TEMPLATES
from scrutiny.execution.handlers import RuffFormatterHandler, RuffHandler


def _load_from_pyproject(
    pyproject_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]]]:
    """
    Return mapped-config and native-keys produced by the real loader pipeline.

    Parameters
    ----------
    pyproject_path : Path
        Path to the pyproject.toml used in the test.

    Returns
    -------
    tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]]]
        Pair of (mapped tool config, native keys per section).

    """
    raw = PyProjectLoader.load_from_path(pyproject_path)
    mapped: dict[str, dict[str, Any]] = {}
    # Mirror main._load_pyproject_config: translate each known section.
    for tool_name in PYPROJECT_KEY_MAP:
        native = PyProjectLoader.extract_tool_config(raw, tool_name)
        # Skip empty sections so the caller sees only populated results.
        if native:
            mapped[tool_name] = PyProjectLoader.map_to_internal_keys(tool_name, native)
    native_keys = PyProjectLoader.collect_native_keys(raw, tuple(PYPROJECT_TEMPLATES.keys()))
    return mapped, native_keys


def _build_resolver(
    tmp_path: Path,
    pyproject_body: str,
    *,
    cli_args: Optional[dict[str, Any]] = None,
    is_pyproject_only: bool = False,
) -> ConfigResolver:
    """
    Write a pyproject.toml into *tmp_path* and build a ConfigResolver against it.

    Parameters
    ----------
    tmp_path : Path
        Pytest tmp directory receiving the pyproject.toml body.
    pyproject_body : str
        TOML content to write into ``pyproject.toml``.
    cli_args : Optional[dict[str, Any]]
        Scrutiny CLI overrides keyed by internal field name.  ``None``
        is treated as an empty dict.
    is_pyproject_only : bool
        When True the resolver skips script defaults in favour of the
        pyproject + CLI sources only.

    Returns
    -------
    ConfigResolver
        Fully populated resolver wired to the on-disk pyproject.toml.

    """
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(pyproject_body, encoding="utf-8")
    mapped, native_keys = _load_from_pyproject(pyproject_path)
    return ConfigResolver(
        cli_args=cli_args or {},
        pyproject_config=mapped,
        pyproject_native_keys=native_keys,
        context=ContextDetection.CLI,
        tier=ConfigTier.STRICT,
        pyproject_only=is_pyproject_only,
    )


# ====================================== #
#       FIX PYPROJECT AUTHORITY          #
# ====================================== #


@pytest.mark.unit
class TestFixPyprojectAuthoritative:
    """Regression: [tool.ruff] fix = false must suppress scrutiny's --fix."""

    def test_fix_false_in_pyproject_resolves_to_false(self, tmp_path: Path) -> None:
        """Pyproject fix=false flows through _FieldSpec to global_config.fix."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nfix = false\n",
        )

        # Act
        global_config = resolver.build_global_config()

        # Assert
        assert global_config.fix is False
        assert global_config.effective_fix is False

    def test_fix_false_causes_ruff_check_only_path(self, tmp_path: Path) -> None:
        """With fix=false in pyproject, RuffConfig.fix is False and handler skips --fix."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nfix = false\n",
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act - a fix_mode=True command should still omit --fix because the
        # flag is suppressed when pyproject owns the setting.
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
            fix_mode=True,
        )

        # Assert
        assert ruff_config.fix is False
        assert "--fix" not in command

    def test_unsafe_fixes_false_in_pyproject_resolves_to_false(self, tmp_path: Path) -> None:
        """Pyproject unsafe-fixes=false flows through and handler suppresses --unsafe-fixes."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nfix = true\nunsafe-fixes = false\n",
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
            fix_mode=True,
        )

        # Assert
        assert ruff_config.unsafe_fixes is False
        assert "--unsafe-fixes" not in command


# ====================================== #
#     EXCLUDE PYPROJECT AUTHORITY        #
# ====================================== #


@pytest.mark.unit
class TestExcludePyprojectAuthoritative:
    """Regression: [tool.ruff] exclude = [...] must suppress scrutiny's --exclude flags."""

    def test_pyproject_exclude_registered_as_native_key(self, tmp_path: Path) -> None:
        """Native keys collection reports [tool.ruff] exclude even without a key map entry."""
        # Arrange
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text(
            '[tool.ruff]\nexclude = ["vendor/"]\n',
            encoding="utf-8",
        )

        # Act
        _mapped, native_keys = _load_from_pyproject(pyproject_path)

        # Assert - PYPROJECT_KEY_MAP does not translate `exclude`, but the
        # native-keys collector still records it so the handler can suppress
        # its own --exclude emissions.
        assert "exclude" in native_keys.get("ruff", frozenset())

    def test_ruff_check_command_omits_exclude_when_pyproject_owns_it(
        self,
        tmp_path: Path,
    ) -> None:
        """RuffHandler.build_command skips --exclude when pyproject has exclude."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            '[tool.ruff]\nexclude = ["*_original.py", "vendor/"]\n',
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
        )

        # Assert - even though scrutiny's default SCR_EXCLUDE_DIRS contains
        # entries, no --exclude flag is emitted because pyproject owns exclude.
        assert "--exclude" not in command

    def test_ruff_format_command_omits_exclude_when_pyproject_owns_it(
        self,
        tmp_path: Path,
    ) -> None:
        """RuffFormatterHandler.build_command also suppresses --exclude for exclusion parity."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            '[tool.ruff]\nexclude = ["vendor/"]\n',
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffFormatterHandler(tool_name="ruff_formatter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
        )

        # Assert
        assert "--exclude" not in command


# ====================================== #
#      CLI OVERRIDES BEAT PYPROJECT      #
# ====================================== #


@pytest.mark.unit
class TestCliOverridesBeatPyproject:
    """The user's scrutiny CLI input must remain the highest-priority source."""

    def test_cli_line_length_overrides_pyproject_line_length(
        self,
        tmp_path: Path,
    ) -> None:
        """--line-length on the scrutiny CLI wins over pyproject's line-length."""
        # Arrange
        cli_line_length = 150
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nline-length = 120\n",
            cli_args={"line_length": cli_line_length},
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
        )

        # Assert
        assert global_config.line_length == cli_line_length
        assert f"--line-length={cli_line_length}" in command


# ====================================== #
#        PYPROJECT ONLY MODE             #
# ====================================== #


@pytest.mark.unit
class TestPyprojectOnlyMode:
    """pyproject_only=True restricts emission to CLI overrides plus operational flags."""

    def test_pyproject_only_suppresses_line_length_without_cli_override(
        self,
        tmp_path: Path,
    ) -> None:
        """Without CLI or pyproject line-length, pyproject_only mode omits --line-length."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nfix = true\n",
            is_pyproject_only=True,
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
        )

        # Assert
        assert not any(token.startswith("--line-length=") for token in command)
        assert not any(token.startswith("--select=") for token in command)

    def test_pyproject_only_honours_cli_override_for_line_length(
        self,
        tmp_path: Path,
    ) -> None:
        """Even in pyproject_only mode, an explicit CLI --line-length is emitted."""
        # Arrange
        cli_line_length = 111
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nfix = true\n",
            cli_args={"line_length": cli_line_length},
            is_pyproject_only=True,
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
        )

        # Assert
        assert f"--line-length={cli_line_length}" in command


# ====================================== #
#       LINE LENGTH ENUM RELAXED         #
# ====================================== #


@pytest.mark.unit
class TestLineLengthEnumRelaxation:
    """Defect D: scrutiny must accept any positive int within bounds for line_length."""

    def test_pyproject_line_length_123_is_accepted(self, tmp_path: Path) -> None:
        """line-length=123 resolves to int 123 without hitting the old LineLength enum."""
        # Arrange
        resolver = _build_resolver(
            tmp_path,
            "[tool.ruff]\nline-length = 123\n",
        )

        # Act
        global_config = resolver.build_global_config()

        # Assert
        assert global_config.line_length == 123


# ====================================== #
#    FRAMEWORK RULES VIA EXTEND SELECT   #
# ====================================== #


@pytest.mark.unit
class TestFrameworkExtendSelect:
    """Framework rule families are additive rather than overriding pyproject's select."""

    def test_framework_rules_emit_as_extend_select_flag(self, tmp_path: Path) -> None:
        """When pyproject has select, framework rules flow through --extend-select."""
        # Arrange
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text(
            '[tool.ruff.lint]\nselect = ["E", "F"]\n',
            encoding="utf-8",
        )
        mapped, native_keys = _load_from_pyproject(pyproject_path)
        resolver = ConfigResolver(
            cli_args={"framework": FrameworkSelection.DJANGO},
            pyproject_config=mapped,
            pyproject_native_keys=native_keys,
            context=ContextDetection.CLI,
            tier=ConfigTier.STRICT,
        )
        global_config = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(global_config)
        handler = RuffHandler(tool_name="ruff_linter")

        # Act
        command = handler.build_command(
            [Path("sample.py")],
            ruff_config,
            global_config,
            tmp_path,
        )

        # Assert - pyproject's select is left alone; framework additions
        # travel via --extend-select so ruff reads the pyproject list
        # natively and only appends the framework families on top.
        assert "--select=E,F" not in command
        assert any(token.startswith("--extend-select=") for token in command)
        extend_token = next(
            token for token in command if token.startswith("--extend-select=")
        )
        assert "DJ" in extend_token
