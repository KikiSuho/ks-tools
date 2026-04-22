"""
CLI argument parser, namespace-to-dict conversion, and doctor mode.

Functions
---------
create_argument_parser : Build the argparse CLI interface.
parse_cli_to_dict : Extract non-None CLI arguments into a configuration dictionary.
cli_dict_to_flags : Convert a cli_dict into human-readable CLI flag strings.
run_doctor : Check availability of all required tools.

Examples
--------
>>> parser = create_argument_parser()
>>> parser.prog
'scrutiny'

"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from scrutiny import __version__ as _VERSION
from scrutiny.core.enums import (
    ConfigTier,
    FrameworkSelection,
    LoggerLevel,
    LogLocation,
    SecurityTool,
)
from scrutiny.core.exceptions import ExitCode, handle_errors
from scrutiny.core.tool_data import TOOL_REGISTRY
from scrutiny.execution.services import which

# Generate-config mode values.  ``--generate-config`` without a value
# implicitly uses ``GENERATE_MODE_NORMAL``; explicit values are ``test`` or
# ``all`` to include test sections (and optionally plugin addopts).
GENERATE_MODE_NORMAL = "normal"
GENERATE_MODE_TEST = "test"
GENERATE_MODE_ALL = "all"
GENERATE_CONFIG_MODES: tuple[str, ...] = (
    GENERATE_MODE_NORMAL,
    GENERATE_MODE_TEST,
    GENERATE_MODE_ALL,
)

# Generate-test-config mode values.  The standalone flag defaults to the
# base test configuration; ``=plugins`` augments it with pytest plugin
# addopts such as pytest-cov and pytest-xdist.
TEST_CONFIG_MODE_NORMAL = "normal"
TEST_CONFIG_MODE_PLUGINS = "plugins"
GENERATE_TEST_CONFIG_MODES: tuple[str, ...] = (
    TEST_CONFIG_MODE_NORMAL,
    TEST_CONFIG_MODE_PLUGINS,
)


@handle_errors
def create_argument_parser() -> argparse.ArgumentParser:
    """
    Build the argparse CLI interface.

    Returns
    -------
    argparse.ArgumentParser
        Configured parser with all supported arguments.

    """
    parser = argparse.ArgumentParser(
        prog="scrutiny",
        description="Unified code quality orchestration for Python projects.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional arguments
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=None,
        help="Files or directories to analyse (default: current directory).",
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--essential",
        action="store_const",
        const=ConfigTier.ESSENTIAL,
        dest="config_tier",
        help="Use ESSENTIAL tier (core correctness only).",
    )
    mode_group.add_argument(
        "--standard",
        action="store_const",
        const=ConfigTier.STANDARD,
        dest="config_tier",
        help="Use STANDARD tier (quality + correctness).",
    )
    mode_group.add_argument(
        "--strict",
        action="store_const",
        const=ConfigTier.STRICT,
        dest="config_tier",
        help="Use STRICT tier (maximum rigor).",
    )
    mode_group.add_argument(
        "--insane",
        action="store_const",
        const=ConfigTier.INSANE,
        dest="config_tier",
        help="Use INSANE tier (maximum strictness across all tools).",
    )

    # Execution
    parser.add_argument(
        "--check-only",
        action="store_true",
        default=None,
        dest="check_only",
        help="Disable auto-fix (check mode only, for CI gates).",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        default=None,
        help="Run tools in parallel using thread pool.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=None,
        dest="no_cache",
        help="Disable tool caches.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        default=None,
        dest="fix",
        help="Enable auto-fix for Ruff (format + lint fixes).",
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        default=False,
        dest="no_parallel",
        help="Disable parallel tool execution.",
    )
    parser.add_argument(
        "--unsafe-fixes",
        action="store_true",
        default=None,
        dest="unsafe_fixes",
        help="Allow Ruff unsafe fixes (may change code semantics).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        metavar="SECONDS",
        default=None,
        dest="tool_timeout",
        help="Override per-tool timeout in seconds.",
    )

    # Tool selection
    parser.add_argument(
        "--tool",
        choices=["ruff", "mypy", "radon", "bandit", "ruff_security"],
        action="append",
        dest="tools",
        help="Run only specified tool(s). May be repeated.",
    )
    parser.add_argument(
        "--no-ruff",
        action="store_true",
        default=False,
        help="Skip Ruff (formatter + linter).",
    )
    parser.add_argument(
        "--no-mypy",
        action="store_true",
        default=False,
        help="Skip Mypy.",
    )
    parser.add_argument(
        "--no-radon",
        action="store_true",
        default=False,
        help="Skip Radon.",
    )
    parser.add_argument(
        "--no-security",
        action="store_true",
        default=False,
        help="Skip security analysis (bandit or ruff_security).",
    )
    parser.add_argument(
        "--security-tool",
        type=str,
        choices=["bandit", "ruff_security"],
        default=None,
        dest="security_tool",
        help="Override IDE/CLI security tool (bandit or ruff_security).",
    )
    parser.add_argument(
        "--pipeline-security-tool",
        type=str,
        choices=["bandit", "ruff_security"],
        default=None,
        dest="pipeline_security_tool",
        help="Override CI/pipeline security tool (bandit or ruff_security).",
    )

    # Path behaviour
    parser.add_argument(
        "--no-current-dir-as-root",
        action="store_true",
        default=False,
        dest="no_current_dir_as_root",
        help="Disable CWD-as-root; use upward pyproject.toml search.",
    )
    parser.add_argument(
        "--max-search-depth",
        type=int,
        metavar="N",
        default=None,
        dest="max_upward_search_depth",
        help="Override maximum upward directory search depth.",
    )
    parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        default=None,
        dest="follow_symlinks",
        help="Follow symbolic links during file discovery.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        default=None,
        dest="clear_cache",
        help=(
            "Delete tool cache directories "
            "(.mypy_cache, .ruff_cache, __pycache__) before execution."
        ),
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        dest="exclude_dirs",
        metavar="DIR",
        help="Add directory to exclusion list (repeatable).",
    )
    parser.add_argument(
        "--exclude-file",
        action="append",
        default=None,
        dest="exclude_files",
        metavar="PATTERN",
        help="Add file pattern to exclusion list (repeatable).",
    )

    # Configuration generation.  ``--generate-config`` and
    # ``--generate-test-config`` are mutually exclusive: one generates the
    # full managed set (scoped by mode), the other generates only the test
    # sections (scoped by an optional ``=plugins`` modifier).
    generate_group = parser.add_mutually_exclusive_group()
    generate_group.add_argument(
        "--generate-config",
        nargs="?",
        const=GENERATE_MODE_NORMAL,
        default=None,
        choices=GENERATE_CONFIG_MODES,
        dest="generate_config",
        metavar="MODE",
        help=(
            "Generate or merge pyproject.toml managed sections. "
            "Without a value: [tool.ruff], [tool.mypy], [tool.bandit]. "
            "=test adds [tool.pytest.ini_options] and [tool.coverage.*]. "
            "=all also adds pytest plugin addopts (pytest-cov, pytest-xdist)."
        ),
    )
    generate_group.add_argument(
        "--generate-test-config",
        nargs="?",
        const=TEST_CONFIG_MODE_NORMAL,
        default=None,
        choices=GENERATE_TEST_CONFIG_MODES,
        dest="generate_test_config",
        metavar="MODE",
        help=(
            "Generate or merge only the test sections "
            "([tool.pytest.ini_options] and [tool.coverage.*]) "
            "without touching [tool.ruff] / [tool.mypy] / [tool.bandit]. "
            "=plugins augments with pytest plugin addopts."
        ),
    )
    parser.add_argument(
        "--override-config",
        action="store_true",
        default=None,
        dest="override_config",
        help="With --generate-config: overwrite existing managed tool sections.",
    )
    parser.add_argument(
        "--config-in-cwd",
        action="store_true",
        default=None,
        dest="generate_config_in_cwd",
        help="With --generate-config: target CWD instead of project root.",
    )
    parser.add_argument(
        "--pyproject-only",
        action="store_true",
        default=None,
        dest="pyproject_only",
        help="Use pyproject.toml as sole config source, bypassing script defaults.",
    )
    parser.add_argument(
        "--line-length",
        type=int,
        metavar="N",
        default=None,
        dest="line_length",
        help="Override line length.",
    )
    parser.add_argument(
        "--python-version",
        type=str,
        metavar="VER",
        default=None,
        dest="python_version",
        help="Override Python version target (e.g. py39).",
    )
    parser.add_argument(
        "--framework",
        type=str,
        choices=["none", "django", "fastapi", "airflow", "numpy", "pandas"],
        default=None,
        dest="framework",
        help="Enable framework-specific ruff rules.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        default=False,
        dest="show_config",
        help="Display effective configuration and exit.",
    )

    # Output
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "-q",
        "--quiet",
        action="store_const",
        const=LoggerLevel.QUIET,
        dest="console_logger_level",
        help="Minimal terminal output.",
    )
    log_group.add_argument(
        "--detailed",
        action="store_const",
        const=LoggerLevel.DETAILED,
        dest="console_logger_level",
        help="Issues with metadata, URLs, and source context.",
    )
    log_group.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        const=LoggerLevel.VERBOSE,
        dest="console_logger_level",
        help="Detailed + Ruff fixed items and subprocess debug.",
    )

    # File logging
    parser.add_argument(
        "--no-log",
        action="store_true",
        default=False,
        dest="no_log",
        help="Disable log file creation.",
    )
    parser.add_argument(
        "--log-location",
        type=str,
        choices=["project_root", "current_dir", "hybrid"],
        default=None,
        dest="log_location",
        help="Where to place log files (project_root, current_dir, hybrid).",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        metavar="DIR",
        default=None,
        dest="log_dir",
        help="Override log file directory.",
    )
    parser.add_argument(
        "--file-log-level",
        type=str,
        choices=["quiet", "normal", "detailed", "verbose"],
        default=None,
        dest="file_logger_level",
        help="Set file log verbosity (quiet, normal, detailed, verbose).",
    )

    # Utilities
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_VERSION}",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        default=False,
        help="Check tool availability and versions.",
    )

    return parser


# Internal config keys → CLI flag names.  Keys produced by
# parse_cli_to_dict that do not appear here are displayed as
# ``--{key.replace('_', '-')}``.
_CLI_KEY_TO_FLAG: dict[str, str] = {
    "config_tier": "--tier",
    "tool_timeout": "--timeout",
    "max_upward_search_depth": "--max-search-depth",
    "console_logger_level": "--verbose",
    "file_logger_level": "--file-log-level",
    "tools": "--tool",
    "exclude_dirs": "--exclude-dir",
    "exclude_files": "--exclude-file",
    "generate_config_in_cwd": "--config-in-cwd",
    "run_ruff_formatter": "--no-ruff",
    "run_ruff_linter": "--no-ruff",
    "run_mypy": "--no-mypy",
    "run_radon": "--no-radon",
    "run_security": "--no-security",
    "create_log": "--no-log",
}


def cli_dict_to_flags(cli_dict: dict[str, Any]) -> tuple[str, ...]:
    """
    Convert a cli_dict into human-readable CLI flag strings.

    Excludes ``paths`` (redundant with Root/Files display) and
    diagnostic-only keys (``doctor``, ``show_config``).

    Parameters
    ----------
    cli_dict : dict[str, Any]
        Non-None CLI overrides from ``parse_cli_to_dict``.

    Returns
    -------
    tuple[str, ...]
        Ordered flag strings (e.g. ``("--strict", "--fix")``).

    """
    skip_keys = {"paths", "doctor", "show_config"}
    flags: list[str] = []
    seen: set[str] = set()

    # Convert each CLI override key into its display flag string
    for key, value in cli_dict.items():
        # Skip keys that are displayed elsewhere or are diagnostic-only
        if key in skip_keys:
            continue

        # Resolve the display flag, applying special-case overrides.
        if key == "config_tier" and hasattr(value, "value"):
            # Tier uses the enum value directly as the flag name
            flag = f"--{value.value}"
        elif key == "console_logger_level":
            # Map logger level enum to its short/long flag form
            level_to_flag: dict[object, str] = {
                LoggerLevel.QUIET: "-q",
                LoggerLevel.DETAILED: "--detailed",
                LoggerLevel.VERBOSE: "-v",
            }
            flag = level_to_flag.get(value, "--verbose")
        else:
            # Default: look up in the mapping or derive from the key name
            flag = _CLI_KEY_TO_FLAG.get(key, f"--{key.replace('_', '-')}")

        # Deduplicate: e.g. --no-ruff maps two keys to the same flag.
        if flag in seen:
            continue
        seen.add(flag)
        flags.append(flag)

    return tuple(flags)


@handle_errors
def run_doctor() -> int:
    """
    Check availability of all required tools.

    Returns
    -------
    int
        0 if all tools are available, ``ExitCode.SYSTEM`` (2) if any
        required tool is not found in PATH.

    """
    # Deduplicate executables from the registry (multiple logical names
    # may share the same executable, e.g. ruff_formatter / ruff_linter).
    seen: set[str] = set()
    executables: list[tuple[str, str]] = []
    # Collect unique executables from the registry
    for executable, install_pkg in TOOL_REGISTRY.values():
        # Skip duplicate executables shared by multiple logical tool names
        if executable not in seen:
            seen.add(executable)
            executables.append((executable, install_pkg))
    is_all_ok = True
    missing_tools: list[tuple[str, str]] = []

    # Check each tool's availability and print its version.
    for executable, install_pkg in executables:
        tool_path = which(executable)
        # Report availability and version for each executable
        if tool_path is not None:
            # Tool found; attempt to retrieve its version string
            try:
                version_check = subprocess.run(  # nosec B603 -- tool_path from which() is a validated filesystem path, not user input
                    [tool_path, "--version"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                version = version_check.stdout.strip() or version_check.stderr.strip()
                print(f"  {executable}: {version}")  # noqa: T201
            except (OSError, subprocess.SubprocessError):
                # Version check failed; report path without version
                print(f"  {executable}: found at {tool_path} (version unknown)")  # noqa: T201
        else:
            # Tool not found on PATH
            print(f"  {executable}: NOT FOUND")  # noqa: T201
            missing_tools.append((executable, install_pkg))
            is_all_ok = False

    # Print install guidance when any tools are missing
    if missing_tools:
        install_list = " ".join(pkg for _, pkg in missing_tools)
        print(  # noqa: T201
            f"\n  Install missing tools: pip install {install_list} | conda install {install_list}",
        )

    return 0 if is_all_ok else ExitCode.SYSTEM


def _extract_valued_args(args: argparse.Namespace, cli_dict: dict[str, Any]) -> None:
    """
    Copy non-None valued arguments from *args* into *cli_dict*.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    cli_dict : dict[str, Any]
        Accumulator for configuration overrides.

    """
    valued_args = (
        "config_tier",
        "line_length",
        "python_version",
        "tool_timeout",
        "max_upward_search_depth",
        "log_dir",
    )
    # Copy each non-None argument value into the config dict.
    for attr in valued_args:
        value = getattr(args, attr, None)
        # Only include arguments the user explicitly provided
        if value is not None:
            cli_dict[attr] = value


def _extract_enum_args(args: argparse.Namespace, cli_dict: dict[str, Any]) -> None:
    """
    Convert raw enum-valued arguments to their enum types.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    cli_dict : dict[str, Any]
        Accumulator for configuration overrides.

    """
    # Convert string-valued CLI args to their enum types when present.
    security_tool_raw = getattr(args, "security_tool", None)
    if security_tool_raw is not None:
        cli_dict["security_tool"] = SecurityTool(security_tool_raw)

    pipeline_security_tool_raw = getattr(args, "pipeline_security_tool", None)
    if pipeline_security_tool_raw is not None:
        cli_dict["pipeline_security_tool"] = SecurityTool(pipeline_security_tool_raw)

    log_location_raw = getattr(args, "log_location", None)
    if log_location_raw is not None:
        cli_dict["log_location"] = LogLocation(log_location_raw)

    framework_raw = getattr(args, "framework", None)
    if framework_raw is not None:
        cli_dict["framework"] = FrameworkSelection(framework_raw)

    # Map file log level string to LoggerLevel enum.
    file_log_level_raw = getattr(args, "file_logger_level", None)
    if file_log_level_raw is not None:
        logger_level_map: dict[str, LoggerLevel] = {
            "quiet": LoggerLevel.QUIET,
            "normal": LoggerLevel.NORMAL,
            "detailed": LoggerLevel.DETAILED,
            "verbose": LoggerLevel.VERBOSE,
        }
        cli_dict["file_logger_level"] = logger_level_map[file_log_level_raw]


def _extract_toggle_overrides(args: argparse.Namespace, cli_dict: dict[str, Any]) -> None:
    """
    Process ``--no-*`` flags, negation flags, and append-style flags.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    cli_dict : dict[str, Any]
        Accumulator for configuration overrides.

    """
    # Tool toggle overrides from --no-* flags.
    tool_disable_map: dict[str, tuple[str, ...]] = {
        "no_ruff": ("run_ruff_formatter", "run_ruff_linter"),
        "no_mypy": ("run_mypy",),
        "no_radon": ("run_radon",),
        "no_security": ("run_security",),
    }
    # Disable tool toggles when the corresponding --no-* flag is set
    for flag_attr, config_keys in tool_disable_map.items():
        # Check whether the user passed the --no-* flag
        if getattr(args, flag_attr, False):
            # Disable each config key mapped to this flag
            for config_key in config_keys:
                cli_dict[config_key] = False

    # Negation flags: map --no-X to config_key=False.
    negation_map: dict[str, str] = {
        "no_parallel": "parallel",
        "no_current_dir_as_root": "current_dir_as_root",
        "no_log": "create_log",
    }
    # Apply negation flags that set a config key to False
    for flag_attr, config_key in negation_map.items():
        # Set the target config key to False when the negation flag is active
        if getattr(args, flag_attr, False):
            cli_dict[config_key] = False

    # Append-style flags: convert lists to tuples.
    exclude_dirs_raw = getattr(args, "exclude_dirs", None)
    # Convert mutable lists to immutable tuples for config storage
    if exclude_dirs_raw:
        cli_dict["exclude_dirs"] = tuple(exclude_dirs_raw)

    exclude_files_raw = getattr(args, "exclude_files", None)
    # Same conversion for file exclusion patterns
    if exclude_files_raw:
        cli_dict["exclude_files"] = tuple(exclude_files_raw)


def _extract_generate_config_args(
    args: argparse.Namespace,
    cli_dict: dict[str, Any],
) -> None:
    """
    Translate generate-config mode flags into internal configuration keys.

    Handles the two mutually exclusive flags:

    * ``--generate-config[=test|all]`` toggles ``generate_config`` and, when
      a scope is requested, ``include_test_config`` and
      ``include_test_plugins``.  The normal managed sections
      (``[tool.ruff]`` / ``[tool.mypy]`` / ``[tool.bandit]``) are always
      written when this flag is used.
    * ``--generate-test-config[=plugins]`` toggles ``generate_config`` with
      ``test_config_only`` so only the test sections are emitted; the
      optional ``=plugins`` mode adds pytest plugin addopts.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.
    cli_dict : dict[str, Any]
        Accumulator for configuration overrides.

    """
    generate_mode = getattr(args, "generate_config", None)
    test_config_mode = getattr(args, "generate_test_config", None)

    # Honor --generate-config[=<mode>] when present.
    if generate_mode is not None:
        cli_dict["generate_config"] = True
        # Scope inclusion by the selected mode; ``normal`` generates only
        # the managed tool sections and leaves test config alone.
        if generate_mode == GENERATE_MODE_TEST:
            # Include pytest + coverage sections but skip plugin addopts.
            cli_dict["include_test_config"] = True
        elif generate_mode == GENERATE_MODE_ALL:
            # Include pytest + coverage sections with plugin addopts too.
            cli_dict["include_test_config"] = True
            cli_dict["include_test_plugins"] = True
        return

    # Honor --generate-test-config[=plugins] when present.  The mutex group
    # at the parser level guarantees the two flags cannot coexist.
    if test_config_mode is not None:
        cli_dict["generate_config"] = True
        cli_dict["include_test_config"] = True
        cli_dict["test_config_only"] = True
        # Augment with plugin addopts only when explicitly requested.
        if test_config_mode == TEST_CONFIG_MODE_PLUGINS:
            cli_dict["include_test_plugins"] = True


def parse_cli_to_dict(args: argparse.Namespace) -> dict[str, Any]:
    """
    Extract non-None CLI arguments into a configuration dictionary.

    Delegates to focused helpers for valued args, boolean flags, enum
    conversions, and toggle overrides.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed CLI arguments.

    Returns
    -------
    dict[str, Any]
        Configuration overrides from the command line.

    """
    cli_dict: dict[str, Any] = {}

    # Phase 1: valued args (tier, lengths, timeouts, etc.).
    _extract_valued_args(args, cli_dict)

    # Phase 2: boolean flags -- include when truthy.
    bool_flags = (
        "check_only",
        "parallel",
        "no_cache",
        "clear_cache",
        "override_config",
        "generate_config_in_cwd",
        "pyproject_only",
        "fix",
        "unsafe_fixes",
        "follow_symlinks",
    )
    # Include boolean flags that the user explicitly set to True
    for attr in bool_flags:
        # Only record flags the user actively passed on the command line
        if getattr(args, attr, False):
            cli_dict[attr] = True

    # Phase 3: generate-config scoping from the two mode-valued flags.
    _extract_generate_config_args(args, cli_dict)

    # Phase 4: console logger level (directly from argparse const).
    if args.console_logger_level is not None:
        cli_dict["console_logger_level"] = args.console_logger_level

    # Phase 5: enum conversions and --no-* toggle overrides.
    _extract_enum_args(args, cli_dict)
    _extract_toggle_overrides(args, cli_dict)

    return cli_dict
