"""Regression tests for subprocess argv-injection defenses.

Tool configuration values flow from pyproject.toml (untrusted) through
the resolver into ``RuffConfig`` / ``MypyConfig`` / ``BanditConfig`` /
``RadonConfig`` and eventually into ``subprocess.run`` via flag
templates.  Without validation, a crafted pyproject.toml can inject
additional CLI flags; for example ``select = ["E,--unsafe-fixes"]``
would be joined into ``--select=E,--unsafe-fixes``, silently enabling
unsafe auto-fix.  These tests pin the argv-safety validators that
reject such crafted payloads at dataclass construction.
"""

from __future__ import annotations

import pytest

from scrutiny.configs.dataclasses import (
    BanditConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.core.exceptions import SCRConfigurationError


# ====================================== #
#          RULE TOKEN INJECTION          #
# ====================================== #


@pytest.mark.unit
class TestRuleTokenInjection:
    """Rule-token tuple fields reject comma/equals/flag injection."""

    @pytest.mark.parametrize(
        "malicious_element",
        [
            "E,--unsafe-fixes",
            "E=--config=/etc/passwd",
            "--add-noqa",
            "E F",
            "E\nF",
            "E\x00F",
        ],
    )
    def test_select_rules_rejects_injection(self, malicious_element: str) -> None:
        """RuffConfig.select_rules rejects tokens with injection metacharacters."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"select_rules"):
            RuffConfig(select_rules=("E501", malicious_element))

    @pytest.mark.parametrize(
        "malicious_element",
        [
            "E501,--fix",
            "--disable",
            "E501=X",
        ],
    )
    def test_ignore_rules_rejects_injection(self, malicious_element: str) -> None:
        """RuffConfig.ignore_rules rejects tokens with injection metacharacters."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"ignore_rules"):
            RuffConfig(ignore_rules=("E501", malicious_element))

    def test_extend_select_rules_rejects_injection(self) -> None:
        """RuffConfig.extend_select_rules rejects tokens with embedded flags."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"extend_select_rules"):
            RuffConfig(extend_select_rules=("DJ,--unsafe-fixes",))

    def test_bandit_skip_tests_rejects_injection(self) -> None:
        """BanditConfig.skip_tests rejects tokens that could inject flags."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"skip_tests"):
            BanditConfig(skip_tests=("B101,--config=evil",))


# ====================================== #
#      VERSION FIELD INJECTION           #
# ====================================== #


@pytest.mark.unit
class TestVersionFieldInjection:
    """target_version / python_version reject argv injection."""

    @pytest.mark.parametrize(
        "malicious_value",
        [
            "--config=evil",
            "py39=X",
            "py 39",
            "py39,--fix",
        ],
    )
    def test_ruff_target_version_rejects_injection(self, malicious_value: str) -> None:
        """RuffConfig.target_version rejects argv-unsafe values."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"target_version"):
            RuffConfig(target_version=malicious_value)

    def test_mypy_python_version_rejects_injection(self) -> None:
        """MypyConfig.python_version rejects argv-unsafe values."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"python_version"):
            MypyConfig(python_version="--config=evil")


# ====================================== #
#         PATH FIELD INJECTION           #
# ====================================== #


@pytest.mark.unit
class TestPathFieldInjection:
    """exclude_dirs / exclude_files reject flag-shaped path entries."""

    @pytest.mark.parametrize(
        "malicious_path",
        [
            "--fix",
            "--config=evil",
        ],
    )
    def test_ruff_exclude_dirs_rejects_flag_shaped_paths(self, malicious_path: str) -> None:
        """Leading-dash path entries are rejected to prevent flag confusion."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"exclude_dirs"):
            RuffConfig(exclude_dirs=(malicious_path,))

    def test_ruff_exclude_files_rejects_null_byte(self) -> None:
        """Null bytes in exclusion patterns are rejected (argv corruption risk)."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"exclude_files"):
            RuffConfig(exclude_files=("bad\x00file.py",))

    def test_ruff_exclude_files_rejects_newline(self) -> None:
        """Newlines in exclusion patterns are rejected (line-parser corruption)."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"exclude_files"):
            RuffConfig(exclude_files=("bad\nfile.py",))

    def test_mypy_exclude_dirs_rejects_leading_dash(self) -> None:
        """MypyConfig.exclude_dirs rejects leading-dash paths."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"exclude_dirs"):
            MypyConfig(exclude_dirs=("--fix",))

    def test_bandit_exclude_dirs_rejects_leading_dash(self) -> None:
        """BanditConfig.exclude_dirs rejects leading-dash paths."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"exclude_dirs"):
            BanditConfig(exclude_dirs=("--config=evil",))

    def test_radon_exclude_dirs_rejects_leading_dash(self) -> None:
        """RadonConfig.exclude_dirs rejects leading-dash paths."""
        # Act / Assert
        with pytest.raises(SCRConfigurationError, match=r"exclude_dirs"):
            RadonConfig(exclude_dirs=("--disable",))


# ====================================== #
#   LEGITIMATE VALUES REMAIN ACCEPTED    #
# ====================================== #


@pytest.mark.unit
class TestLegitimateValuesAccepted:
    """Argv-safety validation must not reject realistic user values."""

    def test_standard_rule_tokens_accepted(self) -> None:
        """Normal rule tokens pass through unchanged."""
        # Act
        config = RuffConfig(
            select_rules=("E", "F", "PLR0124", "UP007"),
            ignore_rules=("E501", "RUF100"),
            extend_select_rules=("DJ",),
        )

        # Assert
        assert config.select_rules == ("E", "F", "PLR0124", "UP007")

    def test_standard_python_version_accepted(self) -> None:
        """Normal python_version strings pass through unchanged."""
        # Act
        ruff = RuffConfig(target_version="py312")
        mypy = MypyConfig(python_version="3.12")

        # Assert
        assert ruff.target_version == "py312"
        assert mypy.python_version == "3.12"

    def test_realistic_exclude_paths_accepted(self) -> None:
        """Directory globs with slashes and wildcards pass through unchanged."""
        # Act
        config = RuffConfig(
            exclude_dirs=("tests/fixtures", "vendor/third_party"),
            exclude_files=("*_original.py", "conftest.py", "snapshots/*.py"),
        )

        # Assert
        assert "tests/fixtures" in config.exclude_dirs
        assert "*_original.py" in config.exclude_files

    def test_relative_dot_prefix_path_accepted(self) -> None:
        """Relative paths with './' prefix are accepted."""
        # Act
        config = RuffConfig(exclude_files=("./weird.py",))

        # Assert
        assert config.exclude_files == ("./weird.py",)
