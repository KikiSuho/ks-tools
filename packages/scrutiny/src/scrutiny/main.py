"""
Orchestration entry point for scrutiny.

Coordinate CLI parsing, configuration resolution, file discovery, tool
execution, and result aggregation. The ``main()`` function is the sole
public entry point; all other functions are internal orchestration helpers.

Functions
---------
main : Entry point for CLI execution.

Examples
--------
>>> from scrutiny.main import main
>>> callable(main)
True

"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, NamedTuple, Optional

from scrutiny.config import UserDefaults, UserDefaultsSnapshot
from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.configs.pyproject import PyProjectGenerator, PyProjectLoader
from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.cli import (
    cli_dict_to_flags,
    create_argument_parser,
    parse_cli_to_dict,
    run_doctor,
)
from scrutiny.core.enums import ConfigTier, FrameworkSelection, LogLocation, SearchDepth
from scrutiny.core.exceptions import (
    ExitCode,
    SCRConfigurationError,
    SCRError,
    SCRLoggerFileError,
    SCRProjectRootError,
    SCRSystemError,
    SCRUserInputError,
    format_scr_error,
    handle_errors,
)
from scrutiny.core.tool_data import (
    PYPROJECT_KEY_MAP,
    PYPROJECT_TEMPLATES,
    TOOL_ALIASES,
    TOOL_REGISTRY,
)
from scrutiny.execution.handlers import RadonCCHandler, ToolExecutor
from scrutiny.execution.results import ToolResult
from scrutiny.execution.services import (
    FileDiscoveryService,
    ProjectRootService,
    clear_tool_caches,
    which,
)
from scrutiny.output.header import print_header
from scrutiny.output.logger import DeferredLogBuffer, SCRLogger
from scrutiny.output.reporting import report_final_status
from scrutiny.output.run_logging import log_completed_result

_FALLBACK_CPU_COUNT = 4
_KEYBOARD_INTERRUPT_EXIT_CODE = 130
_MIN_TOOLS_FOR_PARALLEL = 2

# ====================================== #
#        ORCHESTRATION FUNCTIONS         #
# ====================================== #


@handle_errors
def _execute_tool(
    executor: ToolExecutor,
    tool_name: str,
    files: list[Path],
    tool_config: Any,
    global_config: GlobalConfig,
    effective_root: Path,
) -> ToolResult:
    """
    Execute a single tool via the executor.

    Decorated with ``@handle_errors`` so that any non-SCRError exception
    is wrapped in ``SCRUnexpectedError`` before reaching the caller.

    Parameters
    ----------
    executor : ToolExecutor
        Executor instance that dispatches to tool handlers.
    tool_name : str
        Tool identifier (e.g. ``"ruff_formatter"``, ``"mypy"``).
    files : list[Path]
        Python files to analyze.
    tool_config : Any
        Tool-specific configuration object.
    global_config : GlobalConfig
        Resolved global settings.
    effective_root : Path
        Effective project root.

    Returns
    -------
    ToolResult
        Execution result from the tool handler.

    """
    return executor.run_tool(
        tool_name,
        files,
        tool_config,
        global_config,
        effective_root,
    )


def _run_tool_safe(
    executor: ToolExecutor,
    tool_name: str,
    files: list[Path],
    tool_config: Any,
    global_config: GlobalConfig,
    effective_root: Path,
    logger: SCRLogger,
) -> ToolResult:
    """
    Run a single tool, returning a failure ``ToolResult`` on error.

    This function is the thread-boundary guard for tool execution.
    It delegates to ``_execute_tool`` (decorated with ``@handle_errors``)
    and catches ``SCRError``, which covers both known tool errors and
    unexpected exceptions wrapped by the decorator. All error paths are
    converted to a synthetic failure ``ToolResult`` so that parallel
    batches are not aborted by a single tool failure.

    Parameters
    ----------
    executor : ToolExecutor
        Executor instance that dispatches to tool handlers.
    tool_name : str
        Tool identifier (e.g. ``"ruff_formatter"``, ``"mypy"``).
    files : list[Path]
        Python files to analyze.
    tool_config : Any
        Tool-specific configuration object.
    global_config : GlobalConfig
        Resolved global settings.
    effective_root : Path
        Effective project root.
    logger : SCRLogger
        Logger for status and error messages.

    Returns
    -------
    ToolResult
        Execution result, or a synthetic failure result if the tool
        raised any exception.

    """
    # Execute the tool; synthesize a failure result on any SCRError (including unexpected errors
    # wrapped by @handle_errors on _execute_tool).
    try:
        result = _execute_tool(
            executor,
            tool_name,
            files,
            tool_config,
            global_config,
            effective_root,
        )
    except SCRError as tool_execution_error:
        # SCRError covers both known tool errors and unexpected errors wrapped by @handle_errors
        logger.error(f"{tool_name} failed: {tool_execution_error}")
        return ToolResult(
            tool=tool_name,
            success=False,
            exit_code=ExitCode.TOOL_FAILURE,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr=str(tool_execution_error),
            error_code=tool_execution_error.exit_code,
        )
    log_completed_result(
        tool_name,
        result,
        {tool_name: tool_config},
        logger,
        effective_root,
    )
    return result


@handle_errors
def _load_pyproject_config(
    start_path: Path,
    max_depth: SearchDepth = SearchDepth.MODERATE,
) -> tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]], Optional[Path]]:
    """
    Discover and parse pyproject.toml tool configuration.

    In addition to the scrutiny-internal mapped configuration, the
    raw native keys present in each managed ``[tool.*]`` section are
    returned so the execution layer can suppress scrutiny-built CLI
    flags when pyproject.toml already defines the equivalent native
    setting.

    Parameters
    ----------
    start_path : Path
        Starting directory for pyproject.toml search.
    max_depth : SearchDepth
        Maximum parent directories to search.

    Returns
    -------
    tuple[dict[str, dict[str, Any]], dict[str, frozenset[str]], Optional[Path]]
        Mapped configuration, raw native keys observed per managed
        tool section, and the path to pyproject.toml (or ``None``).

    """
    pyproject_mapped: dict[str, dict[str, Any]] = {}
    pyproject_native_keys: dict[str, frozenset[str]] = {}
    pyproject_path = PyProjectLoader.find_pyproject_toml(start_path, max_depth=max_depth)
    # Load and remap tool configuration sections from pyproject.toml.
    if pyproject_path is not None:
        # Parse the file and remap each tool section; capture warnings on failure
        try:
            raw_data = PyProjectLoader.load_from_path(pyproject_path)
            # Extract and remap each tool's configuration section.
            for tool_name in PYPROJECT_KEY_MAP:
                native = PyProjectLoader.extract_tool_config(
                    raw_data,
                    tool_name,
                )
                # Only remap sections that contain configuration values
                if native:
                    pyproject_mapped[tool_name] = PyProjectLoader.map_to_internal_keys(
                        tool_name,
                        native,
                    )
            # Collect raw native keys across every managed section so the
            # execution layer can suppress scrutiny-built CLI flags when
            # pyproject.toml already defines the equivalent setting.
            pyproject_native_keys = PyProjectLoader.collect_native_keys(
                raw_data,
                tuple(PYPROJECT_TEMPLATES.keys()),
            )
        except SCRConfigurationError as config_read_error:
            # Log a warning and continue with empty config rather than aborting
            DeferredLogBuffer.capture(
                "warning", f"Failed to read {pyproject_path}: {config_read_error}"
            )
    return pyproject_mapped, pyproject_native_keys, pyproject_path


def _show_effective_config(
    logger: SCRLogger,
    global_config: GlobalConfig,
    context: ContextDetection,
    effective_root: Path,
    pyproject_path: Optional[Path],
) -> int:
    """
    Display effective configuration and return.

    Shows tier, Python version, line length, fix mode, no-cache,
    clear-cache, parallelism, framework (when not ``NONE``),
    pyproject-only mode (when active), root, context, enabled tools,
    pyproject.toml path, and logging settings.

    Parameters
    ----------
    logger : SCRLogger
        Logger instance.
    global_config : GlobalConfig
        Resolved configuration.
    context : ContextDetection
        Detected execution context.
    effective_root : Path
        Effective project root.
    pyproject_path : Optional[Path]
        Path to pyproject.toml (or None).

    Returns
    -------
    int
        Always returns 0 (diagnostic mode; no analysis performed).

    """
    logger.status("Effective Configuration")
    logger.status(f"  Tier: {global_config.config_tier.value}")
    logger.status(f"  Python: {global_config.python_version.value}")
    logger.status(f"  Line length: {global_config.line_length}")
    logger.status(f"  Fix: {global_config.effective_fix}")
    logger.status(f"  No cache: {global_config.no_cache}")
    logger.status(f"  Clear cache: {global_config.clear_cache}")
    logger.status(f"  Parallel: {global_config.parallel}")
    # Show framework only when one is configured
    if global_config.framework != FrameworkSelection.NONE:
        logger.status(f"  Framework: {global_config.framework.value}")
    # Indicate when pyproject-only mode overrides script defaults
    if global_config.pyproject_only:
        logger.status("  Mode: pyproject-only (script defaults bypassed)")
    logger.status(f"  Root: {effective_root}")
    logger.status(f"  Context: {context.value}")
    logger.status(f"  Enabled: {global_config.get_enabled_tools(context)}")
    # Show pyproject.toml path when one was discovered
    if pyproject_path:
        logger.status(f"  pyproject.toml: {pyproject_path}")
    log_info = logger.get_log_info()
    logger.status(f"  Console level: {log_info['console_level']}")
    logger.status(f"  File level: {log_info['file_level']}")
    logger.status(f"  Log file: {log_info['log_file_path'] or 'disabled'}")
    return 0


@handle_errors
def _determine_tool_names(
    args: argparse.Namespace,
    global_config: GlobalConfig,
    context: ContextDetection,
) -> list[str]:
    """
    Resolve tool names from CLI arguments or global configuration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    global_config : GlobalConfig
        Resolved configuration.
    context : ContextDetection
        Detected execution context (determines which security tool to use).

    Returns
    -------
    list[str]
        Tool identifiers to execute.

    """
    # Explicit --tool selection overrides the global enabled-tools list.
    # A user naming a specific tool is expressing explicit intent, so the
    # per-tool run_* defaults are bypassed; the requested tool runs even
    # when its default toggle is off (e.g. ``--tool ruff_formatter`` runs
    # the formatter regardless of ``RUN_RUFF_FORMATTER``).
    if args.tools:
        tool_names: list[str] = []
        # Expand aliases into their constituent tool identifiers.
        for tool_arg in args.tools:
            expanded = TOOL_ALIASES.get(tool_arg, [tool_arg])
            tool_names.extend(expanded)
        return tool_names
    # Default: derive tool list from global config and execution context.
    return global_config.get_enabled_tools(context)


@handle_errors
def _execute_tools_parallel(
    tool_names: list[str],
    executor: ToolExecutor,
    discovered_files: list[Path],
    tool_config_map: dict[str, Any],
    global_config: GlobalConfig,
    effective_root: Path,
    logger: SCRLogger,
) -> list[ToolResult]:
    """
    Execute tools with parallel strategy for read-only analyzers.

    File-modifying tools (ruff_formatter, ruff_linter) run sequentially
    first, then read-only analyzers run in parallel.

    Parameters
    ----------
    tool_names : list[str]
        Tool identifiers to execute.
    executor : ToolExecutor
        Tool executor instance.
    discovered_files : list[Path]
        Python files to process.
    tool_config_map : dict[str, Any]
        Mapping of tool name to configuration.
    global_config : GlobalConfig
        Resolved configuration.
    effective_root : Path
        Project root directory.
    logger : SCRLogger
        Logger instance.

    Returns
    -------
    list[ToolResult]
        Results from all tool executions.

    """
    sequential_tools = {"ruff_formatter", "ruff_linter"}
    results: list[ToolResult] = []

    # Phase 1: Run file-modifying tools sequentially, in order.
    parallel_batch: list[str] = []
    for name in tool_names:
        # Route each tool to sequential or parallel execution based on whether it modifies files
        if name in sequential_tools:
            # File-modifying tools must run sequentially to avoid race conditions
            results.append(
                _run_tool_safe(
                    executor,
                    name,
                    discovered_files,
                    tool_config_map.get(name),
                    global_config,
                    effective_root,
                    logger,
                ),
            )
        else:
            # Queue read-only analyzers for the parallel batch
            parallel_batch.append(name)

    # Phase 2: Run read-only analyzers in parallel.
    if parallel_batch:
        with ThreadPoolExecutor(
            max_workers=min(len(parallel_batch), os.cpu_count() or _FALLBACK_CPU_COUNT),
        ) as pool:
            futures = [
                pool.submit(
                    _run_tool_safe,
                    executor,
                    name,
                    discovered_files,
                    tool_config_map.get(name),
                    global_config,
                    effective_root,
                    logger,
                )
                for name in parallel_batch
            ]
            results.extend(future.result() for future in as_completed(futures))

    return results


def _execute_tools_sequential(
    tool_names: list[str],
    executor: ToolExecutor,
    discovered_files: list[Path],
    tool_config_map: dict[str, Any],
    global_config: GlobalConfig,
    effective_root: Path,
    logger: SCRLogger,
) -> list[ToolResult]:
    """
    Execute all tools sequentially.

    Parameters
    ----------
    tool_names : list[str]
        Tool identifiers to execute.
    executor : ToolExecutor
        Tool executor instance.
    discovered_files : list[Path]
        Python files to process.
    tool_config_map : dict[str, Any]
        Mapping of tool name to configuration.
    global_config : GlobalConfig
        Resolved configuration.
    effective_root : Path
        Project root directory.
    logger : SCRLogger
        Logger instance.

    Returns
    -------
    list[ToolResult]
        Results from all tool executions.

    """
    results: list[ToolResult] = []
    # Execute each tool in order, collecting results
    for name in tool_names:
        results.append(  # noqa: PERF401
            _run_tool_safe(
                executor,
                name,
                discovered_files,
                tool_config_map.get(name),
                global_config,
                effective_root,
                logger,
            ),
        )
    return results


@handle_errors
def _dispatch_tool_execution(
    tool_names: list[str],
    global_config: GlobalConfig,
    discovered_files: list[Path],
    tool_config_map: dict[str, Any],
    effective_root: Path,
    logger: SCRLogger,
) -> list[ToolResult]:
    """
    Choose parallel or sequential execution and run all tools.

    Parameters
    ----------
    tool_names : list[str]
        Tools to execute.
    global_config : GlobalConfig
        Global configuration.
    discovered_files : list[Path]
        Python files to analyze.
    tool_config_map : dict[str, Any]
        Mapping of tool name to config object.
    effective_root : Path
        Project root.
    logger : SCRLogger
        Logger instance.

    Returns
    -------
    list[ToolResult]
        Results from all tool runs.

    """
    executor = ToolExecutor(timeout=int(global_config.tool_timeout))
    # Use parallel execution when enabled and more than one tool is queued.
    if global_config.parallel and len(tool_names) >= _MIN_TOOLS_FOR_PARALLEL:
        return _execute_tools_parallel(
            tool_names,
            executor,
            discovered_files,
            tool_config_map,
            global_config,
            effective_root,
            logger,
        )
    return _execute_tools_sequential(
        tool_names,
        executor,
        discovered_files,
        tool_config_map,
        global_config,
        effective_root,
        logger,
    )


@handle_errors
def _run_config_generation(
    start_path: Path,
    global_config: GlobalConfig,
) -> Optional[str]:
    """
    Generate or merge pyproject.toml using a preliminary config.

    Use the supplied ``GlobalConfig`` (built from CLI + UserDefaults
    only, without pyproject.toml input) for root discovery and
    template rendering.  Returns a status string for deferred
    logging (the logger is not yet available at this point).

    Parameters
    ----------
    start_path : Path
        Starting directory for root discovery.
    global_config : GlobalConfig
        Preliminary configuration built from CLI arguments and
        ``UserDefaults`` only (no pyproject.toml data).

    Returns
    -------
    Optional[str]
        Generation status (``"created"``, ``"updated"``,
        ``"unchanged"``, ``"skipped"``), or None if generation
        is disabled.

    """
    # Skip generation when the flag is not set.
    if not global_config.generate_config:
        return None

    effective_root = ProjectRootService.get_project_root(start_path, global_config)
    actual_root = ProjectRootService.get_actual_project_root(start_path, global_config)
    config_target = effective_root if global_config.generate_config_in_cwd else actual_root
    return PyProjectGenerator.generate_or_merge(config_target, global_config)


def _maybe_emit_config_hint(
    logger: SCRLogger,
    global_config: GlobalConfig,
    *,
    pyproject_has_config: bool,
) -> None:
    """
    Emit a one-line hint when no managed pyproject section was detected.

    Shown once per run at the end of ``_run_analysis_phase`` to nudge
    first-time users toward bootstrapping their pyproject.toml.  The
    hint is suppressed when the current run performed generation (the
    user has already acted), when pyproject.toml already carries any
    managed section, or when pyproject-only mode signals that the user
    has intentionally opted out of scrutiny's own defaults.

    Parameters
    ----------
    logger : SCRLogger
        Active run logger for status-level output.
    global_config : GlobalConfig
        Resolved global configuration.
    pyproject_has_config : bool
        True when pyproject.toml contributed at least one managed
        tool section to the resolved configuration.

    """
    # Skip when pyproject already defines a managed section.
    if pyproject_has_config:
        return
    # Skip when the user explicitly generated this run; they acted.
    if global_config.generate_config:
        return
    # Skip in pyproject-only mode; the user has intentionally opted out.
    if global_config.pyproject_only:
        return
    logger.status(
        "No [tool.ruff] / [tool.mypy] / [tool.bandit] section found. "
        "Run `scrutiny --generate-config` to create one.",
    )


def _resolve_log_root(
    start_path: Path,
    global_config: GlobalConfig,
) -> Optional[Path]:
    """
    Determine the base directory for log file placement.

    Parameters
    ----------
    start_path : Path
        Invocation directory / starting path.
    global_config : GlobalConfig
        Resolved configuration containing ``log_location``.

    Returns
    -------
    Optional[Path]
        Resolved log root, or ``None`` when logging is disabled.

    """
    base = start_path if start_path.is_dir() else start_path.parent

    # CURRENT_DIR: always use the invocation directory.
    if global_config.log_location == LogLocation.CURRENT_DIR:
        return base.resolve()

    # PROJECT_ROOT and HYBRID both attempt upward search.
    try:
        return ProjectRootService.get_actual_project_root(start_path, global_config)
    except SCRProjectRootError:
        # HYBRID: fall back to CWD when no project root is found.
        if global_config.log_location == LogLocation.HYBRID:
            DeferredLogBuffer.capture(
                "warning",
                "No project root found; placing log in current directory.",
            )
            return base.resolve()
        # PROJECT_ROOT: disable logging, inform user.
        DeferredLogBuffer.capture(
            "warning",
            "No project root found for log placement. "
            "Log creation disabled. Use --log-location=current_dir "
            "or --log-location=hybrid to log without a project root.",
        )
        return None


def _create_logger(actual_root: Path, global_config: GlobalConfig) -> SCRLogger:
    """
    Create a SCRLogger, falling back to console-only on file errors.

    Parameters
    ----------
    actual_root : Path
        Project root for log file placement.
    global_config : GlobalConfig
        Logger configuration.

    Returns
    -------
    SCRLogger
        Initialised logger instance.

    """
    # Attempt file-backed logger; fall back to console-only on failure
    try:
        # Normal path: return logger with file logging enabled
        return SCRLogger(actual_root, global_config)
    except SCRLoggerFileError:
        # Fall back to console-only logging when file creation fails. Use dataclasses.replace to
        # preserve all resolved config values.
        fallback_config = dataclasses.replace(global_config, create_log=False)
        logger = SCRLogger(actual_root, fallback_config)
        logger.warning("Log file creation failed; logging to console only.")
        return logger


class _ResolvedConfig(NamedTuple):
    """
    Full configuration produced by ``_build_resolved_config``.

    Attributes
    ----------
    resolver : ConfigResolver
        Fully constructed configuration resolver.
    global_config : GlobalConfig
        Resolved global settings from all configuration sources.
    context : ContextDetection
        Detected execution context (IDE, CI, terminal).
    effective_root : Path
        Effective project root directory.
    pyproject_path : Optional[Path]
        Path to discovered pyproject.toml, or None if absent.
    log_root : Optional[Path]
        Base directory for log file placement, or None to disable.
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    """

    resolver: ConfigResolver
    global_config: GlobalConfig
    context: ContextDetection
    effective_root: Path
    pyproject_path: Optional[Path]
    log_root: Optional[Path]
    pyproject_has_config: bool


class _PreLoggerResult(NamedTuple):
    """
    Values produced by the pre-logger bootstrap phase.

    Attributes
    ----------
    gen_status : Optional[str]
        Deferred generation status message, or None if skipped.
    resolver : ConfigResolver
        Fully constructed configuration resolver.
    global_config : GlobalConfig
        Resolved global settings from all configuration sources.
    context : ContextDetection
        Detected execution context (IDE, CI, terminal).
    effective_root : Path
        Effective project root directory.
    pyproject_path : Optional[Path]
        Path to discovered pyproject.toml, or None if absent.
    log_root : Optional[Path]
        Base directory for log file placement, or None to disable.
    cli_overrides : tuple[str, ...]
        Human-readable CLI flags passed by the user.
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    """

    gen_status: Optional[str]
    resolver: ConfigResolver
    global_config: GlobalConfig
    context: ContextDetection
    effective_root: Path
    pyproject_path: Optional[Path]
    log_root: Optional[Path]
    cli_overrides: tuple[str, ...]
    pyproject_has_config: bool


@handle_errors
def _build_preliminary_config(
    start_path: Path,
    cli_dict: dict[str, Any],
    snapshot: UserDefaultsSnapshot,
    tier: ConfigTier,
) -> Optional[str]:
    """
    Build a preliminary config and run pyproject.toml generation.

    Constructs a ``GlobalConfig`` from CLI args and ``UserDefaults`` only
    (empty pyproject, no context) so that generation runs before the
    resolver reads the file it is about to create or update.

    Parameters
    ----------
    start_path : Path
        Starting directory for root discovery.
    cli_dict : dict[str, Any]
        Parsed CLI arguments as a flat dictionary.
    snapshot : UserDefaultsSnapshot
        Frozen snapshot of user-configurable defaults.
    tier : ConfigTier
        Resolved configuration tier.

    Returns
    -------
    Optional[str]
        Generation status message, or ``None`` if generation was not requested.

    """
    prelim_resolver = ConfigResolver(
        cli_args=cli_dict,
        pyproject_config={},
        context=None,
        tier=tier,
        snapshot=snapshot,
    )
    prelim_config = prelim_resolver.build_global_config()
    return _run_config_generation(start_path, prelim_config)


@handle_errors
def _build_resolved_config(
    start_path: Path,
    cli_dict: dict[str, Any],
    snapshot: UserDefaultsSnapshot,
    tier: ConfigTier,
) -> _ResolvedConfig:
    """
    Resolve the full configuration and discover the project root.

    Reads the now-fresh ``pyproject.toml``, builds the full
    ``GlobalConfig`` with the complete five-level priority chain,
    and discovers the project root.  Logger creation is deferred to
    ``_run_analysis_phase`` so the file handle is always born inside
    a ``with`` block.

    Parameters
    ----------
    start_path : Path
        Starting directory for root discovery.
    cli_dict : dict[str, Any]
        Parsed CLI arguments as a flat dictionary.
    snapshot : UserDefaultsSnapshot
        Frozen snapshot of user-configurable defaults.
    tier : ConfigTier
        Resolved configuration tier.

    Returns
    -------
    _ResolvedConfig
        Full configuration bundle including resolver, global config,
        detected context, effective root, pyproject path, log root,
        and whether pyproject.toml contributed tool configuration.

    """
    # Detect execution context (IDE, CI, terminal, etc.).
    context = ContextDetection.detect()
    # Load pyproject.toml configuration (may be empty if no file found).
    pyproject_mapped, pyproject_native_keys, pyproject_path = _load_pyproject_config(
        start_path,
        max_depth=snapshot.scr_max_upward_search_depth,
    )

    # Build the full five-level config resolver with all sources.
    pyproject_only = cli_dict.get("pyproject_only", snapshot.scr_pyproject_only)
    resolver = ConfigResolver(
        cli_args=cli_dict,
        pyproject_config=pyproject_mapped,
        pyproject_native_keys=pyproject_native_keys,
        context=context,
        tier=tier,
        pyproject_only=pyproject_only,
        snapshot=snapshot,
    )
    global_config = resolver.build_global_config()

    # Discover project root and resolve log file placement.
    effective_root = ProjectRootService.get_project_root(start_path, global_config)
    log_root = _resolve_log_root(start_path, global_config)

    return _ResolvedConfig(
        resolver=resolver,
        global_config=global_config,
        context=context,
        effective_root=effective_root,
        pyproject_path=pyproject_path,
        log_root=log_root,
        pyproject_has_config=bool(pyproject_mapped),
    )


@handle_errors
def _resolve_start_path(args: argparse.Namespace) -> Path:
    """
    Derive the analysis root from CLI path arguments.

    When no paths are given, fall back to the current working directory.
    When a file path is provided, use its parent directory as the start.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments (may contain ``paths`` attribute).

    Returns
    -------
    Path
        Resolved starting directory for analysis.

    Raises
    ------
    SCRUserInputError
        If any user-supplied path does not exist on disk.

    """
    # Validate and resolve user-supplied paths when provided
    if args.paths:
        paths: list[Path] = args.paths
        # Validate every path before using the first one as the start directory
        for user_path in paths:
            # Reject user-supplied paths that do not exist on disk
            if not user_path.exists():
                raise SCRUserInputError(f"Path does not exist: {user_path}")
        return paths[0] if paths[0].is_dir() else paths[0].parent
    return Path.cwd()


def _verify_tool_availability(tool_names: list[str]) -> None:
    """
    Check that all required tool executables exist on PATH.

    Collects all missing tools and raises a single ``SCRSystemError``
    listing every missing executable with install guidance.

    Parameters
    ----------
    tool_names : list[str]
        Logical tool names scheduled for execution.

    Raises
    ------
    SCRSystemError
        If one or more required executables are not found.

    """
    seen_executables: set[str] = set()
    missing_tools: list[tuple[str, str]] = []
    # Check each tool's executable, deduplicating shared binaries
    for logical_name in tool_names:
        executable, install_pkg = TOOL_REGISTRY.get(
            logical_name,
            (logical_name, logical_name),
        )
        # Skip duplicate executables shared by multiple logical tool names
        if executable in seen_executables:
            continue
        seen_executables.add(executable)
        # Record tools whose executable is not found on PATH
        if which(executable) is None:
            missing_tools.append((executable, install_pkg))
    # Raise a single error listing all missing tools with install guidance
    if missing_tools:
        all_pkgs = " ".join(pkg for _, pkg in missing_tools)
        raise SCRSystemError(
            f"Missing tools: {', '.join(exe for exe, _ in missing_tools)}. "
            f"Install: pip install {all_pkgs} | conda install {all_pkgs}",
        )


def _compute_mi_ranks(
    tool_names: list[str],
    discovered_files: list[Path],
    effective_root: Path,
    global_config: GlobalConfig,
) -> Optional[dict[str, str]]:
    """
    Compute Maintainability Index ranks when radon is enabled.

    Parameters
    ----------
    tool_names : list[str]
        Active tool names.
    discovered_files : list[Path]
        Python files to analyse.
    effective_root : Path
        Project root directory.
    global_config : GlobalConfig
        Resolved global configuration.

    Returns
    -------
    Optional[dict[str, str]]
        MI rank mapping, or ``None`` when radon is not enabled.

    """
    # Skip MI computation when radon is not in the active tool set
    if "radon" not in tool_names:
        return None
    radon_handler = RadonCCHandler(timeout=int(global_config.tool_timeout))
    return radon_handler.compute_maintainability_index(
        discovered_files,
        effective_root,
    )


@handle_errors
def _run_analysis_phase(
    args: argparse.Namespace,
    gen_status: Optional[str],
    resolver: ConfigResolver,
    global_config: GlobalConfig,
    context: ContextDetection,
    effective_root: Path,
    pyproject_path: Optional[Path],
    log_root: Optional[Path],
    cli_overrides: tuple[str, ...] = (),
    pyproject_has_config: bool = False,
) -> int:
    """
    Execute the analysis phase: discover files, run tools, report.

    This function owns the ``with logger:`` block and the inner
    ``try / except SCRError`` boundary.  It covers everything from
    deferred-log flushing through final status reporting.

    Logger creation is deferred to this function so the file handle
    is always born inside the ``with`` block.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    gen_status : Optional[str]
        Deferred generation status message (logged once logger is live).
    resolver : ConfigResolver
        Fully resolved configuration resolver.
    global_config : GlobalConfig
        Resolved global configuration.
    context : ContextDetection
        Detected execution context.
    effective_root : Path
        Effective project root directory.
    pyproject_path : Optional[Path]
        Path to pyproject.toml (for ``--show-config``).
    log_root : Optional[Path]
        Base directory for log file placement, or None to disable
        file logging.
    cli_overrides : tuple[str, ...]
        Human-readable CLI flags passed by the user (empty when none).
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    Returns
    -------
    int
        0 when all tools pass or no work to do, ``ExitCode.ISSUES_FOUND``
        (10) when tools found problems, ``ExitCode.TOOL_FAILURE`` (11)
        when a tool crashed, or 1-8 when a ``SCRError`` is caught during
        the analysis phase.

    """
    # Create logger before the `with` block so the context manager guards its full lifecycle.
    if log_root is not None:
        # Normal path: create logger with file logging at the resolved root
        logger = _create_logger(log_root, global_config)
    else:
        # No valid log root: create console-only logger
        fallback_config = dataclasses.replace(global_config, create_log=False)
        logger = SCRLogger(effective_root, fallback_config)

    with logger:
        # Run the full analysis pipeline; catch SCRErrors for structured reporting
        try:
            # Flush deferred messages now that the logger is live
            DeferredLogBuffer.flush(logger)

            # Show-config mode (early return).
            if args.show_config:
                return _show_effective_config(
                    logger,
                    global_config,
                    context,
                    effective_root,
                    pyproject_path,
                )

            # Clear tool caches when requested (before tool execution).
            if global_config.clear_cache:
                clear_tool_caches(effective_root, logger)

            # Determine tools to run (before banner so we can display them).
            tool_names = _determine_tool_names(args, global_config, context)
            # Exit early when no tools are enabled for execution
            if not tool_names:
                logger.warning("No tools enabled. Nothing to do.")
                return 0

            # Pre-flight: verify all required executables are available.
            _verify_tool_availability(tool_names)

            # Discover files.
            paths_to_scan = (
                [Path(path_arg) for path_arg in args.paths] if args.paths else [effective_root]
            )
            discovered_files = FileDiscoveryService.discover_files(
                paths_to_scan,
                global_config,
            )
            # Exit early when no Python files are found to analyse
            if not discovered_files:
                logger.warning("No Python files found to analyse.")
                return 0

            # Compute Maintainability Index when radon is enabled.
            mi_ranks = _compute_mi_ranks(
                tool_names,
                discovered_files,
                effective_root,
                global_config,
            )

            # Header banner (after discovery so file count is available).
            print_header(
                logger,
                global_config,
                context,
                effective_root,
                tool_names,
                len(discovered_files),
                discovered_files=discovered_files,
                log_discovered_files=global_config.log_discovered_files,
                mi_ranks=mi_ranks,
                gen_status=gen_status,
                cli_overrides=cli_overrides,
                pyproject_has_config=pyproject_has_config,
            )

            # Build tool configs.
            ruff_config = resolver.build_ruff_config(global_config)
            mypy_config = resolver.build_mypy_config(global_config)
            radon_config = resolver.build_radon_config(global_config)
            bandit_config = resolver.build_bandit_config(global_config)
            ruff_security_config = resolver.build_ruff_security_config(
                global_config,
            )

            tool_config_map: dict[str, Any] = {
                "ruff_formatter": ruff_config,
                "ruff_linter": ruff_config,
                "mypy": mypy_config,
                "radon": radon_config,
                "bandit": bandit_config,
                "ruff_security": ruff_security_config,
            }

            # Execute tools and report.
            results = _dispatch_tool_execution(
                tool_names,
                global_config,
                discovered_files,
                tool_config_map,
                effective_root,
                logger,
            )
            exit_code = report_final_status(results, discovered_files, logger)
            # Nudge first-time users toward config generation when no
            # managed section was detected and this run did not generate.
            _maybe_emit_config_hint(
                logger,
                global_config,
                pyproject_has_config=pyproject_has_config,
            )
            return exit_code

        except SCRError as analysis_pipeline_failure:
            # Buffer was already drained at DeferredLogBuffer.flush() above; no pre-logger messages
            # remain, so a second flush is unnecessary.
            logger.error(
                f"{analysis_pipeline_failure.display_tag} {analysis_pipeline_failure}",
            )
            logger.status(
                f"Error Code: {analysis_pipeline_failure.exit_code} "
                f"({ExitCode(analysis_pipeline_failure.exit_code).name})",
            )
            return analysis_pipeline_failure.exit_code


# ====================================== #
#         PRE-LOGGER BOOTSTRAP           #
# ====================================== #


def _bootstrap_pre_logger(
    args: argparse.Namespace,
) -> _PreLoggerResult:
    """
    Run pre-logger bootstrap: CLI parsing, config resolution, root discovery.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.

    Returns
    -------
    _PreLoggerResult
        All values needed by ``_run_analysis_phase``.

    Raises
    ------
    SCRError
        On any configuration or system error during bootstrap.

    """
    start_path = _resolve_start_path(args)
    cli_dict = parse_cli_to_dict(args)
    cli_overrides = cli_dict_to_flags(cli_dict)
    snapshot = UserDefaults.to_frozen()

    tier = cli_dict.get("config_tier", snapshot.scr_config_tier)
    # Only build the preliminary config when generate_config is active; otherwise the double-resolve
    # is wasted work (the common case).
    should_generate = cli_dict.get("generate_config", snapshot.scr_generate_config)
    gen_status = (
        _build_preliminary_config(start_path, cli_dict, snapshot, tier) if should_generate else None
    )
    resolved = _build_resolved_config(start_path, cli_dict, snapshot, tier)

    return _PreLoggerResult(
        gen_status=gen_status,
        resolver=resolved.resolver,
        global_config=resolved.global_config,
        context=resolved.context,
        effective_root=resolved.effective_root,
        pyproject_path=resolved.pyproject_path,
        log_root=resolved.log_root,
        cli_overrides=cli_overrides,
        pyproject_has_config=resolved.pyproject_has_config,
    )


# ====================================== #
#              ENTRY POINT               #
# ====================================== #


@handle_errors
def main() -> int:
    """
    Entry point for CLI execution.

    Orchestrate argument parsing, pyproject.toml generation,
    configuration resolution, file discovery, tool execution, and
    result aggregation.

    Execution proceeds in two phases using a double-build strategy:

    1. **Generation**: build a preliminary ``GlobalConfig`` from CLI
       args and ``UserDefaults`` only (empty pyproject, no context).
       Use it to write or merge pyproject.toml before the resolver
       reads the file.
    2. **Resolution**: read the now-fresh pyproject.toml, build the
       full ``GlobalConfig`` with the complete five-level priority
       chain, discover files, and run tools.

    Returns
    -------
    int
        0 for success, ``ExitCode.SYSTEM`` (2) from ``--doctor`` mode,
        1-8 from a ``SCRError`` during bootstrap, or 0/10/11 from the
        analysis phase via ``_run_analysis_phase``.

    """
    parser = create_argument_parser()
    args = parser.parse_args()

    # Handle --doctor diagnostic mode before any other processing
    if args.doctor:
        return run_doctor()

    # Clear any stale messages from a previous main() call in the same process.
    DeferredLogBuffer.clear()

    # Bootstrap config resolution; capture errors before the logger exists
    try:
        # Run pre-logger phases (CLI parsing, config resolution, root discovery)
        result = _bootstrap_pre_logger(args)
    except SCRError as pre_logger_error:
        # No logger yet; buffer the error and flush to stderr
        traceback_text = traceback.format_exc()
        DeferredLogBuffer.capture(
            "error",
            f"{format_scr_error(pre_logger_error)}\n\n{traceback_text}",
        )
        DeferredLogBuffer.flush_or_stderr()
        return pre_logger_error.exit_code

    return _run_analysis_phase(
        args,
        result.gen_status,
        result.resolver,
        result.global_config,
        result.context,
        result.effective_root,
        result.pyproject_path,
        result.log_root,
        cli_overrides=result.cli_overrides,
        pyproject_has_config=result.pyproject_has_config,
    )


# Last-resort error handler: catches SCRErrors that escape main() when the handle_errors decorator
# re-raises a SCRError or when the decorator itself fails. Produces exit codes 1-8 exclusively
# (SCRError subclass codes).
if __name__ == "__main__":
    # Execute main and translate exceptions to exit codes
    try:
        # Normal exit path; main() returns an integer exit code
        sys.exit(main())
    except KeyboardInterrupt:
        # User pressed Ctrl+C; exit with the conventional signal code
        print("\nInterrupted.", file=sys.stderr)  # noqa: T201
        sys.exit(_KEYBOARD_INTERRUPT_EXIT_CODE)
    except SCRError as unhandled_main_error:
        # SCRError escaped main(); print diagnostics and exit with its code
        print(f"\n  {format_scr_error(unhandled_main_error)}\n", file=sys.stderr)  # noqa: T201
        traceback.print_exc(file=sys.stderr)
        sys.exit(unhandled_main_error.exit_code)
