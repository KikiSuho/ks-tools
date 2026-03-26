"""Tests for trellis.pyast.analyzer module.

Covers AST parsing, node extraction (including guarded definitions),
class inheritance formatting, name visibility rules, function signature
formatting, decorator extraction, call extraction, and import extraction.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from trellis.pyast.analyzer import (
    extract_class_inheritance,
    extract_decorators,
    extract_imported_names,
    extract_top_level_calls,
    extract_top_level_nodes,
    format_function_signature,
    _get_attribute_name,
    is_name_hidden,
    parse_python_file,
)


def _parse_code(code: str) -> ast.Module:
    """Parse a code string into an AST module."""
    return ast.parse(textwrap.dedent(code))


def _get_func_node(code: str) -> ast.FunctionDef:
    """Extract the first function node from code."""
    tree = _parse_code(code)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise AssertionError("No function found in code")


# ---------------------------------------------------------------------------
# parse_python_file
# ---------------------------------------------------------------------------


def test_parse_python_file_raises_on_missing_file(tmp_path: Path) -> None:
    # Arrange
    missing_path = str(tmp_path / "nonexistent.py")

    # Act / Assert
    with pytest.raises(OSError, match="No such file"):
        parse_python_file(missing_path)


def test_parse_python_file_raises_on_syntax_error(tmp_path: Path) -> None:
    # Arrange
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def :\n", encoding="utf-8")

    # Act / Assert
    with pytest.raises(SyntaxError, match="invalid syntax"):
        parse_python_file(str(bad_file))


def test_parse_python_file_with_source_parameter(tmp_path: Path) -> None:
    # Arrange
    source_code = "x = 1\n"
    file_path = str(tmp_path / "example.py")
    (tmp_path / "example.py").write_text(source_code, encoding="utf-8")

    # Act
    tree = parse_python_file(file_path, source=source_code)

    # Assert
    classes, functions = extract_top_level_nodes(tree)
    assert classes == []
    assert functions == []


# ---------------------------------------------------------------------------
# extract_top_level_nodes
# ---------------------------------------------------------------------------


def test_extract_classes_and_functions() -> None:
    # Arrange
    tree = _parse_code("""
        class Foo:
            pass
        def bar():
            pass
        async def baz():
            pass
    """)

    # Act
    classes, functions = extract_top_level_nodes(tree)

    # Assert
    assert len(classes) == 1
    assert classes[0].name == "Foo"
    assert len(functions) == 2
    assert [func.name for func in functions] == ["bar", "baz"]


def test_extract_empty_module() -> None:
    # Arrange
    tree = _parse_code("")

    # Act
    classes, functions = extract_top_level_nodes(tree)

    # Assert
    assert classes == []
    assert functions == []


def test_nested_classes_not_extracted() -> None:
    # Arrange
    tree = _parse_code("""
        class Outer:
            class Inner:
                pass
    """)

    # Act
    classes, _functions = extract_top_level_nodes(tree)

    # Assert
    assert len(classes) == 1
    assert classes[0].name == "Outer"


def test_extract_excludes_main_guard() -> None:
    # Arrange
    tree = _parse_code("""
        def public():
            pass
        if __name__ == "__main__":
            def main_only():
                pass
    """)

    # Act
    _classes, functions = extract_top_level_nodes(tree)

    # Assert
    assert [func.name for func in functions] == ["public"]


def test_extract_if_guarded_definitions() -> None:
    # Arrange
    tree = _parse_code("""
        TYPE_CHECKING = False
        if TYPE_CHECKING:
            class TypeOnly:
                pass
        def always_present():
            pass
    """)

    # Act
    classes, functions = extract_top_level_nodes(tree)

    # Assert
    assert any(cls.name == "TypeOnly" for cls in classes)
    assert any(func.name == "always_present" for func in functions)


def test_extract_try_guarded_definitions() -> None:
    # Arrange
    tree = _parse_code("""
        try:
            from fast_lib import FastImpl as Impl
        except ImportError:
            class Impl:
                pass
    """)

    # Act
    classes, _functions = extract_top_level_nodes(tree)

    # Assert
    assert any(cls.name == "Impl" for cls in classes)


def test_extract_deduplicates_guarded_branches() -> None:
    # Arrange
    tree = _parse_code("""
        import sys
        if sys.platform == "win32":
            def platform_func():
                pass
        else:
            def platform_func():
                pass
    """)

    # Act
    _classes, functions = extract_top_level_nodes(tree)

    # Assert
    names = [func.name for func in functions]
    assert names.count("platform_func") == 1


# ---------------------------------------------------------------------------
# extract_class_inheritance
# ---------------------------------------------------------------------------


def test_no_inheritance_returns_empty_string() -> None:
    # Arrange
    tree = _parse_code("class Foo: pass")
    class_node = tree.body[0]

    # Act
    result = extract_class_inheritance(class_node)

    # Assert
    assert result == ""


def test_single_base_class() -> None:
    # Arrange
    tree = _parse_code("class Foo(Bar): pass")
    class_node = tree.body[0]

    # Act
    result = extract_class_inheritance(class_node)

    # Assert
    assert result == "(Bar)"


def test_multiple_base_classes() -> None:
    # Arrange
    tree = _parse_code("class Foo(Bar, Baz): pass")
    class_node = tree.body[0]

    # Act
    result = extract_class_inheritance(class_node)

    # Assert
    assert result == "(Bar, Baz)"


# ---------------------------------------------------------------------------
# _get_attribute_name
# ---------------------------------------------------------------------------


def test_simple_attribute() -> None:
    # Arrange
    tree = _parse_code("x = module.attr")
    assign_node = tree.body[0]
    attr_node = assign_node.value

    # Act
    result = _get_attribute_name(attr_node)

    # Assert
    assert result == "module.attr"


def test_nested_attribute() -> None:
    # Arrange
    tree = _parse_code("x = a.b.c")
    assign_node = tree.body[0]
    attr_node = assign_node.value

    # Act
    result = _get_attribute_name(attr_node)

    # Assert
    assert result == "a.b.c"


# ---------------------------------------------------------------------------
# is_name_hidden
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, show_private, show_mangled, show_dunder, is_expected_hidden",
    [
        pytest.param("public", False, False, False, False, id="public-visible"),
        pytest.param("_private", False, False, False, True, id="private-hidden"),
        pytest.param("_private", True, False, False, False, id="private-shown"),
        pytest.param("__mangled", False, False, False, True, id="mangled-hidden"),
        pytest.param("__mangled", False, True, False, False, id="mangled-shown"),
        pytest.param("__dunder__", False, False, False, True, id="dunder-hidden"),
        pytest.param("__dunder__", False, False, True, False, id="dunder-shown"),
    ],
)
def test_is_name_hidden(
    name: str,
    show_private: bool,
    show_mangled: bool,
    show_dunder: bool,
    is_expected_hidden: bool,
) -> None:
    # Arrange
    visibility_args = {
        "show_private": show_private,
        "show_mangled": show_mangled,
        "show_dunder": show_dunder,
    }

    # Act
    result = is_name_hidden(name, **visibility_args)

    # Assert
    assert result == is_expected_hidden


# ---------------------------------------------------------------------------
# format_function_signature
# ---------------------------------------------------------------------------


def test_simple_params() -> None:
    # Arrange
    func = _get_func_node("def foo(a, b): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "(a, b)"


def test_params_with_types() -> None:
    # Arrange
    func = _get_func_node("def foo(a: int, b: str): pass")

    # Act
    result = format_function_signature(func, include_types=True)

    # Assert
    assert result == "(a: int, b: str)"


def test_no_params() -> None:
    # Arrange
    func = _get_func_node("def foo(): pass")

    # Act
    result = format_function_signature(func)

    # Assert
    assert result == "()"


def test_self_param_stripped() -> None:
    # Arrange
    func = _get_func_node("def foo(self, x): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "(x)"


def test_kwargs() -> None:
    # Arrange
    func = _get_func_node("def foo(**kwargs): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "(**kwargs)"


def test_args_and_kwargs() -> None:
    # Arrange
    func = _get_func_node("def foo(*args, **kwargs): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "(*args, **kwargs)"


def test_keyword_only_params() -> None:
    # Arrange
    func = _get_func_node("def foo(a, *, b): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "(a, *, b)"


def test_positional_only_params() -> None:
    # Arrange
    func = _get_func_node("def foo(a, b, /, c): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "(a, b, /, c)"


def test_return_type_annotation() -> None:
    # Arrange
    func = _get_func_node("def foo(a: int) -> str: pass")

    # Act
    result = format_function_signature(
        func, include_types=True, include_return_type=True
    )

    # Assert
    assert result == "(a: int) -> str"


# ---------------------------------------------------------------------------
# self/cls stripping
# ---------------------------------------------------------------------------


def test_self_only_becomes_empty_parens() -> None:
    # Arrange
    func = _get_func_node("def stop(self): pass")

    # Act
    result = format_function_signature(func, include_types=False)

    # Assert
    assert result == "()"


def test_cls_stripped() -> None:
    # Arrange
    func = _get_func_node("def from_file(cls, path: str): pass")

    # Act
    result = format_function_signature(func, include_types=True)

    # Assert
    assert result == "(path: str)"


def test_staticmethod_no_self_unchanged() -> None:
    # Arrange
    func = _get_func_node("def validate(key: str): pass")

    # Act
    result = format_function_signature(func, include_types=True)

    # Assert
    assert result == "(key: str)"


def test_self_with_typed_params() -> None:
    # Arrange
    func = _get_func_node("def get(self, user_id: int) -> dict: pass")

    # Act
    result = format_function_signature(
        func, include_types=True, include_return_type=True
    )

    # Assert
    assert result == "(user_id: int) -> dict"


# ---------------------------------------------------------------------------
# return type annotations
# ---------------------------------------------------------------------------


def test_return_type_complex() -> None:
    # Arrange
    func = _get_func_node("def foo(x) -> dict[str, list[int]]: pass")

    # Act
    result = format_function_signature(
        func, include_types=True, include_return_type=True
    )

    # Assert
    assert result == "(x) -> dict[str, list[int]]"


def test_return_type_optional() -> None:
    # Arrange
    func = _get_func_node("def foo() -> Optional[str]: pass")

    # Act
    result = format_function_signature(
        func, include_types=True, include_return_type=True
    )

    # Assert
    assert result == "() -> Optional[str]"


def test_no_return_annotation_unchanged() -> None:
    # Arrange
    func = _get_func_node("def foo(x): pass")

    # Act
    result = format_function_signature(
        func, include_types=True, include_return_type=True
    )

    # Assert
    assert result == "(x)"


def test_return_type_not_shown_when_disabled() -> None:
    # Arrange
    func = _get_func_node("def foo() -> int: pass")

    # Act
    result = format_function_signature(func, include_return_type=False)

    # Assert
    assert result == "()"


# ---------------------------------------------------------------------------
# extract_decorators
# ---------------------------------------------------------------------------


def test_extract_simple_decorator() -> None:
    # Arrange
    tree = _parse_code("""
        @staticmethod
        def foo(): pass
    """)
    func_node = tree.body[0]

    # Act
    decorators = extract_decorators(func_node)

    # Assert
    assert len(decorators) == 1
    assert decorators[0].name == "staticmethod"
    assert decorators[0].raw_text == "@staticmethod"


def test_extract_call_decorator() -> None:
    # Arrange
    tree = _parse_code("""
        @app.route("/api", methods=["GET"])
        def handler(): pass
    """)
    func_node = tree.body[0]

    # Act
    decorators = extract_decorators(func_node)

    # Assert
    assert len(decorators) == 1
    assert decorators[0].name == "app.route"
    assert "'/api'" in decorators[0].arguments
    assert "methods" in decorators[0].keyword_arguments


def test_extract_attribute_decorator() -> None:
    # Arrange
    tree = _parse_code("""
        @app.route
        def handler(): pass
    """)
    func_node = tree.body[0]

    # Act
    decorators = extract_decorators(func_node)

    # Assert
    assert len(decorators) == 1
    assert decorators[0].name == "app.route"
    assert decorators[0].raw_text == "@app.route"


def test_extract_no_decorators() -> None:
    # Arrange
    tree = _parse_code("def foo(): pass")
    func_node = tree.body[0]

    # Act
    decorators = extract_decorators(func_node)

    # Assert
    assert decorators == []


def test_extract_multiple_decorators() -> None:
    # Arrange
    tree = _parse_code("""
        @staticmethod
        @lru_cache(maxsize=128)
        def foo(): pass
    """)
    func_node = tree.body[0]

    # Act
    decorators = extract_decorators(func_node)

    # Assert
    assert len(decorators) == 2
    assert decorators[0].name == "staticmethod"
    assert decorators[1].name == "lru_cache"


# ---------------------------------------------------------------------------
# extract_top_level_calls
# ---------------------------------------------------------------------------


def test_extract_bare_calls() -> None:
    # Arrange
    func = _get_func_node("""
        def main():
            setup()
            run()
    """)

    # Act
    calls = extract_top_level_calls(func)

    # Assert
    assert calls == ["setup", "run"]


def test_extract_assigned_calls() -> None:
    # Arrange
    func = _get_func_node("""
        def main():
            result = process()
    """)

    # Act
    calls = extract_top_level_calls(func)

    # Assert
    assert calls == ["process"]


def test_extract_return_call() -> None:
    # Arrange
    func = _get_func_node("""
        def main():
            return compute()
    """)

    # Act
    calls = extract_top_level_calls(func)

    # Assert
    assert calls == ["compute"]


def test_extract_await_call() -> None:
    # Arrange
    func = _get_func_node("""
        async def main():
            await fetch()
    """)

    # Act
    calls = extract_top_level_calls(func)

    # Assert
    assert calls == ["fetch"]


def test_ignores_nested_calls() -> None:
    # Arrange
    func = _get_func_node("""
        def main():
            setup()
            if True:
                nested_call()
    """)

    # Act
    calls = extract_top_level_calls(func)

    # Assert
    assert calls == ["setup"]


def test_empty_function_no_calls() -> None:
    # Arrange
    func = _get_func_node("def main(): pass")

    # Act
    calls = extract_top_level_calls(func)

    # Assert
    assert calls == []


# ---------------------------------------------------------------------------
# extract_imported_names
# ---------------------------------------------------------------------------


def test_extract_import_names() -> None:
    # Arrange
    tree = _parse_code("""
        import os
        from pathlib import Path
        import sys as system
    """)

    # Act
    names = extract_imported_names(tree)

    # Assert
    assert "os" in names
    assert "Path" in names
    assert "system" in names
    assert "sys" not in names


def test_extract_no_imports() -> None:
    # Arrange
    tree = _parse_code("x = 1")

    # Act
    names = extract_imported_names(tree)

    # Assert
    assert names == frozenset()
