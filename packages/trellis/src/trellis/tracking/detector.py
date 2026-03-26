"""
Structure change detection and tr_meta management.

Detect differences between saved structure files, manage the tr_meta
footer encoding current settings, and extract structural elements
for comparison by the persistence layer.

Constants
---------
TR_META_PREFIX : Prefix string for tr_meta footer lines in structure files.
NO_FILE_INDENT : Sentinel indent value indicating no active file context.

Functions
---------
format_tr_meta : Build the tr_meta footer line from a pre-built meta string.
parse_tr_meta_line : Parse a tr_meta footer line and return the compact meta string.
append_tr_meta : Append the tr_meta footer below the tree content.
split_tree_and_meta : Split a structure file into tree content and tr_meta state.
detect_structure_changes : Compare old and new tree structures to detect changes.
analyze_structure_paths : Extract paths and build hierarchy from structure text.
analyze_structure_elements : Extract per-file code elements from tree text.

Examples
--------
>>> format_tr_meta("D1I1F1T1@0C0P1V0U0S0Woff")
'# tr_meta:D1I1F1T1@0C0P1V0U0S0Woff'

>>> parse_tr_meta_line("# tr_meta:D1I1F1")
'D1I1F1T1@1C0P1V0U0S0Wsmart'

"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Callable, Optional

from trellis.config import FilterSettings

# Prefix for tr_meta footer lines in the structure file.
TR_META_PREFIX = "# tr_meta:"
NO_FILE_INDENT = -1
_CONNECTOR_LENGTH = 4


# ====================================== #
#          TR_META MANAGEMENT            #
# ====================================== #


def format_tr_meta(meta: str) -> str:
    """
    Build the tr_meta footer line from a pre-built meta string.

    Parameters
    ----------
    meta : str
        Compact metadata string (e.g. from ``build_tr_meta``).

    Returns
    -------
    str
        The complete tr_meta footer line.

    """
    return f"{TR_META_PREFIX}{meta}"


def parse_tr_meta_line(line: str) -> Optional[str]:
    """
    Parse a tr_meta footer line and return the compact meta string.

    Parameters
    ----------
    line : str
        A line from the structure file to parse.

    Returns
    -------
    Optional[str]
        The parsed compact meta string, or None if the line is not
        a valid tr_meta footer.

    """
    match = re.fullmatch(
        r"# tr_meta:D([01])I([01])F([01])"
        r"(?:T([01])@([01])C([01])"
        r"(?:P([01])V([01])U([01])S([01])W(off|raw|smart))?"
        r")?",
        line.strip(),
    )
    # Reject lines that do not match the tr_meta format
    if not match:
        return None

    # Extract group indices 4-11 from the tr_meta regex match. Groups 1-3 are always present (D, I,
    # F flags); groups 4-11 are optional with sensible defaults for backward compatibility.
    type_bit = match.group(4) or "1"
    decorator_bit = match.group(5) or "1"
    compact_bit = match.group(6) or "0"
    params_bit = match.group(7) or "1"
    private_bit = match.group(8) or "0"
    dunder_bit = match.group(9) or "0"
    mangled_bit = match.group(10) or "0"
    call_flow = match.group(11) or "smart"

    return (
        f"D{match.group(1)}I{match.group(2)}F{match.group(3)}"
        f"T{type_bit}@{decorator_bit}C{compact_bit}"
        f"P{params_bit}V{private_bit}U{dunder_bit}"
        f"S{mangled_bit}W{call_flow}"
    )


def append_tr_meta(tree_content: str, meta: str) -> str:
    """
    Append the tr_meta footer three blank lines below the tree.

    Parameters
    ----------
    tree_content : str
        The tree content to append the footer to.
    meta : str
        Compact metadata string (e.g. from ``build_tr_meta``).

    Returns
    -------
    str
        The tree content with tr_meta footer appended.

    """
    footer = format_tr_meta(meta)
    base = tree_content.rstrip("\n")
    return f"{base}\n\n\n{footer}\n"


def split_tree_and_meta(content: str, project_name: str) -> tuple[str, Optional[str], str]:
    """
    Split a structure file into tree content and tr_meta state.

    Parameters
    ----------
    content : str
        The structure file content to parse.
    project_name : str
        Name of the project, used to locate the root line.

    Returns
    -------
    tuple[str, Optional[str], str]
        A tuple containing:
        - tree_content: The tree portion of the file (empty if invalid)
        - meta_value: The parsed tr_meta string, or None if missing/invalid
        - meta_status: State indicator; "valid", "invalid", or "missing"

    """
    lines = content.splitlines()
    root_line = f"{project_name}/"

    # Locate the tree start by finding the project root line
    for line_number, line in enumerate(lines):
        # Match the current line against the expected root entry
        if line.strip() == root_line:
            # Record position and stop scanning
            tree_start = line_number
            break
    else:
        # No root line found; the file content is not a valid structure file
        return "", None, "invalid"

    # Strip trailing blank lines from the tree section
    tree_lines = lines[tree_start:]
    while tree_lines and tree_lines[-1].strip() == "":
        tree_lines.pop()

    # Detect and extract the tr_meta footer if present
    meta_status = "missing"
    meta_value: Optional[str] = None

    # Check whether the last tree line is a tr_meta footer
    if tree_lines:
        last_line = tree_lines[-1].strip()
        # Parse and remove the footer when recognized
        if last_line.startswith(TR_META_PREFIX):
            meta_value = parse_tr_meta_line(last_line)
            meta_status = "valid" if meta_value is not None else "invalid"
            tree_lines = tree_lines[:-1]

    # Rebuild the tree content with a trailing newline
    tree_content = "\n".join(tree_lines).rstrip()
    if tree_content:
        tree_content += "\n"

    return tree_content, meta_value, meta_status


# ====================================== #
#           CHANGE DETECTION             #
# ====================================== #


def _resolve_new_paths(
    new_content: str,
    project_name: str,
    collected_paths: Optional[tuple[frozenset[str], dict[str, tuple[str, ...]]]],
) -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    """
    Resolve new path set from collected data or by parsing content.

    Parameters
    ----------
    new_content : str
        The new structure content to parse if no collected paths.
    project_name : str
        Name of the project for tree parsing.
    collected_paths : tuple[frozenset[str], dict[str, tuple[str, ...]]], optional
        Pre-collected ``(paths, hierarchy)`` from directory scanning.

    Returns
    -------
    tuple[frozenset[str], dict[str, tuple[str, ...]]]
        Path set and hierarchy mapping.

    """
    # Use pre-collected paths when available to avoid reparsing
    if collected_paths is not None:
        return collected_paths
    new_tree_content, _, _ = split_tree_and_meta(new_content, project_name)
    paths, hierarchy = analyze_structure_paths(new_tree_content)
    return frozenset(paths), {k: tuple(v) for k, v in hierarchy.items()}


def _apply_path_filtering(
    paths: AbstractSet[str],
    hierarchy: Mapping[str, Sequence[str]],
    path_filter: Callable[[str, Sequence[str]], bool],
) -> set[str]:
    """
    Apply hierarchical ignore filtering to a path set.

    Parameters
    ----------
    paths : AbstractSet[str]
        Paths to filter (``set`` or ``frozenset``).
    hierarchy : Mapping[str, Sequence[str]]
        Ancestry mapping for each path.
    path_filter : Callable[[str, Sequence[str]], bool]
        Callable that returns True if a path should be excluded.

    Returns
    -------
    set[str]
        Filtered path set.

    """
    # Always filter: hard ignores in filters.py fire unconditionally even
    # when both enable_ignore_dirs and enable_ignore_files are False.
    return {path for path in paths if not path_filter(path, hierarchy.get(path, ()))}


def detect_structure_changes(
    new_content: str,
    old_content: str,
    project_name: str,
    path_filter: Callable[[str, Sequence[str]], bool],
    settings: FilterSettings,
    collected_paths: Optional[tuple[frozenset[str], dict[str, tuple[str, ...]]]] = None,
    old_tree_content: Optional[str] = None,
) -> tuple[list[str], list[str], bool]:
    """
    Compare old and new tree structures to detect changes.

    Parameters
    ----------
    new_content : str
        The new structure content to be compared.
    old_content : str
        Previous structure file content for comparison.  Ignored when
        *old_tree_content* is provided.
    project_name : str
        Name of the project for tree parsing.
    path_filter : Callable[[str, Sequence[str]], bool]
        Callable that returns True if a path (given its ancestry)
        should be excluded from change detection.
    settings : FilterSettings
        Immutable snapshot of filtering and change detection settings.
    collected_paths : tuple[frozenset[str], dict[str, tuple[str, ...]]], optional
        Pre-collected ``(paths, hierarchy)`` from directory scanning.
        When provided, skips ``analyze_structure_paths`` for the new
        content side.  The old content is always parsed from text since
        it comes from a previously saved file.
    old_tree_content : str, optional
        Pre-parsed tree content from the old file.  When provided,
        skips ``split_tree_and_meta`` for the old content side.

    Returns
    -------
    tuple[list[str], list[str], bool]
        A tuple containing:
        - added_paths: list of paths added since last generation
        - deleted_paths: list of paths removed since last generation
        - has_changes: whether any changes were detected

    """
    # Skip change detection entirely when logging is disabled
    if not settings.log_structure_changes:
        return [], [], False

    new_paths, new_hierarchy = _resolve_new_paths(new_content, project_name, collected_paths)

    # Parse old tree from raw content when no pre-parsed version is provided
    if old_tree_content is None:
        old_tree_content, _, _ = split_tree_and_meta(old_content, project_name)
    old_paths, old_hierarchy = analyze_structure_paths(old_tree_content)

    filtered_new = _apply_path_filtering(new_paths, new_hierarchy, path_filter)
    filtered_old = _apply_path_filtering(old_paths, old_hierarchy, path_filter)

    added_paths = sorted(filtered_new - filtered_old)
    deleted_paths = sorted(filtered_old - filtered_new)
    has_changes = bool(added_paths or deleted_paths)

    return added_paths, deleted_paths, has_changes


# ====================================== #
#          STRUCTURE ANALYSIS            #
# ====================================== #


def _clean_path_entry(path_part: str) -> tuple[str, bool]:
    """
    Classify a path entry as file or directory and strip tag annotations.

    Parameters
    ----------
    path_part : str
        Raw path text after the tree connector.

    Returns
    -------
    tuple[str, bool]
        Cleaned path string and whether it is a directory.

    """
    is_directory = path_part.endswith("/") or "/ " in path_part
    # Strip annotations based on entry type
    if is_directory:
        # Remove optional tag annotations from directory entries: "name/ [pkg]" → "name/".
        clean_part = path_part.split(" [")[0]
        if not clean_part.endswith("/"):
            clean_part += "/"
    else:
        # Strip line count annotation from file entries: "main.py {285}" → "main.py".
        clean_part = path_part.split(" {")[0]

    return clean_part, is_directory


def _iter_tree_entries(structure_text: str) -> Iterator[tuple[int, str]]:
    """
    Yield (indent, content) pairs from tree-formatted structure text.

    Parameters
    ----------
    structure_text : str
        The rendered directory structure text.

    Yields
    ------
    tuple[int, str]
        Indentation level (connector position) and content after the connector.

    """
    # Walk each line looking for a tree connector to extract depth and content
    for line in structure_text.splitlines():
        # Locate the tree connector to determine depth
        branch_pos = line.find("├── ")
        # Fall back to the end connector when the branch connector is absent
        if branch_pos == -1:
            branch_pos = line.find("└── ")
        # Skip lines without any tree connector
        if branch_pos == -1:
            continue

        yield branch_pos, line[branch_pos + _CONNECTOR_LENGTH :]


def analyze_structure_paths(
    structure_text: str,
) -> tuple[set[str], dict[str, list[str]]]:
    """
    Extract paths and build hierarchy from structure text in one pass.

    Parse the structure text to extract file and directory paths while
    simultaneously building parent-child ancestry chains for hierarchy
    tracking.

    Parameters
    ----------
    structure_text : str
        The directory structure text representation.

    Returns
    -------
    tuple[set[str], dict[str, list[str]]]
        A tuple containing:
        - paths: set of extracted file and directory paths
        - hierarchy: dictionary mapping each path to its ancestry list

    """
    paths: set[str] = set()
    path_hierarchy: dict[str, list[str]] = {}
    path_stack: list[str] = []
    indent_levels: list[int] = []

    # Process each tree entry to build path set and hierarchy
    for indent, content in _iter_tree_entries(structure_text):
        # Skip code elements, call flow lines, and symlink annotations
        if content.startswith(("def ", "class ", "async def ", "@", "calls: ", "/wrapper\\ ")):
            continue

        # Skip symlink annotations
        if " -> [symlink" in content:
            continue

        # Unwind the stack to find the correct parent directory
        while indent_levels and indent <= indent_levels[-1]:
            indent_levels.pop()
            path_stack.pop()

        clean_part, is_directory = _clean_path_entry(content)

        # Build the full path key using "/" as separator
        full_path_key = "/".join([*path_stack, clean_part])

        # Add to the flat path set and record ancestry chain
        paths.add(full_path_key)
        path_hierarchy[full_path_key] = path_stack.copy()

        # Push directories onto the stack for child resolution
        if is_directory:
            stack_entry = clean_part.rstrip("/")
            path_stack.append(stack_entry)
            indent_levels.append(indent)

    return paths, path_hierarchy


def _resolve_decorator_element(
    stripped: str,
    pending_decorators: list[str],
) -> str:
    """
    Join pending decorators with a def/class line into a composite element.

    Parameters
    ----------
    stripped : str
        The def/class line content.
    pending_decorators : list[str]
        Accumulated decorator lines to prepend.

    Returns
    -------
    str
        Composite element line with decorators joined by ``" | "``.

    """
    # Prepend accumulated decorators when present
    if pending_decorators:
        combined = " | ".join(pending_decorators) + " | " + stripped
        pending_decorators.clear()
        return combined
    return stripped


def _process_path_entry(
    content: str,
    indent: int,
    path_stack: list[str],
    indent_levels: list[int],
    elements: dict[str, list[str]],
    current_file: Optional[str],
    current_file_indent: int,
) -> tuple[Optional[str], int]:
    """
    Process a non-code path entry (file or directory).

    Parameters
    ----------
    content : str
        Line content after the tree connector.
    indent : int
        Indentation level of the entry.
    path_stack : list[str]
        Current directory nesting stack (mutated).
    indent_levels : list[int]
        Indent levels matching path_stack (mutated).
    elements : dict[str, list[str]]
        Element accumulator (mutated for new .py files).
    current_file : str or None
        Currently active .py file key.
    current_file_indent : int
        Indent level of the current file.

    Returns
    -------
    tuple[str or None, int]
        Updated (current_file, current_file_indent).

    """
    # Check if indent has returned to or above current file level
    if current_file is not None and indent <= current_file_indent:
        current_file = None
        current_file_indent = NO_FILE_INDENT

    # Unwind path stack for directory tracking
    while indent_levels and indent <= indent_levels[-1]:
        indent_levels.pop()
        path_stack.pop()

    # Route to file or directory handling based on extension
    clean_part, is_directory = _clean_path_entry(content)
    if clean_part.endswith(".py"):
        # Track as the active Python file for element collection
        current_file_indent = indent
        file_key = "/".join([*path_stack, clean_part])
        current_file = file_key
        if file_key not in elements:
            elements[file_key] = []
    elif is_directory:
        # Push directory onto the stack for child path resolution
        dir_name = clean_part.rstrip("/")
        path_stack.append(dir_name)
        indent_levels.append(indent)

    return current_file, current_file_indent


def analyze_structure_elements(structure_text: str) -> dict[str, list[str]]:
    """
    Extract per-file code elements (functions, classes, decorators) from tree text.

    Parameters
    ----------
    structure_text : str
        The rendered directory structure text.

    Returns
    -------
    dict[str, list[str]]
        Mapping of file path keys to their normalized code element lines.

    """
    elements: dict[str, list[str]] = {}
    path_stack: list[str] = []
    indent_levels: list[int] = []
    current_file: Optional[str] = None
    current_file_indent: int = NO_FILE_INDENT
    pending_decorators: list[str] = []

    # Process each tree entry to collect code elements per file
    for indent, content in _iter_tree_entries(structure_text):
        # Skip call flow lines entirely
        if content.startswith("calls: "):
            continue

        # Skip symlink annotations
        if " -> [symlink" in content:
            continue

        # Check if this is a code element line
        is_code_element = content.startswith(("def ", "class ", "async def ", "@", "/wrapper\\ "))

        # Dispatch to path tracking or element collection based on entry type
        if not is_code_element:
            # Non-code entry; reset decorators and update file/directory tracking
            pending_decorators.clear()
            current_file, current_file_indent = _process_path_entry(
                content,
                indent,
                path_stack,
                indent_levels,
                elements,
                current_file,
                current_file_indent,
            )
        elif current_file is not None:
            # Code element inside an active file; collect or accumulate decorator
            stripped = content.strip()
            # Separate decorators from definitions for composite element assembly
            if stripped.startswith("@"):
                # Accumulate decorator for attachment to the next def/class
                pending_decorators.append(stripped)
            else:
                # Resolve any pending decorators and record the element
                combined = _resolve_decorator_element(stripped, pending_decorators)
                elements[current_file].append(combined)
        else:
            # Code element outside any tracked file; discard pending decorators
            pending_decorators.clear()

    return elements
