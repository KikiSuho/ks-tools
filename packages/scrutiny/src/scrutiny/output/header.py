"""
Pre-execution banner, header formatting, and discovered-files listing.

Build and emit the header banner displayed before tool execution.
Content scales with the configured logger level: normal mode shows
a compact single-column layout, verbose mode renders a two-column
grid with full configuration details.

Functions
---------
print_header : Emit the run header with tiered detail.

Examples
--------
>>> callable(print_header)
True

"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.configs.resolver import ContextDetection
from scrutiny.core.enums import LoggerLevel
from scrutiny.output import relative_display_path
from scrutiny.output.logger import SCRLogger

_BANNER_WIDTH = 70
_RIGHT_COLUMN_INDENT = 35
_COLUMN_PADDING = 4


def _mode_label(global_config: GlobalConfig, pyproject_has_config: bool) -> str:
    """
    Return a human-readable label for the configuration mode.

    Parameters
    ----------
    global_config : GlobalConfig
        Resolved configuration.
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    Returns
    -------
    str
        ``"pyproject"`` when pyproject.toml is authoritative,
        ``"standard"`` when pyproject.toml + defaults both contribute,
        or ``"defaults"`` when no pyproject.toml tool config is active.

    """
    # No pyproject.toml tool sections found; using built-in defaults only
    if not pyproject_has_config:
        return "defaults"
    # Pyproject-only mode bypasses script defaults entirely
    if global_config.pyproject_only:
        return "pyproject"
    return "standard"


def _format_header_verbose(
    logger: SCRLogger,
    global_config: GlobalConfig,
    context: ContextDetection,
    file_count: int,
    column_width: int,
    pyproject_has_config: bool = False,
) -> None:
    """
    Emit verbose two-column header layout.

    Every setting is always shown.  Row order reflects importance:
    quality profile, code-style constraints, modification behaviour,
    execution behaviour, environment, and mode/framework.

    Parameters
    ----------
    logger : SCRLogger
        Logger instance for header output.
    global_config : GlobalConfig
        Resolved configuration.
    context : ContextDetection
        Detected execution context.
    file_count : int
        Number of discovered Python files.
    column_width : int
        Left-column width for two-column alignment.
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    """
    # Build human-readable labels.
    fix_label = "enabled" if global_config.effective_fix else "disabled"
    unsafe_label = "on" if global_config.unsafe_fixes else "off"
    parallel_label = "enabled" if global_config.parallel else "disabled"
    security_label = "enabled" if global_config.run_security else "disabled"

    cache_parts: list[str] = []
    # Describe the cache state for the header display
    if global_config.no_cache:
        # Caching is fully disabled
        cache_parts.append("disabled")
    else:
        # Default path; caching remains active
        cache_parts.append("enabled")
    # Append clear-before-run when the user requested cache eviction
    if global_config.clear_cache:
        cache_parts.append("clear before run")
    cache_label = ", ".join(cache_parts)

    mode = _mode_label(global_config, pyproject_has_config)
    framework = global_config.framework.value

    # Two-column grid, ordered by importance.
    tier_col = f"  Tier:      {global_config.config_tier.value}"
    python_col = f"  Python:    {global_config.python_version.value}"
    fix_col = f"  Fix:       {fix_label} (unsafe: {unsafe_label})"
    security_col = f"  Security:  {security_label}"
    context_col = f"  Context:   {context.value}"
    mode_col = f"  Mode:      {mode}"

    logger.header(f"{tier_col:<{column_width}}Files:     {file_count}")
    logger.header(f"{python_col:<{column_width}}Lines:     {global_config.line_length.value}")
    logger.header(f"{fix_col:<{column_width}}Cache:     {cache_label}")
    logger.header(f"{security_col:<{column_width}}Parallel:  {parallel_label}")
    logger.header(f"{context_col:<{column_width}}Timeout:   {int(global_config.tool_timeout)}s")
    logger.header(f"{mode_col:<{column_width}}Framework: {framework}")


def _format_header_normal(
    logger: SCRLogger,
    global_config: GlobalConfig,
    context: ContextDetection,
    pyproject_has_config: bool = False,
) -> None:
    """
    Emit normal/detailed header layout.

    All settings are always shown.

    Parameters
    ----------
    logger : SCRLogger
        Logger instance for header output.
    global_config : GlobalConfig
        Resolved configuration.
    context : ContextDetection
        Detected execution context.
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    """
    logger.header(f"  Tier:      {global_config.config_tier.value}")
    security_label = "enabled" if global_config.run_security else "disabled"
    logger.header(f"  Security:  {security_label}")
    logger.header(f"  Context:   {context.value}")
    logger.header(f"  Mode:      {_mode_label(global_config, pyproject_has_config)}")
    logger.header(f"  Framework: {global_config.framework.value}")


def _log_discovered_files(
    logger: SCRLogger,
    discovered_files: list[Path],
    effective_root: Path,
    mi_ranks: Optional[dict[str, str]],
) -> None:
    """
    Render the discovered-files listing in a two-column layout.

    Each file path is shown relative to *effective_root*.  When *mi_ranks*
    is provided, files that appear in the mapping are annotated with the
    Maintainability Index rank letter in brackets (e.g. ``script.py [C]``).

    Parameters
    ----------
    logger : SCRLogger
        Logger instance for header-level output.
    discovered_files : list[Path]
        Absolute paths of discovered Python files.
    effective_root : Path
        Project root used to compute relative display paths.
    mi_ranks : Optional[dict[str, str]]
        Mapping of root-relative file paths to MI rank letters.

    """
    relative_paths = sorted(
        relative_display_path(str(discovered_file), effective_root)
        for discovered_file in discovered_files
    )

    # Build display labels: append MI rank when available.
    display_labels: list[str] = []
    for relative_path in relative_paths:
        # Annotate files with their Maintainability Index rank when available
        if mi_ranks and relative_path in mi_ranks:
            # Append rank letter in brackets (e.g. "script.py [C]")
            display_labels.append(f"{relative_path} [{mi_ranks[relative_path]}]")
        else:
            # Show the path without annotation
            display_labels.append(relative_path)

    logger.header(f"Discovered {len(relative_paths)} Python file(s)")
    column_width = max(len(label) for label in display_labels) + _COLUMN_PADDING
    midpoint = (len(display_labels) + 1) // 2
    # Render files in a two-column layout
    for row_index in range(midpoint):
        left_label = display_labels[row_index]
        right_index = row_index + midpoint
        right_label = display_labels[right_index] if right_index < len(display_labels) else ""
        logger.header(f"  {left_label:<{column_width}}{right_label}")


def _format_cli_overrides(
    logger: SCRLogger,
    cli_overrides: tuple[str, ...],
    banner_width: int,
) -> None:
    """
    Render CLI override flags, wrapping within the banner width.

    Parameters
    ----------
    logger : SCRLogger
        Logger instance for header output.
    cli_overrides : tuple[str, ...]
        Human-readable CLI flags passed by the user.
    banner_width : int
        Maximum line width (matches the ``=`` banner).

    """
    prefix = "  CLI:       "
    continuation = " " * len(prefix)
    max_content = banner_width - len(prefix)

    line = prefix
    is_first = True
    # Wrap CLI flags across lines when they exceed the banner width
    for flag in cli_overrides:
        needed = len(flag) if is_first else len(flag) + 1
        # Start a new line when the current flag would exceed the banner width
        if not is_first and (len(line) - len(continuation)) + needed > max_content:
            logger.header(line)
            line = continuation + flag
        else:
            line += ("" if is_first else " ") + flag
        is_first = False

    # Flush any remaining content on the last line
    if line.strip():
        logger.header(line)


def print_header(
    logger: SCRLogger,
    global_config: GlobalConfig,
    context: ContextDetection,
    effective_root: Path,
    tool_names: list[str],
    file_count: int,
    discovered_files: Optional[list[Path]] = None,
    log_discovered_files: bool = False,
    mi_ranks: Optional[dict[str, str]] = None,
    gen_status: Optional[str] = None,
    cli_overrides: tuple[str, ...] = (),
    pyproject_has_config: bool = False,
) -> None:
    """
    Emit the run header with tiered detail.

    Content scales with logger level:

    * **NORMAL / DETAILED** — root, tools, tier, security, context,
      mode, framework (single-column).
    * **VERBOSE** — root and tools full-width at top, then two-column
      grid ordered by importance: quality profile, code-style
      constraints, modification behaviour, execution behaviour,
      environment, and mode/framework.

    All settings are always shown regardless of their values.
    When the user passed explicit CLI flags, a ``CLI:`` line appears
    at the bottom of the settings block (before the closing banner).

    Parameters
    ----------
    logger : SCRLogger
        Logger instance (controls per-destination gating).
    global_config : GlobalConfig
        Resolved configuration.
    context : ContextDetection
        Detected execution context.
    effective_root : Path
        Effective project root.
    tool_names : list[str]
        Names of tools that will run.
    file_count : int
        Number of discovered Python files.
    discovered_files : Optional[list[Path]]
        Discovered file paths (shown when *log_discovered_files* is True).
    log_discovered_files : bool
        Whether to list discovered files after the header banner.
    mi_ranks : Optional[dict[str, str]]
        Mapping of root-relative file paths to Maintainability Index rank
        letters (e.g. ``{"scrutiny.py": "C"}``).  When provided, each
        file in the discovery listing is annotated with ``[rank]``.
    gen_status : Optional[str]
        pyproject.toml generation result (e.g. ``"unchanged"``,
        ``"updated"``).  Shown in the header when not None.
    cli_overrides : tuple[str, ...]
        Human-readable CLI flags the user passed. When non-empty, a
        ``CLI:`` line is rendered at the bottom of the settings block.
    pyproject_has_config : bool
        Whether pyproject.toml contributed tool configuration.

    """
    is_verbose = logger.console_level >= LoggerLevel.VERBOSE

    # Top banner with root and tool list (always shown).
    logger.header("=" * _BANNER_WIDTH)
    logger.header("Code Quality Analysis")
    logger.header(f"  Project:   {effective_root.name}")
    logger.header(f"  Tools:     {', '.join(tool_names)}")

    # Delegate detail layout based on verbosity tier.
    if is_verbose:
        # Two-column grid with full configuration details
        _format_header_verbose(
            logger,
            global_config,
            context,
            file_count,
            _RIGHT_COLUMN_INDENT,
            pyproject_has_config=pyproject_has_config,
        )
    else:
        # Compact single-column layout
        _format_header_normal(
            logger, global_config, context, pyproject_has_config=pyproject_has_config
        )

    # Show pyproject.toml generation result when config was generated
    if gen_status is not None:
        logger.header(f"  Config:    pyproject.toml {gen_status}")

    # CLI overrides (only when user passed explicit flags).
    if cli_overrides:
        _format_cli_overrides(logger, cli_overrides, _BANNER_WIDTH)

    logger.header("=" * _BANNER_WIDTH)

    # Discovered files listing (two-column, root-relative paths with
    # optional Maintainability Index rank in brackets).
    if log_discovered_files and discovered_files:
        _log_discovered_files(logger, discovered_files, effective_root, mi_ranks)
