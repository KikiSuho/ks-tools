"""
User-editable configuration defaults for scrutiny.

Provides ``UserDefaults`` (mutable class-level settings) and
``UserDefaultsSnapshot`` (frozen dataclass created at bootstrap time).
Edit ``UserDefaults`` values to change script behavior without touching
execution logic.

Classes
-------
UserDefaults : Mutable class-level configuration defaults.
UserDefaultsSnapshot : Frozen dataclass snapshot of UserDefaults.

Examples
--------
>>> UserDefaults.SCR_CONFIG_TIER.value
'standard'

"""

from __future__ import annotations

from dataclasses import dataclass

from scrutiny.core.enums import (
    ConfigTier,
    FrameworkSelection,
    LineLength,
    LoggerLevel,
    LogLocation,
    PythonVersion,
    SearchDepth,
    SecurityTool,
    ToolTimeout,
)


class UserDefaults:
    """
    User-editable defaults controlling script behavior.

    Edit these values to change script behavior without modifying
    execution logic.

    Attributes
    ----------
    SCR_CONFIG_TIER : ConfigTier
        Default quality tier.
    SCR_PYTHON_VERSION : PythonVersion
        Target Python version for tools.
    SCR_LINE_LENGTH : LineLength
        Maximum line length for formatters and linters.
    SCR_CLEAR_CACHE : bool
        Delete tool cache directories before execution.
    SCR_NO_CACHE : bool
        Disable tool caching entirely.
    RUN_RUFF_FORMATTER : bool
        Enable Ruff formatter execution.
    RUN_RUFF_LINTER : bool
        Enable Ruff linter execution.
    RUN_MYPY : bool
        Enable Mypy type checking.
    RUN_RADON : bool
        Enable Radon complexity analysis.
    RUN_SECURITY : bool
        Enable security scanning.
    SECURITY_TOOL : SecurityTool
        Security tool for IDE/CLI context.
    PIPELINE_SECURITY_TOOL : SecurityTool
        Security tool for CI/pipeline context.
    RUFF_FIX : bool
        Enable Ruff auto-fix.
    RUFF_UNSAFE_FIXES : bool
        Allow Ruff unsafe fixes.
    RUFF_CHECK_ONLY : bool
        When True, disable Ruff auto-fix and run formatter
        in check mode.
    RUFF_FRAMEWORK : FrameworkSelection
        Optional framework for additional ruff rule families.
    SCR_CURRENT_DIR_AS_ROOT : bool
        When True, treat invocation directory as project root.
    SCR_MAX_UPWARD_SEARCH_DEPTH : SearchDepth
        Maximum parent directories to search for project markers.
    SCR_FOLLOW_SYMLINKS : bool
        Follow symbolic links during file discovery.
    SCR_CREATE_LOG : bool
        Create a log file for the run.
    SCR_LOG_LOCATION : LogLocation
        Controls where log files are placed (project root, current
        directory, or hybrid fallback).
    SCR_LOG_DIR : str
        Directory for log files, relative to the log location root.
    SCR_CONSOLE_LOGGER_LEVEL : LoggerLevel
        Default console verbosity.
    SCR_FILE_LOGGER_LEVEL : LoggerLevel
        Default file log verbosity.
    SCR_LOG_DISCOVERED_FILES : bool
        List discovered files in the log header.
    SCR_GENERATE_CONFIG : bool
        Generate or merge pyproject.toml on this run.
    SCR_OVERRIDE_CONFIG : bool
        Overwrite existing tool settings during generation.
    SCR_GENERATE_CONFIG_IN_CWD : bool
        Target CWD instead of actual project root for generation.
    SCR_INCLUDE_TEST_CONFIG : bool
        Include pytest/coverage sections in generated pyproject.toml.
    SCR_INCLUDE_TEST_PLUGINS : bool
        Include test plugin config in generated pyproject.toml.
    SCR_TEST_CONFIG_ONLY : bool
        Restrict generation to test sections only, skipping the
        normal ``[tool.ruff]`` / ``[tool.mypy]`` / ``[tool.bandit]``
        sections.  Used by ``--generate-test-config`` to scope
        generation to ``[tool.pytest.ini_options]`` and
        ``[tool.coverage.*]`` on a fresh project.
    SCR_PYPROJECT_ONLY : bool
        When True, use pyproject.toml as the sole authoritative
        config source, bypassing script defaults (priorities 4-5).
    SCR_TOOL_TIMEOUT : ToolTimeout
        Per-tool execution timeout.
    SCR_PARALLEL : bool
        Run tools in parallel using thread pool.
    SCR_EXCLUDE_DIRS : tuple[str, ...]
        Project-specific directory exclusions (additions to
        ``_STANDARD_EXCLUDE_DIRS``).
    SCR_EXCLUDE_FILES : tuple[str, ...]
        Project-specific file pattern exclusions.

    """

    # Quality tier.  ``STANDARD`` covers production-ready rules without the
    # documentation / pylint / per-file overhead of ``STRICT``; users who
    # want maximum rigor opt in via ``--strict`` or ``--insane``.
    SCR_CONFIG_TIER: ConfigTier = ConfigTier.STANDARD

    # Shared tool settings
    SCR_PYTHON_VERSION: PythonVersion = PythonVersion.PY39
    SCR_LINE_LENGTH: LineLength = LineLength.STANDARD
    SCR_CLEAR_CACHE: bool = False
    SCR_NO_CACHE: bool = False

    # Tool toggles; read-only analyzers run by default.  File-modifying
    # capabilities (``ruff_formatter``, ``ruff check --fix``) are opt-in
    # so ``scrutiny`` never rewrites source without explicit user intent.
    RUN_RUFF_FORMATTER: bool = False
    RUN_RUFF_LINTER: bool = True
    RUN_MYPY: bool = True
    RUN_RADON: bool = True
    RUN_SECURITY: bool = True

    # Ruff removes noqa suppression comments via --fix;
    # Bandit is currently more reliable.
    SECURITY_TOOL: SecurityTool = SecurityTool.BANDIT
    PIPELINE_SECURITY_TOOL: SecurityTool = SecurityTool.BANDIT

    # Ruff behaviour.  Auto-fix is opt-in via ``--fix`` so analysis runs
    # never silently modify the user's working tree.
    RUFF_FIX: bool = False
    RUFF_UNSAFE_FIXES: bool = False
    RUFF_CHECK_ONLY: bool = False
    RUFF_FRAMEWORK: FrameworkSelection = FrameworkSelection.NONE

    # Path behavior
    SCR_CURRENT_DIR_AS_ROOT: bool = False
    SCR_MAX_UPWARD_SEARCH_DEPTH: SearchDepth = SearchDepth.DEFAULT
    SCR_FOLLOW_SYMLINKS: bool = False

    # Logging
    SCR_CREATE_LOG: bool = True
    SCR_LOG_LOCATION: LogLocation = LogLocation.HYBRID
    SCR_LOG_DIR: str = "logs/scrutiny/"
    SCR_CONSOLE_LOGGER_LEVEL: LoggerLevel = LoggerLevel.NORMAL
    SCR_FILE_LOGGER_LEVEL: LoggerLevel = LoggerLevel.VERBOSE
    SCR_LOG_DISCOVERED_FILES: bool = True

    # pyproject.toml generation; opt-in per invocation via --generate-config
    # flags.  Scrutiny no longer modifies pyproject.toml unless the user
    # explicitly asks; running ``scrutiny`` analyses the project without
    # touching the config file, honoring whatever is already there.
    SCR_GENERATE_CONFIG: bool = False
    SCR_OVERRIDE_CONFIG: bool = False
    SCR_GENERATE_CONFIG_IN_CWD: bool = False
    SCR_INCLUDE_TEST_CONFIG: bool = False
    SCR_INCLUDE_TEST_PLUGINS: bool = False
    SCR_TEST_CONFIG_ONLY: bool = False
    SCR_PYPROJECT_ONLY: bool = False

    # Execution
    SCR_TOOL_TIMEOUT: ToolTimeout = ToolTimeout.PATIENT
    SCR_PARALLEL: bool = True

    # Exclusions; project-specific additions to ``_STANDARD_EXCLUDE_DIRS``.
    # Standard directories (VCS, caches, build artifacts, virtual
    # environments) are always excluded automatically.  Add only
    # project-specific directories here (e.g. ``"migrations"``).
    SCR_EXCLUDE_DIRS: tuple[str, ...] = ("tests",)
    SCR_EXCLUDE_FILES: tuple[str, ...] = ()

    @classmethod
    def to_frozen(cls) -> UserDefaultsSnapshot:
        """
        Create an immutable snapshot of current class-level defaults.

        Returns
        -------
        UserDefaultsSnapshot
            Frozen copy of every ``UserDefaults`` attribute.

        """
        return UserDefaultsSnapshot(
            scr_config_tier=cls.SCR_CONFIG_TIER,
            scr_python_version=cls.SCR_PYTHON_VERSION,
            scr_line_length=cls.SCR_LINE_LENGTH,
            scr_clear_cache=cls.SCR_CLEAR_CACHE,
            scr_no_cache=cls.SCR_NO_CACHE,
            run_ruff_formatter=cls.RUN_RUFF_FORMATTER,
            run_ruff_linter=cls.RUN_RUFF_LINTER,
            run_mypy=cls.RUN_MYPY,
            run_radon=cls.RUN_RADON,
            run_security=cls.RUN_SECURITY,
            security_tool=cls.SECURITY_TOOL,
            pipeline_security_tool=cls.PIPELINE_SECURITY_TOOL,
            ruff_framework=cls.RUFF_FRAMEWORK,
            ruff_fix=cls.RUFF_FIX,
            ruff_unsafe_fixes=cls.RUFF_UNSAFE_FIXES,
            ruff_check_only=cls.RUFF_CHECK_ONLY,
            scr_current_dir_as_root=cls.SCR_CURRENT_DIR_AS_ROOT,
            scr_max_upward_search_depth=cls.SCR_MAX_UPWARD_SEARCH_DEPTH,
            scr_follow_symlinks=cls.SCR_FOLLOW_SYMLINKS,
            scr_create_log=cls.SCR_CREATE_LOG,
            scr_log_location=cls.SCR_LOG_LOCATION,
            scr_log_dir=cls.SCR_LOG_DIR,
            scr_console_logger_level=cls.SCR_CONSOLE_LOGGER_LEVEL,
            scr_file_logger_level=cls.SCR_FILE_LOGGER_LEVEL,
            scr_log_discovered_files=cls.SCR_LOG_DISCOVERED_FILES,
            scr_generate_config=cls.SCR_GENERATE_CONFIG,
            scr_override_config=cls.SCR_OVERRIDE_CONFIG,
            scr_generate_config_in_cwd=cls.SCR_GENERATE_CONFIG_IN_CWD,
            scr_include_test_config=cls.SCR_INCLUDE_TEST_CONFIG,
            scr_include_test_plugins=cls.SCR_INCLUDE_TEST_PLUGINS,
            scr_test_config_only=cls.SCR_TEST_CONFIG_ONLY,
            scr_pyproject_only=cls.SCR_PYPROJECT_ONLY,
            scr_tool_timeout=cls.SCR_TOOL_TIMEOUT,
            scr_parallel=cls.SCR_PARALLEL,
            scr_exclude_dirs=cls.SCR_EXCLUDE_DIRS,
            scr_exclude_files=cls.SCR_EXCLUDE_FILES,
        )


@dataclass(frozen=True)
class UserDefaultsSnapshot:
    """
    Immutable snapshot of user-configurable defaults.

    Created at bootstrap via ``UserDefaults.to_frozen()``.
    Downstream code can read from the snapshot without risk of
    accidental mutation.  Adding a new configuration field requires
    changes in three places: ``UserDefaults`` (canonical class
    attribute), ``UserDefaultsSnapshot`` (frozen dataclass field),
    and ``GlobalConfig`` (resolved dataclass field).

    Attributes
    ----------
    scr_config_tier : ConfigTier
        Default quality tier.
    scr_python_version : PythonVersion
        Target Python version for tools.
    scr_line_length : LineLength
        Maximum line length for formatters and linters.
    scr_clear_cache : bool
        Whether to clear tool caches before execution.
    scr_no_cache : bool
        Whether to disable tool caching entirely.
    run_ruff_formatter : bool
        Enable Ruff formatter execution.
    run_ruff_linter : bool
        Enable Ruff linter execution.
    run_mypy : bool
        Enable Mypy type checking.
    run_radon : bool
        Enable Radon complexity analysis.
    run_security : bool
        Enable security scanning.
    security_tool : SecurityTool
        Security tool for IDE/CLI context.
    pipeline_security_tool : SecurityTool
        Security tool for CI/pipeline context.
    ruff_framework : FrameworkSelection
        Optional framework for additional ruff rule families.
    ruff_fix : bool
        Enable Ruff auto-fix.
    ruff_unsafe_fixes : bool
        Allow Ruff unsafe fixes.
    ruff_check_only : bool
        When True, disable Ruff auto-fix and run formatter in check mode.
    scr_current_dir_as_root : bool
        When True, treat invocation directory as project root.
    scr_max_upward_search_depth : SearchDepth
        Maximum parent directories to search for project markers.
    scr_follow_symlinks : bool
        Whether to follow symbolic links during file discovery.
    scr_create_log : bool
        Whether to create a log file.
    scr_log_location : LogLocation
        Controls where log files are placed (project root, current
        directory, or hybrid fallback).
    scr_log_dir : str
        Directory for log files, relative to project root.
    scr_console_logger_level : LoggerLevel
        Default console verbosity.
    scr_file_logger_level : LoggerLevel
        Default file log verbosity.
    scr_log_discovered_files : bool
        List discovered files in the log header.
    scr_generate_config : bool
        Whether to generate or merge pyproject.toml on this run.
    scr_override_config : bool
        Whether to overwrite existing tool settings during generation.
    scr_generate_config_in_cwd : bool
        Whether to target CWD instead of actual project root for generation.
    scr_include_test_config : bool
        Include pytest/coverage sections in generated pyproject.toml.
    scr_include_test_plugins : bool
        Include test plugin config in generated pyproject.toml.
    scr_test_config_only : bool
        Restrict generation to test sections only, skipping the
        normal ``[tool.ruff]`` / ``[tool.mypy]`` / ``[tool.bandit]``
        sections.
    scr_pyproject_only : bool
        When True, use pyproject.toml as the sole authoritative config
        source, bypassing script defaults (priorities 4-5).
    scr_tool_timeout : ToolTimeout
        Per-tool execution timeout.
    scr_parallel : bool
        Run tools in parallel using thread pool.
    scr_exclude_dirs : tuple[str, ...]
        Project-specific directory exclusions (additions to standard set).
    scr_exclude_files : tuple[str, ...]
        Project-specific file pattern exclusions.

    """

    # Defaults reference UserDefaults so direct construction (e.g. in tests)
    # stays in sync with the canonical source of truth.  In production,
    # to_frozen() copies every value explicitly, so these defaults are
    # only reached when constructing UserDefaultsSnapshot() without arguments.
    scr_config_tier: ConfigTier = UserDefaults.SCR_CONFIG_TIER
    scr_python_version: PythonVersion = UserDefaults.SCR_PYTHON_VERSION
    scr_line_length: LineLength = UserDefaults.SCR_LINE_LENGTH
    scr_clear_cache: bool = UserDefaults.SCR_CLEAR_CACHE
    scr_no_cache: bool = UserDefaults.SCR_NO_CACHE
    run_ruff_formatter: bool = UserDefaults.RUN_RUFF_FORMATTER
    run_ruff_linter: bool = UserDefaults.RUN_RUFF_LINTER
    run_mypy: bool = UserDefaults.RUN_MYPY
    run_radon: bool = UserDefaults.RUN_RADON
    run_security: bool = UserDefaults.RUN_SECURITY
    security_tool: SecurityTool = UserDefaults.SECURITY_TOOL
    pipeline_security_tool: SecurityTool = UserDefaults.PIPELINE_SECURITY_TOOL
    ruff_framework: FrameworkSelection = UserDefaults.RUFF_FRAMEWORK
    ruff_fix: bool = UserDefaults.RUFF_FIX
    ruff_unsafe_fixes: bool = UserDefaults.RUFF_UNSAFE_FIXES
    ruff_check_only: bool = UserDefaults.RUFF_CHECK_ONLY
    scr_current_dir_as_root: bool = UserDefaults.SCR_CURRENT_DIR_AS_ROOT
    scr_max_upward_search_depth: SearchDepth = UserDefaults.SCR_MAX_UPWARD_SEARCH_DEPTH
    scr_follow_symlinks: bool = UserDefaults.SCR_FOLLOW_SYMLINKS
    scr_create_log: bool = UserDefaults.SCR_CREATE_LOG
    scr_log_location: LogLocation = UserDefaults.SCR_LOG_LOCATION
    scr_log_dir: str = UserDefaults.SCR_LOG_DIR
    scr_console_logger_level: LoggerLevel = UserDefaults.SCR_CONSOLE_LOGGER_LEVEL
    scr_file_logger_level: LoggerLevel = UserDefaults.SCR_FILE_LOGGER_LEVEL
    scr_log_discovered_files: bool = UserDefaults.SCR_LOG_DISCOVERED_FILES
    scr_generate_config: bool = UserDefaults.SCR_GENERATE_CONFIG
    scr_override_config: bool = UserDefaults.SCR_OVERRIDE_CONFIG
    scr_generate_config_in_cwd: bool = UserDefaults.SCR_GENERATE_CONFIG_IN_CWD
    scr_include_test_config: bool = UserDefaults.SCR_INCLUDE_TEST_CONFIG
    scr_include_test_plugins: bool = UserDefaults.SCR_INCLUDE_TEST_PLUGINS
    scr_test_config_only: bool = UserDefaults.SCR_TEST_CONFIG_ONLY
    scr_pyproject_only: bool = UserDefaults.SCR_PYPROJECT_ONLY
    scr_tool_timeout: ToolTimeout = UserDefaults.SCR_TOOL_TIMEOUT
    scr_parallel: bool = UserDefaults.SCR_PARALLEL
    scr_exclude_dirs: tuple[str, ...] = UserDefaults.SCR_EXCLUDE_DIRS
    scr_exclude_files: tuple[str, ...] = UserDefaults.SCR_EXCLUDE_FILES
