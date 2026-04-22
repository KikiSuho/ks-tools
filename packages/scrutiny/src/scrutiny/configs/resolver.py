"""
Configuration resolution for scrutiny.

Provide environment-context detection and the five-level priority
resolver that combines CLI arguments, pyproject.toml values, context
detection, script defaults, and tool defaults into concrete config
dataclasses consumed by the tool handlers.

Classes
-------
ContextDetection : Detected execution context (CI, pre-commit, IDE, CLI).
EffectiveValue : A resolved configuration value paired with its source.
ConfigResolver : Five-level configuration resolution.

Examples
--------
>>> context = ContextDetection.detect()
>>> isinstance(context, ContextDetection)
True

"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from scrutiny.config import UserDefaults, UserDefaultsSnapshot
from scrutiny.configs.dataclasses import (
    BanditConfig,
    GlobalConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.core.enums import (
    ConfigSource,
    ConfigTier,
    FrameworkSelection,
    LoggerLevel,
    LogLocation,
    PythonVersion,
    SearchDepth,
    SecurityTool,
    ToolTimeout,
)
from scrutiny.core.exceptions import (
    EnumT,
    SCRError,
    SCRLoggerLevelError,
    SCRUserInputError,
    handle_errors,
)
from scrutiny.core.tool_data import (
    BANDIT_TIER_SETTINGS,
    MYPY_TIER_SETTINGS,
    RADON_TEST_EXCLUSIONS,
    RADON_TIER_SETTINGS,
    RUFF_FRAMEWORK_RULES,
    RUFF_SECURITY_RULES,
    build_ruff_rules,
)
from scrutiny.platforms import IDE_ENV_VARS, IDE_PROCESSES

# ====================================== #
#          CONTEXT DETECTION             #
# ====================================== #


CI_ENV_VARS: frozenset[str] = frozenset(
    {
        "CI",
        "CONTINUOUS_INTEGRATION",
        "BUILD_NUMBER",
        "GITHUB_ACTIONS",
        "GITHUB_RUN_ID",
        "JENKINS_URL",
        "JENKINS_HOME",
        "BUILD_ID",
        "TRAVIS",
        "TRAVIS_BUILD_ID",
        "CIRCLECI",
        "CIRCLE_BUILD_NUM",
        "GITLAB_CI",
        "CI_PIPELINE_ID",
        "CODEBUILD_BUILD_ID",
        "BITBUCKET_BUILD_NUMBER",
        "AZURE_HTTP_USER_AGENT",
        "TF_BUILD",
        "AGENT_ID",
        "TEAMCITY_VERSION",
        "BUILDKITE",
        "BUILDKITE_BUILD_ID",
        "DRONE",
        "DRONE_BUILD_NUMBER",
        "APPVEYOR",
        "APPVEYOR_BUILD_NUMBER",
        "HEROKU_TEST_RUN_ID",
        "SEMAPHORE",
        "BUDDY",
        "NETLIFY",
        "VERCEL",
        "RENDER",
        "RAILWAY_ENVIRONMENT",
        "FLY_APP_NAME",
    },
)

PRECOMMIT_ENV_VARS: frozenset[str] = frozenset(
    {
        "PRE_COMMIT",
        "PRE_COMMIT_FROM_REF",
        "PRE_COMMIT_TO_REF",
        "PRE_COMMIT_ORIGIN",
        "PRE_COMMIT_SOURCE",
        "PRE_COMMIT_CONFIG_FILE",
        "PRE_COMMIT_HOOK_TYPE",
    },
)


# IDE_ENV_VARS and IDE_PROCESSES are imported from platforms/ -- they
# contain platform-appropriate process names and environment variables.


@dataclass(frozen=True)
class _FieldSpec:
    """
    Declarative specification for a single GlobalConfig field.

    Attributes
    ----------
    gc_field : str
        GlobalConfig constructor keyword.
    cli_key : str
        Key in the parsed CLI arguments dict.
    snapshot_attr : str
        Attribute name on ``UserDefaultsSnapshot``.
    enum_class : Optional[type]
        Enum to wrap the resolved value in, or ``None`` for passthrough.
    exception_class : Optional[type]
        Exception class for enum construction errors (defaults to
        ``SCRUserInputError`` when ``None``).
    pyproject_tool : Optional[str]
        Tool section name in pyproject.toml config.
    pyproject_key : Optional[str]
        Key within the pyproject tool section.
    context_key : Optional[str]
        Key into the pre-computed context values dict.

    """

    gc_field: str
    cli_key: str
    snapshot_attr: str
    enum_class: Optional[type] = None
    exception_class: Optional[type] = None
    pyproject_tool: Optional[str] = None
    pyproject_key: Optional[str] = None
    context_key: Optional[str] = None


_GLOBAL_CONFIG_FIELDS: tuple[_FieldSpec, ...] = (
    # Category A: Simple resolve (19 entries)
    _FieldSpec("current_dir_as_root", "current_dir_as_root", "scr_current_dir_as_root"),
    _FieldSpec("follow_symlinks", "follow_symlinks", "scr_follow_symlinks"),
    _FieldSpec("run_ruff_formatter", "run_ruff_formatter", "run_ruff_formatter"),
    _FieldSpec("run_ruff_linter", "run_ruff_linter", "run_ruff_linter"),
    _FieldSpec("run_mypy", "run_mypy", "run_mypy"),
    _FieldSpec("run_radon", "run_radon", "run_radon"),
    _FieldSpec("run_security", "run_security", "run_security"),
    _FieldSpec(
        "fix",
        "fix",
        "ruff_fix",
        pyproject_tool="ruff",
        pyproject_key="fix",
    ),
    _FieldSpec(
        "unsafe_fixes",
        "unsafe_fixes",
        "ruff_unsafe_fixes",
        pyproject_tool="ruff",
        pyproject_key="unsafe_fixes",
    ),
    _FieldSpec("no_cache", "no_cache", "scr_no_cache"),
    _FieldSpec("clear_cache", "clear_cache", "scr_clear_cache"),
    _FieldSpec("parallel", "parallel", "scr_parallel"),
    _FieldSpec("generate_config", "generate_config", "scr_generate_config"),
    _FieldSpec("override_config", "override_config", "scr_override_config"),
    _FieldSpec("generate_config_in_cwd", "generate_config_in_cwd", "scr_generate_config_in_cwd"),
    _FieldSpec("include_test_config", "include_test_config", "scr_include_test_config"),
    _FieldSpec("include_test_plugins", "include_test_plugins", "scr_include_test_plugins"),
    _FieldSpec("test_config_only", "test_config_only", "scr_test_config_only"),
    _FieldSpec("pyproject_only", "pyproject_only", "scr_pyproject_only"),
    _FieldSpec("log_discovered_files", "log_discovered_files", "scr_log_discovered_files"),
    _FieldSpec("log_dir", "log_dir", "scr_log_dir"),
    _FieldSpec("exclude_dirs", "exclude_dirs", "scr_exclude_dirs"),
    _FieldSpec("exclude_files", "exclude_files", "scr_exclude_files"),
    # Category B: Enum-wrapped resolve (9 entries)
    _FieldSpec(
        "python_version",
        "python_version",
        "scr_python_version",
        enum_class=PythonVersion,
        pyproject_tool="ruff",
        pyproject_key="python_version",
    ),
    # line_length is resolved as a plain int so user-provided values from
    # pyproject.toml or the scrutiny CLI are not rejected when they do not
    # match a LineLength enum member.  Bounds are enforced by GlobalConfig
    # validation; scrutiny's own LineLength enum members remain the source
    # of script defaults and are unwrapped to int by build_global_config.
    _FieldSpec(
        "line_length",
        "line_length",
        "scr_line_length",
        pyproject_tool="ruff",
        pyproject_key="line_length",
    ),
    _FieldSpec(
        "max_upward_search_depth",
        "max_upward_search_depth",
        "scr_max_upward_search_depth",
        enum_class=SearchDepth,
    ),
    _FieldSpec(
        "file_logger_level",
        "file_logger_level",
        "scr_file_logger_level",
        enum_class=LoggerLevel,
        exception_class=SCRLoggerLevelError,
    ),
    _FieldSpec(
        "log_location",
        "log_location",
        "scr_log_location",
        enum_class=LogLocation,
    ),
    _FieldSpec(
        "security_tool",
        "security_tool",
        "security_tool",
        enum_class=SecurityTool,
    ),
    _FieldSpec(
        "pipeline_security_tool",
        "pipeline_security_tool",
        "pipeline_security_tool",
        enum_class=SecurityTool,
    ),
    _FieldSpec(
        "framework",
        "framework",
        "ruff_framework",
        enum_class=FrameworkSelection,
    ),
    _FieldSpec(
        "tool_timeout",
        "tool_timeout",
        "scr_tool_timeout",
        enum_class=ToolTimeout,
    ),
    # Category C: Context-aware resolve (3 entries)
    _FieldSpec(
        "console_logger_level",
        "console_logger_level",
        "scr_console_logger_level",
        enum_class=LoggerLevel,
        exception_class=SCRLoggerLevelError,
        context_key="ctx_console_level",
    ),
    _FieldSpec(
        "create_log",
        "create_log",
        "scr_create_log",
        context_key="ctx_create_log",
    ),
    _FieldSpec(
        "check_only",
        "check_only",
        "ruff_check_only",
        context_key="ctx_check_only",
    ),
)


def _coerce_line_length(raw_value: Any) -> int:
    """
    Convert a resolved line_length value to a plain ``int``.

    Parameters
    ----------
    raw_value : Any
        Value resolved from the priority chain.  Script defaults arrive
        as ``LineLength`` IntEnum members; pyproject and CLI values
        arrive as raw integers; any other type is rejected.

    Returns
    -------
    int
        Plain integer suitable for storage on ``GlobalConfig``.

    Raises
    ------
    SCRUserInputError
        If *raw_value* is not an integer-compatible value.

    """
    # Booleans are technically int in Python but meaningless here; reject them.
    if isinstance(raw_value, bool):
        raise SCRUserInputError(
            f"line_length must be int, got bool: {raw_value!r}",
        )
    # Accept any int (including IntEnum members); coerce to plain int.
    if isinstance(raw_value, int):
        return int(raw_value)
    raise SCRUserInputError(
        f"line_length must be int, got {type(raw_value).__name__}: {raw_value!r}",
    )


def _resolve_ruff_select(
    select_result: EffectiveValue,
    framework_rules: tuple[str, ...],
    *,
    is_pyproject_only: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Split the resolved ``select`` into a base list and an extend list.

    When pyproject.toml provides ``[tool.ruff.lint] select``, the returned
    ``select_rules`` mirrors the user's list verbatim and scrutiny's
    framework-specific rule families are placed into ``extend_select_rules``.
    Handlers emit the latter via ``--extend-select`` so framework rules are
    additive rather than an override of the user's list.  When pyproject
    does not provide ``select``, framework rules are folded into
    ``select_rules`` as before and ``extend_select_rules`` is empty.

    Parameters
    ----------
    select_result : EffectiveValue
        Result of resolving ``select_rules`` through the priority chain.
    framework_rules : tuple[str, ...]
        Framework-specific rule families derived from the scrutiny
        framework selection (may be empty when no framework is active).
    is_pyproject_only : bool
        When True, pyproject is the sole authoritative source; scrutiny
        defaults are skipped and framework rules are additive even when
        pyproject does not provide ``select``.

    Returns
    -------
    tuple[tuple[str, ...], tuple[str, ...]]
        ``(select_rules, extend_select_rules)`` pair.

    """
    # When pyproject provides select, keep it authoritative and make
    # framework rules additive via --extend-select.
    if select_result.source == ConfigSource.PYPROJECT:
        return tuple(select_result.value), framework_rules
    # In pyproject-only mode without a pyproject select, scrutiny emits
    # nothing for select.  Framework rules are still populated so that a
    # user passing ``--framework=<name>`` on the scrutiny CLI still gets
    # them via ``--extend-select``; the handler gate suppresses them
    # otherwise because ``pyproject_only`` blocks non-CLI emissions that
    # could shadow a native setting.
    if is_pyproject_only:
        return (), framework_rules
    # Fall back: the resolver already baked framework rules into script
    # defaults, so select_result.value is the full merged list and no
    # extend_select is needed on top of it.
    return tuple(select_result.value), ()


def _resolve_ruff_ignores(
    ignore_result: EffectiveValue,
    scrutiny_ignores: tuple[str, ...],
    *,
    is_pyproject_only: bool,
) -> tuple[str, ...]:
    """
    Resolve the final ``ignore`` list under the pyproject-authoritative rule.

    Parameters
    ----------
    ignore_result : EffectiveValue
        Result of resolving ``ignore_rules`` through the priority chain.
    scrutiny_ignores : tuple[str, ...]
        Scrutiny-derived ignores (version-gated plus mypy overlap) that
        apply only when pyproject does not express its own ignore list.
    is_pyproject_only : bool
        When True, pyproject is the sole authoritative source.

    Returns
    -------
    tuple[str, ...]
        The final ignore-rules list to store on ``RuffConfig``.

    """
    # When pyproject provides ignores, honour them verbatim; the handler
    # will suppress --ignore emission entirely so ruff reads the pyproject
    # value natively.
    if ignore_result.source == ConfigSource.PYPROJECT:
        return tuple(ignore_result.value)
    # In pyproject-only mode without a pyproject ignores list, scrutiny
    # suppresses --ignore emission so no ignore list is materialised.
    if is_pyproject_only:
        return ()
    return tuple(ignore_result.value) if ignore_result.value else scrutiny_ignores


def _flatten_native_pairs(
    native_keys_by_section: dict[str, frozenset[str]],
) -> frozenset[tuple[str, str]]:
    """
    Flatten per-section native keys into ``(section, key)`` tuples.

    The flat set supports O(1) membership tests by ``GlobalConfig.should_emit``
    when deciding whether to suppress a scrutiny-built CLI flag.

    Parameters
    ----------
    native_keys_by_section : dict[str, frozenset[str]]
        Mapping from section name to the frozenset of native keys observed
        in that section.

    Returns
    -------
    frozenset[tuple[str, str]]
        Flattened pair set ready for storage on ``GlobalConfig``.

    """
    pairs: set[tuple[str, str]] = set()
    # Fan out each section's native keys into (section, key) tuples.
    for section_name, native_keys in native_keys_by_section.items():
        # Pair every native key with its section name.
        for native_key in native_keys:
            pairs.add((section_name, native_key))
    return frozenset(pairs)


class ContextDetection(Enum):
    """
    Detected execution context.

    Attributes
    ----------
    IDE : str
        Running inside an IDE terminal.
    CI : str
        Running in a CI / CD pipeline.
    CLI : str
        Running from a standard terminal.
    PRECOMMIT : str
        Running as a pre-commit hook.

    """

    IDE = "ide"
    CI = "ci"
    CLI = "cli"
    PRECOMMIT = "precommit"

    @classmethod
    def detect(cls) -> ContextDetection:
        """
        Auto-detect the current execution context.

        Returns
        -------
        ContextDetection
            Detected context, checked in priority order:
            CI > pre-commit > IDE > CLI (fallback).

        """
        # CI takes highest priority; check pipeline indicators first
        if cls._detect_ci():
            return cls.CI
        # Pre-commit hooks run outside normal terminals
        if cls._detect_precommit():
            return cls.PRECOMMIT
        # IDE terminals get enriched output
        if cls._detect_ide():
            return cls.IDE
        return cls.CLI

    @classmethod
    def _detect_ci(cls) -> bool:
        """
        Check for CI environment variables.

        Returns
        -------
        bool
            True if any CI indicator is present.

        """
        return any(os.environ.get(env_variable) for env_variable in CI_ENV_VARS)

    @staticmethod
    def _detect_via_env_and_process(
        env_vars: frozenset[str],
        process_names: frozenset[str],
        *,
        substring_match: bool = False,
    ) -> bool:
        """
        Check environment variables and parent process name.

        Parameters
        ----------
        env_vars : frozenset[str]
            Environment variable names to check.
        process_names : frozenset[str]
            Parent process names (lowered) to match.
        substring_match : bool, optional
            When True, match any process name as a substring of the
            parent name.  When False, use exact set membership
            (default False).

        Returns
        -------
        bool
            True if any indicator matches.

        """
        # Check environment variables first (fast path).
        if any(os.environ.get(env_variable) for env_variable in env_vars):
            return True
        # Fall back to parent process name matching via psutil (lazy import
        # to avoid module-level side effects when the library is absent).
        # Lazy-import psutil to avoid module-level side effects
        try:
            import psutil  # noqa: PLC0415
        except ImportError:
            # psutil not installed; cannot check parent process
            return False
        # Look up parent process name for IDE/pre-commit detection
        try:
            parent = psutil.Process(os.getpid()).parent()
            # Check the parent process name when a parent exists
            if parent:
                name = (parent.name() or "").lower()
                # Use substring matching for processes like pre-commit
                if substring_match:
                    return any(process_name in name for process_name in process_names)
                return name in process_names
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            # Process lookup failed; fall through to return False.
            pass
        return False

    @classmethod
    def _detect_precommit(cls) -> bool:
        """
        Check for pre-commit environment variables or parent process.

        Returns
        -------
        bool
            True if pre-commit context is detected.

        """
        return cls._detect_via_env_and_process(
            PRECOMMIT_ENV_VARS,
            frozenset({"pre-commit"}),
            substring_match=True,
        )

    @classmethod
    def _detect_ide(cls) -> bool:
        """
        Check for IDE environment variables or parent process.

        Returns
        -------
        bool
            True if IDE context is detected.

        """
        return cls._detect_via_env_and_process(
            IDE_ENV_VARS,
            IDE_PROCESSES,
        )

    @classmethod
    def get_console_logger_level(
        cls,
        context: ContextDetection,
        snapshot: UserDefaultsSnapshot,
    ) -> LoggerLevel:
        """
        Determine console logger level for the given context.

        Parameters
        ----------
        context : ContextDetection
            The detected execution context.
        snapshot : UserDefaultsSnapshot
            Frozen snapshot of user-configurable defaults.

        Returns
        -------
        LoggerLevel
            QUIET for CI / pre-commit; snapshot value otherwise.

        """
        # Suppress console output in non-interactive environments
        if context in (cls.CI, cls.PRECOMMIT):
            return LoggerLevel.QUIET
        return snapshot.scr_console_logger_level

    @classmethod
    def should_create_log(
        cls,
        context: ContextDetection,
        snapshot: UserDefaultsSnapshot,
    ) -> bool:
        """
        Determine whether a log file should be created.

        Parameters
        ----------
        context : ContextDetection
            The detected execution context.
        snapshot : UserDefaultsSnapshot
            Frozen snapshot of user-configurable defaults.

        Returns
        -------
        bool
            False for CI / pre-commit; snapshot value otherwise.

        """
        # Disable file logging in non-interactive environments
        if context in (cls.CI, cls.PRECOMMIT):
            return False
        return snapshot.scr_create_log

    @classmethod
    def should_check_only(
        cls,
        context: ContextDetection,
        snapshot: UserDefaultsSnapshot,
    ) -> bool:
        """
        Determine whether check-only mode should be active.

        Parameters
        ----------
        context : ContextDetection
            The detected execution context.
        snapshot : UserDefaultsSnapshot
            Frozen snapshot of user-configurable defaults.

        Returns
        -------
        bool
            True for CI / pre-commit; snapshot value otherwise.

        """
        # Force check-only mode in CI and pre-commit to prevent file modification
        if context in (cls.CI, cls.PRECOMMIT):
            return True
        return snapshot.ruff_check_only


# ====================================== #
#       CONFIGURATION RESOLUTION         #
# ====================================== #


@dataclass(frozen=True)
class EffectiveValue:
    """
    A resolved configuration value paired with its source.

    Used by ``ConfigResolver`` to track where each setting came from.

    Parameters
    ----------
    value : Any
        The resolved configuration value.
    source : ConfigSource
        Priority level that provided this value.

    """

    value: Any
    source: ConfigSource

    def __repr__(self) -> str:
        return f"EffectiveValue({self.value!r}, source={self.source})"


class ConfigResolver:
    """
    Resolve configuration values using a five-level priority chain.

    Priority order (highest to lowest):
    1. CLI arguments
    2. pyproject.toml native ``[tool.*]`` sections
    3. Context detection (CI / IDE / pre-commit / CLI)
    4. Script defaults (``UserDefaults``)
    5. Tool defaults

    When *pyproject_only* is True, priorities 4 and 5 are skipped
    so that pyproject.toml is the sole authoritative config source
    (CLI still takes precedence).

    Parameters
    ----------
    cli_args : dict[str, Any]
        Parsed CLI arguments as a dict.
    pyproject_config : dict[str, dict[str, Any]]
        Mapped pyproject.toml configuration keyed by tool name.
    context : Optional[ContextDetection]
        Detected execution context.
    tier : ConfigTier
        Active quality tier.
    pyproject_only : bool
        When True, skip priorities 4-5 (script and tool defaults).
    snapshot : Optional[UserDefaultsSnapshot]
        Frozen snapshot of ``UserDefaults``.  When ``None``, one is
        created automatically via ``UserDefaults.to_frozen()``.

    """

    def __init__(
        self,
        cli_args: dict[str, Any],
        pyproject_config: Optional[dict[str, dict[str, Any]]] = None,
        context: Optional[ContextDetection] = None,
        tier: ConfigTier = ConfigTier.STRICT,
        pyproject_only: bool = False,
        snapshot: Optional[UserDefaultsSnapshot] = None,
        pyproject_native_keys: Optional[dict[str, frozenset[str]]] = None,
    ) -> None:
        self._cli = cli_args
        self._pyproject = pyproject_config or {}
        self._context = context
        self._tier = tier
        self._pyproject_only = pyproject_only
        self._snapshot: UserDefaultsSnapshot = snapshot or UserDefaults.to_frozen()
        # Raw native keys observed in pyproject.toml tool sections.  Used by
        # the execution layer to suppress scrutiny-built CLI flags when the
        # user has already expressed the equivalent setting natively.
        self._pyproject_native_keys: dict[str, frozenset[str]] = pyproject_native_keys or {}

    def _resolve_from_pyproject(
        self,
        pyproject_tool: Optional[str],
        pyproject_key: Optional[str],
    ) -> Optional[EffectiveValue]:
        """
        Look up a configuration value from pyproject.toml.

        Search the stored pyproject config for *pyproject_key* inside
        the *pyproject_tool* section.  TOML arrays (parsed as lists)
        are coerced to tuples for compatibility with frozen dataclass
        fields.

        Parameters
        ----------
        pyproject_tool : Optional[str]
            Tool section name in *pyproject_config*.
        pyproject_key : Optional[str]
            Key within the tool section.

        Returns
        -------
        Optional[EffectiveValue]
            Resolved value with ``ConfigSource.PYPROJECT`` source, or
            ``None`` when either argument is ``None`` or the key is
            not present in the tool section.

        """
        # Skip lookup when no tool section or key is specified
        if pyproject_tool is None or pyproject_key is None:
            return None
        tool_section = self._pyproject.get(pyproject_tool, {})
        # Key not present in the tool section
        if pyproject_key not in tool_section:
            return None
        raw = tool_section[pyproject_key]
        # TOML arrays parse as lists; coerce to tuples for
        # compatibility with frozen dataclass fields.
        if isinstance(raw, list):
            raw = tuple(raw)
        return EffectiveValue(raw, ConfigSource.PYPROJECT)

    @handle_errors
    def resolve(
        self,
        cli_key: Optional[str] = None,
        pyproject_tool: Optional[str] = None,
        pyproject_key: Optional[str] = None,
        context_value: Optional[Any] = None,
        script_default: Optional[Any] = None,
        tool_default: Optional[Any] = None,
    ) -> EffectiveValue:
        """
        Resolve a single configuration value.

        Walk the five-level priority chain and return the first
        non-None match.  In pyproject-only mode, priorities 4
        (script defaults) and 5 (tool defaults) are skipped —
        except that a safety-net fallback still returns
        *tool_default* when priorities 1-3 all yield ``None``.
        This prevents ``None`` resolution for fields that cannot
        be expressed in ``pyproject.toml`` (e.g., ``generate_config``,
        ``clear_cache``, ``create_log``).

        Parameters
        ----------
        cli_key : Optional[str]
            Key in *cli_args* dict.
        pyproject_tool : Optional[str]
            Tool section name in *pyproject_config*.
        pyproject_key : Optional[str]
            Key within the tool section.
        context_value : Optional[Any]
            Value determined by context detection.
        script_default : Optional[Any]
            Value from ``UserDefaults``.
        tool_default : Optional[Any]
            Tool's built-in default.

        Returns
        -------
        EffectiveValue
            Resolved value with its source.  In pyproject-only mode,
            if no higher-priority source provides a value, the
            safety net returns ``EffectiveValue(tool_default,
            ConfigSource.TOOL_DEFAULT)`` rather than ``None``.

        """
        # Priority 1: CLI
        if cli_key is not None:
            cli_val = self._cli.get(cli_key)
            if cli_val is not None:
                return EffectiveValue(cli_val, ConfigSource.CLI)

        # Priority 2: pyproject.toml
        pyproject_result = self._resolve_from_pyproject(pyproject_tool, pyproject_key)
        if pyproject_result is not None:
            return pyproject_result

        # Priority 3: Context
        if context_value is not None:
            return EffectiveValue(context_value, ConfigSource.CONTEXT)

        # Priorities 4-5 are skipped in pyproject-only mode.
        if not self._pyproject_only:
            # Priority 4: Script defaults
            if script_default is not None:
                return EffectiveValue(script_default, ConfigSource.SCRIPT)

            # Priority 5: Tool default
            if tool_default is not None:
                return EffectiveValue(tool_default, ConfigSource.TOOL_DEFAULT)

        # Safety net: when pyproject-only mode skipped priorities 4-5,
        # fall back to tool_default to prevent None resolution for
        # fields that lack a pyproject.toml key mapping (CRT-1/CRT-2).
        if tool_default is not None:
            return EffectiveValue(tool_default, ConfigSource.TOOL_DEFAULT)

        return EffectiveValue(None, ConfigSource.TOOL_DEFAULT)

    @staticmethod
    def _safe_enum_construct(
        enum_class: type[EnumT],
        raw_value: Any,
        field_name: str,
        exception_class: type[SCRError] = SCRUserInputError,
    ) -> EnumT:
        """
        Construct an enum member with a user-friendly error on failure.

        Parameters
        ----------
        enum_class : type[EnumT]
            Enum class to construct.
        raw_value : Any
            Value resolved from the priority chain.
        field_name : str
            Config field name for the error message.
        exception_class : type[SCRError]
            Exception class to raise on failure.

        Returns
        -------
        EnumT
            The constructed enum member.

        Raises
        ------
        SCRError
            If *raw_value* is not a valid member of *enum_class*.

        """
        # Attempt enum construction; re-raise with a user-friendly message on failure.
        try:
            return enum_class(raw_value)
        except (ValueError, TypeError) as error:
            valid_values = [member.value for member in enum_class]
            raise exception_class(
                f"Invalid value for {field_name}: {raw_value!r}. Valid options: {valid_values}",
            ) from error

    @handle_errors
    def build_global_config(self) -> GlobalConfig:
        """
        Build ``GlobalConfig`` from the priority chain.

        Iterates over ``_GLOBAL_CONFIG_FIELDS`` to resolve each field
        through the five-level priority chain, applying enum
        construction when specified.  ``config_tier`` is handled as a
        special case outside the loop because it sources its default
        from ``self._tier`` rather than the snapshot.

        Returns
        -------
        GlobalConfig
            Fully resolved orchestration configuration.

        """
        # Pre-compute context-sensitive values.
        context_values: dict[str, Any] = {}
        # Compute context-derived values when an execution context was detected
        if self._context is not None:
            context_values["ctx_console_level"] = ContextDetection.get_console_logger_level(
                self._context,
                self._snapshot,
            )
            context_values["ctx_create_log"] = ContextDetection.should_create_log(
                self._context,
                self._snapshot,
            )
            context_values["ctx_check_only"] = ContextDetection.should_check_only(
                self._context,
                self._snapshot,
            )

        snapshot = self._snapshot
        resolved: dict[str, Any] = {}

        # Resolve each field through the five-level priority chain
        for spec in _GLOBAL_CONFIG_FIELDS:
            raw = self.resolve(
                cli_key=spec.cli_key,
                pyproject_tool=spec.pyproject_tool,
                pyproject_key=spec.pyproject_key,
                context_value=context_values.get(spec.context_key) if spec.context_key else None,
                script_default=getattr(snapshot, spec.snapshot_attr),
                # tool_default intentionally mirrors script_default — no current
                # field distinguishes them.  Extend _FieldSpec if one ever does.
                tool_default=getattr(snapshot, spec.snapshot_attr),
            ).value

            # Wrap the raw value in its enum type when the spec requires it
            if spec.enum_class is not None:
                exc = spec.exception_class or SCRUserInputError
                raw = self._safe_enum_construct(spec.enum_class, raw, spec.gc_field, exc)

            resolved[spec.gc_field] = raw

        # Coerce line_length to plain int.  Script defaults arrive as LineLength
        # IntEnum members (which compare equal to ints but are not plain ints);
        # pyproject and CLI values arrive as raw ints.  Bounds are enforced by
        # GlobalConfig validation.
        resolved["line_length"] = _coerce_line_length(resolved["line_length"])

        # Special case: config_tier uses self._tier, not snapshot.
        resolved["config_tier"] = self.resolve(
            cli_key="config_tier",
            script_default=self._tier,
            tool_default=self._tier,
        ).value

        # Force the resolved pyproject_only to match the resolver's active mode
        # so should_emit sees a consistent state.  Without this override a
        # caller can pass pyproject_only=True to the resolver while the field
        # spec resolves False from snapshot defaults, causing handlers to
        # emit flags that the resolver itself has already suppressed.
        resolved["pyproject_only"] = self._pyproject_only

        # Attach provenance so the execution layer can honor the priority
        # contract: CLI overrides win, then pyproject, then scrutiny defaults.
        resolved["cli_override_keys"] = frozenset(self._cli.keys())
        resolved["pyproject_native_pairs"] = _flatten_native_pairs(self._pyproject_native_keys)

        return GlobalConfig(**resolved)

    @handle_errors
    def build_ruff_config(self, global_config: GlobalConfig) -> RuffConfig:
        """
        Build ``RuffConfig`` from tier, framework overlay, and overrides.

        Tier rules are merged with framework-specific rule families
        (when ``global_config.framework`` is not ``NONE``) before
        resolution through the priority chain.  Ignore rules are
        version-aware (``RUFF_VERSION_GATED_IGNORES``) and include
        mypy overlap rules (``RUFF_MYPY_OVERLAP``) when mypy is enabled.

        Parameters
        ----------
        global_config : GlobalConfig
            Resolved global configuration.

        Returns
        -------
        RuffConfig
            Ruff-specific configuration.

        """
        # Build combined tier+framework select rules so non-pyproject
        # resolutions still receive framework-specific families.  Framework
        # rules are also captured separately so that when pyproject owns the
        # select list they can flow into extend_select_rules as additive
        # --extend-select payloads rather than overriding the user's list.
        combined_tier_rules, effective_ignores = build_ruff_rules(
            global_config.config_tier,
            global_config.framework,
            global_config.python_version,
            global_config.run_mypy,
        )
        framework_rules = RUFF_FRAMEWORK_RULES.get(global_config.framework.value, ())

        # Resolve select and ignore rules through the priority chain.
        select_result = self.resolve(
            pyproject_tool="ruff.lint",
            pyproject_key="select_rules",
            script_default=combined_tier_rules,
            tool_default=combined_tier_rules,
        )
        ignore_result = self.resolve(
            pyproject_tool="ruff.lint",
            pyproject_key="ignore_rules",
            script_default=effective_ignores,
            tool_default=effective_ignores,
        )

        # Determine the final select list and any additive framework rules.
        # When pyproject provides select, framework rules become extensions
        # so the user's pyproject rule list stays authoritative; scrutiny's
        # own tier rules are dropped on the floor in that case.
        select_rules, extend_select_rules = _resolve_ruff_select(
            select_result,
            framework_rules,
            is_pyproject_only=self._pyproject_only,
        )

        # Ignore rules follow the same pyproject-authoritative contract:
        # pyproject's list wins, scrutiny-derived ignores only fill the gap.
        ignore_rules = _resolve_ruff_ignores(
            ignore_result,
            effective_ignores,
            is_pyproject_only=self._pyproject_only,
        )

        return RuffConfig(
            select_rules=select_rules,
            ignore_rules=ignore_rules,
            extend_select_rules=extend_select_rules,
            line_length=global_config.line_length,
            target_version=global_config.python_version.value,
            fix=global_config.effective_fix,
            unsafe_fixes=global_config.unsafe_fixes,
            no_cache=global_config.no_cache,
            exclude_dirs=global_config.exclude_dirs,
            exclude_files=global_config.exclude_files,
        )

    @handle_errors
    def build_mypy_config(self, global_config: GlobalConfig) -> MypyConfig:
        """
        Build ``MypyConfig`` from tier + overrides.

        Parameters
        ----------
        global_config : GlobalConfig
            Resolved global configuration.

        Returns
        -------
        MypyConfig
            Mypy-specific configuration.

        """
        tier = global_config.config_tier
        tier_settings = MYPY_TIER_SETTINGS.get(tier.value, {})

        dotted_version = global_config.python_version.to_dotted

        return MypyConfig(
            strict_mode=self.resolve(
                pyproject_tool="mypy",
                pyproject_key="strict_mode",
                script_default=tier_settings.get("strict_mode", False),
                tool_default=tier_settings.get("strict_mode", False),
            ).value,
            warn_unreachable=self.resolve(
                pyproject_tool="mypy",
                pyproject_key="warn_unreachable",
                script_default=tier_settings.get("warn_unreachable", True),
                tool_default=tier_settings.get("warn_unreachable", True),
            ).value,
            disallow_untyped_globals=self.resolve(
                pyproject_tool="mypy",
                pyproject_key="disallow_untyped_globals",
                script_default=tier_settings.get(
                    "disallow_untyped_globals",
                    False,
                ),
                tool_default=tier_settings.get(
                    "disallow_untyped_globals",
                    False,
                ),
            ).value,
            disallow_any_explicit=self.resolve(
                pyproject_tool="mypy",
                pyproject_key="disallow_any_explicit",
                script_default=tier_settings.get(
                    "disallow_any_explicit",
                    False,
                ),
                tool_default=tier_settings.get(
                    "disallow_any_explicit",
                    False,
                ),
            ).value,
            ignore_missing_imports=self.resolve(
                pyproject_tool="mypy",
                pyproject_key="ignore_missing_imports",
                script_default=tier_settings.get(
                    "ignore_missing_imports",
                    True,
                ),
                tool_default=tier_settings.get(
                    "ignore_missing_imports",
                    True,
                ),
            ).value,
            disable_error_code_import_untyped=self.resolve(
                pyproject_tool="mypy",
                pyproject_key="disable_error_code_import_untyped",
                script_default=tier_settings.get(
                    "disable_error_code_import_untyped",
                    True,
                ),
                tool_default=tier_settings.get(
                    "disable_error_code_import_untyped",
                    True,
                ),
            ).value,
            python_version=dotted_version,
            exclude_dirs=global_config.exclude_dirs,
            exclude_files=global_config.exclude_files,
        )

    @handle_errors
    def build_radon_config(self, global_config: GlobalConfig) -> RadonConfig:
        """
        Build ``RadonConfig`` from tier + overrides.

        Parameters
        ----------
        global_config : GlobalConfig
            Resolved global configuration.

        Returns
        -------
        RadonConfig
            Radon-specific configuration.

        """
        tier = global_config.config_tier
        tier_settings = RADON_TIER_SETTINGS.get(tier.value, {})

        return RadonConfig(
            minimum_complexity=self.resolve(
                script_default=tier_settings.get("minimum_complexity", "B"),
                tool_default=tier_settings.get("minimum_complexity", "B"),
            ).value,
            exclude_dirs=(RADON_TEST_EXCLUSIONS["dirs"] + global_config.exclude_dirs),
            exclude_files=(RADON_TEST_EXCLUSIONS["files"] + global_config.exclude_files),
        )

    @handle_errors
    def build_bandit_config(
        self,
        global_config: GlobalConfig,
    ) -> BanditConfig:
        """
        Build ``BanditConfig`` from tier + overrides.

        Parameters
        ----------
        global_config : GlobalConfig
            Resolved global configuration.

        Returns
        -------
        BanditConfig
            Bandit-specific configuration.

        """
        tier = global_config.config_tier
        tier_settings = BANDIT_TIER_SETTINGS.get(tier.value, {})

        return BanditConfig(
            severity=self.resolve(
                script_default=tier_settings.get("severity", "medium"),
                tool_default=tier_settings.get("severity", "medium"),
            ).value,
            confidence=self.resolve(
                script_default=tier_settings.get("confidence", "medium"),
                tool_default=tier_settings.get("confidence", "medium"),
            ).value,
            exclude_dirs=global_config.exclude_dirs,
            exclude_files=global_config.exclude_files,
        )

    @handle_errors
    def build_ruff_security_config(self, global_config: GlobalConfig) -> RuffConfig:
        """
        Build ``RuffConfig`` for security-only S-rules scan.

        Parameters
        ----------
        global_config : GlobalConfig
            Resolved global configuration.

        Returns
        -------
        RuffConfig
            Ruff configuration limited to S (security) rules.

        """
        return RuffConfig(
            select_rules=RUFF_SECURITY_RULES,
            ignore_rules=(),
            line_length=global_config.line_length,
            target_version=global_config.python_version.value,
            fix=False,
            unsafe_fixes=False,
            no_cache=global_config.no_cache,
            exclude_dirs=global_config.exclude_dirs,
            exclude_files=global_config.exclude_files,
        )
