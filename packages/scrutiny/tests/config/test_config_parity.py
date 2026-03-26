"""Tests enforcing field parity across UserDefaults, UserDefaultsSnapshot, and GlobalConfig.

Catches configuration drift when a field is added to one class but not the others.
"""

from __future__ import annotations

import dataclasses

import pytest

from scrutiny.config import UserDefaults, UserDefaultsSnapshot
from scrutiny.configs.dataclasses import GlobalConfig


def _get_user_defaults_fields() -> set[str]:
    """Return UPPER_CASE class attribute names from UserDefaults (excluding methods/dunders)."""
    return {
        name
        for name in dir(UserDefaults)
        if name.isupper() and not name.startswith("_") and not callable(getattr(UserDefaults, name))
    }


def _upper_to_snapshot_name(upper_name: str) -> str:
    """Convert UserDefaults UPPER_CASE name to expected UserDefaultsSnapshot field name."""
    return upper_name.lower()


# Explicit rename map: snapshot field name -> GlobalConfig field name.
# Only needed where the prefix strip is ambiguous or the name differs.
_SNAPSHOT_TO_GLOBAL: dict[str, str] = {
    "scr_config_tier": "config_tier",
    "scr_python_version": "python_version",
    "scr_line_length": "line_length",
    "scr_clear_cache": "clear_cache",
    "scr_no_cache": "no_cache",
    "scr_current_dir_as_root": "current_dir_as_root",
    "scr_max_upward_search_depth": "max_upward_search_depth",
    "scr_follow_symlinks": "follow_symlinks",
    "scr_create_log": "create_log",
    "scr_log_location": "log_location",
    "scr_log_dir": "log_dir",
    "scr_console_logger_level": "console_logger_level",
    "scr_file_logger_level": "file_logger_level",
    "scr_log_discovered_files": "log_discovered_files",
    "scr_generate_config": "generate_config",
    "scr_override_config": "override_config",
    "scr_generate_config_in_cwd": "generate_config_in_cwd",
    "scr_include_test_config": "include_test_config",
    "scr_include_test_plugins": "include_test_plugins",
    "scr_pyproject_only": "pyproject_only",
    "scr_tool_timeout": "tool_timeout",
    "scr_parallel": "parallel",
    "scr_exclude_dirs": "exclude_dirs",
    "scr_exclude_files": "exclude_files",
    "ruff_framework": "framework",
    "ruff_fix": "fix",
    "ruff_unsafe_fixes": "unsafe_fixes",
    "ruff_check_only": "check_only",
    "run_ruff_formatter": "run_ruff_formatter",
    "run_ruff_linter": "run_ruff_linter",
    "run_mypy": "run_mypy",
    "run_radon": "run_radon",
    "run_security": "run_security",
    "security_tool": "security_tool",
    "pipeline_security_tool": "pipeline_security_tool",
}

# GlobalConfig fields that are computed properties, not direct snapshot mappings.
_GLOBAL_COMPUTED_FIELDS: frozenset[str] = frozenset({"effective_fix"})


@pytest.mark.unit
class TestConfigFieldParity:
    """Enforce field parity across the three config classes."""

    def test_user_defaults_snapshot_has_all_user_defaults_fields(self) -> None:
        """Every UserDefaults class attribute maps to a UserDefaultsSnapshot field."""
        # Arrange
        ud_fields = _get_user_defaults_fields()
        snapshot_fields = {f.name for f in dataclasses.fields(UserDefaultsSnapshot)}
        expected_snapshot = {_upper_to_snapshot_name(name) for name in ud_fields}

        # Act
        missing = expected_snapshot - snapshot_fields
        extra = snapshot_fields - expected_snapshot

        # Assert
        assert not missing, f"UserDefaultsSnapshot missing fields for UserDefaults: {missing}"
        assert not extra, f"UserDefaultsSnapshot has extra fields not in UserDefaults: {extra}"

    def test_global_config_has_all_snapshot_fields(self) -> None:
        """Every UserDefaultsSnapshot field maps to a GlobalConfig field."""
        # Arrange
        snapshot_fields = {f.name for f in dataclasses.fields(UserDefaultsSnapshot)}
        global_fields = {f.name for f in dataclasses.fields(GlobalConfig)}
        missing = []

        # Act; check each snapshot field maps to a GlobalConfig field
        for snap_field in snapshot_fields:
            global_name = _SNAPSHOT_TO_GLOBAL.get(snap_field, snap_field)
            # Record any snapshot field that has no GlobalConfig counterpart
            if global_name not in global_fields:
                missing.append(f"{snap_field} -> {global_name}")

        # Assert
        assert not missing, f"GlobalConfig missing fields: {missing}"

    def test_global_config_fields_covered_by_snapshot(self) -> None:
        """Every GlobalConfig dataclass field maps back to a snapshot field."""
        # Arrange
        global_fields = {f.name for f in dataclasses.fields(GlobalConfig)}
        reverse_map = {v: k for k, v in _SNAPSHOT_TO_GLOBAL.items()}
        snapshot_fields = {f.name for f in dataclasses.fields(UserDefaultsSnapshot)}
        uncovered = []

        # Act; verify each GlobalConfig field has a snapshot counterpart
        for gf in global_fields:
            snap_name = reverse_map.get(gf, gf)
            # Record any GlobalConfig field that has no snapshot counterpart
            if snap_name not in snapshot_fields:
                uncovered.append(f"{gf} (expected snapshot field: {snap_name})")

        # Assert
        assert not uncovered, f"GlobalConfig fields not covered by snapshot: {uncovered}"

    def test_to_frozen_copies_all_fields(self) -> None:
        """UserDefaults.to_frozen() copies every field correctly."""
        # Arrange
        snapshot = UserDefaults.to_frozen()
        ud_fields = _get_user_defaults_fields()

        # Act / Assert; verify each field value matches between source and snapshot
        for ud_name in ud_fields:
            snap_name = _upper_to_snapshot_name(ud_name)
            ud_value = getattr(UserDefaults, ud_name)
            snap_value = getattr(snapshot, snap_name)
            assert snap_value == ud_value, (
                f"to_frozen() mismatch: UserDefaults.{ud_name}={ud_value!r} "
                f"vs snapshot.{snap_name}={snap_value!r}"
            )
