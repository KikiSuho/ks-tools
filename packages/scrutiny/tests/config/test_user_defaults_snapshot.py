"""Tests for UserDefaults.to_frozen() and UserDefaultsSnapshot behaviour."""

from __future__ import annotations

import dataclasses

import pytest

from scrutiny.config import UserDefaults, UserDefaultsSnapshot


# ── UserDefaults.to_frozen() ── #


@pytest.mark.unit
class TestUserDefaultsToFrozen:
    """Test that UserDefaults.to_frozen() produces a correct frozen snapshot."""

    def test_to_frozen_returns_snapshot_type(self) -> None:
        """Verify to_frozen returns a UserDefaultsSnapshot instance."""
        # Arrange / Act
        snapshot = UserDefaults.to_frozen()

        # Assert
        assert isinstance(snapshot, UserDefaultsSnapshot)

    def test_snapshot_captures_config_tier(self) -> None:
        """Verify snapshot captures the current SCR_CONFIG_TIER value."""
        # Arrange / Act
        snapshot = UserDefaults.to_frozen()

        # Assert
        assert snapshot.scr_config_tier == UserDefaults.SCR_CONFIG_TIER

    def test_snapshot_captures_python_version(self) -> None:
        """Verify snapshot captures the current SCR_PYTHON_VERSION value."""
        # Arrange / Act
        snapshot = UserDefaults.to_frozen()

        # Assert
        assert snapshot.scr_python_version == UserDefaults.SCR_PYTHON_VERSION

    def test_snapshot_captures_line_length(self) -> None:
        """Verify snapshot captures the current SCR_LINE_LENGTH value."""
        # Arrange / Act
        snapshot = UserDefaults.to_frozen()

        # Assert
        assert snapshot.scr_line_length == UserDefaults.SCR_LINE_LENGTH

    def test_snapshot_captures_bool_fields(self) -> None:
        """Verify snapshot captures boolean toggle fields accurately."""
        # Arrange / Act
        snapshot = UserDefaults.to_frozen()

        # Assert
        assert snapshot.run_ruff_formatter == UserDefaults.RUN_RUFF_FORMATTER
        assert snapshot.run_mypy == UserDefaults.RUN_MYPY
        assert snapshot.scr_create_log == UserDefaults.SCR_CREATE_LOG

    def test_snapshot_captures_exclude_dirs(self) -> None:
        """Verify snapshot captures the SCR_EXCLUDE_DIRS tuple."""
        # Arrange / Act
        snapshot = UserDefaults.to_frozen()

        # Assert
        assert snapshot.scr_exclude_dirs == UserDefaults.SCR_EXCLUDE_DIRS

    def test_snapshot_is_frozen(self) -> None:
        """Verify that mutating a snapshot attribute raises an error."""
        # Arrange
        snapshot = UserDefaults.to_frozen()

        # Act / Assert — frozen dataclasses raise FrozenInstanceError (a subclass of
        # AttributeError); FrozenInstanceError was only exposed publicly in 3.11, so
        # we catch AttributeError for compatibility with 3.9.
        with pytest.raises(AttributeError, match="cannot assign to field"):
            snapshot.scr_config_tier = "MUTATED"  # type: ignore[misc]

    def test_snapshot_field_count(self) -> None:
        """Verify the snapshot dataclass exposes the expected field count."""
        # Arrange
        snapshot = UserDefaults.to_frozen()
        expected_field_count = 36

        # Act
        fields = dataclasses.fields(snapshot)

        # Assert
        assert len(fields) == expected_field_count

    def test_snapshot_supports_dataclass_fields(self) -> None:
        """Verify dataclasses.fields returns field objects with correct names."""
        # Arrange
        snapshot = UserDefaults.to_frozen()
        expected_names = {
            "scr_config_tier",
            "scr_python_version",
            "scr_line_length",
            "scr_clear_cache",
            "scr_no_cache",
            "run_ruff_formatter",
            "run_ruff_linter",
            "run_mypy",
            "run_radon",
            "run_security",
            "security_tool",
            "pipeline_security_tool",
            "ruff_framework",
            "ruff_fix",
            "ruff_unsafe_fixes",
            "ruff_check_only",
            "scr_current_dir_as_root",
            "scr_max_upward_search_depth",
            "scr_follow_symlinks",
            "scr_create_log",
            "scr_log_location",
            "scr_log_dir",
            "scr_console_logger_level",
            "scr_file_logger_level",
            "scr_generate_config",
            "scr_override_config",
            "scr_generate_config_in_cwd",
            "scr_include_test_config",
            "scr_include_test_plugins",
            "scr_test_config_only",
            "scr_pyproject_only",
            "scr_tool_timeout",
            "scr_parallel",
            "scr_exclude_dirs",
            "scr_exclude_files",
            "scr_log_discovered_files",
        }

        # Act
        actual_names = {field.name for field in dataclasses.fields(snapshot)}

        # Assert
        assert actual_names == expected_names

    def test_to_frozen_reflects_modified_class_attribute(self) -> None:
        """Verify to_frozen captures a class attribute changed at runtime."""
        # Arrange
        original_value = UserDefaults.SCR_NO_CACHE
        try:
            UserDefaults.SCR_NO_CACHE = True

            # Act
            snapshot = UserDefaults.to_frozen()

            # Assert
            assert snapshot.scr_no_cache is True
        finally:
            UserDefaults.SCR_NO_CACHE = original_value
