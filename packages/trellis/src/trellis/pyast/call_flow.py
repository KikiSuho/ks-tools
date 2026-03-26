"""
Call flow scoring, filtering, and formatting.

Score and filter function call names for SMART call flow display,
and format call flow summary lines with width-aware truncation.

Constants
---------
ORCHESTRATION_NAMES : Function names considered orchestration entry points.

Functions
---------
format_call_flow_line : Format a compact call flow summary line with width-aware truncation.
filter_smart_calls : Filter call names using SMART scoring, preserving source order.

Examples
--------
>>> format_call_flow_line(["setup", "run"], prefix="", max_line_width=100)
'└── calls: setup -> run'

>>> "main" in ORCHESTRATION_NAMES
True

"""

from __future__ import annotations

from typing import Callable

__all__ = ["ORCHESTRATION_NAMES"]

ORCHESTRATION_NAMES: frozenset[str] = frozenset({"main", "run", "execute", "orchestrate"})

_VisibilityPredicate = Callable[[str], bool]


# ====================================== #
#         CALL FLOW FORMATTING           #
# ====================================== #


def format_call_flow_line(
    call_names: list[str],
    prefix: str,
    max_line_width: int,
    connector: str = "└── ",
) -> str:
    """
    Format a compact call flow summary line with width-aware truncation.

    Build a ``calls: name1 -> name2 -> ...`` string that fits within
    the width budget.  If the full chain exceeds the budget, truncate
    from the right and append ``... +N more``.

    Parameters
    ----------
    call_names : list[str]
        Call names in source order.
    prefix : str
        Tree prefix preceding the ``calls:`` line (used for width
        calculation and as the line's leading whitespace).
    max_line_width : int
        Target maximum line width including the prefix.
    connector : str
        Tree connector symbol (default ``"└── "``).  Use ``"├── "``
        when sibling nodes follow the call flow line.

    Returns
    -------
    str
        Formatted call flow line with tree connector.

    """
    # Return empty when there are no calls to format
    if not call_names:
        return ""

    label_prefix = f"{prefix}{connector}calls: "
    budget = max_line_width - len(label_prefix)

    # Short-circuit for single-call chains that never need truncation
    if len(call_names) == 1:
        return f"{label_prefix}{call_names[0]}"

    parts: list[str] = []
    current_width = 0

    # Build the chain left-to-right, truncating when the budget is exceeded
    for call_index, name in enumerate(call_names):
        separator = " -> " if parts else ""
        addition = f"{separator}{name}"
        remaining_count = len(call_names) - call_index - 1
        overflow_suffix = f" -> ... +{remaining_count} more" if remaining_count > 0 else ""
        projected_width = current_width + len(addition) + len(overflow_suffix)

        # Truncate and append overflow suffix when budget is exceeded
        if budget > 0 and projected_width > budget and parts:
            overflow_count = len(call_names) - call_index
            parts.append(f" -> ... +{overflow_count} more")
            break

        parts.append(addition)
        current_width += len(addition)

    return f"{label_prefix}{''.join(parts)}"


# ====================================== #
#        SCORING AND FILTERING           #
# ====================================== #


_BUILTIN_NAMES: frozenset[str] = frozenset(
    {
        "print",
        "len",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "type",
        "isinstance",
        "issubclass",
        "super",
        "range",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "min",
        "max",
        "sum",
        "abs",
        "any",
        "all",
        "hash",
        "id",
        "repr",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "hasattr",
        "callable",
        "iter",
        "next",
        "open",
        "round",
        "format",
    }
)

_LOGGING_NAMES: frozenset[str] = frozenset(
    {
        "log",
        "debug",
        "info",
        "warning",
        "error",
        "exception",
        "critical",
        "warn",
    }
)

_ORCHESTRATION_PREFIXES: tuple[str, ...] = (
    "analyze",
    "build",
    "configure",
    "create",
    "execute",
    "fetch",
    "find",
    "generate",
    "init",
    "load",
    "parse",
    "prepare",
    "process",
    "render",
    "run",
    "save",
    "scan",
    "setup",
    "validate",
    "write",
)

_UTILITY_LEAF_NAMES: frozenset[str] = frozenset(
    {
        "resolve",
        "join",
        "exists",
        "mkdir",
        "open",
        "cwd",
        "read_text",
        "write_text",
        "absolute",
        "relative_to",
        "append",
        "extend",
        "strip",
        "split",
        "replace",
        "encode",
        "decode",
        "copy",
        "deepcopy",
        "close",
        "flush",
        "items",
        "keys",
        "values",
        "get",
        "pop",
        "clear",
        "lower",
        "upper",
        "name",
        "parent",
        "stem",
        "suffix",
        "read",
        "write",
        "seek",
        "tell",
    }
)

_SMART_MAX_CALLS = 4
_SMART_SCORE_THRESHOLD = 1
_DESCRIPTIVE_NAME_MIN_LENGTH = 6
_SHORT_NAME_MAX_LENGTH = 2

# Additive score weights for SMART call flow filtering.
_SCORE_SIBLING = 3
_SCORE_IMPORTED = 2
_SCORE_ORCHESTRATION_PREFIX = 2
_SCORE_DESCRIPTIVE_NAME = 1
_PENALTY_BUILTIN = -3
_PENALTY_LOGGING = -3
_PENALTY_UTILITY_LEAF = -2
_PENALTY_SHORT_NAME = -1


def _score_call(
    name: str,
    sibling_names: frozenset[str],
    imported_names: frozenset[str],
) -> int:
    """
    Score a call name for SMART mode filtering.

    Uses an additive model with positive and negative signals.
    Sibling functions (same-file definitions) receive the strongest
    positive signal.  Imported names and orchestration-style prefixes
    receive a moderate boost.  Descriptive underscore names add a
    weaker positive signal.  Builtins, logging calls, and
    generic utility leaf names receive penalties.

    Parameters
    ----------
    name : str
        The call name to score.
    sibling_names : frozenset[str]
        Names of other top-level functions in the same file.
    imported_names : frozenset[str]
        Names bound by import statements in the same file.

    Returns
    -------
    int
        The computed score for this call name.

    """
    score = 0

    # Positive signals: same-file, imported, orchestration prefix, descriptive name
    if name in sibling_names:
        score += _SCORE_SIBLING
    if name in imported_names:
        score += _SCORE_IMPORTED
    if name.startswith(_ORCHESTRATION_PREFIXES):
        score += _SCORE_ORCHESTRATION_PREFIX
    if len(name) >= _DESCRIPTIVE_NAME_MIN_LENGTH and "_" in name:
        score += _SCORE_DESCRIPTIVE_NAME

    # Negative signals: builtins, logging, utility leaves, very short names
    if name in _BUILTIN_NAMES:
        score += _PENALTY_BUILTIN
    if name in _LOGGING_NAMES:
        score += _PENALTY_LOGGING
    if name in _UTILITY_LEAF_NAMES:
        score += _PENALTY_UTILITY_LEAF
    if len(name) <= _SHORT_NAME_MAX_LENGTH:
        score += _PENALTY_SHORT_NAME

    return score


def _top_indices_by_score(
    scored: list[tuple[int, str, int]],
    max_calls: int,
) -> set[int]:
    """
    Return the indices of the top-scoring calls above threshold.

    Parameters
    ----------
    scored : list[tuple[int, str, int]]
        Scored entries as ``(original_index, name, score)``.
    max_calls : int
        Maximum number of indices to keep.

    Returns
    -------
    set[int]
        Indices of the kept entries.

    """
    by_score = sorted(scored, key=lambda entry: entry[2], reverse=True)
    kept: set[int] = set()
    # Collect indices from highest score down until limit or threshold is reached
    for index, _name, score in by_score:
        # Stop when scores drop below the minimum threshold
        if score < _SMART_SCORE_THRESHOLD:
            break
        kept.add(index)
        # Stop when the maximum number of calls is reached
        if len(kept) >= max_calls:
            break
    return kept


def _score_visible_calls(
    call_names: list[str],
    sibling_names: frozenset[str],
    imported_names: frozenset[str],
    is_hidden: _VisibilityPredicate,
) -> tuple[list[tuple[int, str, int]], bool]:
    """
    Score visible calls and return scored list with validity flag.

    Parameters
    ----------
    call_names : list[str]
        Raw call names in source order.
    sibling_names : frozenset[str]
        Names of other top-level functions in the same file.
    imported_names : frozenset[str]
        Names bound by import statements in the same file.
    is_hidden : _VisibilityPredicate
        Visibility predicate — returns True if hidden.

    Returns
    -------
    tuple[list[tuple[int, str, int]], bool]
        Scored entries as ``(original_index, name, score)`` and
        whether any visible calls were found.

    """
    visible = [(index, name) for index, name in enumerate(call_names) if not is_hidden(name)]
    # Return early when all calls are hidden by visibility rules
    if not visible:
        return [], False
    scored = [
        (index, name, _score_call(name, sibling_names, imported_names)) for index, name in visible
    ]
    return scored, True


def filter_smart_calls(
    call_names: list[str],
    sibling_names: frozenset[str],
    imported_names: frozenset[str],
    is_hidden: _VisibilityPredicate,
) -> list[str]:
    """
    Filter call names using SMART scoring, preserving source order.

    First removes calls that fail visibility rules, then scores the
    remaining calls and keeps the top ``_SMART_MAX_CALLS`` at or above
    the score threshold.  Falls back to the full raw list if no calls
    survive filtering.

    Parameters
    ----------
    call_names : list[str]
        Raw call names in source order.
    sibling_names : frozenset[str]
        Names of other top-level functions in the same file.
    imported_names : frozenset[str]
        Names bound by import statements in the same file.
    is_hidden : Callable[[str], bool]
        Visibility predicate — returns True if a name should be hidden
        under current visibility settings.

    Returns
    -------
    list[str]
        Filtered call names in original source order.

    """
    scored, has_visible = _score_visible_calls(
        call_names,
        sibling_names,
        imported_names,
        is_hidden,
    )
    # Fall back to raw list when all calls are hidden
    if not has_visible:
        return call_names

    above_threshold = [
        (index, name, score) for index, name, score in scored if score >= _SMART_SCORE_THRESHOLD
    ]

    # Fall back to raw list when no calls meet the score threshold
    if not above_threshold:
        return call_names

    # Trim to the top-scoring calls when there are more than the maximum
    if len(above_threshold) > _SMART_MAX_CALLS:
        kept_indices = _top_indices_by_score(above_threshold, _SMART_MAX_CALLS)
        above_threshold = [
            (index, name, score) for index, name, score in above_threshold if index in kept_indices
        ]

    return [name for _index, name, _score in above_threshold]
