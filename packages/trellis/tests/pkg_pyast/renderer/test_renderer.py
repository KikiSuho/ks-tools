"""Tests for trellis.pyast.renderer module.

Covers RenderSettings, build_render_settings, and AstRenderer rendering
of Python files into tree-style output including visibility filtering,
decorator scaffolding, call flow, and wrapper collapsing.
"""

from __future__ import annotations

from pathlib import Path

from trellis.config import CallFlowMode, Config
from trellis.pyast.renderer import (
    AstRenderer,
    RenderSettings,
    build_render_settings,
)


def _make_render_settings(**overrides: object) -> RenderSettings:
    """Build a RenderSettings with sensible defaults."""
    defaults: dict[str, object] = {
        "show_params": True,
        "show_types": True,
        "show_decorators": False,
        "max_line_width": 100,
        "call_flow_mode": CallFlowMode.OFF,
    }
    defaults.update(overrides)
    return RenderSettings(**defaults)  # type: ignore[arg-type]


def _make_renderer(
    lines: list[str],
    show_private: bool = False,
    show_mangled: bool = False,
    show_dunder: bool = False,
    **settings_overrides: object,
) -> AstRenderer:
    """Build an AstRenderer with given settings."""
    settings = _make_render_settings(**settings_overrides)
    return AstRenderer(lines, show_private, show_mangled, show_dunder, settings)


def _render_source(
    tmp_path: Path,
    code: str,
    **renderer_overrides: object,
) -> str:
    """Write source to a temp file, render it, and return the output."""
    source_file = tmp_path / "example.py"
    source_file.write_text(code, encoding="utf-8")
    lines: list[str] = []
    show_private = renderer_overrides.pop("show_private", False)
    show_mangled = renderer_overrides.pop("show_mangled", False)
    show_dunder = renderer_overrides.pop("show_dunder", False)
    renderer = _make_renderer(
        lines,
        show_private=show_private,
        show_mangled=show_mangled,
        show_dunder=show_dunder,
        **renderer_overrides,
    )
    renderer.render_python_structure(str(source_file), prefix="", show_params=True)
    return "".join(lines)


# ---------------------------------------------------------------------------
# build_render_settings
# ---------------------------------------------------------------------------


def test_build_render_settings_captures_config_defaults() -> None:
    # Arrange
    expected_params = Config.SHOW_PARAMS

    # Act
    result = build_render_settings()

    # Assert
    assert result.show_params == expected_params


def test_build_render_settings_override_replaces_default() -> None:
    # Arrange
    custom_width = 120

    # Act
    result = build_render_settings(max_line_width=custom_width)

    # Assert
    assert result.max_line_width == custom_width


# ---------------------------------------------------------------------------
# AstRenderer.render_python_structure — basic rendering
# ---------------------------------------------------------------------------


def test_render_simple_function(tmp_path: Path) -> None:
    # Arrange
    code = "def hello(name: str) -> None:\n    pass\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def hello(name: str)" in output


def test_render_class_with_methods(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class MyClass:\n"
        "    def method_a(self) -> None:\n"
        "        pass\n"
        "    def method_b(self, x: int) -> int:\n"
        "        return x\n"
    )

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "class MyClass" in output
    assert "def method_a" in output
    assert "def method_b" in output


def test_render_class_inheritance(tmp_path: Path) -> None:
    # Arrange
    code = "class Child(Parent):\n    pass\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "class Child(Parent)" in output


def test_render_async_function(tmp_path: Path) -> None:
    # Arrange
    code = "async def fetch(url: str):\n    pass\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "async def fetch" in output


def test_render_nested_class(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class Outer:\n"
        "    def method(self) -> None:\n"
        "        pass\n"
        "    class Inner:\n"
        "        def nested_method(self) -> None:\n"
        "            pass\n"
    )

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "class Outer" in output
    assert "class Inner" in output
    assert "def nested_method" in output


def test_render_with_source_parameter(tmp_path: Path) -> None:
    # Arrange
    source_file = tmp_path / "example.py"
    source_code = "def hello() -> None:\n    pass\n"
    source_file.write_text(source_code, encoding="utf-8")
    lines: list[str] = []
    renderer = _make_renderer(lines)

    # Act
    renderer.render_python_structure(
        str(source_file), prefix="", show_params=True, source=source_code
    )

    # Assert
    output = "".join(lines)
    assert "def hello()" in output


# ---------------------------------------------------------------------------
# Visibility filtering
# ---------------------------------------------------------------------------


def test_render_hides_private_by_default(tmp_path: Path) -> None:
    # Arrange
    code = "def _private_func():\n    pass\ndef public_func():\n    pass\n"

    # Act
    output = _render_source(tmp_path, code, show_private=False)

    # Assert
    assert "_private_func" not in output
    assert "public_func" in output


def test_render_shows_private_when_enabled(tmp_path: Path) -> None:
    # Arrange
    code = "def _private_func():\n    pass\n"

    # Act
    output = _render_source(tmp_path, code, show_private=True)

    # Assert
    assert "_private_func" in output


def test_render_hides_dunder_by_default(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class Foo:\n"
        "    def __init__(self) -> None:\n"
        "        pass\n"
        "    def public(self) -> None:\n"
        "        pass\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_dunder=False)

    # Assert
    assert "__init__" not in output
    assert "def public" in output


def test_render_shows_dunder_when_enabled(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class Foo:\n"
        "    def __init__(self) -> None:\n"
        "        pass\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_dunder=True)

    # Assert
    assert "__init__" in output


def test_render_hides_mangled_by_default(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class Foo:\n"
        "    def __secret(self) -> None:\n"
        "        pass\n"
        "    def public(self) -> None:\n"
        "        pass\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_mangled=False)

    # Assert
    assert "__secret" not in output
    assert "def public" in output


def test_render_shows_mangled_when_enabled(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class Foo:\n"
        "    def __secret(self) -> None:\n"
        "        pass\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_mangled=True)

    # Assert
    assert "__secret" in output


def test_render_hides_params_when_disabled(tmp_path: Path) -> None:
    # Arrange
    code = "def func(a: int, b: str):\n    pass\n"
    source_file = tmp_path / "example.py"
    source_file.write_text(code, encoding="utf-8")
    lines: list[str] = []
    renderer = _make_renderer(lines)

    # Act
    renderer.render_python_structure(str(source_file), prefix="", show_params=False)

    # Assert
    output = "".join(lines)
    assert "def func" in output
    assert "(a: int" not in output


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_render_handles_syntax_error(tmp_path: Path) -> None:
    # Arrange
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def :\n", encoding="utf-8")
    lines: list[str] = []
    renderer = _make_renderer(lines)

    # Act
    renderer.render_python_structure(str(bad_file), prefix="", show_params=True)

    # Assert
    output = "".join(lines)
    assert "[Error reading file:" in output


def test_render_handles_missing_file(tmp_path: Path) -> None:
    # Arrange
    missing_path = str(tmp_path / "missing.py")
    lines: list[str] = []
    renderer = _make_renderer(lines)

    # Act
    renderer.render_python_structure(missing_path, prefix="", show_params=True)

    # Assert
    output = "".join(lines)
    assert "[Error reading file:" in output


# ---------------------------------------------------------------------------
# Decorator rendering
# ---------------------------------------------------------------------------


def test_render_with_decorators(tmp_path: Path) -> None:
    # Arrange
    code = "@staticmethod\ndef helper():\n    pass\n"

    # Act
    output = _render_source(tmp_path, code, show_decorators=True)

    # Assert
    assert "@staticmethod" in output
    assert "def helper" in output


def test_render_without_decorators(tmp_path: Path) -> None:
    # Arrange
    code = "@staticmethod\ndef helper():\n    pass\n"

    # Act
    output = _render_source(tmp_path, code, show_decorators=False)

    # Assert
    assert "@staticmethod" not in output
    assert "def helper" in output


def test_render_decorator_scaffolding_empty_returns_prefix_no_output() -> None:
    # Arrange
    lines: list[str] = []
    renderer = _make_renderer(lines)

    # Act
    child_prefix = renderer.render_decorator_scaffolding(
        [], prefix="", connector="\u251c\u2500\u2500 ", is_last_item=True
    )

    # Assert
    assert child_prefix != ""
    assert lines == []


# ---------------------------------------------------------------------------
# Return type annotations
# ---------------------------------------------------------------------------


def test_render_shows_return_type(tmp_path: Path) -> None:
    # Arrange
    code = "def greet(name: str) -> str:\n    return f'Hello {name}'\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def greet(name: str) -> str" in output


def test_render_no_return_type_when_absent(tmp_path: Path) -> None:
    # Arrange
    code = "def greet(name):\n    pass\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def greet(name)" in output
    assert "->" not in output


# ---------------------------------------------------------------------------
# Self/cls stripping
# ---------------------------------------------------------------------------


def test_render_strips_self_from_methods(tmp_path: Path) -> None:
    # Arrange
    code = "class Foo:\n    def bar(self, x: int) -> None:\n        pass\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def bar(x: int) -> None" in output
    assert "self" not in output


def test_render_strips_cls_from_classmethod(tmp_path: Path) -> None:
    # Arrange
    code = (
        "class Foo:\n"
        "    @classmethod\n"
        "    def create(cls, val: str) -> None:\n"
        "        pass\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_decorators=True)

    # Assert
    assert "def create(val: str) -> None" in output
    assert "cls" not in output


def test_render_self_only_method_empty_parens(tmp_path: Path) -> None:
    # Arrange
    code = "class Foo:\n    def stop(self) -> None:\n        pass\n"

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def stop() -> None" in output


# ---------------------------------------------------------------------------
# Wrapper collapsing
# ---------------------------------------------------------------------------


def test_collapse_wraps_decorated_pattern(tmp_path: Path) -> None:
    # Arrange
    code = (
        "from functools import wraps\n"
        "def require_auth(f):\n"
        "    @wraps(f)\n"
        "    def decorated(*args, **kwargs):\n"
        "        pass\n"
        "    return decorated\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_decorators=True)

    # Assert
    assert "/wrapper\\ def require_auth(f)" in output
    assert "decorated" not in output
    assert "@wraps" not in output


def test_collapse_wrapper_name_without_wraps_decorator(tmp_path: Path) -> None:
    # Arrange
    code = (
        "def my_decorator(f):\n"
        "    def wrapper(*args, **kwargs):\n"
        "        return f(*args, **kwargs)\n"
        "    return wrapper\n"
    )

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "/wrapper\\ def my_decorator(f)" in output
    assert "def wrapper" not in output


def test_collapse_two_level_decorator_factory(tmp_path: Path) -> None:
    # Arrange
    code = (
        "from functools import wraps\n"
        "def require_role(role):\n"
        "    def decorator(f):\n"
        "        @wraps(f)\n"
        "        def decorated(*args, **kwargs):\n"
        "            pass\n"
        "        return decorated\n"
        "    return decorator\n"
    )

    # Act
    output = _render_source(tmp_path, code, show_decorators=True)

    # Assert
    assert "def require_role(role)" in output
    assert "/wrapper\\ def decorator(f)" in output
    assert "decorated" not in output


def test_no_collapse_real_nested_functions(tmp_path: Path) -> None:
    # Arrange
    code = (
        "def create_app():\n"
        "    def health():\n"
        "        return 'ok'\n"
        "    def ready():\n"
        "        return 'ok'\n"
    )

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def create_app()" in output
    assert "def health()" in output
    assert "def ready()" in output
    assert "/wrapper\\" not in output


def test_no_collapse_non_wrapper_single_nested(tmp_path: Path) -> None:
    # Arrange
    code = (
        "def create_pipeline():\n"
        "    def stage_one(data):\n"
        "        pass\n"
    )

    # Act
    output = _render_source(tmp_path, code)

    # Assert
    assert "def create_pipeline()" in output
    assert "def stage_one(data)" in output
    assert "/wrapper\\" not in output


# ---------------------------------------------------------------------------
# Call flow rendering
# ---------------------------------------------------------------------------


def test_call_flow_smart_mode_emits_calls_line(tmp_path: Path) -> None:
    # Arrange
    code = (
        "from utils import process, validate\n"
        "def main():\n"
        "    process()\n"
        "    validate()\n"
    )

    # Act
    output = _render_source(tmp_path, code, call_flow_mode=CallFlowMode.SMART)

    # Assert
    assert "def main()" in output
    assert "calls:" in output


def test_call_flow_raw_mode_emits_calls_line(tmp_path: Path) -> None:
    # Arrange
    code = (
        "def run():\n"
        "    setup()\n"
        "    execute()\n"
    )

    # Act
    output = _render_source(tmp_path, code, call_flow_mode=CallFlowMode.RAW)

    # Assert
    assert "def run()" in output
    assert "calls:" in output


def test_call_flow_off_mode_no_calls_line(tmp_path: Path) -> None:
    # Arrange
    code = (
        "def main():\n"
        "    process()\n"
        "    validate()\n"
    )

    # Act
    output = _render_source(tmp_path, code, call_flow_mode=CallFlowMode.OFF)

    # Assert
    assert "def main()" in output
    assert "calls:" not in output


def test_call_flow_non_orchestration_function_no_calls(tmp_path: Path) -> None:
    # Arrange
    code = (
        "def helper():\n"
        "    process()\n"
        "    validate()\n"
    )

    # Act
    output = _render_source(tmp_path, code, call_flow_mode=CallFlowMode.SMART)

    # Assert
    assert "def helper()" in output
    assert "calls:" not in output
