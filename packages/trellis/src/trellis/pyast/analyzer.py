"""
AST analysis utilities for Python code structure extraction.

Provide reusable functions for parsing Python files, extracting class and
function definitions, formatting signatures with type annotations, extracting
decorator information, and applying name-based visibility filtering.

Constants
---------
FunctionNode : Type alias for ``ast.FunctionDef | ast.AsyncFunctionDef``.

Classes
-------
DecoratorInfo : Information about a decorator on a function or class.

Functions
---------
parse_python_file : Parse a Python file into an Abstract Syntax Tree.
extract_top_level_nodes : Extract top-level class and function definitions from an AST module.
extract_class_inheritance : Format class inheritance as a parenthesized string.
is_name_hidden : Check if a name should be hidden based on visibility rules.
format_function_signature : Format function parameters with optional type annotations.
extract_decorators : Extract decorator information from an AST function or class node.
extract_top_level_calls : Extract direct call names from the top-level body of a function.
extract_imported_names : Extract locally bound names from import statements in an AST module.

Examples
--------
>>> tree = parse_python_file(__file__)
>>> classes, functions = extract_top_level_nodes(tree)
>>> isinstance(classes, list) and isinstance(functions, list)
True

"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]


# ====================================== #
#             AST PARSING                #
# ====================================== #


@dataclass
class DecoratorInfo:
    """
    Information about a decorator on a function or class.

    Attributes
    ----------
    name : str
        Full dotted name of the decorator (e.g. ``"app.route"``,
        ``"staticmethod"``).
    arguments : list[str]
        Positional arguments as unparsed strings.
    keyword_arguments : dict[str, str]
        Keyword arguments as name-to-value string pairs.
    raw_text : str
        Full decorator text including the ``@`` prefix
        (e.g. ``"@app.route('/api/users', methods=['GET'])"``).

    """

    name: str
    arguments: list[str] = field(default_factory=list)
    keyword_arguments: dict[str, str] = field(default_factory=dict)
    raw_text: str = ""


def parse_python_file(file_path: str, source: Optional[str] = None) -> ast.Module:
    """
    Parse a Python file into an Abstract Syntax Tree.

    Parameters
    ----------
    file_path : str
        Path to the Python file to parse.
    source : str, optional
        Pre-read source text.  When provided the file is not read from
        disk, avoiding a redundant I/O round-trip.

    Returns
    -------
    ast.Module
        AST representation of the Python file.

    Raises
    ------
    OSError
        When the file cannot be read (only when *source* is None).
    SyntaxError
        When the file contains invalid Python syntax.

    """
    # Read the file from disk when no pre-read source is provided
    if source is None:
        with Path(file_path).open(encoding="utf-8") as source_file:
            source = source_file.read()
    return ast.parse(source, filename=file_path)


def _is_main_guard(node: ast.If) -> bool:
    """Check whether an ``if`` node is ``if __name__ == "__main__":``."""
    test = node.test
    # Reject nodes that are not comparison expressions
    if not isinstance(test, ast.Compare):
        return False
    # Reject when left side is not the __name__ identifier
    if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
        return False
    # Reject when comparison has more than one comparator
    if len(test.comparators) != 1:
        return False
    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value == "__main__"


def _collect_guarded_defs(
    stmts: list[ast.stmt],
) -> tuple[list[ast.ClassDef], list[FunctionNode]]:
    """Collect class and function definitions from a statement block."""
    classes = [node for node in stmts if isinstance(node, ast.ClassDef)]
    functions: list[FunctionNode] = [
        node for node in stmts if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return classes, functions


def _merge_guarded_blocks(
    blocks: list[list[ast.stmt]],
    class_nodes: list[ast.ClassDef],
    function_nodes: list[FunctionNode],
    seen_class_names: set[str],
    seen_func_names: set[str],
) -> None:
    """
    Merge unique class/function defs from guarded blocks into accumulator lists.

    Parameters
    ----------
    blocks : list[list[ast.stmt]]
        Statement blocks to scan for definitions.
    class_nodes : list[ast.ClassDef]
        Accumulator for class definitions (mutated in place).
    function_nodes : list[FunctionNode]
        Accumulator for function definitions (mutated in place).
    seen_class_names : set[str]
        Tracks already-seen class names to prevent duplicates.
    seen_func_names : set[str]
        Tracks already-seen function names to prevent duplicates.

    """
    # Extract and deduplicate definitions from each guarded block
    for block in blocks:
        classes, functions = _collect_guarded_defs(block)
        # Append class definitions not already seen
        for class_def in classes:
            # Skip duplicate class names across guarded branches
            if class_def.name not in seen_class_names:
                class_nodes.append(class_def)
                seen_class_names.add(class_def.name)
        # Append function definitions not already seen
        for func_def in functions:
            # Skip duplicate function names across guarded branches
            if func_def.name not in seen_func_names:
                function_nodes.append(func_def)
                seen_func_names.add(func_def.name)


def _collect_if_branches(node: ast.If) -> list[list[ast.stmt]]:
    """
    Collect all branches from an if/elif/else chain.

    Parameters
    ----------
    node : ast.If
        The top-level ``if`` node.

    Returns
    -------
    list[list[ast.stmt]]
        Statement blocks from each branch.

    """
    branches: list[list[ast.stmt]] = [node.body]
    else_block = node.orelse
    # Walk the elif chain by following single-element else blocks
    while else_block:
        branches.append(else_block)
        # Continue following the chain when the else contains a single elif
        if len(else_block) == 1 and isinstance(else_block[0], ast.If):
            else_block = else_block[0].orelse
        else:
            # Terminal else block or non-elif content; stop walking
            break
    return branches


def _collect_try_blocks(node: ast.stmt) -> Optional[list[list[ast.stmt]]]:
    """
    Collect statement blocks from a try or try/except* node.

    Parameters
    ----------
    node : ast.stmt
        An AST statement node.

    Returns
    -------
    list[list[ast.stmt]] or None
        Statement blocks if *node* is ``ast.Try`` or ``ast.TryStar``,
        otherwise ``None``.

    """
    # Collect all branches from a standard try/except/else/finally block
    if isinstance(node, ast.Try):
        blocks: list[list[ast.stmt]] = [node.body, node.orelse, node.finalbody]
        blocks.extend(handler.body for handler in node.handlers)
        return blocks
    # Collect handlers from try/except* (ExceptionGroup) on Python 3.11.
    # TryStar was merged back into Try in Python 3.12+.
    try_star_class_name = "TryStar"
    # Handle the TryStar node type when available on this Python version
    if hasattr(ast, try_star_class_name) and isinstance(node, getattr(ast, try_star_class_name)):
        blocks = [node.body, node.orelse]
        blocks.extend(handler.body for handler in node.handlers)
        return blocks
    return None


def extract_top_level_nodes(
    tree: ast.Module,
) -> tuple[list[ast.ClassDef], list[FunctionNode]]:
    """
    Extract top-level class and function definitions from an AST module.

    In addition to bare definitions, this function extracts definitions
    guarded by ``if`` and ``try`` blocks (e.g. ``if TYPE_CHECKING:``,
    ``try/except ImportError:``, platform checks).  Definitions inside
    ``if __name__ == "__main__":`` are excluded.  When both branches of
    a guard define the same name, only the first occurrence is kept.

    Parameters
    ----------
    tree : ast.Module
        AST module to extract nodes from.

    Returns
    -------
    tuple[list[ast.ClassDef], list[FunctionNode]]
        Tuple containing lists of class definition nodes and function
        definition nodes (including async functions).

    """
    class_nodes: list[ast.ClassDef] = []
    function_nodes: list[FunctionNode] = []
    seen_class_names: set[str] = set()
    seen_func_names: set[str] = set()

    # Categorize each top-level statement by node type
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            # Bare class definition at module level
            class_nodes.append(node)
            seen_class_names.add(node.name)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Bare function definition at module level
            function_nodes.append(node)
            seen_func_names.add(node.name)

        elif isinstance(node, ast.If) and not _is_main_guard(node):
            # Guarded definitions inside if/elif/else (e.g. TYPE_CHECKING)
            _merge_guarded_blocks(
                _collect_if_branches(node),
                class_nodes,
                function_nodes,
                seen_class_names,
                seen_func_names,
            )

        else:
            # Extract definitions guarded by try/except blocks when present
            try_blocks = _collect_try_blocks(node)
            # Merge guarded definitions when try blocks were found
            if try_blocks is not None:
                _merge_guarded_blocks(
                    try_blocks, class_nodes, function_nodes, seen_class_names, seen_func_names
                )

    return class_nodes, function_nodes


# ====================================== #
#        NAMING AND SIGNATURES           #
# ====================================== #


def extract_class_inheritance(class_node: ast.ClassDef) -> str:
    """
    Format class inheritance as a parenthesized string.

    Parameters
    ----------
    class_node : ast.ClassDef
        Class definition node to extract inheritance from.

    Returns
    -------
    str
        Formatted inheritance string (e.g. ``"(Parent1, Parent2)"``),
        or an empty string if the class has no base classes.

    """
    # Return empty when the class has no base classes
    if not class_node.bases:
        return ""

    base_names = [ast.unparse(base) for base in class_node.bases]
    return f"({', '.join(base_names)})"


def _get_attribute_name(attribute_node: ast.Attribute) -> str:
    """
    Recursively extract a full dotted attribute name from an AST node.

    Parameters
    ----------
    attribute_node : ast.Attribute
        An AST Attribute node to process.

    Returns
    -------
    str
        The full dotted attribute name (e.g. ``"module.submodule.attr"``).

    """
    # Resolve simple name.attr pattern directly
    if isinstance(attribute_node.value, ast.Name):
        return f"{attribute_node.value.id}.{attribute_node.attr}"
    # Recurse into nested attribute chains (a.b.c)
    if isinstance(attribute_node.value, ast.Attribute):
        return f"{_get_attribute_name(attribute_node.value)}.{attribute_node.attr}"
    return f"(...).{attribute_node.attr}"


def is_name_hidden(
    name: str,
    *,
    show_private: bool = False,
    show_mangled: bool = False,
    show_dunder: bool = False,
) -> bool:
    """
    Check if a name should be hidden based on visibility rules.

    Apply Python naming convention rules to determine whether a class,
    method, or function name should be excluded from output based on
    its prefix pattern.

    Parameters
    ----------
    name : str
        The name to check (class name, method name, or function name).
    show_private : bool, optional
        Whether to show private names (starting with ``_``).
        Default is False.
    show_mangled : bool, optional
        Whether to show name-mangled names (starting with ``__`` but not
        ending with ``__``). Default is False.
    show_dunder : bool, optional
        Whether to show dunder names (starting and ending with ``__``).
        Default is False.

    Returns
    -------
    bool
        True if the name should be hidden, False if it should be visible.

    """
    # Dunder names (__name__)
    if name.startswith("__") and name.endswith("__"):
        return not show_dunder

    # Name-mangled names (__name without trailing underscores)
    if name.startswith("__"):
        return not show_mangled

    # Private names (_name)
    if name.startswith("_"):
        return not show_private

    return False


def _format_single_param(
    arg_node: ast.arg,
    default_node: Optional[ast.expr],
    *,
    include_type: bool,
    include_default: bool,
    prefix: str = "",
) -> str:
    """
    Format a single function parameter with optional type and default.

    Parameters
    ----------
    arg_node : ast.arg
        The AST argument node.
    default_node : ast.expr or None
        The default value AST node, or None if no default.
    include_type : bool
        Whether to include the type annotation.
    include_default : bool
        Whether to include the default value.
    prefix : str, optional
        Prefix to prepend (e.g. ``"*"`` or ``"**"``). Default is ``""``.

    Returns
    -------
    str
        Formatted parameter string.

    """
    parts: list[str] = [f"{prefix}{arg_node.arg}"]

    # Append type annotation when requested and present
    if include_type and arg_node.annotation is not None:
        annotation_text = ast.unparse(arg_node.annotation)
        parts.append(f": {annotation_text}")

    # Append default value when requested and present
    if include_default and default_node is not None:
        default_text = ast.unparse(default_node)
        parts.append(f" = {default_text}")

    return "".join(parts)


def format_function_signature(
    func_node: FunctionNode,
    *,
    include_types: bool = True,
    include_return_type: bool = False,
    include_defaults: bool = False,
) -> str:
    """
    Format function parameters with optional type annotations.

    Build a formatted parameter string from an AST function definition node.
    Automatically strip ``self`` and ``cls`` receiver parameters. Support
    type annotations, default values, positional-only and keyword-only
    parameters, ``*args``, and ``**kwargs``.

    Parameters
    ----------
    func_node : ast.FunctionDef or ast.AsyncFunctionDef
        AST function definition node.
    include_types : bool, optional
        Whether to include type annotations. Default is True.
    include_return_type : bool, optional
        Whether to include the return type annotation. Default is False.
    include_defaults : bool, optional
        Whether to include default values. Default is False.

    Returns
    -------
    str
        Formatted parameter string in the form ``"(param1, param2, ...)"``,
        optionally followed by ``" -> ReturnType"``.

    """
    all_params = _build_param_list(func_node, include_types, include_defaults)
    signature = f"({', '.join(all_params)})"

    # Append return type annotation when requested and present
    if include_return_type and func_node.returns is not None:
        return_text = ast.unparse(func_node.returns)
        signature += f" -> {return_text}"

    return signature


def _collect_positional_params(
    args: ast.arguments,
    include_types: bool,
    include_defaults: bool,
) -> list[str]:
    """
    Collect positional-only and regular positional parameter strings.

    Parameters
    ----------
    args : ast.arguments
        The function's arguments node.
    include_types : bool
        Whether to include type annotations.
    include_defaults : bool
        Whether to include default values.

    Returns
    -------
    list[str]
        Formatted parameter strings including ``/`` separator if needed.

    """
    params: list[str] = []
    total_positional = len(args.posonlyargs) + len(args.args)
    defaults_offset = total_positional - len(args.defaults)

    # Append positional-only parameters that precede the / separator
    for index, arg_node in enumerate(args.posonlyargs):
        default_index = index - defaults_offset
        default_node = args.defaults[default_index] if default_index >= 0 else None
        params.append(
            _format_single_param(
                arg_node, default_node, include_type=include_types, include_default=include_defaults
            )
        )

    # Insert the positional-only separator when positional-only params exist
    if args.posonlyargs:
        params.append("/")

    # Append regular positional parameters; skip the self/cls receiver
    start_index = 1 if args.args and args.args[0].arg in ("self", "cls") else 0
    for index, arg_node in enumerate(args.args):
        # Skip the self/cls receiver parameter
        if index < start_index:
            continue
        default_index = index + len(args.posonlyargs) - defaults_offset
        default_node = args.defaults[default_index] if default_index >= 0 else None
        params.append(
            _format_single_param(
                arg_node, default_node, include_type=include_types, include_default=include_defaults
            )
        )

    return params


def _build_param_list(
    func_node: FunctionNode,
    include_types: bool,
    include_defaults: bool,
) -> list[str]:
    """
    Build the full list of formatted parameter strings.

    Parameters
    ----------
    func_node : ast.FunctionDef or ast.AsyncFunctionDef
        AST function definition node.
    include_types : bool
        Whether to include type annotations.
    include_defaults : bool
        Whether to include default values.

    Returns
    -------
    list[str]
        List of formatted parameter strings.

    """
    args = func_node.args
    params = _collect_positional_params(args, include_types, include_defaults)

    # Append the *args parameter when a variadic positional argument exists
    if args.vararg:
        # Format the *args parameter with its type annotation
        params.append(
            _format_single_param(
                args.vararg,
                None,
                include_type=include_types,
                include_default=False,
                prefix="*",
            )
        )
    elif args.kwonlyargs:
        # Insert bare * separator when there are keyword-only args but no *args
        params.append("*")

    # Append keyword-only parameters with their defaults
    for index, arg_node in enumerate(args.kwonlyargs):
        default_node = args.kw_defaults[index]
        params.append(
            _format_single_param(
                arg_node,
                default_node,
                include_type=include_types,
                include_default=include_defaults,
            )
        )

    # Append the **kwargs parameter when a variadic keyword argument exists
    if args.kwarg:
        params.append(
            _format_single_param(
                args.kwarg,
                None,
                include_type=include_types,
                include_default=False,
                prefix="**",
            )
        )

    return params


# ====================================== #
#       DECORATORS AND CALLS             #
# ====================================== #


def extract_decorators(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef],
) -> list[DecoratorInfo]:
    """
    Extract decorator information from an AST function or class node.

    Parameters
    ----------
    node : ast.FunctionDef or ast.AsyncFunctionDef or ast.ClassDef
        AST node to extract decorators from.

    Returns
    -------
    list[DecoratorInfo]
        List of decorator information objects, one per decorator.

    """
    decorators: list[DecoratorInfo] = []

    # Classify each decorator by its AST node type to extract name and arguments
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call):
            # Called decorator: @route("/api", methods=["GET"])
            name = ast.unparse(decorator.func)
            arguments = [ast.unparse(arg) for arg in decorator.args]
            keyword_arguments = {
                keyword.arg: ast.unparse(keyword.value)
                for keyword in decorator.keywords
                if keyword.arg is not None
            }
            raw_text = f"@{ast.unparse(decorator)}"
            decorators.append(
                DecoratorInfo(
                    name=name,
                    arguments=arguments,
                    keyword_arguments=keyword_arguments,
                    raw_text=raw_text,
                )
            )
        elif isinstance(decorator, ast.Attribute):
            # Dotted decorator without call: @app.route
            name = ast.unparse(decorator)
            decorators.append(
                DecoratorInfo(
                    name=name,
                    raw_text=f"@{name}",
                )
            )
        elif isinstance(decorator, ast.Name):
            # Simple name decorator: @staticmethod
            decorators.append(
                DecoratorInfo(
                    name=decorator.id,
                    raw_text=f"@{decorator.id}",
                )
            )
        else:
            # Fallback for complex expressions (subscripts, lambdas, etc.)
            raw = ast.unparse(decorator)
            decorators.append(
                DecoratorInfo(
                    name=raw,
                    raw_text=f"@{raw}",
                )
            )

    return decorators


def _resolve_call_name(call_node: ast.Call) -> Optional[str]:
    """
    Extract the function name from a Call node.

    Parameters
    ----------
    call_node : ast.Call
        The AST call node to extract the name from.

    Returns
    -------
    Optional[str]
        The function name, or None for computed calls that cannot
        be resolved to a simple name.

    """
    # Return the identifier directly for simple name calls
    if isinstance(call_node.func, ast.Name):
        return call_node.func.id
    # Return the attribute name for dotted calls (e.g. obj.method)
    if isinstance(call_node.func, ast.Attribute):
        return call_node.func.attr
    return None


def _unwrap_call(value_node: Optional[ast.expr]) -> Optional[ast.Call]:
    """
    Unwrap a value expression to find a direct Call node.

    Handles both direct calls and single-level ``await`` wrapping.

    Parameters
    ----------
    value_node : ast.expr or None
        The value expression from a statement.

    Returns
    -------
    Optional[ast.Call]
        The Call node if found, or None.

    """
    # Reject when no value expression exists
    if value_node is None:
        return None
    # Return direct call nodes as-is
    if isinstance(value_node, ast.Call):
        return value_node
    # Unwrap a single await layer to reach the inner call
    if isinstance(value_node, ast.Await) and isinstance(value_node.value, ast.Call):
        return value_node.value
    return None


def extract_top_level_calls(func_node: FunctionNode) -> list[str]:
    """
    Extract direct call names from the top-level body of a function.

    Iterate over the direct statements in ``func_node.body`` and extract
    function call names in source order.  Only immediate body statements
    are inspected; calls inside nested control flow (``if``, ``try``,
    ``for``, ``with``, etc.) are not included.

    Both sync and async call patterns are supported: bare calls,
    assignments with calls, annotated assignments with calls, and
    return statements with calls, each optionally wrapped in a single
    ``await``.

    Parameters
    ----------
    func_node : ast.FunctionDef or ast.AsyncFunctionDef
        The function node whose body is inspected.

    Returns
    -------
    list[str]
        Call names in source order.  Repeated calls are preserved.
        No filtering or deduplication is applied.

    """
    calls: list[str] = []

    # Walk direct body statements to extract call names in source order
    for statement in func_node.body:
        value_node: Optional[ast.expr] = None

        # Extract the value expression from statement types that can contain calls
        if isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Return)):
            value_node = statement.value

        call_node = _unwrap_call(value_node)
        # Resolve and collect the call name when a call node was found
        if call_node is not None:
            name = _resolve_call_name(call_node)
            # Append the resolved name when it is not a computed call
            if name is not None:
                calls.append(name)

    return calls


def extract_imported_names(tree: ast.Module) -> frozenset[str]:
    """
    Extract locally bound names from import statements in an AST module.

    Collects the names that import statements bind in the local
    namespace.  For ``import foo`` this is ``foo``; for
    ``from bar import baz`` this is ``baz``; aliases (``as``) use the
    alias name.

    Parameters
    ----------
    tree : ast.Module
        Parsed AST module to extract imports from.

    Returns
    -------
    frozenset[str]
        Set of locally bound import names.

    """
    names: list[str] = []

    # Collect bound names from all import statements in the module
    for node in tree.body:
        # Extract aliases from both import and from-import statements
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend(alias.asname or alias.name for alias in node.names)

    return frozenset(names)
