"""
Tree connector symbol utilities for directory and AST tree rendering.

Functions
---------
get_tree_connectors : Return the connector symbol and next prefix for a tree item.

Examples
--------
>>> connector, child_prefix = get_tree_connectors("", is_last_item=True)
>>> connector
'└── '
>>> child_prefix
'    '

"""

from __future__ import annotations


def get_tree_connectors(prefix: str, is_last_item: bool) -> tuple[str, str]:
    """
    Get tree connector symbols based on item position.

    Parameters
    ----------
    prefix : str
        Current prefix string.
    is_last_item : bool
        Whether this is the last item in the list.

    Returns
    -------
    tuple[str, str]
        Tuple of ``(connector, next_prefix)`` where ``connector`` is the
        branch symbol (``"└── "`` or ``"├── "``) and ``next_prefix`` is
        the prefix string to pass to children of this item.

    """
    connector = "└── " if is_last_item else "├── "
    next_prefix = prefix + ("    " if is_last_item else "│   ")
    return connector, next_prefix
