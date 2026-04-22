"""Tests for _SharedConfigValidator, tool config __post_init__, and _safe_enum_construct."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from scrutiny.config import UserDefaults, UserDefaultsSnapshot
from scrutiny.configs.dataclasses import (
    BanditConfig,
    GlobalConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.configs.resolver import ConfigResolver
from scrutiny.core.enums import ConfigTier, PythonVersion
from scrutiny.core.exceptions import SCRConfigurationError, SCRUserInputError


# ====================================== #
#       CONFIG FIELD PARITY              #
# ====================================== #


# Mapping from UserDefaults class attributes to their UserDefaultsSnapshot
# and GlobalConfig field names.  Keys that appear in UserDefaults but NOT in
# the other two classes will cause the parity test to fail, catching drift
# from the triple-update requirement.

# Fields in UserDefaults that map to a different name in GlobalConfig.
_UD_TO_GC_RENAMES: dict[str, str] = {
    "SCR_CONFIG_TIER": "config_tier",
    "SCR_PYTHON_VERSION": "python_version",
    "SCR_LINE_LENGTH": "line_length",
    "SCR_CLEAR_CACHE": "clear_cache",
    "SCR_NO_CACHE": "no_cache",
    "SCR_CURRENT_DIR_AS_ROOT": "current_dir_as_root",
    "SCR_MAX_UPWARD_SEARCH_DEPTH": "max_upward_search_depth",
    "SCR_FOLLOW_SYMLINKS": "follow_symlinks",
    "SCR_CREATE_LOG": "create_log",
    "SCR_LOG_LOCATION": "log_location",
    "SCR_LOG_DIR": "log_dir",
    "SCR_CONSOLE_LOGGER_LEVEL": "console_logger_level",
    "SCR_FILE_LOGGER_LEVEL": "file_logger_level",
    "SCR_LOG_DISCOVERED_FILES": "log_discovered_files",
    "SCR_GENERATE_CONFIG": "generate_config",
    "SCR_OVERRIDE_CONFIG": "override_config",
    "SCR_GENERATE_CONFIG_IN_CWD": "generate_config_in_cwd",
    "SCR_INCLUDE_TEST_CONFIG": "include_test_config",
    "SCR_INCLUDE_TEST_PLUGINS": "include_test_plugins",
    "SCR_TEST_CONFIG_ONLY": "test_config_only",
    "SCR_PYPROJECT_ONLY": "pyproject_only",
    "SCR_TOOL_TIMEOUT": "tool_timeout",
    "SCR_PARALLEL": "parallel",
    "SCR_EXCLUDE_DIRS": "exclude_dirs",
    "SCR_EXCLUDE_FILES": "exclude_files",
    "RUN_RUFF_FORMATTER": "run_ruff_formatter",
    "RUN_RUFF_LINTER": "run_ruff_linter",
    "RUN_MYPY": "run_mypy",
    "RUN_RADON": "run_radon",
    "RUN_SECURITY": "run_security",
    "SECURITY_TOOL": "security_tool",
    "PIPELINE_SECURITY_TOOL": "pipeline_security_tool",
    "RUFF_FRAMEWORK": "framework",
    "RUFF_FIX": "fix",
    "RUFF_UNSAFE_FIXES": "unsafe_fixes",
    "RUFF_CHECK_ONLY": "check_only",
}


def _get_user_defaults_fields() -> set[str]:
    """Return the set of UserDefaults class attributes (config fields only)."""
    return {
        name
        for name in vars(UserDefaults)
        if not name.startswith("_") and name.isupper() and not callable(getattr(UserDefaults, name))
    }


def test_user_defaults_snapshot_parity() -> None:
    """UserDefaultsSnapshot has a field for every UserDefaults attribute."""
    ud_fields = _get_user_defaults_fields()
    snapshot_fields = set(UserDefaultsSnapshot.__dataclass_fields__)
    # Snapshot uses lowercase versions of UD names.
    ud_lower = {name.lower() for name in ud_fields}
    missing = ud_lower - snapshot_fields
    assert not missing, f"UserDefaultsSnapshot missing fields for UserDefaults attrs: {missing}"


def test_global_config_parity() -> None:
    """GlobalConfig has a field for every UserDefaults attribute."""
    ud_fields = _get_user_defaults_fields()
    gc_fields = set(GlobalConfig.__dataclass_fields__)
    # Map UD names to GC names via the rename table.
    expected_gc = {_UD_TO_GC_RENAMES.get(name, name.lower()) for name in ud_fields}
    missing = expected_gc - gc_fields
    assert not missing, f"GlobalConfig missing fields for UserDefaults attrs: {missing}"


# ── _SharedConfigValidator.validate_int_fields ── #


@pytest.mark.unit
class TestValidateIntFields:
    """Test integer field validation with min/max constraints."""

    def test_rejects_value_below_minimum(self) -> None:
        """Raise SCRConfigurationError when int field is below min_value."""
        with pytest.raises(SCRConfigurationError, match="must be >= 40"):
            RuffConfig(line_length=10)

    def test_rejects_value_above_maximum(self) -> None:
        """Raise SCRConfigurationError when int field is above max_value."""
        with pytest.raises(SCRConfigurationError, match="must be <= 500"):
            RuffConfig(line_length=999)

    def test_rejects_bool_as_int(self) -> None:
        """Raise SCRConfigurationError when bool is passed for an int field."""
        # bool is subclass of int, but validator explicitly rejects it
        with pytest.raises(SCRConfigurationError, match="must be int"):
            RuffConfig(line_length=True)

    def test_rejects_non_int_type(self) -> None:
        """Raise SCRConfigurationError when a string is passed for an int field."""
        with pytest.raises(SCRConfigurationError, match="must be int"):
            RuffConfig(line_length="100")


# ── _SharedConfigValidator.validate_enum_field ── #


@pytest.mark.unit
class TestValidateEnumField:
    """Test enum field validation on GlobalConfig."""

    def test_rejects_invalid_enum_type(self) -> None:
        """Raise SCRConfigurationError when field is not an enum member."""
        with pytest.raises(SCRConfigurationError, match="must be ConfigTier"):
            GlobalConfig(config_tier="not_an_enum")


# ── _SharedConfigValidator.validate_bool_fields ── #


@pytest.mark.unit
class TestValidateBoolFields:
    """Test boolean field validation on tool configs."""

    def test_rejects_non_bool_for_fix(self) -> None:
        """Raise SCRConfigurationError when fix is not a boolean."""
        with pytest.raises(SCRConfigurationError, match="must be bool"):
            RuffConfig(fix="yes")

    def test_rejects_non_bool_for_strict_mode(self) -> None:
        """Raise SCRConfigurationError when strict_mode is not a boolean."""
        with pytest.raises(SCRConfigurationError, match="must be bool"):
            MypyConfig(strict_mode=1)


# ── _SharedConfigValidator.validate_string_fields ── #


@pytest.mark.unit
class TestValidateStringFields:
    """Test string field validation with allowed_values and non_empty."""

    def test_rejects_empty_target_version(self) -> None:
        """Raise SCRConfigurationError for empty target_version."""
        with pytest.raises(SCRConfigurationError, match="must not be empty"):
            RuffConfig(target_version="")

    def test_rejects_invalid_bandit_severity(self) -> None:
        """Raise SCRConfigurationError for invalid bandit severity value."""
        with pytest.raises(SCRConfigurationError, match="must be one of"):
            BanditConfig(severity="critical")

    def test_rejects_invalid_radon_complexity_grade(self) -> None:
        """Raise SCRConfigurationError for invalid radon complexity grade."""
        with pytest.raises(SCRConfigurationError, match="must be one of"):
            RadonConfig(minimum_complexity="Z")


# ── _SharedConfigValidator.validate_tuple_fields ── #


@pytest.mark.unit
class TestValidateTupleFields:
    """Test tuple field validation on tool configs."""

    def test_rejects_list_for_tuple_field(self) -> None:
        """Raise SCRConfigurationError when list is passed for a tuple field."""
        with pytest.raises(SCRConfigurationError, match="must be tuple"):
            RuffConfig(select_rules=["E", "F"])

    def test_rejects_tuple_with_non_string_elements(self) -> None:
        """Raise SCRConfigurationError when tuple contains non-string elements."""
        with pytest.raises(SCRConfigurationError, match="must contain only strings"):
            RuffConfig(exclude_dirs=(1, 2, 3))


# ── _ToolConfigMixin.get_exclusions ── #


@pytest.mark.unit
class TestGetExclusions:
    """Test combined exclusion merging from _ToolConfigMixin."""

    def test_merges_dirs_and_files(self) -> None:
        """Verify get_exclusions returns dirs + files concatenated."""
        config = RuffConfig(
            exclude_dirs=("vendor", "build"),
            exclude_files=("setup.py",),
        )

        result = config.get_exclusions()

        assert result == ("vendor", "build", "setup.py")

    def test_empty_exclusions_returns_empty_tuple(self) -> None:
        """Verify empty dirs and files produce an empty tuple."""
        config = BanditConfig(exclude_dirs=(), exclude_files=())

        result = config.get_exclusions()

        assert result == ()

    def test_only_dirs_no_files(self) -> None:
        """Verify only dirs returned when files is empty."""
        config = MypyConfig(exclude_dirs=("tests",), exclude_files=())

        result = config.get_exclusions()

        assert result == ("tests",)


# ── ConfigResolver._safe_enum_construct ── #


@pytest.mark.unit
class TestSafeEnumConstruct:
    """Test safe enum construction with user-friendly error messages."""

    def test_constructs_valid_enum_member(self) -> None:
        """Return enum member for a valid value."""
        result = ConfigResolver._safe_enum_construct(
            ConfigTier,
            "strict",
            "config_tier",
        )

        assert result == ConfigTier.STRICT

    def test_raises_on_invalid_value(self) -> None:
        """Raise SCRUserInputError with valid options listed."""
        with pytest.raises(SCRUserInputError, match="Invalid value.*config_tier"):
            ConfigResolver._safe_enum_construct(
                ConfigTier,
                "nonexistent",
                "config_tier",
            )

    def test_raises_custom_exception_class(self) -> None:
        """Raise the specified exception class on failure."""
        with pytest.raises(SCRConfigurationError, match="Invalid value"):
            ConfigResolver._safe_enum_construct(
                PythonVersion,
                "py20",
                "python_version",
                exception_class=SCRConfigurationError,
            )

    def test_error_message_lists_valid_options(self) -> None:
        """Verify the error message includes all valid enum values."""
        with pytest.raises(SCRUserInputError) as exc_info:
            ConfigResolver._safe_enum_construct(
                ConfigTier,
                "bad",
                "config_tier",
            )

        error_text = str(exc_info.value)
        assert "strict" in error_text
        assert "standard" in error_text
