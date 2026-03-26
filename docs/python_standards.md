# Python Standards

Hard rules for all Python projects. No exceptions, no interpretation.

---

## Formatting

- 4 spaces for indentation. Never tabs.
- 100 characters max line length, measured from column 0.
- `snake_case` for functions, methods, and variables.
- `CamelCase` for classes.
- `UPPER_SNAKE_CASE` for constants.
- No trailing whitespace on any line, including blank lines.

### Section Headers

Files with multiple logical sections use centered box headers to separate them. A logical section is a group of definitions that serves a distinct purpose within the module. Closely related classes or functions that share a single purpose do not constitute separate sections.

```python
# ====================================== #
#           SECTION NAME                 #
# ====================================== #
```

- 40 characters wide: `# ` + 36 `=` + ` #`.
- Label is uppercase, centered within the box.
- Module-level only. Never inside a class or function.

### Magic Numbers

No magic numbers. Every literal number used in logic gets a named constant. The only exception is arithmetic adjustments within an expression where the number is part of the calculation, not a standalone value.

```python
# Do
MAX_RETRIES = 3
CONNECTION_TIMEOUT = 30
HEADER_LINES = 2

for attempt in range(MAX_RETRIES):
    connect(timeout=CONNECTION_TIMEOUT)

# Arithmetic adjustments are acceptable inline
last_index = len(items) - 1
zero_based = line_number - 1

# Do not
for attempt in range(3):
    connect(timeout=30)
```

### Boolean Naming

Boolean variables used in logic and boolean-returning functions must use `is_`, `has_`, `can_`, or `should_` prefix.

```python
# Do
is_valid = check_format(data)
has_permission = user.check_access("read")
can_retry = attempt < MAX_RETRIES

def is_available(self) -> bool:
    ...

def has_dependencies(self) -> bool:
    ...

# Do not
valid = check_format(data)
permission = user.check_access("read")
retry = attempt < MAX_RETRIES

def check_available(self) -> bool:
    ...
```

User-facing configuration booleans (CLI flags, config fields, constructor parameters that control features) use descriptive verb phrases instead. The name describes what the setting controls, not the state it represents.

```python
# Do — configuration booleans describe the feature they control
show_private: bool = False
show_types: bool = True
create_log: bool = True
enable_strict: bool = False
include_decorators: bool = True

# Do not — prefix adds noise without clarity in config contexts
is_show_private: bool = False
should_show_types: bool = True
has_create_log: bool = True
```

### Variable Naming

Every variable name describes its purpose. No single-letter variables. The only exception is `_` for explicitly unused values in unpacking or iteration.

```python
# Do
for index, tool in enumerate(tools):
    print(f"{index}: {tool.name}")

for key, value in config_pairs.items():
    resolved[key] = value

_, extension = os.path.splitext(filename)

for _ in range(MAX_RETRIES):
    retry_connection()

# Do not
for i, t in enumerate(tools):
    print(f"{i}: {t.name}")

for k, v in config_pairs.items():
    resolved[k] = v
```

### Exception Variable Naming

Exception variables describe the context of what went wrong, not the exception type. The type is already in the `except` clause.

```python
# Do
except FileNotFoundError as missing_config:
    log_error(missing_config)

except TimeoutError as tool_execution_timeout:
    raise CQError("Tool did not respond") from tool_execution_timeout

except PermissionError as log_dir_access:
    raise CQError("Cannot write logs") from log_dir_access

# Do not
except FileNotFoundError as e:
    log_error(e)

except TimeoutError as timeout_error:
    raise CQError("Tool did not respond") from timeout_error
```

### Exception Handling

Always catch specific exception types. Bare `except` clauses and broad `except Exception` are never allowed. Every `except` clause names the exact exception it expects.

```python
# Do
except FileNotFoundError as missing_config:
    log_error(missing_config)

except (PermissionError, OSError) as filesystem_failure:
    raise CQError("Cannot access output directory") from filesystem_failure

# Do not — bare except catches everything including KeyboardInterrupt, SystemExit
except:
    log("something failed")

# Do not — too broad, swallows all errors and hides real problems
except Exception:
    log("something failed")

# Do not — catching Exception with a variable is still too broad
except Exception as error:
    log(str(error))
```

### Comprehensions

Use a comprehension when building a collection with a single transformation or filter. Use an explicit loop when there are side effects, multiple statements per iteration, or nested conditions.

```python
# Do — single transformation or filter, obvious at a glance
extensions = [f.suffix for f in files]
python_files = [f for f in files if f.suffix == ".py"]
config_map = {key: value for key, value in raw.items() if value is not None}

# Do — explicit loop for side effects or multi-step logic
results = []
for tool in tools:
    if tool.is_available():
        executor.register(tool)
        results.append(tool.run())

# Do not — comprehension with complex logic that requires thought to read
results = [
    tool.run()
    for tool in tools
    if tool.is_available() and tool.config.strict and not tool.is_deprecated()
]
```

---

## Comments

Every comment uses `# ` (hash, space), indented to match the code it describes. Full sentences. 100 characters max per line measured from column 0. Multi-line comments must use the available width before wrapping to the next line; do not wrap short when the text fits on fewer lines within the 100-character limit. When a comment has two related clauses, separate them with a semicolon.

```python
# Validate user permissions; deny early to avoid unnecessary work
```

Never use em dashes, en dashes, or hyphens as clause separators in comments.

### Intent Comments

Required above every block structure: `for`, `while`, `if`, `try`, guard clauses. States why the block exists.

```python
# Skip processing when no tools passed pre-flight checks
if not validated_tools:
    return

# Retry with backoff to handle transient network failures
for attempt in range(max_retries):
    ...

# Route output based on user's configured format
if config.output_format == "json":
    ...
```

### Mechanical Comments

Required inside any block that has more than one branch. Every branch gets a mechanical comment. No discretion; if there are multiple paths, each one is commented.

```python
# Catch OS-level errors separately for targeted recovery
try:
    data = read_file(path)
except PermissionError:
    # Log and re-raise; caller must handle access restrictions
    log_error(path, "permission denied")
    raise
except FileNotFoundError:
    # Fall back to empty dataset; missing files are expected on first run
    data = {}
```

```python
# Route output based on user's configured format
if config.output_format == "json":
    # Serialize with sorted keys for deterministic diffs
    write_json(results, sort_keys=True)
elif config.output_format == "csv":
    # Flatten nested structures before writing rows
    flat = flatten_results(results)
    write_csv(flat)
else:
    # Plain text as default; no transformation needed
    print(results)
```

```python
# Validate all discovered tools before execution
for tool in discovered_tools:
    if tool.is_available():
        # Register for execution with resolved config
        executor.register(tool, config)
    else:
        # Record missing tools; report all at once after loop
        missing.append(tool.name)
```

### What Never Gets a Comment

Simple assignments, returns, and variable setup where the names convey the meaning.

```python
items = []
name = user.first_name
path = Path(directory) / filename
return result
```

---

## Docstrings

NumPy format. Every function, method, and class gets a docstring. The only exceptions are dunder methods that implement a standard Python protocol with no domain-specific behavior.

### Functions and Methods

```python
def process_user_data(
    user_id: str,
    data: dict[str, Any],
    validate: bool = True,
) -> dict[str, Any]:
    """
    Process and validate user data for storage.

    Parameters
    ----------
    user_id : str
        Unique identifier for the user.
    data : dict[str, Any]
        Raw user data to be processed.
    validate : bool, optional
        Whether to run validation checks. Default is True.

    Returns
    -------
    dict[str, Any]
        Processed and validated user data.

    Raises
    ------
    ValidationError
        When data fails validation checks.
    UserNotFoundError
        When user_id does not exist in system.
    """
```

Only these sections are allowed, in this order: Parameters, Returns, Raises. No other sections (Examples, Notes, See Also, etc.) are permitted in function or method docstrings. One blank line between sections.

### Classes

Document everything at the class level. Do not write a docstring for `__init__`.

```python
class DataProcessor:
    """
    Process and validate data for machine learning workflows.

    Parameters
    ----------
    config : dict[str, Any]
        Configuration settings for data processing.
    validation_rules : list[str]
        List of validation rules to apply.
    max_retries : int
        Maximum number of retry attempts.

    Attributes
    ----------
    config : dict[str, Any]
        Current configuration settings.
    processed_count : int
        Number of successfully processed records.
    """

    def __init__(
        self,
        config: dict[str, Any],
        validation_rules: list[str],
        max_retries: int = 3,
    ) -> None:
        self.config = config
        self.validation_rules = validation_rules
        self.max_retries = max_retries
        self.processed_count = 0
```

Only these sections are allowed, in this order: Parameters, Attributes, Raises (when the constructor can raise), Methods (when needed). No other sections are permitted in class docstrings. One blank line between sections. Since ``__init__`` does not get a docstring, constructor exceptions are documented in the class-level ``Raises`` section.

### Modules

The module docstring is the front door. It tells anyone who opens the file what is available and how to use it. List every class, function, and module-level constant that is designed to be called or referenced from outside the module. This is the external API. A name that is public to Python (no underscore) but exists only to support other names within the same file is not external API and must not be listed. Omit internal helpers, private functions, and private classes. When constants or enums have their own dedicated file, they do not need listing in another module's docstring. Every module with external API includes an `Examples` section demonstrating usage.

```python
"""
Configuration resolution for code quality tools.

Resolves final configuration by merging CLI arguments, user defaults,
and built-in fallbacks.

Constants
---------
DEFAULT_LINE_LENGTH : Maximum characters per line.
DEFAULT_TIMEOUT : Tool execution timeout in seconds.

Classes
-------
ConfigResolver : Merges configuration sources into a final GlobalConfig.
UserDefaults : User-configured default values loaded from disk.

Functions
---------
load_defaults : Load user defaults from the configuration file.

Examples
--------
>>> defaults = UserDefaults(line_length=100)
>>> resolver = ConfigResolver(defaults)
>>> config = resolver.resolve({"strict": True})
>>> config.line_length
100
>>> config.strict
True
"""
```

Only these sections are allowed, in this order: Summary, Extended Summary (when needed), Constants (required when the module defines public constants), Classes, Functions, Examples. Omit a section only when the module has no items of that kind. One blank line between sections. The `Examples` section is exclusive to module docstrings; it must not appear in function, method, or class docstrings. Examples use `>>>` doctest format. Every example must be valid and verifiable; do not write examples that would fail if executed.

### Dunder Methods

Do not write docstrings for dunder methods that implement a standard Python protocol with no domain-specific behavior.

```python
# No docstrings; behavior is defined by the protocol
def __repr__(self) -> str:
    return f"Vector({self.x}, {self.y})"

def __eq__(self, other: object) -> bool:
    if not isinstance(other, Vector):
        return NotImplemented
    return self.x == other.x and self.y == other.y

def __len__(self) -> int:
    return len(self._items)

def __hash__(self) -> int:
    return hash((self.x, self.y))

def __str__(self) -> str:
    return f"({self.x}, {self.y})"
```

Do write a docstring when a dunder has non-obvious logic, side effects, or deviates from standard protocol expectation.

```python
def __contains__(self, item: str) -> bool:
    """
    Check membership using case-insensitive comparison.

    Parameters
    ----------
    item : str
        Key to search for.

    Returns
    -------
    bool
        True if the key exists regardless of case.
    """
    return item.lower() in self._normalized_keys

def __enter__(self) -> "DatabaseConnection":
    """
    Open a connection and begin a transaction.

    Returns
    -------
    DatabaseConnection
        Active connection with an open transaction.
    """
    self._conn = connect(self._dsn)
    self._conn.begin()
    return self
```

### Single-Line Docstrings

A function gets a single-line docstring only when it has no parameters, or all parameters are self-evident from the function name and type hints, and it raises no exceptions.

```python
def get_project_root() -> Path:
    """Return the project root directory."""
```

If a function has parameters that need explanation, a Returns value that needs description, or raises exceptions, it gets a full multi-line docstring regardless of how simple the function appears.

### Formatting Rules

- The opening `"""` is alone on its own line. The summary sentence starts on the next line, indented to match.
- 100 characters max line length, measured from column 0.
- Blank line before the closing `"""` is managed by Ruff's formatter.
- No trailing whitespace on any line.
- One blank line between sections.
- Imperative mood for summaries: "Process data" not "Processes data."

```python
# Do
def process_data(source: str) -> dict[str, Any]:
    """
    Process raw data from the given source.

    Parameters
    ----------
    source : str
        Path to the data source.

    Returns
    -------
    dict[str, Any]
        Processed data keyed by record ID.
    """

# Do not
def process_data(source: str) -> dict[str, Any]:
    """Process raw data from the given source.

    Parameters
    ----------
    source : str
        Path to the data source.

    Returns
    -------
    dict[str, Any]
        Processed data keyed by record ID.
    """
```

---

## Type Hints

Every function gets a return type annotation, including `-> None`. Every parameter gets a type annotation. Never mix old and new syntax in the same codebase. The target Python version dictates the syntax.

### All Versions (3.9+)

Use built-in types directly. Never import `List`, `Dict`, `Tuple`, `Set`, `Type`, or `FrozenSet` from `typing`.

```python
# Do
list[int]
dict[str, float]
tuple[str, int, bool]
set[str]
type[MyClass]
frozenset[int]

# Do not
from typing import List, Dict, Tuple, Set, Type
```

### Python 3.9

Use `Optional` and `Union` from `typing` for union types. Every module includes `from __future__ import annotations` as the first import for deferred annotation evaluation.

```python
from __future__ import annotations

from typing import Optional, Union

def find(name: str) -> Optional[str]:
    ...

def process(value: Union[str, int]) -> None:
    ...
```

### Python 3.10+

Use `|` syntax. Do not import `Optional` or `Union`.

```python
def find(name: str) -> str | None:
    ...

def process(value: str | int) -> None:
    ...
```

### Python 3.12+

Use inline type parameter syntax. Do not import `TypeVar`, `Generic`, or `TypeAlias` for standard generics.

```python
# Do
def first[T](items: list[T]) -> T:
    return items[0]

class Stack[T]:
    def push(self, item: T) -> None:
        ...

type Vector = list[float]

# Do not
from typing import TypeVar, Generic, TypeAlias
T = TypeVar("T")
class Stack(Generic[T]):
    ...
Vector: TypeAlias = list[float]
```

---

## Imports

### Absolute Imports Only

Never use relative imports. Always use the full module path.

```python
# Do
from tools.code_quality.core.enums import ToolMode

# Do not
from .core.enums import ToolMode
from ..output.logger import CQLogger
```

### Import Style

Use `import x` for standard library and third-party modules. Use `from x import y` for specific names from your own codebase and for standard library objects that are classes or types.

```python
import os
import sys
import subprocess

from pathlib import Path
from dataclasses import dataclass, field
from collections import defaultdict

from tools.code_quality.core.enums import ToolMode
from tools.code_quality.core.exceptions import CQError
```

### Import Order

Three groups, separated by a blank line, alphabetical within each group:

1. Standard library
2. Third-party packages
3. Project imports

---

## Test Structure

### Directory Layout

Tests mirror the source structure. Source packages (directories with ``__init__.py``) get a ``pkg_`` prefix in the test tree to distinguish them from module-level test directories. Top-level source modules get a plain directory named after the module.

```
source/
├── core/
│   ├── enums.py
│   └── exceptions.py
├── output/
│   ├── formatting.py
│   └── logger.py
├── config.py
└── main.py

tests/
├── pkg_core/
│   ├── enums/
│   │   └── test_enums.py
│   └── exceptions/
│       └── test_exceptions.py
├── pkg_output/
│   ├── formatting/
│   │   └── test_formatting.py
│   └── logger/
│       └── test_logger.py
├── config/
│   └── test_config.py
└── main/
    └── test_main.py
```

When a module's tests grow, split them into focused files within the subdirectory:

```
tests/pkg_core/exceptions/
├── test_exceptions.py
├── test_error_hierarchy.py
└── test_error_display.py
```

### File Naming

Test files are always named `test_<behavior>.py`. The primary file is `test_<module>.py`. Additional files describe the specific focus.

### Function Naming

Test functions describe the behavior being verified. Always `test_<thing>_<expected_behavior>`.

```python
def test_config_resolver_uses_cli_over_defaults() -> None:
def test_empty_file_list_raises_input_error() -> None:
def test_tool_registry_returns_none_for_unknown_tool() -> None:
```

Never use generic names like `test_1`, `test_basic`, `test_it_works`.

---

## Test Scales

Three scales of testing, in order of priority.

### Integration (Highest Priority)

Tests how multiple components work together. Verifies that handoffs between classes produce correct outcomes. This is how code actually gets used.

```python
def test_discovered_files_pass_through_tool_execution() -> None:
    # Arrange
    discovery = FileDiscoveryService(root=project_path, extensions=[".py"])
    executor = ToolExecutor(tools=["ruff"])

    # Act
    files = discovery.discover()
    result = executor.run(files)

    # Assert
    assert result.exit_code == ExitCode.SUCCESS
    assert result.files_checked == len(files)
```

### Component (High Priority)

Tests one class through its lifecycle. Construction through usage, verifying the class fulfills its purpose.

```python
def test_file_discovery_finds_python_files_in_nested_dirs() -> None:
    # Arrange
    service = FileDiscoveryService(root=project_path, extensions=[".py"])

    # Act
    files = service.discover()

    # Assert
    assert all(f.suffix == ".py" for f in files)
    assert len(files) > 0
```

### Unit (Targeted Use)

Tests a single function that contains conditional logic routing to different outcomes. A function gets a unit test when it makes decisions. Functions that transform without branching are covered by component and integration tests.

```python
def test_resolve_config_value_prefers_cli_over_env() -> None:
    # Arrange
    cli_value = 120
    env_value = 80
    default = 100

    # Act
    result = resolve_config_value(cli_value, env_value, default)

    # Assert
    assert result == 120

def test_resolve_config_value_falls_back_to_env() -> None:
    # Arrange
    cli_value = None
    env_value = 80
    default = 100

    # Act
    result = resolve_config_value(cli_value, env_value, default)

    # Assert
    assert result == 80
```

---

## Test Style

### Arrange-Act-Assert

Every test uses AAA structure with all three comments. No exceptions.

```python
def test_config_resolver_merges_cli_and_defaults() -> None:
    # Arrange
    defaults = UserDefaults(line_length=100)
    cli_args = {"line_length": 120, "strict": True}

    # Act
    config = ConfigResolver(defaults).resolve(cli_args)

    # Assert
    assert config.line_length == 120
    assert config.strict is True
```

The one exception is `pytest.raises`, where the act and assertion are the same operation. Use `# Act / Assert` as a single comment.

```python
def test_negative_line_length_raises_config_error() -> None:
    # Arrange
    invalid_value = -1

    # Act / Assert
    with pytest.raises(ValueError, match="line_length must be positive"):
        Config(line_length=invalid_value)
```

### Test Classes

Use flat functions by default. Use a test class only when an existing group of tests already shares identical setup. Never create a test class preemptively.

```python
class TestToolExecutor:
    """Test tool executor lifecycle."""

    def setup_method(self) -> None:
        """Set up shared state for each test."""
        self.executor = ToolExecutor(tools=["ruff", "mypy"])
        self.test_files = [Path("main.py"), Path("utils.py")]

    def test_executor_runs_all_registered_tools(self) -> None:
        # Arrange
        expected_tools = {"ruff", "mypy"}

        # Act
        result = self.executor.run(self.test_files)

        # Assert
        assert result.tools_run == expected_tools

    def test_executor_reports_failure_on_tool_error(self) -> None:
        # Arrange
        self.executor.tools.append("nonexistent")

        # Act
        result = self.executor.run(self.test_files)

        # Assert
        assert result.exit_code == ExitCode.TOOL_ERROR
```

### Parametrize Over Loops

Use `@pytest.mark.parametrize` for testing multiple inputs. Never use a `for` loop inside a test to iterate over cases.

```python
# Do
@pytest.mark.parametrize("invalid_input", [
    "",
    None,
    "  ",
])
def test_component_creation_rejects_invalid_names(invalid_input: str) -> None:
    # Arrange
    name = invalid_input

    # Act / Assert
    with pytest.raises(ValueError, match="name must not be empty"):
        Component(name, "description")

# Do not
def test_component_creation_rejects_invalid_names() -> None:
    for invalid_input in ["", None, "  "]:
        with pytest.raises(ValueError):
            Component(invalid_input, "description")
```

### Exception Testing

Always use `pytest.raises` with a `match` argument.

```python
# Do
with pytest.raises(ValueError, match="line_length must be positive"):
    Config(line_length=-1)

# Do not
with pytest.raises(ValueError):
    Config(line_length=-1)
```

### Helper Functions Over Fixtures

Use helper functions for test setup. The only fixtures allowed are pytest built-ins (`tmp_path`, `monkeypatch`, `capfd`, etc.).

```python
# Do
def make_config(**overrides) -> GlobalConfig:
    """Create a test configuration with optional overrides."""
    defaults = {"line_length": 100, "strict": False}
    defaults.update(overrides)
    return GlobalConfig(**defaults)

def test_strict_mode_enables_all_checks() -> None:
    # Arrange
    config = make_config(strict=True)

    # Act
    result = run_analysis(config)

    # Assert
    assert result.all_checks_enabled is True

# Do not
@pytest.fixture
def config():
    return GlobalConfig(line_length=100, strict=False)
```

---

## Mocking

### When to Mock

Mock only what crosses a boundary: filesystem, network, time, OS, subprocess. Use real instances from your own codebase.

A module's real instances are trusted only when that module has component and integration tests that meet this guide's standards. If a module is untested or has only line-level unit tests, mock it.

### Mock Specification

Use `autospec=True` by default. If autospec cannot introspect a specific object, fall back to `spec=True` and comment why. Never use a bare `MagicMock` without spec.

```python
# Default
@patch("subprocess.run", autospec=True)
def test_tool_executor_passes_timeout(mock_run: MagicMock) -> None:
    # Arrange
    executor = ToolExecutor(timeout=30)

    # Act
    executor.run(["main.py"])

    # Assert
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["timeout"] == 30

# Fallback with explanation
@patch(
    "tools.code_quality.output.logger.CQLogger",
    spec=True,  # autospec fails on classmethod binding
)
def test_logger_creation(mock_logger: MagicMock) -> None:
    ...
```

### Patch Location

Patch where the object is used, not where it is defined.

```python
# Module under test imports: from shutil import which
# Patch at the usage location
@patch("tools.code_quality.cli.which", autospec=True)

# Do not patch at the definition
@patch("shutil.which", autospec=True)
```

---

## Anti-Patterns

Do not do any of the following:

- **Line testing.** Testing a single attribute or return value in isolation without exercising behavior. Tests verify functionality and lifecycle, not individual lines.
- **Coverage chasing.** Writing tests to hit coverage percentages. Tests exist to verify behavior and build confidence for refactoring.
- **Testing framework behavior.** Do not test that pytest, Python, or third-party libraries work correctly.
- **Testing private methods directly.** Private methods are covered through the public interface via component and integration tests.
- **Complex fixture hierarchies.** Fixtures that depend on other fixtures create hidden coupling. Use explicit helper functions.
- **Mocking your own tested code.** If a module has proven tests, use real instances. Mocks hide integration failures.
- **`autouse=True` fixtures.** Implicit setup obscures what a test depends on.
- **Generic test names.** `test_basic`, `test_it_works`, `test_1` say nothing about behavior.
- **Loops inside tests.** Use `@pytest.mark.parametrize` to test multiple inputs.
