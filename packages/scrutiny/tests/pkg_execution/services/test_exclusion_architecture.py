"""Tests for the two-layer exclusion architecture and cache clearing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scrutiny.config import UserDefaults
from scrutiny.configs.dataclasses import GlobalConfig, MypyConfig
from scrutiny.configs.resolver import ConfigResolver
from scrutiny.core.enums import ConfigTier
from scrutiny.core.tool_data import RADON_TEST_EXCLUSIONS
from scrutiny.execution.handlers import MypyHandler
from scrutiny.execution.services import (
    FileDiscoveryService,
    _STANDARD_EXCLUDE_DIRS,
    clear_tool_caches,
)
from conftest import make_global_config


# ── _STANDARD_EXCLUDE_DIRS ── #


@pytest.mark.unit
class TestStandardExcludeDirs:
    """Verify the hardcoded standard exclusion constant."""

    @pytest.mark.parametrize(
        "directory_name",
        [".git", "__pycache__", ".venv", ".mypy_cache", ".ruff_cache", "node_modules"],
    )
    def test_contains_expected_directory(self, directory_name: str) -> None:
        """Standard exclusions include common build and cache directories."""
        assert directory_name in _STANDARD_EXCLUDE_DIRS

    def test_is_frozenset(self) -> None:
        """Standard exclusions are a frozenset (immutable)."""
        assert isinstance(_STANDARD_EXCLUDE_DIRS, frozenset)

    def test_does_not_contain_migrations(self) -> None:
        """Standard exclusions do NOT include project-specific dirs."""
        assert "migrations" not in _STANDARD_EXCLUDE_DIRS

    def test_does_not_contain_docs(self) -> None:
        """Standard exclusions do NOT include docs."""
        assert "docs" not in _STANDARD_EXCLUDE_DIRS

    def test_minimum_count(self) -> None:
        """Standard exclusions contain at least 25 entries."""
        assert len(_STANDARD_EXCLUDE_DIRS) >= 25


# ── UserDefaults.SCR_EXCLUDE_DIRS default ── #


@pytest.mark.unit
class TestUserDefaultsExcludeDirs:
    """Verify SCR_EXCLUDE_DIRS and SCR_EXCLUDE_FILES defaults."""

    def test_default_exclude_dirs(self) -> None:
        """SCR_EXCLUDE_DIRS defaults to ('tests',)."""
        assert UserDefaults.SCR_EXCLUDE_DIRS == ("tests",)

    def test_default_exclude_files(self) -> None:
        """SCR_EXCLUDE_FILES defaults to empty (no files excluded)."""
        assert UserDefaults.SCR_EXCLUDE_FILES == ()


# ── File discovery merges both layers ── #


@pytest.mark.unit
class TestDiscoveryExclusionMerge:
    """Verify FileDiscoveryService merges standard + user exclusions."""

    def test_standard_dirs_excluded(self, tmp_path: Path) -> None:
        """Directories in _STANDARD_EXCLUDE_DIRS are skipped."""
        # Arrange — create .git/ with a .py file inside
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "hooks.py").write_text("x = 1\n")
        (tmp_path / "main.py").write_text("x = 1\n")

        config = make_global_config()

        # Act
        found = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert — only main.py, not .git/hooks.py
        names = [found_file.name for found_file in found]
        assert "main.py" in names
        assert "hooks.py" not in names

    def test_user_exclude_dirs_applied(self, tmp_path: Path) -> None:
        """User-specified exclude_dirs are honoured."""
        # Arrange — create a custom dir to exclude
        custom_dir = tmp_path / "vendor"
        custom_dir.mkdir()
        (custom_dir / "lib.py").write_text("x = 1\n")
        (tmp_path / "app.py").write_text("x = 1\n")

        config = make_global_config(exclude_dirs=("vendor",))

        # Act
        found = FileDiscoveryService.discover_files([tmp_path], config)

        # Assert
        names = [found_file.name for found_file in found]
        assert "app.py" in names
        assert "lib.py" not in names

    def test_pycache_excluded_by_default(self, tmp_path: Path) -> None:
        """__pycache__ is excluded even without user exclusions."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "module.py").write_text("x = 1\n")
        (tmp_path / "real.py").write_text("x = 1\n")

        config = make_global_config()

        found = FileDiscoveryService.discover_files([tmp_path], config)

        names = [found_file.name for found_file in found]
        assert "real.py" in names
        assert "module.py" not in names


# ── User exclusions propagate to tool configs ── #


@pytest.mark.unit
class TestToolConfigExclusionPropagation:
    """Verify user exclusions flow through to all tool configs."""

    def _make_resolver(
        self,
        exclude_dirs: tuple[str, ...] = ("custom_dir",),
    ) -> ConfigResolver:
        """Create a ConfigResolver with the given user exclusions."""
        cli_dict: dict[str, object] = {"exclude_dirs": exclude_dirs}
        return ConfigResolver(
            cli_args=cli_dict,
            pyproject_config={},
            context=None,
            tier=ConfigTier.STRICT,
        )

    def test_ruff_config_gets_user_exclusions(self) -> None:
        """RuffConfig receives user-specified exclude_dirs."""
        resolver = self._make_resolver()
        gc = resolver.build_global_config()
        ruff_config = resolver.build_ruff_config(gc)

        assert "custom_dir" in ruff_config.exclude_dirs

    def test_mypy_config_gets_user_exclusions(self) -> None:
        """MypyConfig receives user-specified exclude_dirs."""
        resolver = self._make_resolver()
        gc = resolver.build_global_config()
        mypy_config = resolver.build_mypy_config(gc)

        assert "custom_dir" in mypy_config.exclude_dirs

    def test_bandit_config_gets_user_exclusions(self) -> None:
        """BanditConfig receives user-specified exclude_dirs."""
        resolver = self._make_resolver()
        gc = resolver.build_global_config()
        bandit_config = resolver.build_bandit_config(gc)

        assert "custom_dir" in bandit_config.exclude_dirs

    def test_radon_config_gets_user_exclusions(self) -> None:
        """RadonConfig receives user exclusions merged with test exclusions."""
        resolver = self._make_resolver()
        gc = resolver.build_global_config()
        radon_config = resolver.build_radon_config(gc)

        assert "custom_dir" in radon_config.exclude_dirs

    def test_radon_config_retains_test_exclusions(self) -> None:
        """RadonConfig still excludes test directories by default."""
        resolver = self._make_resolver()
        gc = resolver.build_global_config()
        radon_config = resolver.build_radon_config(gc)

        assert "test" in radon_config.exclude_dirs
        assert "tests" in radon_config.exclude_dirs

    def test_radon_config_retains_test_file_patterns(self) -> None:
        """RadonConfig still excludes test file patterns by default."""
        resolver = self._make_resolver()
        gc = resolver.build_global_config()
        radon_config = resolver.build_radon_config(gc)

        assert "test_*.py" in radon_config.exclude_files


# ── RADON_TEST_EXCLUSIONS ── #


@pytest.mark.unit
class TestRadonTestExclusions:
    """Verify Radon's hardcoded test exclusion constant."""

    def test_contains_test_dirs(self) -> None:
        """Radon test exclusions include standard test directory names."""
        dirs = RADON_TEST_EXCLUSIONS["dirs"]
        assert "test" in dirs
        assert "tests" in dirs

    def test_contains_test_file_patterns(self) -> None:
        """Radon test exclusions include standard test file patterns."""
        files = RADON_TEST_EXCLUSIONS["files"]
        assert "test_*.py" in files
        assert "*_test.py" in files


# ── clear_tool_caches ── #


@pytest.mark.unit
class TestClearToolCaches:
    """Verify clear_tool_caches deletes expected directories."""

    def test_clears_pycache(self, tmp_path: Path) -> None:
        """Delete __pycache__ directories."""
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-39.pyc").write_text("")

        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        assert not cache.exists()

    def test_clears_mypy_cache(self, tmp_path: Path) -> None:
        """Delete .mypy_cache directories."""
        cache = tmp_path / ".mypy_cache"
        cache.mkdir()
        (cache / "cache.json").write_text("{}")

        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        assert not cache.exists()

    def test_clears_ruff_cache(self, tmp_path: Path) -> None:
        """Delete .ruff_cache directories."""
        cache = tmp_path / ".ruff_cache"
        cache.mkdir()

        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        assert not cache.exists()

    def test_does_not_clear_unrelated_dirs(self, tmp_path: Path) -> None:
        """Leave directories not matching cache names intact."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "app.py").write_text("x = 1\n")

        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        assert src.exists()

    def test_logs_cleared_count(self, tmp_path: Path) -> None:
        """Log the number of cleared directories."""
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / ".mypy_cache").mkdir()

        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        # Should log "Cleared 2 cache directories"
        info_calls = [str(call_arg) for call_arg in logger.info.call_args_list]
        assert any("2" in call and "cache" in call for call in info_calls)

    def test_logs_nothing_when_empty(self, tmp_path: Path) -> None:
        """Log info when no caches found."""
        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        info_calls = [str(call_arg) for call_arg in logger.info.call_args_list]
        assert any("No cache" in call for call in info_calls)

    def test_handles_nested_caches(self, tmp_path: Path) -> None:
        """Clear caches in subdirectories."""
        sub = tmp_path / "subproject"
        sub.mkdir()
        cache = sub / "__pycache__"
        cache.mkdir()
        (cache / "mod.pyc").write_text("")

        logger = MagicMock()
        clear_tool_caches(tmp_path, logger)

        assert not cache.exists()


# ── GlobalConfig.clear_cache field ── #


@pytest.mark.unit
class TestGlobalConfigClearCache:
    """Verify clear_cache field on GlobalConfig."""

    def test_default_false(self) -> None:
        """clear_cache defaults to False."""
        config = make_global_config()
        assert config.clear_cache is False

    def test_can_set_true(self) -> None:
        """clear_cache can be set to True."""
        config = make_global_config(clear_cache=True)
        assert config.clear_cache is True


# ── Mypy no_cache wiring ── #


@pytest.mark.unit
class TestMypyNoCacheWiring:
    """Verify --no-incremental is passed to mypy when no_cache=True."""

    def test_no_incremental_when_no_cache(self) -> None:
        """MypyHandler command includes --no-incremental with no_cache."""
        handler = MypyHandler(60, tool_name="mypy")
        mypy_config = MypyConfig()
        gc = make_global_config(no_cache=True)

        cmd = handler.build_command(
            [Path("test.py")],
            mypy_config,
            gc,
            Path(),
        )

        assert "--no-incremental" in cmd

    def test_no_incremental_absent_when_cache_enabled(self) -> None:
        """MypyHandler command omits --no-incremental with cache enabled."""
        handler = MypyHandler(60, tool_name="mypy")
        mypy_config = MypyConfig()
        gc = make_global_config(no_cache=False)

        cmd = handler.build_command(
            [Path("test.py")],
            mypy_config,
            gc,
            Path(),
        )

        assert "--no-incremental" not in cmd
