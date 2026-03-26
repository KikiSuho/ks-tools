# CLI Reference

## Usage

```bash
trellis [OPTIONS]
python -m trellis [OPTIONS]
```

Run from any directory inside a project. Trellis auto-discovers the project
root by walking upward from the module location looking for `.git`,
`pyproject.toml`, and other markers. See
[Configuration](configuration.md#project-root-discovery) for the full marker
list.

Output is saved to `docs/{project}_structure.txt` by default.

## Visibility Flags

Each visibility setting has a `--show-*` and `--hide-*` flag pair. When
neither is specified, the `Config` class default is used.

### --show-private / --hide-private

Include or exclude members starting with a single underscore (`_private`).
Default: hidden.

```
# With --show-private
├── module.py {50}
│   ├── def public_func() -> None  :5
│   └── def _internal_helper() -> str  :20

# Without (default)
├── module.py {50}
│   └── def public_func() -> None  :5
```

### --show-mangled / --hide-mangled

Include or exclude name-mangled members starting with double underscore but not
ending with double underscore (`__secret`). Default: hidden.

### --show-dunder / --hide-dunder

Include or exclude special/dunder methods like `__init__`, `__repr__`,
`__eq__`. Default: hidden.

```
# With --show-dunder
├── models.py {80}
│   └── class DataStore  :5
│       ├── def __init__(host: str, port: int) -> None  :10
│       ├── def __repr__() -> str  :15
│       └── def connect() -> None  :20

# Without (default)
├── models.py {80}
│   └── class DataStore  :5
│       └── def connect() -> None  :20
```

### --show-types / --hide-types

Include or exclude type annotations on function parameters and return types.
Default: shown.

```
# With --show-types (default)
│   └── def process_data(input: str, limit: int) -> list[dict]  :10

# With --hide-types
│   └── def process_data(input, limit) -> list[dict]  :10
```

### --show-decorators / --hide-decorators

Include or exclude decorator rendering. When shown, decorators appear as parent
nodes with the definition nested beneath. Default: shown.

```
# With --show-decorators (default)
│   ├── @staticmethod
│   │   └── def from_env() -> Config  :30
│   └── @app.route('/api')
│       └── def handle(request: Request) -> Response  :45

# With --hide-decorators
│   ├── def from_env() -> Config  :30
│   └── def handle(request: Request) -> Response  :45
```

## Call Flow

Control how orchestration function call chains are displayed. Only applies to
functions named `main`, `run`, `execute`, or `orchestrate`.

### --call-flow off

Disable call flow display entirely.

### --call-flow raw

Show all direct calls in the function body with width-aware truncation. When
the call chain exceeds the line width, it truncates with `... +N more`.

```
└── def main() -> int  :8
    └── calls: build_config -> connect -> process_data -> validate -> save -> cleanup -> ... +3 more
```

### --call-flow smart

Score calls using an additive model and keep only the top 4 above the score
threshold. This filters out noise like `print`, `len`, and logging calls while
preserving high-signal calls like imported functions and same-file definitions.
This is the default mode.

**Scoring signals:**

| Signal | Score | Description |
|---|---|---|
| Same-file function | +3 | Defined in the same file |
| Imported name | +2 | Bound by an import statement |
| Orchestration prefix | +2 | Name starts with `build_`, `process_`, `run_`, etc. |
| Descriptive name | +1 | 6+ characters with an underscore |
| Builtin name | -3 | `print`, `len`, `str`, `isinstance`, etc. |
| Logging call | -3 | `log`, `debug`, `info`, `warning`, etc. |
| Utility leaf | -2 | `append`, `strip`, `join`, `get`, etc. |
| Short name | -1 | 2 characters or fewer |

```
└── def main() -> int  :8
    └── calls: build_config -> process_data -> run
```

## Bulk Overrides

### --show-all

Enable private, mangled, and dunder visibility. If call flow is `OFF`,
upgrades it to `SMART`.

### --hide-all

Disable private, mangled, and dunder visibility. Sets call flow to `OFF`.

**Precedence:** `--hide-all` wins when both `--show-all` and `--hide-all` are
present. Individual flags are applied first, then bulk overrides take effect.

## Console Output

### First Run

When no previous structure file exists:

```
No project_structure.txt found. Generating now.
```

### No Changes Detected

When the structure is identical to the previous run:

```
No structure changes detected.
```

### Change Summary

When structural changes are detected, a formatted banner is printed. See
[Change Tracking](change-tracking.md) for the full format.

```
====================================================================================================
Structure Changes
  Project:   project
  Log:       trellis_20260324_143025.txt
  Summary:   2 API updates · 1 new module · 1 removed file
====================================================================================================

Updated API (2):
  module.py
    core/module.py:42  def process_data
      (input: str, limit: int) -> list
          >>
      (input: str, limit: int, offset: int) -> list

New Modules (1):
  handlers.py
```

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Failure (cannot create output directory or write structure file) |

## Examples

Show all members with raw call flow:

```bash
trellis --show-all --call-flow raw
```

Hide everything except public functions without type annotations:

```bash
trellis --hide-all --hide-types --hide-decorators
```

Show private members but keep dunder/mangled hidden:

```bash
trellis --show-private
```
