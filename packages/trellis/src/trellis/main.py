"""
Project structure generator and change tracker.

Scan a directory tree and produce a text representation including Python
classes and functions discovered via AST analysis. Supports configurable
exclusion, package/command detection, and structure change tracking across
versions. Configuration, CLI parsing, filtering, and change detection are
delegated to subpackage modules. Persistence is delegated to
``core.persistence``. This module retains directory scanning, AST rendering
delegation, and the CLI entry point.

Constants
---------
EXIT_SUCCESS : Exit code for successful execution.
EXIT_FAILURE : Exit code for failed execution.
ROOT_NOT_FOUND_WARNING : Warning message template when no project root is found.
ROOT_NOT_FOUND_WARNING_CATEGORY : Warning category for missing project root.

Classes
-------
DirectoryStructure : Scan directories and render a tree with code insights.

Functions
---------
main : Run the scanner from the command line with visibility options.

Examples
--------
>>> import os
>>> from trellis.main import DirectoryStructure
>>> scanner = DirectoryStructure(os.getcwd())
>>> scanner.project_name == os.path.basename(os.getcwd())
True

"""

from __future__ import annotations

import contextlib
import os
import warnings
from pathlib import Path
from typing import Optional

from trellis.config import (
    CallFlowMode,
    Config,
    FilterSettings,
    _or_default,
    build_filter_settings,
    build_tr_meta,
    parse_visibility_args,
)
from trellis.core.filters import (
    is_special_case_item,
    should_ignore_directory,
    should_ignore_file,
    should_skip_system_file,
)
from trellis.core.persistence import PersistenceContext, SaveResult, WriteStatus
from trellis.core.persistence import save_structure as _persist_save
from trellis.core.project_root import find_project_root
from trellis.pyast.renderer import AstRenderer, RenderSettings, build_render_settings
from trellis.pyast.tree_drawing import get_tree_connectors

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
ROOT_NOT_FOUND_WARNING = "No project root found from {start_path}; using CWD."
ROOT_NOT_FOUND_WARNING_CATEGORY: type[Warning] = UserWarning

__all__ = [
    "DirectoryStructure",
    "main",
]


# ====================================== #
#         DIRECTORY STRUCTURE            #
# ====================================== #


class DirectoryStructure:
    """
    Generate a text representation of a directory structure.

    This class scans directories and Python files to create a hierarchical
    text representation that includes Python classes and functions. It
    provides methods to traverse the directory tree, extract Python code
    structure, and save the results to a text file with change tracking.

    Parameters
    ----------
    root_dir : str
        Path to the root directory to scan.
    show_private : Optional[bool], optional
        Whether to include private methods (starting with '_') in the output.
        Default is determined by Config.SHOW_PRIVATE when None.
    show_mangled : Optional[bool], optional
        Whether to include name-mangled methods (starting with '__' but not
        ending with '__') in the output.
        Default is determined by Config.SHOW_MANGLED when None.
    show_dunder : Optional[bool], optional
        Whether to include special/dunder methods (like '__init__') in the output.
        Default is determined by Config.SHOW_DUNDER when None.
    show_types : Optional[bool], optional
        Whether to include type annotations on function parameters.
        Default is determined by Config.SHOW_TYPES when None.
    show_decorators : Optional[bool], optional
        Whether to show decorators on functions and classes.
        Default is determined by Config.SHOW_DECORATORS when None.
    call_flow_mode : Optional[CallFlowMode], optional
        Call flow display mode for orchestration functions.
        Default is determined by Config.CALL_FLOW_MODE when None.

    Attributes
    ----------
    root_dir : str
        Path to the root directory being scanned.
    project_name : str
        Name of the project (derived from the root directory name).
    show_private : bool
        Whether to include private methods (starting with '_') in the output.
    show_mangled : bool
        Whether to include name-mangled methods (starting with '__' but not
        ending with '__') in the output.
    show_dunder : bool
        Whether to include special/dunder methods (like '__init__') in the output.
    scan_method_used : str
        The scanning method used ('os.scandir()' or 'unknown' on error).

    """

    def __init__(  # noqa: D107
        self,
        root_dir: str,
        show_private: Optional[bool] = None,
        show_mangled: Optional[bool] = None,
        show_dunder: Optional[bool] = None,
        show_types: Optional[bool] = None,
        show_decorators: Optional[bool] = None,
        call_flow_mode: Optional[CallFlowMode] = None,
    ) -> None:
        # Resolve None defaults to current Config values
        show_private = _or_default(show_private, Config.SHOW_PRIVATE)
        show_mangled = _or_default(show_mangled, Config.SHOW_MANGLED)
        show_dunder = _or_default(show_dunder, Config.SHOW_DUNDER)
        show_types = _or_default(show_types, Config.SHOW_TYPES)
        show_decorators = _or_default(show_decorators, Config.SHOW_DECORATORS)
        call_flow_mode = _or_default(call_flow_mode, Config.CALL_FLOW_MODE)

        # Initialize directory identity and visibility flags
        self.root_dir: str = root_dir
        self.project_name: str = Path(root_dir).name
        self._structure_lines: list[str] = []
        self.show_private: bool = show_private
        self.show_mangled: bool = show_mangled
        self.show_dunder: bool = show_dunder
        self.scan_method_used: str = "unknown"

        # Initialize scan-state tracking collections
        self._visited_realpaths: set[str] = set()
        self._scanned_paths: set[str] = set()
        self._path_hierarchy: dict[str, list[str]] = {}
        self._path_stack: list[str] = []

        # Build rendering, filtering, and metadata settings
        self._render_settings: RenderSettings = build_render_settings(
            show_types=show_types,
            show_decorators=show_decorators,
            call_flow_mode=call_flow_mode,
        )
        self._filter_settings: FilterSettings = build_filter_settings()
        self._tr_meta: str = build_tr_meta(
            show_types=show_types,
            show_decorators=show_decorators,
            call_flow_mode=call_flow_mode,
            show_private=show_private,
            show_mangled=show_mangled,
            show_dunder=show_dunder,
        )

        # Create AST renderer for Python file analysis
        self._renderer: AstRenderer = AstRenderer(
            self._structure_lines,
            show_private,
            show_mangled,
            show_dunder,
            self._render_settings,
        )

    @property
    def structure(self) -> str:
        """Return the accumulated structure as a single string."""
        return "".join(self._structure_lines)

    def append_line(self, line: str) -> None:
        """
        Append a line to the structure output.

        Parameters
        ----------
        line : str
            Line to append (should include trailing newline).

        """
        self._structure_lines.append(line)

    @staticmethod
    def _detect_directory_markers(
        directories: list[str], current_dir: str
    ) -> tuple[set[str], set[str], set[str]]:
        """
        Detect package, command, and typed markers in subdirectories.

        Uses a single ``os.scandir`` per subdirectory instead of 3 separate
        ``Path.exists()`` calls, reducing syscalls from 3N to N.

        Parameters
        ----------
        directories : list[str]
            Directory names to check.
        current_dir : str
            Parent directory path.

        Returns
        -------
        tuple[set[str], set[str], set[str]]
            Sets of (package_dirs, command_dirs, typed_dirs).

        """
        # Initialize marker result sets and the file names to look for
        package_dirs: set[str] = set()
        command_dirs: set[str] = set()
        typed_dirs: set[str] = set()
        _marker_names = frozenset({"__init__.py", "__main__.py", "py.typed"})

        # Scan each subdirectory for marker files
        for item in directories:
            subdir = str(Path(current_dir) / item)

            # Collect marker file names present in this subdirectory
            try:
                with os.scandir(subdir) as entries:
                    child_names = {entry.name for entry in entries if entry.name in _marker_names}
            except OSError:
                # Treat inaccessible directories as having no markers
                child_names = set()

            # Classify the directory based on which markers were found
            if "__init__.py" in child_names:
                package_dirs.add(item)
            if "__main__.py" in child_names:
                command_dirs.add(item)
            if "py.typed" in child_names:
                typed_dirs.add(item)

        return package_dirs, command_dirs, typed_dirs

    def scan_directory(self, current_dir: str, prefix: str = "") -> None:
        """
        Scan a directory tree and extract Python class/function names.

        Clears all accumulated state before scanning so the instance can be
        reused. Delegates recursive traversal to ``_scan_recursive``.

        Parameters
        ----------
        current_dir : str
            The directory path to scan.
        prefix : str, optional
            The prefix to use for the tree visualization.
            Default is "".

        """
        # Clear accumulated state so the instance can be reused for multiple scans
        # without stale symlink-loop markers or leftover path data from the previous scan.
        self._visited_realpaths.clear()
        self._scanned_paths.clear()
        self._path_hierarchy.clear()
        self._path_stack.clear()
        # .clear() preserves the list identity shared with AstRenderer via OutputSink;
        # do NOT replace with `self._structure_lines = []` as that would detach the renderer.
        self._structure_lines.clear()
        self._scan_recursive(current_dir, prefix)

    def _scan_recursive(self, current_dir: str, prefix: str) -> None:
        """
        Recursively scan a directory and build the structure tree.

        Parameters
        ----------
        current_dir : str
            The directory path to scan.
        prefix : str
            The prefix to use for the tree visualization.

        """
        # Scan the directory and process each item in tree order
        try:
            # Get filtered directory items with cached is_dir booleans.
            filtered_items = self._filter_directory_items(current_dir)

            # Separate into directories and files.
            directories, files = self._separate_dirs_and_files(filtered_items)
            dir_set = set(directories)

            # Detect package, command, and typed markers in subdirectories
            package_dirs, command_dirs, typed_dirs = self._detect_directory_markers(
                directories, current_dir
            )

            # Process all items with directories first, then files.
            all_sorted_items = directories + files

            # Process each item in the combined directory-then-file order
            for index, item in enumerate(all_sorted_items):
                # Determine position and tree connectors for this item
                item_path = Path(current_dir) / item
                is_last_item = index == len(all_sorted_items) - 1
                connector, next_prefix = get_tree_connectors(prefix, is_last_item)

                # Dispatch item to the appropriate handler based on type
                try:
                    # Skip symlinks without recursing into the linked tree
                    if item_path.is_symlink():
                        # Resolve symlink target without recursing into the linked tree
                        self._process_symlink(item, str(item_path), connector, prefix)
                        continue

                    # Route to directory or file handler based on item type
                    if item in dir_set:
                        # Recurse into subdirectory with package/command/typed classification
                        self._process_directory(
                            item,
                            str(item_path),
                            connector,
                            prefix,
                            next_prefix,
                            is_package=item in package_dirs,
                            is_command=item in command_dirs,
                            is_typed=item in typed_dirs,
                        )
                    else:
                        # Read source and render AST structure for regular files
                        self._process_file(item, str(item_path), connector, prefix, next_prefix)
                except (PermissionError, OSError) as item_access_error:
                    # Record the error inline and continue with the next item
                    self._structure_lines.append(
                        f"{prefix}{connector}{item} [Error: {type(item_access_error).__name__}]\n"
                    )
        except (PermissionError, OSError) as scan_error:
            # Record top-level scan failure as the final tree entry
            self._structure_lines.append(
                f"{prefix}└── [Error scanning directory:"
                f" {type(scan_error).__name__}: {scan_error}]\n"
            )

    def _filter_directory_items(self, directory_path: str) -> list[tuple[str, bool]]:
        """
        Filter directory items, removing ignored directories and files.

        Parameters
        ----------
        directory_path : str
            Path to the directory to filter.

        Returns
        -------
        list[tuple[str, bool]]
            Filtered list of (name, is_directory) tuples that should be processed.

        """
        # Retrieve raw directory listing and filter settings
        directory_items_with_type = self._safe_list_directory(directory_path)
        settings = self._filter_settings
        filtered_items: list[tuple[str, bool]] = []

        # Apply exclusion rules to each item
        for item, is_directory in directory_items_with_type:
            # Skip OS-generated system files that should never appear in structure
            if should_skip_system_file(item):
                continue

            item_path = str(Path(directory_path) / item)

            # Keep special-case items regardless of other exclusion rules
            if is_special_case_item(item, is_directory, settings):
                filtered_items.append((item, is_directory))
                continue

            # Exclude ignored directories based on filter settings
            if is_directory and should_ignore_directory(item_path, settings):
                continue

            # Exclude ignored files based on filter settings
            if not is_directory and should_ignore_file(item_path, settings):
                continue

            filtered_items.append((item, is_directory))

        return filtered_items

    def _safe_list_directory(self, path: str) -> list[tuple[str, bool]]:
        """
        List directory contents using ``os.scandir``.

        On ``OSError``, returns an empty list. No fallback listing
        method is attempted.

        Parameters
        ----------
        path : str
            Path to the directory to scan.

        Returns
        -------
        list[tuple[str, bool]]
            Sorted list of (name, is_directory) tuples.

        """
        # Attempt to list directory entries sorted by name
        try:
            with os.scandir(path) as entries:
                # Record the scan method on first successful call
                if self.scan_method_used == "unknown":
                    self.scan_method_used = "os.scandir()"
                return [
                    (dir_entry.name, dir_entry.is_dir())
                    for dir_entry in sorted(entries, key=lambda dir_entry: dir_entry.name)
                ]
        except OSError as scan_error:
            # Warn and return empty list when directory cannot be accessed
            self.append_line(f"[Warning: cannot read directory: {type(scan_error).__name__}]\n")
            return []

    @staticmethod
    def _separate_dirs_and_files(
        items: list[tuple[str, bool]],
    ) -> tuple[list[str], list[str]]:
        """
        Separate directory items into directories and files.

        Items are assumed to be pre-sorted by name (as returned by
        ``_safe_list_directory``), so no additional sorting is needed.

        Parameters
        ----------
        items : list[tuple[str, bool]]
            Sorted list of (name, is_directory) tuples.

        Returns
        -------
        tuple[list[str], list[str]]
            A tuple containing (directories, files) preserving input order.

        """
        directories: list[str] = []
        files: list[str] = []

        # Partition items into directory and file lists
        for item, is_directory in items:
            if is_directory:
                # Collect directory entries for listing before files
                directories.append(item)
            else:
                # Collect file entries for listing after directories
                files.append(item)

        return directories, files

    def _process_symlink(self, item: str, item_path: str, connector: str, prefix: str) -> None:
        """
        Process a symlink in the structure.

        Parameters
        ----------
        item : str
            Symlink name.
        item_path : str
            Full path to the symlink.
        connector : str
            Tree connector symbol to use.
        prefix : str
            Current line prefix.

        """
        # Resolve symlink target for display, falling back to generic label
        try:
            target = Path(item_path).readlink()
            self._structure_lines.append(f"{prefix}{connector}{item} -> [symlink to {target}]\n")
        except (OSError, AttributeError):
            # Fall back to generic label when target cannot be resolved
            self._structure_lines.append(f"{prefix}{connector}{item} -> [symlink]\n")

    def _process_directory(
        self,
        item: str,
        item_path: str,
        connector: str,
        prefix: str,
        next_prefix: str,
        is_package: bool = False,
        is_command: bool = False,
        is_typed: bool = False,
    ) -> None:
        """
        Process a directory item in the structure.

        Parameters
        ----------
        item : str
            Directory name.
        item_path : str
            Full path to the directory.
        connector : str
            Tree connector symbol to use.
        prefix : str
            Current line prefix.
        next_prefix : str
            Prefix for the next level items.
        is_package : bool, optional
            Whether this directory is a Python package. Default is False.
        is_command : bool, optional
            Whether this directory contains a ``__main__.py``. Default is False.
        is_typed : bool, optional
            Whether this directory contains a ``py.typed`` marker. Default is False.

        """
        # Guard against symlink loops by tracking resolved real paths
        real_path = os.path.realpath(item_path)
        if real_path in self._visited_realpaths:
            self._structure_lines.append(f"{prefix}{connector}{item}/ [symlink loop]\n")
            return
        self._visited_realpaths.add(real_path)

        # Build directory label with package/command/typed tags
        tag_parts: list[str] = []
        # Append each marker tag when the corresponding file is present
        if is_package:
            tag_parts.append("[pkg]")
        if is_command:
            tag_parts.append("[cmd]")
        if is_typed:
            tag_parts.append("[typed]")
        tags = " ".join(tag_parts)
        dir_label = f"{item}/ {tags}" if tags else f"{item}/"
        self._structure_lines.append(f"{prefix}{connector}{dir_label}\n")

        # Use tag-free key for change detection so gaining/losing __init__.py does not cause
        # every child to appear as deleted + re-added.
        clean_key = f"{item}/"
        self._register_path(clean_key)

        # Recurse into the subdirectory with stack-based path tracking
        self._path_stack.append(clean_key.rstrip("/"))
        try:
            self._scan_recursive(item_path, next_prefix)
        finally:
            self._path_stack.pop()

    def _process_file(
        self, item: str, item_path: str, connector: str, prefix: str, next_prefix: str
    ) -> None:
        """
        Process a file in the structure.

        Parameters
        ----------
        item : str
            File name.
        item_path : str
            Full path to the file.
        connector : str
            Tree connector symbol to use.
        prefix : str
            Current line prefix.
        next_prefix : str
            Prefix for the next level items.

        """
        # Read Python files to get line count and source for AST analysis
        source: Optional[str] = None
        if item.endswith(".py"):
            # Attempt to read source and count lines for the display label
            try:
                source = Path(item_path).read_text(encoding="utf-8")
                line_count = source.count("\n") + (1 if source and not source.endswith("\n") else 0)
            except (OSError, UnicodeDecodeError):
                # Default to zero when the file cannot be read or decoded
                line_count = 0
            label = f"{item} {{{line_count}}}" if line_count else item
            self._structure_lines.append(f"{prefix}{connector}{label}\n")
        else:
            # Non-Python files displayed without metadata
            self._structure_lines.append(f"{prefix}{connector}{item}\n")
        self._register_path(item)

        # Render Python AST structure beneath the file entry
        if item.endswith(".py"):
            self._renderer.render_python_structure(
                item_path, next_prefix, self._render_settings.show_params, source=source
            )

    def _register_path(self, key: str) -> None:
        """
        Register a path for change detection tracking.

        Parameters
        ----------
        key : str
            Path key to register (e.g. ``"item/"`` or ``"file.py"``).

        """
        # Build full path key and record it with its parent hierarchy
        full_path_key = "/".join([*self._path_stack, key])
        self._scanned_paths.add(full_path_key)
        self._path_hierarchy[full_path_key] = self._path_stack.copy()

    def save_structure(self) -> SaveResult:
        """
        Save the directory structure to a text file with change tracking.

        Returns
        -------
        SaveResult
            Result containing output path, categorized changes, and log path.

        """
        # Build persistence context and delegate to the save function
        ctx = PersistenceContext(
            project_name=self.project_name,
            root_dir=self.root_dir,
            structure=self.structure,
            scanned_paths=frozenset(self._scanned_paths),
            path_hierarchy={
                path_key: tuple(ancestors) for path_key, ancestors in self._path_hierarchy.items()
            },
            filter_settings=self._filter_settings,
            tr_meta=self._tr_meta,
        )
        return _persist_save(ctx)


# ====================================== #
#            CLI ENTRY POINT             #
# ====================================== #


def _format_display_path(start_path: Path, cwd: Path) -> str:
    """
    Format a path for warnings relative to the current working directory.

    Parameters
    ----------
    start_path : Path
        Path to format for display.
    cwd : Path
        Current working directory used to compute relative paths.

    Returns
    -------
    str
        Relative path when possible, otherwise an absolute path.

    """
    # Attempt relative path, fall back to absolute on ValueError
    try:
        return str(start_path.relative_to(cwd))
    except ValueError:
        # Path is on a different drive or not under cwd; use absolute form
        return str(start_path)


def main() -> int:
    """
    Run the directory structure scanner on the current directory.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on failure.

    """
    import sys

    # Parse CLI arguments and resolve the project root directory
    visibility = parse_visibility_args(sys.argv[1:])
    cwd = Path.cwd().resolve()
    resolved_root: Optional[Path] = find_project_root(start_path=cwd)

    # Warn the user when no project root marker is found
    if resolved_root is None:
        display_path = _format_display_path(cwd, cwd)
        warnings.warn(
            ROOT_NOT_FOUND_WARNING.format(start_path=display_path),
            ROOT_NOT_FOUND_WARNING_CATEGORY,
            stacklevel=2,
        )

    root_directory = str(resolved_root or cwd)

    # Create scanner and generate the directory structure
    directory_scanner = DirectoryStructure(
        root_directory,
        show_private=visibility.show_private,
        show_mangled=visibility.show_mangled,
        show_dunder=visibility.show_dunder,
        show_types=visibility.show_types,
        show_decorators=visibility.show_decorators,
        call_flow_mode=visibility.call_flow_mode,
    )
    directory_scanner.scan_directory(root_directory)
    result = directory_scanner.save_structure()

    # Report errors if the output directory could not be created
    if result.write_status == WriteStatus.DIR_CREATE_FAILED:
        print(  # noqa: T201
            f"Error: cannot create output directory for {directory_scanner.project_name}."
        )
        return EXIT_FAILURE

    # Report errors if the structure file could not be written
    if result.write_status == WriteStatus.WRITE_FAILED:
        print(  # noqa: T201
            f"Error: cannot write {directory_scanner.project_name}_structure.txt."
        )
        return EXIT_FAILURE

    # Notify user about read errors on previous structure file
    if result.read_error:
        print(  # noqa: T201
            f"Warning: could not read previous structure file ({result.read_error}). Regenerating."
        )

    # Report first-run generation or detected changes
    if result.changes is None and not result.read_error:
        # Inform user this is a first-run generation with no prior file
        print(  # noqa: T201
            f"No {directory_scanner.project_name}_structure.txt found. Generating now."
        )
    elif result.changes is not None:
        # Display detected changes with formatted summary and optional log
        _report_changes(
            result, directory_scanner.project_name, root_directory, Config.MAX_LINE_WIDTH
        )

    return EXIT_SUCCESS


def _report_changes(
    result: SaveResult, project_name: str, root_directory: str, max_width: int
) -> None:
    """
    Format, log, and print detected structure changes.

    Parameters
    ----------
    result : SaveResult
        Save result with non-None ``changes``.
    project_name : str
        Name of the project.
    root_directory : str
        Absolute path to the project root.
    max_width : int
        Maximum line width for formatted output.

    """
    from trellis.output.console import format_change_summary
    from trellis.tracking.logger import log_structure_changes

    # Extract changes (caller guarantees changes is not None)
    changes = result.changes
    assert changes is not None  # noqa: S101

    display_log_path = ""

    # Write log file if there are changes and a logs directory is available
    if changes.has_changes and result.logs_dir:
        log_content = format_change_summary(changes, project_name, "", max_width)
        raw_log_path = log_structure_changes(result.logs_dir, log_content)
        # Warn when log file could not be written despite having changes
        if not raw_log_path:
            print("Warning: could not write structure change log.")  # noqa: T201
        else:
            # Make log path relative to project root for clickability
            with contextlib.suppress(ValueError):
                raw_log_path = str(Path(raw_log_path).relative_to(root_directory))
            display_log_path = raw_log_path

    # Format and print the change summary to stdout
    print(format_change_summary(changes, project_name, display_log_path, max_width))  # noqa: T201


if __name__ == "__main__":
    raise SystemExit(main())
