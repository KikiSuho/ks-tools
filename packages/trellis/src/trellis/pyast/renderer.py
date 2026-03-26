"""
AST-based Python code structure rendering.

Render Python class and function definitions into tree-style text
using AST analysis.  All rendering state is encapsulated in the
``AstRenderer`` class so that the directory scanner delegates
rendering without owning any AST logic.

Classes
-------
AstRenderer : Render Python AST nodes into tree-style structure lines.
OutputSink : Protocol for line-oriented output targets used by AstRenderer.
RenderSettings : Immutable snapshot of rendering-related configuration.

Functions
---------
build_render_settings : Create a RenderSettings snapshot from the current Config state.

Examples
--------
>>> settings = build_render_settings(show_types=True, show_decorators=False)
>>> settings.show_types
True
>>> settings.show_decorators
False

"""

from __future__ import annotations

import ast
from typing import NamedTuple, Optional, Protocol

from trellis.config import CallFlowMode, Config, _or_default
from trellis.pyast.analyzer import (
    DecoratorInfo,
    FunctionNode,
    extract_class_inheritance,
    extract_decorators,
    extract_imported_names,
    extract_top_level_calls,
    extract_top_level_nodes,
    format_function_signature,
    is_name_hidden,
    parse_python_file,
)
from trellis.pyast.call_flow import (
    ORCHESTRATION_NAMES,
    filter_smart_calls,
    format_call_flow_line,
)
from trellis.pyast.tree_drawing import get_tree_connectors as _get_tree_connectors

# ====================================== #
#          RENDERING SETTINGS            #
# ====================================== #


class OutputSink(Protocol):
    """
    Protocol for line-oriented output targets used by ``AstRenderer``.

    Any object that supports appending lines and indexed access to the
    last appended line satisfies this protocol. ``list[str]`` is the
    canonical implementation.
    """

    def append(self, line: str) -> None: ...  # noqa: D102
    def __len__(self) -> int: ...  # noqa: D105
    def __getitem__(self, index: int) -> str: ...  # noqa: D105
    def __setitem__(self, index: int, value: str) -> None: ...  # noqa: D105


class RenderSettings(NamedTuple):
    """
    Immutable snapshot of rendering-related configuration.

    Attributes
    ----------
    show_params : bool
        Whether to include function parameters in the output.
    show_types : bool
        Whether to include type annotations on parameters.
    show_decorators : bool
        Whether to show decorators on functions and classes.
    max_line_width : int
        Target maximum output line width for call flow truncation.
    call_flow_mode : CallFlowMode
        Call flow display mode for orchestration functions.

    """

    show_params: bool
    show_types: bool
    show_decorators: bool
    max_line_width: int
    call_flow_mode: CallFlowMode


def build_render_settings(
    *,
    show_types: Optional[bool] = None,
    show_decorators: Optional[bool] = None,
    call_flow_mode: Optional[CallFlowMode] = None,
    show_params: Optional[bool] = None,
    max_line_width: Optional[int] = None,
) -> RenderSettings:
    """
    Create a RenderSettings snapshot.

    When a parameter is ``None`` (the default), the current ``Config``
    class attribute is read at call time.

    Parameters
    ----------
    show_types : bool or None
        Whether to include type annotations on parameters.
    show_decorators : bool or None
        Whether to show decorators on functions and classes.
    call_flow_mode : CallFlowMode or None
        Call flow display mode for orchestration functions.
    show_params : bool or None
        Whether to include function parameters in the output.
    max_line_width : int or None
        Target maximum output line width for call flow truncation.

    Returns
    -------
    RenderSettings
        Immutable snapshot of rendering-related configuration values.

    """
    return RenderSettings(
        show_params=_or_default(show_params, Config.SHOW_PARAMS),
        show_types=_or_default(show_types, Config.SHOW_TYPES),
        show_decorators=_or_default(show_decorators, Config.SHOW_DECORATORS),
        max_line_width=_or_default(max_line_width, Config.MAX_LINE_WIDTH),
        call_flow_mode=_or_default(call_flow_mode, Config.CALL_FLOW_MODE),
    )


# ====================================== #
#             AST RENDERER               #
# ====================================== #


class AstRenderer:
    """
    Render Python AST nodes into tree-style structure lines.

    All rendering operates on an ``OutputSink`` provided at construction.
    The renderer does not own the sink; the caller retains ownership.

    Parameters
    ----------
    output : OutputSink
        Line-oriented output target to which rendered lines are appended.
    show_private : bool
        Whether to include private methods.
    show_mangled : bool
        Whether to include name-mangled methods.
    show_dunder : bool
        Whether to include dunder methods.
    settings : RenderSettings
        Immutable rendering configuration snapshot.

    """

    def __init__(  # noqa: D107
        self,
        output: OutputSink,
        show_private: bool,
        show_mangled: bool,
        show_dunder: bool,
        settings: RenderSettings,
    ) -> None:
        self._output: OutputSink = output
        self._show_private: bool = show_private
        self._show_mangled: bool = show_mangled
        self._show_dunder: bool = show_dunder
        self._settings: RenderSettings = settings

    def render_python_structure(
        self,
        file_path: str,
        prefix: str,
        show_params: bool,
        source: Optional[str] = None,
    ) -> None:
        """
        Extract class and function names from a Python file using AST.

        Parameters
        ----------
        file_path : str
            Path to the Python file to analyze.
        prefix : str
            Current indentation prefix for the tree visualization.
        show_params : bool
            Whether to include function parameters in the output.
        source : str, optional
            Pre-read source text to avoid re-reading the file from disk.

        """
        # Parse and render the file's AST; catch all read/parse failures gracefully
        try:
            tree = parse_python_file(file_path, source=source)
            class_nodes, function_nodes = extract_top_level_nodes(tree)

            visible_class_nodes = [
                class_node
                for class_node in class_nodes
                if not self._is_name_hidden(class_node.name)
            ]
            visible_functions = self._filter_methods(function_nodes)

            self._process_classes(visible_class_nodes, visible_functions, prefix, show_params)

            # Only compute call-flow data when call flow is active
            if self._settings.call_flow_mode != CallFlowMode.OFF:
                all_function_names = frozenset(func.name for func in function_nodes)
                imported_names = extract_imported_names(tree)
            else:
                # Provide empty collections when call flow is disabled
                all_function_names = frozenset()
                imported_names = frozenset()

            self._process_functions(
                visible_functions, prefix, show_params, all_function_names, imported_names
            )

        except (OSError, UnicodeDecodeError, SyntaxError) as file_read_error:
            # Record read/parse failure inline so the tree continues for other files
            self._output.append(f"{prefix}└── [Error reading file: {file_read_error}]\n")

    def _process_classes(
        self,
        class_nodes: list[ast.ClassDef],
        function_nodes: list[FunctionNode],
        prefix: str,
        show_params: bool,
    ) -> None:
        """
        Process class definitions found in the AST.

        Parameters
        ----------
        class_nodes : list[ast.ClassDef]
            List of visible class definition nodes to process.
        function_nodes : list[FunctionNode]
            List of visible function nodes (used to determine if a class
            is the last item).
        prefix : str
            Current indentation prefix.
        show_params : bool
            Whether to show function parameters.

        """
        # Render each class with its inheritance, decorators, and members
        for class_index, class_node in enumerate(class_nodes):
            is_last_class = class_index == len(class_nodes) - 1 and len(function_nodes) == 0
            class_connector, class_prefix = _get_tree_connectors(prefix, is_last_class)

            inheritance = extract_class_inheritance(class_node)
            decorators = extract_decorators(class_node) if self._settings.show_decorators else []

            # Choose rendering path based on whether decorators are present
            if decorators:
                # Render decorator scaffolding with class definition as child node
                self._render_decorated_class(
                    class_node,
                    inheritance,
                    decorators,
                    prefix,
                    class_connector,
                    is_last_class,
                    show_params,
                )
            else:
                # Render class directly and process its members
                self._add_class_to_structure(class_node, inheritance, prefix, class_connector)
                self._process_class_members(class_node, class_prefix, show_params)

    def _add_class_to_structure(
        self, class_node: ast.ClassDef, inheritance: str, prefix: str, connector: str
    ) -> None:
        """
        Add a class definition to the structure output.

        Parameters
        ----------
        class_node : ast.ClassDef
            Class node to add to structure.
        inheritance : str
            Inheritance string to append to class name.
        prefix : str
            Current line prefix.
        connector : str
            Tree connector symbol to use.

        """
        self._output.append(
            f"{prefix}{connector}class {class_node.name}{inheritance}  :{class_node.lineno}\n"
        )

    def render_decorator_scaffolding(
        self,
        decorators: list[DecoratorInfo],
        prefix: str,
        connector: str,
        is_last_item: bool,
    ) -> str:
        """
        Render decorator scaffolding and return the child prefix.

        Parameters
        ----------
        decorators : list[DecoratorInfo]
            List of decorator information objects.
        prefix : str
            Current line prefix.
        connector : str
            Tree connector symbol for the first decorator.
        is_last_item : bool
            Whether this is the last item at this level.

        Returns
        -------
        str
            The child prefix for rendering the definition node.

        """
        _, child_prefix = _get_tree_connectors(prefix, is_last_item)
        # Return early when there are no decorators to scaffold
        if not decorators:
            return child_prefix
        self._output.append(f"{prefix}{connector}{decorators[0].raw_text}\n")
        # Append remaining decorators as sibling lines under the child prefix
        for decorator_info in decorators[1:]:
            self._output.append(f"{child_prefix}{decorator_info.raw_text}\n")
        return child_prefix

    def _render_decorated_class(
        self,
        class_node: ast.ClassDef,
        inheritance: str,
        decorators: list[DecoratorInfo],
        prefix: str,
        connector: str,
        is_last_item: bool,
        show_params: bool,
    ) -> None:
        """
        Render a class with decorators using nested child style.

        Parameters
        ----------
        class_node : ast.ClassDef
            Class definition node.
        inheritance : str
            Inheritance string to append to class name.
        decorators : list[DecoratorInfo]
            List of decorator information objects.
        prefix : str
            Current line prefix.
        connector : str
            Tree connector symbol for the first decorator.
        is_last_item : bool
            Whether this is the last item at this level.
        show_params : bool
            Whether to show function parameters.

        """
        child_prefix = self.render_decorator_scaffolding(
            decorators,
            prefix,
            connector,
            is_last_item,
        )
        class_line = (
            f"{child_prefix}└── class {class_node.name}{inheritance}  :{class_node.lineno}\n"
        )
        self._output.append(class_line)
        class_member_prefix = child_prefix + "    "
        self._process_class_members(class_node, class_member_prefix, show_params)

    def _render_decorated_function(
        self,
        func_node: FunctionNode,
        decorators: list[DecoratorInfo],
        prefix: str,
        connector: str,
        is_last_item: bool,
        show_params: bool,
    ) -> str:
        """
        Render a function with decorators using nested child style.

        Parameters
        ----------
        func_node : ast.FunctionDef or ast.AsyncFunctionDef
            Function definition node.
        decorators : list[DecoratorInfo]
            List of decorator information objects.
        prefix : str
            Current line prefix.
        connector : str
            Tree connector symbol for the first decorator.
        is_last_item : bool
            Whether this is the last item at this level.
        show_params : bool
            Whether to show function parameters.

        Returns
        -------
        str
            The child prefix used for rendering nested content.

        """
        child_prefix = self.render_decorator_scaffolding(
            decorators,
            prefix,
            connector,
            is_last_item,
        )
        self._append_function_line(func_node, child_prefix, "└── ", show_params)
        return child_prefix

    def _is_name_hidden(self, name: str) -> bool:
        """
        Check whether a name should be hidden based on visibility settings.

        Parameters
        ----------
        name : str
            Name to check.

        Returns
        -------
        bool
            True if the name should be hidden, False if visible.

        """
        return is_name_hidden(
            name,
            show_private=self._show_private,
            show_mangled=self._show_mangled,
            show_dunder=self._show_dunder,
        )

    def _filter_methods(self, method_nodes: list[FunctionNode]) -> list[FunctionNode]:
        """
        Filter methods based on visibility settings.

        Parameters
        ----------
        method_nodes : list[FunctionNode]
            List of method nodes to filter.

        Returns
        -------
        list[FunctionNode]
            List of method nodes that pass the filtering criteria.

        """
        return [method for method in method_nodes if not self._is_name_hidden(method.name)]

    def _render_visible_methods(
        self,
        visible_methods: list[FunctionNode],
        prefix: str,
        show_params: bool,
        has_nested_classes: bool,
    ) -> None:
        """
        Render filtered methods into the structure output.

        Parameters
        ----------
        visible_methods : list[FunctionNode]
            Methods that passed visibility filtering.
        prefix : str
            Current indentation prefix.
        show_params : bool
            Whether to include function parameters in the output.
        has_nested_classes : bool
            Whether the class has nested classes after these methods.

        """
        # Render each visible method with optional decorator scaffolding
        for method_index, method_node in enumerate(visible_methods):
            is_last_item = method_index == len(visible_methods) - 1 and not has_nested_classes
            method_connector, _ = _get_tree_connectors(prefix, is_last_item)

            decorators = extract_decorators(method_node) if self._settings.show_decorators else []
            # Choose rendering path based on whether decorators are present
            if decorators:
                # Render method with decorator scaffolding
                self._render_decorated_function(
                    method_node,
                    decorators,
                    prefix,
                    method_connector,
                    is_last_item,
                    show_params,
                )
            else:
                # Render method definition directly
                self._append_function_line(method_node, prefix, method_connector, show_params)

    def _render_nested_classes(
        self,
        nested_classes: list[ast.ClassDef],
        prefix: str,
        show_params: bool,
    ) -> None:
        """
        Render nested class definitions into the structure output.

        Parameters
        ----------
        nested_classes : list[ast.ClassDef]
            Nested class definition nodes to render.
        prefix : str
            Current indentation prefix.
        show_params : bool
            Whether to include function parameters in the output.

        """
        # Render each nested class definition with its own members
        for nested_index, nested_class in enumerate(nested_classes):
            is_last_nested = nested_index == len(nested_classes) - 1
            nested_connector, nested_prefix = _get_tree_connectors(prefix, is_last_nested)

            self._output.append(
                f"{prefix}{nested_connector}class {nested_class.name}  :{nested_class.lineno}\n"
            )
            self._process_class_members(nested_class, nested_prefix, show_params)

    def _process_class_members(
        self, class_node: ast.ClassDef, prefix: str, show_params: bool
    ) -> None:
        """
        Process class members (methods and nested classes).

        Parameters
        ----------
        class_node : ast.ClassDef
            The AST class definition node to process.
        prefix : str
            The prefix to use for indentation.
        show_params : bool
            Whether to include function parameters in the output.

        """
        method_nodes: list[FunctionNode] = []
        all_nested_classes: list[ast.ClassDef] = []
        # Partition class body into methods and nested class definitions
        for node in class_node.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Collect function/method definitions
                method_nodes.append(node)
            elif isinstance(node, ast.ClassDef):
                # Collect nested class definitions
                all_nested_classes.append(node)

        visible_methods = self._filter_methods(method_nodes)
        nested_classes = [
            nested_class
            for nested_class in all_nested_classes
            if not self._is_name_hidden(nested_class.name)
        ]

        self._render_visible_methods(visible_methods, prefix, show_params, bool(nested_classes))
        self._render_nested_classes(nested_classes, prefix, show_params)

    _WRAPPER_NAMES: frozenset[str] = frozenset({"decorated", "wrapper", "inner", "wrapped"})

    def _is_wrapper_chain(self, nested_functions: list[FunctionNode]) -> bool:
        """
        Detect whether nested functions are purely decorator wrapper boilerplate.

        A wrapper chain is detected when:
        1. There is exactly one visible nested function.
        2. That function's name is a known wrapper name *or* it has a
           ``@wraps(...)`` decorator.
        3. Its own visible children (if any) also satisfy these rules
           recursively.

        Parameters
        ----------
        nested_functions : list[FunctionNode]
            Visible nested function nodes to evaluate.

        Returns
        -------
        bool
            True if the entire nesting is wrapper boilerplate.

        """
        # Require exactly one visible nested function to be a wrapper chain
        if len(nested_functions) != 1:
            return False

        nested_func = nested_functions[0]
        is_name_match = nested_func.name in self._WRAPPER_NAMES
        has_wraps = any(
            decorator.name in ("wraps", "functools.wraps")
            for decorator in extract_decorators(nested_func)
        )
        # Reject when the name is not a known wrapper and has no @wraps decorator
        if not is_name_match and not has_wraps:
            return False

        inner_nested = [
            node
            for node in nested_func.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        visible_inner = self._filter_methods(inner_nested)
        # Accept as wrapper when no further nesting exists to check
        if not visible_inner:
            return True
        return self._is_wrapper_chain(visible_inner)

    def _should_collapse_nested(self, visible_nested: list[FunctionNode]) -> bool:
        """Determine if nested functions are wrapper boilerplate and should be collapsed."""
        return bool(visible_nested) and self._is_wrapper_chain(visible_nested)

    def _tag_last_line_as_wrapper(self) -> None:
        r"""Prepend a ``/wrapper\`` tag to the last appended function line."""
        # Guard against empty structure when called before any lines are appended
        if not self._output:
            return
        last = self._output[-1]
        # Find the def/async def keyword and insert /wrapper\ before it
        for keyword in ("async def ", "def "):
            keyword_pos = last.find(keyword)
            # Insert the wrapper tag at the keyword position when found
            if keyword_pos != -1:
                self._output[-1] = last[:keyword_pos] + "/wrapper\\ " + last[keyword_pos:]
                return

    def _append_function_line(
        self,
        func_node: FunctionNode,
        prefix: str,
        connector: str,
        show_params: bool,
    ) -> None:
        """Append a single function definition line to the structure."""
        async_prefix = "async " if isinstance(func_node, ast.AsyncFunctionDef) else ""
        params = self._get_function_params(func_node) if show_params else ""
        self._output.append(
            f"{prefix}{connector}{async_prefix}def {func_node.name}{params}  :{func_node.lineno}\n"
        )

    def _process_functions(
        self,
        function_nodes: list[FunctionNode],
        prefix: str,
        show_params: bool,
        sibling_names: frozenset[str] = frozenset(),
        imported_names: frozenset[str] = frozenset(),
    ) -> None:
        """
        Process standalone functions with optional call flow summaries.

        When call flow mode is ``RAW`` or ``SMART``, orchestration-style
        functions (those whose names appear in ``ORCHESTRATION_NAMES``)
        receive a compact ``calls:`` child line.  In ``SMART`` mode the
        call list is scored and filtered for high-signal calls.

        Parameters
        ----------
        function_nodes : list[FunctionNode]
            List of AST function definition nodes to process.
        prefix : str
            The prefix to use for indentation.
        show_params : bool
            Whether to include function parameters in the output.
        sibling_names : frozenset[str]
            Names of all top-level functions in the same file, used
            for SMART mode same-file scoring.
        imported_names : frozenset[str]
            Names bound by import statements in the same file, used
            for SMART mode imported-name scoring.

        """
        call_flow_mode = self._settings.call_flow_mode

        # Render each function with decorators, call flow, and nested children
        for func_index, func_node in enumerate(function_nodes):
            is_last_item = func_index == len(function_nodes) - 1
            func_connector, func_next_prefix = _get_tree_connectors(prefix, is_last_item)

            decorators = extract_decorators(func_node) if self._settings.show_decorators else []

            # Choose rendering path based on whether decorators are present
            if decorators:
                # Render function with decorator scaffolding
                child_prefix = self._render_decorated_function(
                    func_node, decorators, prefix, func_connector, is_last_item, show_params
                )
                children_prefix = child_prefix + "    "
            else:
                # Render function definition directly
                self._append_function_line(func_node, prefix, func_connector, show_params)
                children_prefix = func_next_prefix

            # Extract nested function definitions from the function body.
            nested_functions = [
                node
                for node in func_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            visible_nested = self._filter_methods(nested_functions)

            # Tag wrapper boilerplate and suppress nested children
            if self._should_collapse_nested(visible_nested):
                self._tag_last_line_as_wrapper()
                visible_nested = []

            self._emit_call_flow(
                func_node,
                children_prefix,
                call_flow_mode,
                sibling_names,
                imported_names,
                has_following_siblings=bool(visible_nested),
            )

            # Recurse into visible nested functions with their own call flow context
            if visible_nested:
                nested_names = frozenset(node.name for node in nested_functions)
                self._process_functions(
                    visible_nested, children_prefix, show_params, nested_names, imported_names
                )

    def _emit_call_flow(
        self,
        func_node: FunctionNode,
        calls_prefix: str,
        call_flow_mode: CallFlowMode,
        sibling_names: frozenset[str],
        imported_names: frozenset[str],
        has_following_siblings: bool = False,
    ) -> None:
        """
        Emit a call flow summary line for orchestration-style functions.

        Parameters
        ----------
        func_node : ast.FunctionDef or ast.AsyncFunctionDef
            The function node to inspect for calls.
        calls_prefix : str
            Tree prefix for the calls line.
        call_flow_mode : CallFlowMode
            Current call flow display mode.
        sibling_names : frozenset[str]
            Names of other top-level functions in the same file.
        imported_names : frozenset[str]
            Names bound by import statements in the same file.
        has_following_siblings : bool
            Whether sibling nodes (e.g. nested functions) follow this line.
            When True, uses ``├──`` instead of ``└──``.

        """
        # Skip call flow entirely when disabled
        if call_flow_mode == CallFlowMode.OFF:
            return
        # Only emit call flow for orchestration-style function names
        if func_node.name not in ORCHESTRATION_NAMES:
            return
        call_names = extract_top_level_calls(func_node)
        # Skip when the function body contains no calls
        if not call_names:
            return
        # Apply scoring and filtering in SMART mode; use full width in RAW mode
        if call_flow_mode == CallFlowMode.SMART:
            # Score calls and retain only high-signal orchestration targets
            call_names = filter_smart_calls(
                call_names, sibling_names, imported_names, self._is_name_hidden
            )
            max_width_for_smart = 0
        else:
            # RAW mode shows all calls with line-width truncation
            max_width_for_smart = self._settings.max_line_width
        connector = "├── " if has_following_siblings else "└── "
        calls_line = format_call_flow_line(call_names, calls_prefix, max_width_for_smart, connector)
        self._output.append(f"{calls_line}\n")

    def _get_function_params(self, func_node: FunctionNode) -> str:
        """
        Extract function parameters as a string.

        Parameters
        ----------
        func_node : ast.FunctionDef or ast.AsyncFunctionDef
            AST function definition node.

        Returns
        -------
        str
            Formatted parameter string in the form ``(param1, param2, ...)``,
            optionally followed by ``" -> ReturnType"``.

        """
        return format_function_signature(
            func_node,
            include_types=self._settings.show_types,
            include_return_type=True,
        )
