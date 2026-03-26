"""
Terminal banner formatting for structure change summaries.

Format categorized structure changes as a terminal-ready summary
with a header banner, per-category detail sections grouped by file,
and a clickable log file link.

Functions
---------
format_change_summary : Format categorized changes into a terminal-ready summary string.

Examples
--------
>>> from trellis.tracking.comparator import StructureChanges
>>> empty = StructureChanges([], [], [], [], [], [], [], [], [], False)
>>> format_change_summary(empty, "demo", "", 100)
'No structure changes detected.'

"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from trellis.tracking.comparator import (
    ApiChange,
    ApiEntry,
    StructureChanges,
    extract_lineno,
    extract_signature_detail,
    strip_lineno,
)

_T = TypeVar("_T", ApiChange, ApiEntry)

# Regex pattern to extract function/class name from element lines.
_NAME_PREFIX = re.compile(r"((?:async def |def |class )\w+)")
_SIGNATURE_INDENT = 6


# ====================================== #
#          FORMATTING HELPERS            #
# ====================================== #


def _counted(items: Sequence[object], singular: str, plural: str = "") -> str:
    """
    Format a count with singular/plural label.

    Parameters
    ----------
    items : Sequence[object]
        Items to count.
    singular : str
        Label when count is 1.
    plural : str
        Label when count is not 1. Defaults to ``singular + "s"``.

    Returns
    -------
    str
        Formatted string like ``"2 modules"`` or ``"1 module"``.

    """
    count = len(items)
    label = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {label}"


_SUMMARY_PREFIX = "  Summary:   "


_SUMMARY_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("api_changes", "API update", ""),
    ("new_api", "new API", "new API"),
    ("removed_api", "removed", "removed"),
    ("new_packages", "new package", ""),
    ("removed_packages", "removed package", ""),
    ("new_modules", "new module", ""),
    ("removed_modules", "removed module", ""),
    ("new_files", "new file", ""),
    ("removed_files", "removed file", ""),
)


def _build_summary_line(changes: StructureChanges, max_line_width: int) -> str:
    """
    Build the summary of change counts, wrapping at *max_line_width*.

    When the summary exceeds the line width, it splits evenly across
    two lines with the continuation aligned under the first count.

    Parameters
    ----------
    changes : StructureChanges
        Categorized structural changes.
    max_line_width : int
        Maximum total line width including the summary prefix.

    Returns
    -------
    str
        Summary like ``"2 API updates \u00b7 1 new API \u00b7 1 removed"``,
        possibly with a newline and continuation indent.

    """
    parts: list[str] = []
    # Collect count labels for each non-empty change category
    for attr, singular, plural in _SUMMARY_CATEGORIES:
        items = getattr(changes, attr)
        if items:
            parts.append(_counted(items, singular, plural))
    # Fall back to a generic label when no categories have counts
    if not parts:
        return "changes detected"

    joined = " \u00b7 ".join(parts)

    # Return single-line summary when it fits within the width budget
    if len(_SUMMARY_PREFIX) + len(joined) <= max_line_width:
        return joined

    # Split into two balanced halves at the nearest part boundary.
    sep = " \u00b7 "
    # Ceiling division: -(-n // 2) computes ceil(n / 2)
    half = -(-len(parts) // 2)

    first_half = sep.join(parts[:half])
    second_half = sep.join(parts[half:])
    cont_indent = " " * len(_SUMMARY_PREFIX)
    return f"{first_half}\n{cont_indent}{second_half}"


def _extract_lineno_number(element_line: str) -> str:
    """
    Extract the bare line number from an element line.

    Parameters
    ----------
    element_line : str
        Full element line that may end with ``  :NN``.

    Returns
    -------
    str
        The line number as a string (e.g. ``"42"``), or ``""`` if absent.

    """
    lineno = extract_lineno(element_line)
    return lineno.lstrip(":") if lineno else ""


def _format_element_name(element_line: str) -> str:
    """
    Extract 'def/class name' from a full element line (no line number).

    Parameters
    ----------
    element_line : str
        Full element line like ``"def process_data(input: str) -> int  :42"``.

    Returns
    -------
    str
        Name portion like ``"def process_data"``.

    """
    stripped = strip_lineno(element_line)
    # Remove decorator prefix
    if " | " in stripped:
        stripped = stripped.rsplit(" | ", 1)[-1]
    # Extract "def name" or "class name" or "async def name"
    match = _NAME_PREFIX.match(stripped)
    return match.group(1) if match else stripped


def _split_params(params_str: str) -> list[str]:
    """
    Split parameter string at top-level commas only.

    Commas inside brackets (``[]``, ``()``, ``{}``) are preserved
    so that generic type annotations like ``dict[str, int]`` are
    not broken across parameters.

    Parameters
    ----------
    params_str : str
        The parameter string without outer parentheses.

    Returns
    -------
    list[str]
        Parameter strings split at depth-zero commas.

    """
    params: list[str] = []
    depth = 0
    start = 0
    # Walk each character tracking bracket depth to find top-level commas
    for char_pos, char in enumerate(params_str):
        if char in "([{":
            # Increase nesting depth on opening brackets
            depth += 1
        elif char in ")]}":
            # Decrease nesting depth on closing brackets
            depth -= 1
        elif char == "," and depth == 0:
            # Split at top-level commas outside any bracket nesting
            params.append(params_str[start:char_pos].strip())
            start = char_pos + 1

    # Append the final parameter after the last comma
    params.append(params_str[start:].strip())
    return params


def _wrap_signature(detail: str, indent: int, max_width: int) -> str:
    """
    Wrap a signature detail string to fit within a line width.

    Breaks at comma boundaries so each continuation line aligns one
    character past the opening ``(``, mirroring PEP 8 continuation
    style.  If the detail does not start with ``(`` or fits on one
    line, it is returned unchanged.

    Parameters
    ----------
    detail : str
        Signature detail like ``"(a: int, b: str) -> bool"``.
    indent : int
        Column where the detail starts (number of leading spaces).
    max_width : int
        Maximum total line width including indent.

    Returns
    -------
    str
        Possibly multi-line string with continuation indentation.

    """
    prefix = " " * indent
    # Return non-parenthesized details unchanged (e.g. class inheritance)
    if not detail.startswith("("):
        return prefix + detail
    # Return single-line when the detail fits within the width budget
    if indent + len(detail) <= max_width:
        return prefix + detail

    # Split params from return type: "(params) -> ReturnType"
    close_paren = detail.rfind(")")
    # Return unchanged when no closing parenthesis is found
    if close_paren == -1:
        return prefix + detail

    # Extract parameter portion and return type annotation
    params_str = detail[1:close_paren]
    suffix = detail[close_paren:]

    params = _split_params(params_str)
    # Return unchanged when the parameter list is empty
    if not params:
        return detail

    # Continuation lines align one character past the opening "("
    cont_indent = " " * (indent + 1)
    lines: list[str] = []
    current = " " * indent + "(" + params[0]

    # Append remaining parameters, wrapping to continuation lines when needed
    for param in params[1:]:
        candidate = f"{current}, {param}"
        # When adding the next parameter would exceed line width and we already
        # have at least one parameter on the current line, wrap to continuation.
        if len(candidate) + len(suffix) > max_width and current != " " * indent + "(":
            lines.append(current + ",")
            current = cont_indent + param
        else:
            # Extend the current line when the parameter still fits
            current = candidate

    current += suffix
    lines.append(current)
    return "\n".join(lines)


def _build_clickable_link(file_path: str, element_line: str) -> str:
    """
    Build a terminal-clickable ``file:line`` link from a change entry.

    Parameters
    ----------
    file_path : str
        Relative file path (e.g. ``"pyast/analyzer.py"``).
    element_line : str
        Element line containing an optional ``:NN`` suffix.

    Returns
    -------
    str
        Clickable link like ``"pyast/analyzer.py:42"``, or just the
        file path if no line number is present.

    """
    lineno = _extract_lineno_number(element_line)
    # Append line number to the path when present for terminal clickability
    if lineno:
        return f"{file_path}:{lineno}"
    return file_path


def _group_by_file(
    items: Sequence[_T],
) -> dict[str, list[_T]]:
    """
    Group changes/entries by file_path, preserving insertion order.

    Parameters
    ----------
    items : Sequence[ApiChange or ApiEntry]
        Items to group.

    Returns
    -------
    dict[str, list[ApiChange or ApiEntry]]
        File path to list of items.

    """
    groups: dict[str, list[_T]] = {}
    # Accumulate items into per-file buckets in encounter order
    for item in items:
        groups.setdefault(item.file_path, []).append(item)
    return groups


def _file_label(file_path: str) -> str:
    """
    Extract the leaf filename from a relative path for group headers.

    Parameters
    ----------
    file_path : str
        Relative file path (e.g. ``"demo_pkg/core.py"``).

    Returns
    -------
    str
        Leaf filename (e.g. ``"core.py"``).

    """
    return Path(file_path).name


# ====================================== #
#          ENTRY FORMATTING              #
# ====================================== #


def _format_api_change_entry(change: ApiChange, max_line_width: int) -> list[str]:
    """
    Format an API change with a terminal-clickable file:line link.

    Parameters
    ----------
    change : ApiChange
        The change to format.
    max_line_width : int
        Maximum total line width.

    Returns
    -------
    list[str]
        Formatted lines for this change entry.

    """
    name = _format_element_name(change.new_signature)
    link = _build_clickable_link(change.file_path, change.new_signature)
    old_detail = extract_signature_detail(change.old_signature)
    new_detail = extract_signature_detail(change.new_signature)

    sig_indent = _SIGNATURE_INDENT
    old_wrapped = _wrap_signature(old_detail, sig_indent, max_line_width)
    new_wrapped = _wrap_signature(new_detail, sig_indent, max_line_width)

    return [
        f"    {link}  {name}",
        old_wrapped,
        "          >>",
        new_wrapped,
    ]


def _format_new_api_entry(entry: ApiEntry, max_line_width: int) -> list[str]:
    """
    Format a new API entry with a clickable file:line link.

    The link and name appear on the first line; when signature detail
    is present, it is placed on a separate indented line below,
    matching the layout used by the Updated API section.

    Parameters
    ----------
    entry : ApiEntry
        The entry to format.
    max_line_width : int
        Maximum total line width.

    Returns
    -------
    list[str]
        Formatted lines for this entry.

    """
    link = _build_clickable_link(entry.file_path, entry.signature)
    name = _format_element_name(entry.signature)
    detail = extract_signature_detail(entry.signature)

    # Return name-only line when there is no signature detail to show
    if not detail:
        return [f"    {link}  {name}"]

    sig_indent = _SIGNATURE_INDENT
    wrapped = _wrap_signature(detail, sig_indent, max_line_width)
    return [f"    {link}  {name}", wrapped]


def _format_removed_api_entry(entry: ApiEntry) -> str:
    """
    Format a removed API entry as file path + name only.

    Parameters
    ----------
    entry : ApiEntry
        The entry to format.

    Returns
    -------
    str
        Formatted line with file path and element name.

    """
    name = _format_element_name(entry.signature)
    return f"  {entry.file_path}  {name}"


# ====================================== #
#           CHANGE SUMMARY               #
# ====================================== #


def _append_api_changes_section(
    lines: list[str], changes: list[ApiChange], max_line_width: int
) -> None:
    """
    Append API changes section grouped by file.

    Parameters
    ----------
    lines : list[str]
        Accumulator (mutated).
    changes : list[ApiChange]
        API changes to format.
    max_line_width : int
        Maximum total line width.

    """
    # Skip section entirely when there are no changes to show
    if not changes:
        return
    lines.append("")
    lines.append(f"Updated API ({len(changes)}):")
    groups = _group_by_file(changes)
    file_paths = list(groups)

    # Format each file's changes with inter-group spacing
    for file_index, file_path in enumerate(file_paths):
        lines.append(f"  {_file_label(file_path)}")
        # Append formatted entries for this file
        for change in groups[file_path]:
            change_lines = _format_api_change_entry(change, max_line_width)
            lines.extend(change_lines)

        # Add blank line separator between file groups
        if file_index < len(file_paths) - 1:
            lines.append("")


def _append_new_api_section(lines: list[str], entries: list[ApiEntry], max_line_width: int) -> None:
    """
    Append new API entries section grouped by file.

    Parameters
    ----------
    lines : list[str]
        Accumulator (mutated).
    entries : list[ApiEntry]
        New API entries to format.
    max_line_width : int
        Maximum total line width.

    """
    # Skip section entirely when there are no entries to show
    if not entries:
        return
    lines.append("")
    lines.append(f"New API ({len(entries)}):")
    groups = _group_by_file(entries)
    file_paths = list(groups)

    # Format each file's entries with inter-group spacing
    for file_index, file_path in enumerate(file_paths):
        lines.append(f"  {_file_label(file_path)}")
        # Append formatted entries for this file
        for entry in groups[file_path]:
            lines.extend(_format_new_api_entry(entry, max_line_width))

        # Add blank line separator between file groups
        if file_index < len(file_paths) - 1:
            lines.append("")


def _append_removed_api_section(lines: list[str], entries: list[ApiEntry]) -> None:
    """
    Append removed API entries as a flat list.

    Parameters
    ----------
    lines : list[str]
        Accumulator (mutated).
    entries : list[ApiEntry]
        Removed API entries to format.

    """
    # Skip section entirely when there are no entries to show
    if not entries:
        return
    lines.append("")
    lines.append(f"Removed API ({len(entries)}):")
    lines.extend(_format_removed_api_entry(entry) for entry in entries)


def _append_flat_section(lines: list[str], label: str, items: list[str]) -> None:
    """
    Append a flat path list section to lines.

    Parameters
    ----------
    lines : list[str]
        Accumulator (mutated).
    label : str
        Section label.
    items : list[str]
        Path strings to list.

    """
    # Skip section entirely when there are no items to show
    if not items:
        return
    lines.append("")
    lines.append(f"{label} ({len(items)}):")
    lines.extend(f"  {item}" for item in items)


def _build_detail_sections(changes: StructureChanges, max_line_width: int) -> list[str]:
    """
    Build the detail sections below the banner.

    Parameters
    ----------
    changes : StructureChanges
        Categorized structural changes.
    max_line_width : int
        Maximum total line width.

    Returns
    -------
    list[str]
        Lines for all non-empty detail sections.

    """
    lines: list[str] = []

    _append_api_changes_section(lines, changes.api_changes, max_line_width)
    _append_new_api_section(lines, changes.new_api, max_line_width)
    _append_removed_api_section(lines, changes.removed_api)
    _append_flat_section(lines, "New Packages", changes.new_packages)
    _append_flat_section(lines, "Removed Packages", changes.removed_packages)
    _append_flat_section(lines, "New Modules", changes.new_modules)
    _append_flat_section(lines, "Removed Modules", changes.removed_modules)
    _append_flat_section(lines, "New Files", changes.new_files)
    _append_flat_section(lines, "Removed Files", changes.removed_files)

    return lines


def format_change_summary(
    changes: StructureChanges,
    project_name: str,
    log_path: str,
    max_line_width: int,
) -> str:
    """
    Format categorized changes into a terminal-ready summary string.

    Parameters
    ----------
    changes : StructureChanges
        Categorized structural changes.
    project_name : str
        Name of the project.
    log_path : str
        Relative path to the log file.
    max_line_width : int
        Maximum total line width.

    Returns
    -------
    str
        Formatted summary string ready for printing.

    """
    # Return early with a short message when there are no changes
    if not changes.has_changes:
        return "No structure changes detected."

    summary_line = _build_summary_line(changes, max_line_width)

    # Build header banner
    banner_width = max_line_width
    banner = "=" * banner_width
    log_name = Path(log_path).name if log_path else ""
    lines: list[str] = [
        banner,
        "Structure Changes",
        f"  Project:   {project_name}",
    ]
    # Include log filename in the banner when a log was written
    if log_name:
        lines.append(f"  Log:       {log_name}")
    lines.append(f"  Summary:   {summary_line}")
    lines.append(banner)

    lines.extend(_build_detail_sections(changes, max_line_width))

    return "\n".join(lines)
