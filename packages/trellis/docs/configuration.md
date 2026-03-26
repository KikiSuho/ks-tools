# Configuration

All configuration lives in the `Config` class as class attributes. There is no
configuration file. Settings are modified programmatically before scanning or
overridden via CLI flags.

## Visibility Settings

| Setting | Default | CLI Flag | Description |
|---|---|---|---|
| `SHOW_PARAMS` | `True` | -- | Include function parameters in output |
| `SHOW_PRIVATE` | `False` | `--show-private` / `--hide-private` | Include `_private` members |
| `SHOW_MANGLED` | `False` | `--show-mangled` / `--hide-mangled` | Include `__mangled` members (no trailing `__`) |
| `SHOW_DUNDER` | `False` | `--show-dunder` / `--hide-dunder` | Include `__dunder__` methods |
| `SHOW_TYPES` | `True` | `--show-types` / `--hide-types` | Include type annotations on parameters |
| `SHOW_DECORATORS` | `True` | `--show-decorators` / `--hide-decorators` | Show decorators on functions and classes |
| `SHOW_DOCS` | `True` | -- | Include documentation files in structure |

## Output Settings

| Setting | Default | Description |
|---|---|---|
| `OUTPUT_DIR` | `"docs"` | Directory where structure files are saved |
| `LOG_DIR` | `"logs/trellis"` | Directory where change logs are stored |
| `MAX_LINE_WIDTH` | `100` | Target line width for call flow truncation and change summary wrapping |
| `CALL_FLOW_MODE` | `CallFlowMode.SMART` | Call flow display mode (`OFF`, `RAW`, or `SMART`) |

## Change Detection Settings

| Setting | Default | Description |
|---|---|---|
| `LOG_STRUCTURE_CHANGES` | `True` | Enable change tracking between runs |
| `LOG_CONFIG_ONLY_CHANGES` | `False` | When `False`, suppress changes caused only by settings differences |

When `LOG_CONFIG_ONLY_CHANGES` is `False` and the tree content is identical but
the `tr_meta` footer differs (e.g. a flag was toggled), change detection is
skipped entirely. This prevents noisy false positives from configuration changes.

## Ignore Patterns

### Hard Ignores (Always Filtered)

These are filtered regardless of any toggle setting.

**Directories:**

`__pycache__`, `.mypy_cache`, `.ruff_cache`, `.black_cache`, `.pytest_cache`,
`.hypothesis`, `.git`, `.svn`, `.hg`, `venv`, `.venv`, `virtualenv`,
`node_modules`, `bower_components`, `.npm`, `.yarn`, `.tox`,
`.ipynb_checkpoints`, `htmlcov`, `.coverage`, `__MACOSX`

**Directory globs:** `*.egg-info`, `*.eggs`

**Files:**

`*.pyc`, `*.pyo`, `*.pyd`, `*.tmp`, `.coverage`, `.DS_Store`, `nul`

### Soft Ignores (User-Configurable)

Controlled by `ENABLE_IGNORE_DIRS` and `ENABLE_IGNORE_FILES`. When the
corresponding toggle is `False`, these patterns are skipped (but hard ignores
still apply).

**Default directory ignores (`IGNORE_DIRS`):**

| Category | Patterns |
|---|---|
| IDE/editor | `.idea`, `.vscode`, `.vs`, `.atom`, `.eclipse`, `.junie`, `.claude` |
| Virtual environments | `env`, `.env` |
| Build/distribution | `build`, `dist`, `_build`, `site`, `docs/build` |
| Documentation | `docs` |
| Temporary | `tmp`, `temp`, `.direnv`, `logs`, `debug`, `out` |
| CI/CD | `.github`, `.gitlab`, `.circleci` |
| Testing | `tests` |
| Tooling | `scripts` |

**Default file ignores (`IGNORE_FILES`):**

| Category | Patterns |
|---|---|
| Configuration | `*.yml`, `*.toml` |
| Git | `.gitignore`, `.gitattributes` |
| Test files | `conftest.py`, `*_test.py`, `*_tests.py`, `test_*.py` |
| Documentation | `LICENSE` |

### Pattern Matching

Directory patterns support three forms:

- **Exact match:** `build` matches any directory named `build`
- **Glob pattern:** `*.egg-info` uses fnmatch wildcard matching
- **Path pattern:** `docs/build` matches against the full POSIX path, so a
  top-level `build/` directory is not falsely excluded

File patterns use fnmatch glob matching against the filename only.

### Special Cases

The configured `OUTPUT_DIR` directory (default `docs`) is always visible when
`SHOW_DOCS` is `True`, even if it appears in `IGNORE_DIRS`.

System files `__init__.py`, `__main__.py`, and `py.typed` are never shown as
file entries. Instead, they are detected as markers that produce `[pkg]`,
`[cmd]`, and `[typed]` tags on their parent directory.

## Documentation Files

`DOC_EXTENSIONS` defines file extensions considered documentation:
`.md`, `.txt`, `.rst`, `.org`, `.adoc`, `.wiki`, `.rdoc`

When `SHOW_DOCS` is `False`, files with these extensions are filtered from the
structure output and from change detection.

## Project Root Discovery

Trellis walks upward from the module location (not the current working
directory) looking for marker files and directories.

**VCS markers:** `.git`, `.hg`, `.svn`

**Config markers:** `pyproject.toml`, `setup.py`, `setup.cfg`,
`requirements.txt`, `Pipfile`, `poetry.lock`, `Cargo.toml`, `package.json`

The search inspects up to 8 directory levels by default. If no marker is found,
trellis falls back to the current working directory with a warning.

The `preference` parameter can prioritize VCS markers (`"vcs"`) or config
markers (`"config"`) when both are present at the same level.

## tr_meta Encoding

Each structure file ends with a metadata footer encoding all output-affecting
settings:

```
# tr_meta:D1I1F1T1@1C0P1V0U0S0Wsmart
```

| Code | Setting |
|---|---|
| `D` | SHOW_DOCS |
| `I` | ENABLE_IGNORE_DIRS |
| `F` | ENABLE_IGNORE_FILES |
| `T` | SHOW_TYPES |
| `@` | SHOW_DECORATORS |
| `C` | Reserved (always 0) |
| `P` | SHOW_PARAMS |
| `V` | SHOW_PRIVATE |
| `U` | SHOW_DUNDER |
| `S` | SHOW_MANGLED |
| `W` | CALL_FLOW_MODE (off/raw/smart) |

Each letter is followed by `1` (enabled) or `0` (disabled), except `W` which
is followed by the mode string. This encoding enables detection of
configuration-only changes between runs.

## Customizing Settings

Modify `Config` class attributes before creating a scanner:

```python
from trellis.config import Config, CallFlowMode

Config.SHOW_PRIVATE = True
Config.CALL_FLOW_MODE = CallFlowMode.RAW
Config.ENABLE_IGNORE_DIRS = False
Config.MAX_LINE_WIDTH = 120
```

Settings are read once when `DirectoryStructure` is constructed. Changing
`Config` after construction does not affect an existing scanner instance.
