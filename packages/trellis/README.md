# Trellis

Project structure tree visualizer with Python AST analysis and change tracking.

Trellis scans a directory tree and produces a text representation that includes
Python classes, functions, signatures, decorators, and call flow analysis.
It tracks structural changes between runs and generates categorized change
summaries with timestamped log files.

## Installation

```bash
pip install ks-trellis
```

## Quick Start

Run from any directory inside a project. Trellis auto-discovers the project
root by walking upward looking for `.git`, `pyproject.toml`, and other markers.

```bash
trellis
```

Output is saved to `docs/{project}_structure.txt`. On subsequent runs, trellis
detects and reports structural changes.

## Output Example

```
project/ [pkg] [cmd] [typed]
├── core/ [pkg]
│   ├── models.py {85}
│   │   ├── class BaseProcessor  :5
│   │   ├── class DataStore(BaseProcessor)  :20
│   │   │   ├── def connect(host: str, port: int) -> None  :25
│   │   │   └── def query(sql: str) -> list[dict]  :34
│   │   └── def build_config(path: str) -> Config  :60
│   └── utils.py {42}
│       ├── /wrapper\ def cached_lookup(func)  :10
│       └── def format_output(items: list) -> str  :18
├── handlers.py {120}
│   ├── @app.route('/api')
│   │   └── def handle_request(request: Request) -> Response  :15
│   └── def process_data(input: str, limit: int) -> Result  :45
└── main.py {30}
    └── def main() -> int  :8
        └── calls: build_config -> process_data -> run


# tr_meta:D1I1F1T1@1C0P1V0U0S0Wsmart
```

**Markers:** `[pkg]` = Python package, `[cmd]` = has `__main__.py`,
`[typed]` = has `py.typed`

**Line counts:** `{85}` = 85 lines of source code

**Call flow:** `calls: build_config -> process_data -> run` shows orchestration
function call chains (SMART mode filters for high-signal calls)

**Wrapper collapse:** `/wrapper\` tags decorator boilerplate that wraps a
single inner function

## CLI Flags

```bash
trellis --show-private          # include _private members
trellis --show-dunder           # include __dunder__ methods
trellis --show-all              # show everything
trellis --hide-all              # hide private/dunder/mangled, disable call flow
trellis --call-flow raw         # show all calls without filtering
trellis --call-flow off         # disable call flow display
trellis --hide-types            # omit type annotations
trellis --hide-decorators       # omit decorator rendering
```

See [CLI Reference](https://github.com/KikiSuho/ks-tools/blob/main/packages/trellis/docs/cli.md) for the full flag list.

## Documentation

- [CLI Reference](https://github.com/KikiSuho/ks-tools/blob/main/packages/trellis/docs/cli.md) -- all flags with examples
- [Configuration](https://github.com/KikiSuho/ks-tools/blob/main/packages/trellis/docs/configuration.md) -- settings, ignore patterns, project root discovery
- [Change Tracking](https://github.com/KikiSuho/ks-tools/blob/main/packages/trellis/docs/change-tracking.md) -- how change detection works, log format
- [Architecture](https://github.com/KikiSuho/ks-tools/blob/main/packages/trellis/docs/dev/architecture.md) -- package layout, data flow, design patterns
- [API Reference](https://github.com/KikiSuho/ks-tools/blob/main/packages/trellis/docs/dev/api.md) -- programmatic usage from Python

## License

See [LICENSE](https://github.com/KikiSuho/ks-tools/blob/main/LICENSE).
