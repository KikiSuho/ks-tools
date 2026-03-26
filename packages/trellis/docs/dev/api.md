# API Reference

## Public API Surface

The following names are exported from `trellis.main`:

`DirectoryStructure`, `Config`, `CallFlowMode`, `FilterSettings`,
`RenderSettings`, `VisibilitySettings`, `SaveResult`, `WriteStatus`,
`AstRenderer`, `build_filter_settings`, `build_render_settings`,
`get_tree_connectors`, `main`, `parse_visibility_args`

## DirectoryStructure

The primary class for scanning directories and generating structure output.

### Constructor

```python
DirectoryStructure(
    root_dir: str,
    show_private: bool | None = None,
    show_mangled: bool | None = None,
    show_dunder: bool | None = None,
    show_types: bool | None = None,
    show_decorators: bool | None = None,
    call_flow_mode: CallFlowMode | None = None,
)
```

When a parameter is `None`, the current `Config` class attribute is used.
Settings are frozen into immutable snapshots at construction time.

### scan_directory()

```python
scanner.scan_directory(current_dir: str, prefix: str = "") -> None
```

Recursively scan directories and extract Python class/function names. On root
call (empty prefix), all accumulated state is cleared so the instance can be
reused for multiple scans.

### structure (property)

```python
text: str = scanner.structure
```

Return the accumulated structure as a single string.

### save_structure()

```python
result: SaveResult = scanner.save_structure()
```

Save the directory structure to a text file with change tracking. Returns a
`SaveResult` containing the output path, detected changes, and write status.

### Example

```python
from trellis.main import DirectoryStructure
from trellis.config import CallFlowMode

scanner = DirectoryStructure(
    "/path/to/project",
    show_private=True,
    call_flow_mode=CallFlowMode.RAW,
)
scanner.scan_directory("/path/to/project")

# Access the generated tree text
print(scanner.structure)

# Save and check for changes
result = scanner.save_structure()
if result.changes is not None and result.changes.has_changes:
    print(f"Changes detected: {len(result.changes.api_changes)} API updates")
```

## Config

Mutable class with class-level attributes controlling all scanning behavior.
Settings are read once during `DirectoryStructure` construction.

### Visibility

| Attribute | Type | Default |
|---|---|---|
| `SHOW_PARAMS` | `bool` | `True` |
| `SHOW_PRIVATE` | `bool` | `False` |
| `SHOW_MANGLED` | `bool` | `False` |
| `SHOW_DUNDER` | `bool` | `False` |
| `SHOW_DOCS` | `bool` | `True` |
| `SHOW_TYPES` | `bool` | `True` |
| `SHOW_DECORATORS` | `bool` | `True` |

### Output

| Attribute | Type | Default |
|---|---|---|
| `MAX_LINE_WIDTH` | `int` | `100` |
| `CALL_FLOW_MODE` | `CallFlowMode` | `SMART` |
| `OUTPUT_DIR` | `str` | `"docs"` |
| `LOG_DIR` | `str` | `"logs/trellis"` |

### Change Detection

| Attribute | Type | Default |
|---|---|---|
| `LOG_STRUCTURE_CHANGES` | `bool` | `True` |
| `LOG_CONFIG_ONLY_CHANGES` | `bool` | `False` |

### Filtering

| Attribute | Type | Default |
|---|---|---|
| `ENABLE_IGNORE_DIRS` | `bool` | `True` |
| `ENABLE_IGNORE_FILES` | `bool` | `True` |
| `DOC_EXTENSIONS` | `frozenset[str]` | `.md`, `.txt`, `.rst`, `.org`, `.adoc`, `.wiki`, `.rdoc` |
| `IGNORE_DIRS` | `frozenset[str]` | IDE, build, temp, CI, test directories |
| `IGNORE_FILES` | `frozenset[str]` | Config files, test files, LICENSE |

See [Configuration](../configuration.md) for full default lists.

## Settings Builders

### build_filter_settings()

```python
build_filter_settings(
    *,
    enable_ignore_dirs: bool | None = None,
    enable_ignore_files: bool | None = None,
    show_docs: bool | None = None,
    doc_extensions: frozenset[str] | None = None,
    output_dir: str | None = None,
    ignore_dirs: frozenset[str] | None = None,
    ignore_files: frozenset[str] | None = None,
    log_dir: str | None = None,
    log_structure_changes: bool | None = None,
    log_config_only_changes: bool | None = None,
) -> FilterSettings
```

Create an immutable `FilterSettings` snapshot. `None` parameters read the
current `Config` value.

### build_render_settings()

```python
build_render_settings(
    *,
    show_types: bool | None = None,
    show_decorators: bool | None = None,
    call_flow_mode: CallFlowMode | None = None,
    show_params: bool | None = None,
    max_line_width: int | None = None,
) -> RenderSettings
```

Create an immutable `RenderSettings` snapshot.

### build_tr_meta()

```python
build_tr_meta(
    *,
    show_types: bool | None = None,
    show_decorators: bool | None = None,
    call_flow_mode: CallFlowMode | None = None,
    show_docs: bool | None = None,
    enable_ignore_dirs: bool | None = None,
    enable_ignore_files: bool | None = None,
    show_params: bool | None = None,
    show_private: bool | None = None,
    show_dunder: bool | None = None,
    show_mangled: bool | None = None,
) -> str
```

Build the compact `tr_meta` metadata string encoding current settings.

## CLI Parsing

### parse_visibility_args()

```python
parse_visibility_args(argv: list[str]) -> VisibilitySettings
```

Parse CLI flags into an immutable `VisibilitySettings`. This function is pure
and does not mutate `Config`.

## AST Rendering

### AstRenderer

```python
AstRenderer(
    structure_lines: list[str],
    show_private: bool,
    show_mangled: bool,
    show_dunder: bool,
    settings: RenderSettings,
)
```

Render Python AST nodes into tree-style structure lines. Appends to the
provided `structure_lines` list (does not own it).

```python
renderer.render_python_structure(
    file_path: str,
    prefix: str,
    show_params: bool,
    source: str | None = None,
) -> None
```

Parse and render a Python file's AST. Pass pre-read `source` to avoid
redundant file I/O.

### Example

```python
from trellis.pyast.renderer import AstRenderer, build_render_settings

lines: list[str] = []
settings = build_render_settings(show_types=True, show_decorators=True)
renderer = AstRenderer(lines, False, False, False, settings)
renderer.render_python_structure("/path/to/module.py", prefix="    ", show_params=True)
print("".join(lines))
```

## Change Detection

### detect_structure_changes()

```python
from trellis.tracking.detector import detect_structure_changes

added, deleted, has_changes = detect_structure_changes(
    new_content: str,
    old_content: str,
    project_name: str,
    path_filter: Callable[[str, Sequence[str]], bool],
    settings: FilterSettings,
    collected_paths: tuple[frozenset[str], dict[str, tuple[str, ...]]] | None = None,
    old_tree_content: str | None = None,
) -> tuple[list[str], list[str], bool]
```

Compare old and new tree structures to detect path-level changes.

### analyze_structure_elements()

```python
from trellis.tracking.detector import analyze_structure_elements

elements: dict[str, list[str]] = analyze_structure_elements(structure_text: str)
```

Extract per-file code elements (functions, classes, decorators) from tree text.

### compare_structure_elements()

```python
from trellis.tracking.comparator import compare_structure_elements

changes: StructureChanges = compare_structure_elements(
    old_elements: dict[str, list[str]],
    new_elements: dict[str, list[str]],
    added_file_paths: list[str],
    removed_file_paths: list[str],
)
```

Compare old and new element maps and return categorized changes.

## Data Types

### CallFlowMode

Enum with values `OFF`, `RAW`, `SMART`.

### FilterSettings

`NamedTuple` with fields: `enable_ignore_dirs`, `enable_ignore_files`,
`show_docs`, `doc_extensions`, `output_dir`, `ignore_dirs`, `ignore_files`,
`log_dir`, `log_structure_changes`, `log_config_only_changes`.

### VisibilitySettings

`NamedTuple` with fields: `show_private`, `show_mangled`, `show_dunder`,
`show_types`, `show_decorators`, `call_flow_mode`.

### RenderSettings

`NamedTuple` with fields: `show_params`, `show_types`, `show_decorators`,
`max_line_width`, `call_flow_mode`.

### PersistenceContext

`NamedTuple` with fields: `project_name`, `root_dir`, `structure`,
`scanned_paths`, `path_hierarchy`, `filter_settings`, `tr_meta`.

### SaveResult

`NamedTuple` with fields: `output_path`, `changes` (`StructureChanges | None`),
`logs_dir`, `write_status` (default `SUCCESS`), `read_error` (default `""`).

### WriteStatus

Enum with values `SUCCESS`, `DIR_CREATE_FAILED`, `WRITE_FAILED`.

### StructureChanges

`NamedTuple` with fields: `api_changes` (`list[ApiChange]`), `new_api`
(`list[ApiEntry]`), `removed_api` (`list[ApiEntry]`), `new_packages`,
`removed_packages`, `new_modules`, `removed_modules`, `new_files`,
`removed_files` (all `list[str]`), `has_changes` (`bool`).

### ApiChange

`NamedTuple` with fields: `file_path`, `old_signature`, `new_signature`.

### ApiEntry

`NamedTuple` with fields: `file_path`, `signature`.

## Project Root Discovery

### find_project_root()

```python
from trellis.core.project_root import find_project_root

root: Path | None = find_project_root(
    start_path: Path | str | None = None,
    markers: list[str] | tuple[str, ...] | None = None,
    max_depth: int = 8,
    follow_symlinks: bool = False,
    preference: Literal["vcs", "config"] | None = None,
)
```

Walk upward from `start_path` looking for marker files or directories. Returns
the resolved project root path or `None`.

### ProjectRootFinder

```python
from trellis.core.project_root import ProjectRootFinder

finder = ProjectRootFinder(markers=[".git"], max_depth=5, preference="vcs")
root = finder.find(start_path="/path/to/subdir")
cloned = finder.clone(max_depth=10)
```

Store policy defaults and call `find_project_root`. The `.clone()` method
creates a new finder with updated defaults.

## Utilities

### get_tree_connectors()

```python
from trellis.pyast.tree_drawing import get_tree_connectors

connector, child_prefix = get_tree_connectors(prefix: str, is_last_item: bool)
```

Return the connector symbol (`"├── "` or `"└── "`) and the prefix string for
child items.

### atomic_write_text()

```python
from trellis.core.io import atomic_write_text

success: bool = atomic_write_text(output_path: str, content: str)
```

Write text to a file atomically with retry and direct-write fallback. Returns
`True` on success.
