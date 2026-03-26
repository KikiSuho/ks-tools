"""
Configuration dataclasses for scrutiny.

Contain the shared validator, orchestration-level ``GlobalConfig``, the
``_ToolConfigMixin``, and individual tool config dataclasses (``RuffConfig``,
``MypyConfig``, ``RadonConfig``, ``BanditConfig``).

Classes
-------
GlobalConfig : Orchestration-level configuration resolved from all sources.
RuffConfig : Ruff formatter and linter configuration.
MypyConfig : Mypy type checker configuration.
RadonConfig : Radon complexity analysis configuration.
BanditConfig : Bandit security analysis configuration.

Examples
--------
>>> config = GlobalConfig()
>>> config.config_tier
<ConfigTier.STRICT: 'strict'>

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from scrutiny.config import UserDefaults
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
from scrutiny.core.exceptions import SCRConfigurationError, SCRError, SCRLoggerLevelError
from scrutiny.core.tool_data import (
    BANDIT_LEVEL_FLAGS,
    RADON_COMPLEXITY_GRADES,
    RADON_TEST_EXCLUSIONS,
    RUFF_IGNORE_RULES,
    RUFF_RULES_STRICT,
)

if TYPE_CHECKING:
    from scrutiny.configs.resolver import ContextDetection


# ====================================== #
#       CONFIGURATION VALIDATION         #
# ====================================== #


class _SharedConfigValidator:
    """
    Centralized validation methods for configuration dataclass fields.

    All methods are static -- no instances are created.
    """

    @staticmethod
    def validate_bool_fields(instance: Any, *field_names: str) -> None:
        """
        Validate that named fields are booleans.

        Parameters
        ----------
        instance : Any
            Dataclass instance being validated.
        *field_names : str
            Names of fields that must be ``bool``.

        Raises
        ------
        SCRConfigurationError
            If any field is not a boolean.

        """
        # Verify each named field is a boolean.
        for name in field_names:
            value = getattr(instance, name)
            if not isinstance(value, bool):
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be bool, got {type(value).__name__}",
                )

    @staticmethod
    def validate_string_fields(
        instance: Any,
        **field_constraints: dict[str, Any],
    ) -> None:
        """
        Validate string fields with optional constraints.

        Parameters
        ----------
        instance : Any
            Dataclass instance being validated.
        **field_constraints : dict[str, Any]
            Mapping of field name to constraint dict. Supported keys:
            ``non_empty`` (bool), ``allowed_values`` (list[str]).

        Raises
        ------
        SCRConfigurationError
            If any constraint is violated.

        """
        # Check each field against its type, emptiness, and allowed-value constraints.
        for name, constraints in field_constraints.items():
            value = getattr(instance, name)
            if not isinstance(value, str):
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be str, got {type(value).__name__}",
                )
            if constraints.get("non_empty") and not value.strip():
                raise SCRConfigurationError(f"{type(instance).__name__}.{name} must not be empty")
            allowed = constraints.get("allowed_values")
            if allowed is not None and value not in allowed:
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be one of {allowed}, got '{value}'",
                )

    @staticmethod
    def validate_tuple_fields(instance: Any, *field_names: str) -> None:
        """
        Validate that named fields are tuples of strings.

        Parameters
        ----------
        instance : Any
            Dataclass instance being validated.
        *field_names : str
            Names of fields that must be ``tuple[str, ...]``.

        Raises
        ------
        SCRConfigurationError
            If any field is not a tuple of strings.

        """
        # Verify each named field is a tuple containing only strings.
        for name in field_names:
            value = getattr(instance, name)
            if not isinstance(value, tuple):
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be tuple, got {type(value).__name__}",
                )
            if not all(isinstance(element, str) for element in value):
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must contain only strings",
                )

    @staticmethod
    def validate_int_fields(
        instance: Any,
        **field_constraints: dict[str, Any],
    ) -> None:
        """
        Validate integer fields with optional min / max constraints.

        Parameters
        ----------
        instance : Any
            Dataclass instance being validated.
        **field_constraints : dict[str, Any]
            Mapping of field name to constraint dict. Supported keys:
            ``min_value`` (int), ``max_value`` (int).

        Raises
        ------
        SCRConfigurationError
            If any constraint is violated.

        """
        # Validate each field is an integer within its min/max bounds.
        for name, constraints in field_constraints.items():
            value = getattr(instance, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be int, got {type(value).__name__}",
                )
            minimum_value = constraints.get("min_value")
            maximum_value = constraints.get("max_value")
            if minimum_value is not None and value < minimum_value:
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be >= {minimum_value}, got {value}",
                )
            if maximum_value is not None and value > maximum_value:
                raise SCRConfigurationError(
                    f"{type(instance).__name__}.{name} must be <= {maximum_value}, got {value}",
                )

    @staticmethod
    def validate_enum_field(
        instance: Any,
        field_name: str,
        enum_class: type,
        exception_class: type[SCRError] = SCRConfigurationError,
    ) -> None:
        """
        Validate that a field is an instance of the given enum.

        Parameters
        ----------
        instance : Any
            Dataclass instance being validated.
        field_name : str
            Name of the field to validate.
        enum_class : type
            Enum class the field must be an instance of.
        exception_class : type[SCRError]
            Exception class to raise on validation failure.

        Raises
        ------
        SCRError
            If the field is not a valid enum member.

        """
        value = getattr(instance, field_name)
        if not isinstance(value, enum_class):
            raise exception_class(
                f"{type(instance).__name__}.{field_name} must be "
                f"{enum_class.__name__}, got {type(value).__name__}",
            )


# ====================================== #
#       CONFIGURATION DATACLASSES        #
# ====================================== #


@dataclass(frozen=True)
class GlobalConfig:
    """
    Orchestration-level configuration for scrutiny.

    Controls path discovery, logging, tool toggles, exclusions,
    and the quality tier.  Populated by the ``ConfigResolver`` using
    the five-level priority chain.

    Parameters
    ----------
    config_tier : ConfigTier
        Quality tier controlling rule strictness across all tools.
    python_version : PythonVersion
        Target Python version (e.g. ``PythonVersion.PY39``).
    line_length : LineLength
        Maximum line length for formatting and linting.
    current_dir_as_root : bool
        When True, treat invocation directory as project root.
    max_upward_search_depth : SearchDepth
        Maximum parent directories to search for project markers.
    follow_symlinks : bool
        Whether to follow symbolic links during file discovery.
    console_logger_level : LoggerLevel
        Verbosity level for console output.
    file_logger_level : LoggerLevel
        Verbosity level for file output.
    create_log : bool
        Whether to create a log file.
    log_location : LogLocation
        Controls where log files are placed (project root, current
        directory, or hybrid fallback).
    log_dir : str
        Directory for log files, relative to the log location root.
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
    framework : FrameworkSelection
        Optional framework for additional ruff rule families.
    fix : bool
        Enable auto-fix where tools support it.
    check_only : bool
        When True, disable Ruff auto-fix and run formatter in check mode.
        Auto-enabled in CI and pre-commit contexts via ``ContextDetection``.
    unsafe_fixes : bool
        Allow Ruff unsafe fixes.
    no_cache : bool
        Disable tool caching.
    clear_cache : bool
        Delete tool cache directories before execution.
    parallel : bool
        Run tools in parallel using thread pool.
    tool_timeout : ToolTimeout
        Maximum seconds per tool invocation.
    generate_config : bool
        Generate or merge pyproject.toml on this run.
    override_config : bool
        With ``generate_config``, overwrite existing tool settings.
    generate_config_in_cwd : bool
        With ``generate_config``, target CWD instead of actual project root.
    include_test_config : bool
        Include pytest/coverage sections in pyproject.toml generation.
    include_test_plugins : bool
        Include test plugin config in pyproject.toml generation.
    pyproject_only : bool
        When True, use pyproject.toml as the sole authoritative config
        source, bypassing script defaults (priorities 4-5).
    exclude_dirs : tuple[str, ...]
        Project-specific directory exclusions (additions to
        ``_STANDARD_EXCLUDE_DIRS``).
    exclude_files : tuple[str, ...]
        Project-specific file pattern exclusions.
    log_discovered_files : bool
        List discovered files in the log header.

    """

    config_tier: ConfigTier = UserDefaults.SCR_CONFIG_TIER
    python_version: PythonVersion = UserDefaults.SCR_PYTHON_VERSION
    line_length: LineLength = UserDefaults.SCR_LINE_LENGTH
    current_dir_as_root: bool = UserDefaults.SCR_CURRENT_DIR_AS_ROOT
    max_upward_search_depth: SearchDepth = UserDefaults.SCR_MAX_UPWARD_SEARCH_DEPTH
    follow_symlinks: bool = UserDefaults.SCR_FOLLOW_SYMLINKS
    console_logger_level: LoggerLevel = UserDefaults.SCR_CONSOLE_LOGGER_LEVEL
    file_logger_level: LoggerLevel = UserDefaults.SCR_FILE_LOGGER_LEVEL
    create_log: bool = UserDefaults.SCR_CREATE_LOG
    log_location: LogLocation = UserDefaults.SCR_LOG_LOCATION
    log_dir: str = UserDefaults.SCR_LOG_DIR
    run_ruff_formatter: bool = UserDefaults.RUN_RUFF_FORMATTER
    run_ruff_linter: bool = UserDefaults.RUN_RUFF_LINTER
    run_mypy: bool = UserDefaults.RUN_MYPY
    run_radon: bool = UserDefaults.RUN_RADON
    run_security: bool = UserDefaults.RUN_SECURITY
    security_tool: SecurityTool = UserDefaults.SECURITY_TOOL
    pipeline_security_tool: SecurityTool = UserDefaults.PIPELINE_SECURITY_TOOL
    framework: FrameworkSelection = UserDefaults.RUFF_FRAMEWORK
    fix: bool = UserDefaults.RUFF_FIX
    check_only: bool = UserDefaults.RUFF_CHECK_ONLY
    unsafe_fixes: bool = UserDefaults.RUFF_UNSAFE_FIXES
    no_cache: bool = UserDefaults.SCR_NO_CACHE
    clear_cache: bool = UserDefaults.SCR_CLEAR_CACHE
    parallel: bool = UserDefaults.SCR_PARALLEL
    tool_timeout: ToolTimeout = UserDefaults.SCR_TOOL_TIMEOUT
    generate_config: bool = UserDefaults.SCR_GENERATE_CONFIG
    override_config: bool = UserDefaults.SCR_OVERRIDE_CONFIG
    generate_config_in_cwd: bool = UserDefaults.SCR_GENERATE_CONFIG_IN_CWD
    include_test_config: bool = UserDefaults.SCR_INCLUDE_TEST_CONFIG
    include_test_plugins: bool = UserDefaults.SCR_INCLUDE_TEST_PLUGINS
    pyproject_only: bool = UserDefaults.SCR_PYPROJECT_ONLY
    exclude_dirs: tuple[str, ...] = UserDefaults.SCR_EXCLUDE_DIRS
    exclude_files: tuple[str, ...] = UserDefaults.SCR_EXCLUDE_FILES
    log_discovered_files: bool = UserDefaults.SCR_LOG_DISCOVERED_FILES

    # DESIGN NOTE: Every field default references UserDefaults.* so that
    # GlobalConfig() can be constructed directly in tests without going through
    # the full ConfigResolver pipeline.  In production, the resolver overrides
    # all fields explicitly via UserDefaultsSnapshot — these defaults are only
    # reached when constructing GlobalConfig() without keyword arguments.

    def __post_init__(self) -> None:
        """Validate all fields after initialization."""
        _SharedConfigValidator.validate_enum_field(
            self,
            "config_tier",
            ConfigTier,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "python_version",
            PythonVersion,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "line_length",
            LineLength,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "max_upward_search_depth",
            SearchDepth,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "tool_timeout",
            ToolTimeout,
        )
        _SharedConfigValidator.validate_string_fields(
            self,
            log_dir={"non_empty": True},
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "console_logger_level",
            LoggerLevel,
            exception_class=SCRLoggerLevelError,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "file_logger_level",
            LoggerLevel,
            exception_class=SCRLoggerLevelError,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "log_location",
            LogLocation,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "framework",
            FrameworkSelection,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "security_tool",
            SecurityTool,
        )
        _SharedConfigValidator.validate_enum_field(
            self,
            "pipeline_security_tool",
            SecurityTool,
        )
        _SharedConfigValidator.validate_bool_fields(
            self,
            "current_dir_as_root",
            "follow_symlinks",
            "create_log",
            "run_ruff_formatter",
            "run_ruff_linter",
            "run_mypy",
            "run_radon",
            "run_security",
            "fix",
            "check_only",
            "unsafe_fixes",
            "no_cache",
            "clear_cache",
            "parallel",
            "generate_config",
            "override_config",
            "generate_config_in_cwd",
            "pyproject_only",
            "log_discovered_files",
            "include_test_config",
            "include_test_plugins",
        )
        _SharedConfigValidator.validate_tuple_fields(
            self,
            "exclude_dirs",
            "exclude_files",
        )

    def get_enabled_tools(self, context: ContextDetection) -> list[str]:
        """
        Return list of enabled tool names.

        Parameters
        ----------
        context : ContextDetection
            Detected execution context (determines which security tool to use).

        Returns
        -------
        list[str]
            Tool identifiers whose run flags are True.

        """
        # Runtime import: ContextDetection is available via TYPE_CHECKING for
        # annotations, but must be imported at runtime for isinstance/equality checks.
        from scrutiny.configs.resolver import ContextDetection  # noqa: PLC0415

        # Collect tools whose run flags are True, in execution order.
        tools: list[str] = []
        if self.run_ruff_formatter:
            tools.append("ruff_formatter")
        if self.run_ruff_linter:
            tools.append("ruff_linter")
        if self.run_mypy:
            tools.append("mypy")
        if self.run_radon:
            tools.append("radon")
        # Append the appropriate security tool for the execution context
        if self.run_security:
            # Pipeline contexts use a separate security tool setting.
            if context in (ContextDetection.CI, ContextDetection.PRECOMMIT):
                tools.append(self.pipeline_security_tool.value)
            else:
                tools.append(self.security_tool.value)
        return tools

    def get_active_security_tool(self, context: ContextDetection) -> SecurityTool:
        """
        Return the security tool for the given context.

        Parameters
        ----------
        context : ContextDetection
            Detected execution context.

        Returns
        -------
        SecurityTool
            The security tool selected for this context.

        """
        # Runtime import: see get_enabled_tools() for rationale.
        from scrutiny.configs.resolver import ContextDetection  # noqa: PLC0415

        # Use the pipeline-specific tool in CI and pre-commit environments
        if context in (ContextDetection.CI, ContextDetection.PRECOMMIT):
            return self.pipeline_security_tool
        return self.security_tool

    @property
    def effective_fix(self) -> bool:
        """
        Whether auto-fix is active after considering ``--check-only``.

        Returns
        -------
        bool
            True only if ``fix`` is True and ``check_only`` is False.

        """
        return self.fix and not self.check_only


class _ToolConfigMixin:
    """
    Shared behavior for tool configuration dataclasses.

    Provides ``get_exclusions()`` so each frozen config need not
    duplicate the method.

    Attributes
    ----------
    exclude_dirs : tuple[str, ...]
        Directory names to exclude from tool execution.
    exclude_files : tuple[str, ...]
        File names to exclude from tool execution.

    """

    exclude_dirs: tuple[str, ...]
    exclude_files: tuple[str, ...]

    def get_exclusions(self) -> tuple[str, ...]:
        """
        Return combined directory and file exclusions.

        Returns
        -------
        tuple[str, ...]
            Merged exclusion patterns.

        """
        return self.exclude_dirs + self.exclude_files


@dataclass(frozen=True)
class RuffConfig(_ToolConfigMixin):
    """
    Configuration for Ruff formatter and linter.

    Populated from ``RUFF_TIER_RULES`` and ``RUFF_CLI_FLAGS``.

    Parameters
    ----------
    select_rules : tuple[str, ...]
        Ruff rules to enable (from tier).
    ignore_rules : tuple[str, ...]
        Ruff rules to suppress.
    line_length : int
        Maximum line length.
    target_version : str
        Python target version (e.g. ``"py39"``).
    fix : bool
        Enable auto-fix for linter.
    unsafe_fixes : bool
        Allow unsafe auto-fixes.
    no_cache : bool
        Disable Ruff's internal cache.
    exclude_dirs : tuple[str, ...]
        Directories to exclude from analysis.
    exclude_files : tuple[str, ...]
        File patterns to exclude from analysis.

    """

    select_rules: tuple[str, ...] = RUFF_RULES_STRICT
    ignore_rules: tuple[str, ...] = RUFF_IGNORE_RULES
    line_length: int = UserDefaults.SCR_LINE_LENGTH.value
    target_version: str = UserDefaults.SCR_PYTHON_VERSION.value
    fix: bool = UserDefaults.RUFF_FIX
    unsafe_fixes: bool = UserDefaults.RUFF_UNSAFE_FIXES
    no_cache: bool = UserDefaults.SCR_NO_CACHE
    exclude_dirs: tuple[str, ...] = UserDefaults.SCR_EXCLUDE_DIRS
    exclude_files: tuple[str, ...] = UserDefaults.SCR_EXCLUDE_FILES

    def __post_init__(self) -> None:
        """Validate Ruff configuration fields."""
        _SharedConfigValidator.validate_tuple_fields(
            self,
            "select_rules",
            "ignore_rules",
            "exclude_dirs",
            "exclude_files",
        )
        _SharedConfigValidator.validate_int_fields(
            self,
            line_length={"min_value": 40, "max_value": 200},
        )
        _SharedConfigValidator.validate_string_fields(
            self,
            target_version={"non_empty": True},
        )
        _SharedConfigValidator.validate_bool_fields(
            self,
            "fix",
            "unsafe_fixes",
            "no_cache",
        )


@dataclass(frozen=True)
class MypyConfig(_ToolConfigMixin):
    """
    Configuration for the Mypy static type checker.

    Populated from ``MYPY_TIER_SETTINGS``.

    Parameters
    ----------
    strict_mode : bool
        Enable Mypy strict mode.
    warn_unreachable : bool
        Warn about unreachable code.
    disallow_untyped_globals : bool
        Disallow untyped global variables.
    disallow_any_explicit : bool
        Disallow explicit Any annotations.
    ignore_missing_imports : bool
        Ignore errors from missing third-party stubs.
    disable_error_code_import_untyped : bool
        Suppress import-untyped error code.
    show_column_numbers : bool
        Show column numbers in output.
    show_error_codes : bool
        Show error codes in output.
    python_version : str
        Target Python version for Mypy (dotted, e.g. ``"3.9"``).
    exclude_dirs : tuple[str, ...]
        Directories to exclude from type checking.
    exclude_files : tuple[str, ...]
        File patterns to exclude from type checking.

    """

    strict_mode: bool = False
    warn_unreachable: bool = True
    disallow_untyped_globals: bool = False
    disallow_any_explicit: bool = False
    ignore_missing_imports: bool = True
    disable_error_code_import_untyped: bool = True
    show_column_numbers: bool = True
    show_error_codes: bool = True
    python_version: str = "3.9"
    exclude_dirs: tuple[str, ...] = ()
    exclude_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate Mypy configuration fields."""
        _SharedConfigValidator.validate_bool_fields(
            self,
            "strict_mode",
            "warn_unreachable",
            "disallow_untyped_globals",
            "disallow_any_explicit",
            "ignore_missing_imports",
            "disable_error_code_import_untyped",
            "show_column_numbers",
            "show_error_codes",
        )
        _SharedConfigValidator.validate_string_fields(
            self,
            python_version={"non_empty": True},
        )
        _SharedConfigValidator.validate_tuple_fields(
            self,
            "exclude_dirs",
            "exclude_files",
        )


@dataclass(frozen=True)
class RadonConfig(_ToolConfigMixin):
    """
    Configuration for Radon cyclomatic complexity analysis.

    Populated from ``RADON_TIER_SETTINGS``.

    Parameters
    ----------
    minimum_complexity : str
        Minimum grade to report (``"A"`` through ``"F"``).
    show_average : bool
        Display average complexity score.
    show_closures : bool
        Include closures in analysis.
    json_output : bool
        Use JSON output format.
    exclude_dirs : tuple[str, ...]
        Directories to exclude from complexity analysis.
    exclude_files : tuple[str, ...]
        File patterns to exclude from complexity analysis.

    """

    minimum_complexity: str = "B"
    show_average: bool = True
    show_closures: bool = True
    json_output: bool = True
    exclude_dirs: tuple[str, ...] = RADON_TEST_EXCLUSIONS["dirs"]
    exclude_files: tuple[str, ...] = RADON_TEST_EXCLUSIONS["files"]

    def __post_init__(self) -> None:
        """Validate Radon configuration fields."""
        _SharedConfigValidator.validate_bool_fields(
            self,
            "show_average",
            "show_closures",
            "json_output",
        )
        _SharedConfigValidator.validate_string_fields(
            self,
            minimum_complexity={
                "non_empty": True,
                "allowed_values": list(RADON_COMPLEXITY_GRADES.keys()),
            },
        )
        _SharedConfigValidator.validate_tuple_fields(
            self,
            "exclude_dirs",
            "exclude_files",
        )


@dataclass(frozen=True)
class BanditConfig(_ToolConfigMixin):
    """
    Configuration for Bandit security vulnerability scanning.

    Populated from ``BANDIT_TIER_SETTINGS``.

    Parameters
    ----------
    severity : str
        Minimum severity threshold (``"low"``, ``"medium"``, ``"high"``).
    confidence : str
        Minimum confidence threshold (``"low"``, ``"medium"``, ``"high"``).
    quiet : bool
        Suppress progress output.
    skip_tests : tuple[str, ...]
        Bandit test IDs to skip (e.g. ``("B101",)``).
    exclude_dirs : tuple[str, ...]
        Directories to exclude from security scanning.
    exclude_files : tuple[str, ...]
        File patterns to exclude from security scanning.

    """

    severity: str = "medium"
    confidence: str = "medium"
    quiet: bool = True
    skip_tests: tuple[str, ...] = ()
    exclude_dirs: tuple[str, ...] = ()
    exclude_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate Bandit configuration fields."""
        valid_levels = list(BANDIT_LEVEL_FLAGS.keys())
        _SharedConfigValidator.validate_string_fields(
            self,
            severity={"non_empty": True, "allowed_values": valid_levels},
            confidence={"non_empty": True, "allowed_values": valid_levels},
        )
        _SharedConfigValidator.validate_bool_fields(self, "quiet")
        _SharedConfigValidator.validate_tuple_fields(
            self,
            "skip_tests",
            "exclude_dirs",
            "exclude_files",
        )
