# Architecture

## Package Layout

```
src/trellis/
├── __init__.py          Package summary
├── __main__.py          python -m trellis entry point
├── config.py            Config class, CLI parsing, settings snapshots
├── main.py              DirectoryStructure scanner, main() entry point
├── core/
│   ├── filters.py       Filtering predicates, hard/soft ignore lists
│   ├── io.py            Atomic file write with retry and fallback
│   ├── persistence.py   Save pipeline, change detection orchestration
│   └── project_root.py  Project root discovery by marker files
├── tracking/
│   ├── detector.py      Path extraction, tr_meta management, change detection
│   ├── comparator.py    Element-level signature comparison, change categorization
│   └── logger.py        Timestamped per-run log file writing
├── pyast/
│   ├── analyzer.py      AST parsing, node extraction, signature formatting
│   ├── renderer.py      AstRenderer, tree-style output generation
│   ├── call_flow.py     Call flow scoring, filtering, line formatting
│   └── tree_drawing.py  Tree connector symbols (box-drawing characters)
└── output/
    └── console.py       Change summary banner formatting
```

## Data Flow

A typical run follows this path:

```
CLI invocation
  │
  ├── parse_visibility_args(sys.argv)  →  VisibilitySettings
  ├── find_project_root(__file__)      →  Path or None
  │
  ├── DirectoryStructure(root_dir, visibility settings)
  │   ├── build_filter_settings()      →  FilterSettings (immutable)
  │   ├── build_render_settings()      →  RenderSettings (immutable)
  │   ├── build_tr_meta()              →  str
  │   └── AstRenderer(shared list, visibility, RenderSettings)
  │
  ├── scan_directory(root_dir)         ← recursive
  │   ├── os.scandir() per directory
  │   ├── Filter items (hard ignores, soft ignores, doc files)
  │   ├── Detect markers ([pkg], [cmd], [typed])
  │   ├── Process directories (recurse)
  │   └── Process .py files
  │       ├── Read source, count lines
  │       └── AstRenderer.render_python_structure()
  │           ├── parse_python_file()  →  ast.Module
  │           ├── extract_top_level_nodes()  →  classes, functions
  │           ├── Render classes with inheritance, decorators, members
  │           ├── Render functions with decorators, call flow
  │           └── Detect and collapse wrapper boilerplate
  │
  ├── save_structure()
  │   ├── PersistenceContext (immutable snapshot)
  │   └── core.persistence.save_structure()
  │       ├── Create output directories
  │       ├── Build content with tr_meta footer
  │       ├── [First run] Write file, return
  │       └── [Subsequent runs]
  │           ├── Read previous file
  │           ├── split_tree_and_meta()  →  tree, meta, status
  │           ├── Check for config-only change
  │           ├── detect_structure_changes()  →  added, deleted paths
  │           ├── analyze_structure_elements() on both trees
  │           ├── compare_structure_elements()  →  StructureChanges
  │           └── Write new file atomically
  │
  └── Report results
      ├── First run: "Generating now."
      ├── No changes: "No structure changes detected."
      └── Changes found:
          ├── format_change_summary()  →  banner string
          ├── log_structure_changes()  →  log file path
          └── Print to stdout
```

## Key Design Patterns

### Immutable Settings Snapshots

`Config` holds mutable class attributes. At construction time,
`DirectoryStructure` reads these into immutable `NamedTuple` snapshots:
`FilterSettings`, `RenderSettings`, and a `tr_meta` string. All downstream
functions receive snapshots, never the mutable `Config` class. This ensures
consistency within a single scan and makes the functions safe to call
concurrently.

### Delegated Rendering via Shared List

`DirectoryStructure` owns a `_structure_lines: list[str]`. The `AstRenderer`
receives a reference to the same list at construction. Both the scanner (for
directory/file entries) and the renderer (for AST content) append to this
shared list. The scanner uses `.clear()` instead of reassignment to preserve
the shared reference across rescans.

### Single-Pass Tree Parsing

`analyze_structure_paths()` and `analyze_structure_elements()` each parse tree
text in a single pass using `_iter_tree_entries()`. They maintain indent and
path stacks to reconstruct the directory hierarchy without building an
intermediate tree data structure.

### Stateless Filtering

All filter functions accept a `FilterSettings` parameter and read no global
state. Hard-ignore constants are module-level frozensets. Glob patterns are
pre-compiled into regex objects and cached via `@functools.lru_cache` keyed on
the frozen pattern set.

### tr_meta Metadata Encoding

A compact single-line footer encodes all output-affecting settings. This
enables two capabilities: detecting configuration-only changes (same tree,
different settings) and reproducing the exact settings used for a previous scan.
The footer is parsed with a single regex that has backward-compatible optional
groups for older format versions.

### Atomic File Writes

`atomic_write_text()` writes to a `.tmp` sibling file, then uses
`Path.replace()` for an atomic rename. On failure (transient file locks from
Dropbox or antivirus), it retries once after a short delay, then falls back to
a direct write. The temporary file is always cleaned up.

## Module Responsibilities

**main.py** owns the `DirectoryStructure` class and the CLI entry point.
It handles directory traversal, marker detection, symlink handling, and
delegates AST rendering and persistence to other modules.

**config.py** centralizes all settings as `Config` class attributes and
provides pure functions to parse CLI flags (`parse_visibility_args`) and
create immutable snapshots (`build_filter_settings`, `build_tr_meta`).

**core/persistence.py** manages the save pipeline: creating output directories,
reading previous files, orchestrating change detection, and writing new files.
It accepts a `PersistenceContext` value object so it has no dependency on the
scanner class.

**core/filters.py** provides all include/exclude predicates. Hard-ignore
constants define infrastructure noise. User-configurable patterns flow through
`FilterSettings` and are gated by enable toggles. Hierarchy-aware filtering
checks ancestors.

**core/io.py** provides `atomic_write_text()` used by both the persistence
layer and the change logger.

**core/project_root.py** walks upward from a starting path looking for VCS
and config marker files. Designed as a standalone module with no project
dependencies.

**tracking/detector.py** parses tree text to extract paths and code elements,
manages the `tr_meta` footer, and detects path-level changes between structure
versions.

**tracking/comparator.py** compares per-file code element maps to categorize
changes as API updates, additions, or removals. Produces the `StructureChanges`
result used by the formatter.

**tracking/logger.py** writes pre-formatted change content to timestamped
per-run log files using atomic writes.

**pyast/analyzer.py** parses Python files into ASTs, extracts top-level
definitions (including guarded defs in `if`/`try` blocks), formats signatures,
and extracts decorator information.

**pyast/renderer.py** converts AST analysis results into tree-formatted text
lines. Handles decorator scaffolding, call flow emission, wrapper collapse
detection, and visibility filtering.

**pyast/call_flow.py** scores function call names for SMART mode filtering
and formats width-aware `calls:` summary lines.

**pyast/tree_drawing.py** provides tree connector symbols (`├──`, `└──`) and
child prefix computation.

**output/console.py** formats categorized changes into a terminal-ready banner
with header, per-category detail sections grouped by file, and clickable
`file:line` links.

## Module Dependency Graph

```
main
├── config
├── core.filters ← config
├── core.persistence
│   ├── config
│   ├── core.filters
│   ├── core.io
│   ├── tracking.detector ← config
│   └── tracking.comparator
├── core.project_root
├── pyast.renderer
│   ├── config
│   ├── pyast.analyzer
│   ├── pyast.call_flow
│   └── pyast.tree_drawing
├── pyast.tree_drawing
├── output.console ← tracking.comparator
└── tracking.logger ← core.io
```

## Testing Structure

Tests mirror the source package layout. Package directories use a `pkg_`
prefix to distinguish them from module-level test directories.

```
tests/
├── config/              Config module tests
├── main/                Main module tests
├── pkg_core/            Core package tests
│   ├── filters/
│   ├── io/
│   ├── persistence/
│   └── project_root/
├── pkg_tracking/        Tracking package tests
│   ├── comparator/
│   ├── detector/
│   └── logger/
├── pkg_pyast/           PyAST package tests
│   ├── analyzer/
│   ├── call_flow/
│   ├── renderer/
│   └── tree_drawing/
├── pkg_output/          Output package tests
│   └── console/
└── test_*.py            Cross-module integration tests
```

Integration tests at the root level exercise cross-module lifecycles: change
logging across runs, filter interaction with change detection, save structure
lifecycle, shared state between scanner and renderer, and pipeline edge cases.
