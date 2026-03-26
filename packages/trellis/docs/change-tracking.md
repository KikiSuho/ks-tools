# Change Tracking

Trellis compares the current structure output against the previously saved file
and categorizes changes by type and collaboration impact. Results appear on the
console and are optionally written to timestamped log files.

## Change Categories

### Structural Changes (Paths)

Path-level changes are detected by comparing the set of file and directory
paths between runs.

| Category | Description |
|---|---|
| New Packages | Directories added (ending with `/`) |
| Removed Packages | Directories removed |
| New Modules | `.py` files added |
| Removed Modules | `.py` files removed |
| New Files | Non-Python files added |
| Removed Files | Non-Python files removed |

### Element-Level Changes (API)

For Python files that exist in both the old and new structures, trellis
compares the code elements (functions, classes, decorators) within each file.

| Category | Description |
|---|---|
| Updated API | Same function/class name, different signature |
| New API | New functions or classes (in new or existing files) |
| Removed API | Removed functions or classes |

Line number changes alone do not trigger an API update. Only structural
signature changes (parameters, types, decorators, inheritance) are reported.

## Detection Flow

1. Read the previous structure file from `docs/{project}_structure.txt`
2. Split into tree content and `tr_meta` footer
3. Check for configuration-only change (same tree, different `tr_meta`).
   Skip detection if `LOG_CONFIG_ONLY_CHANGES` is `False`
4. Extract paths and ancestry hierarchy from both old and new trees
5. Apply ignore filtering to both path sets (hard ignores always apply;
   soft ignores respect `ENABLE_IGNORE_DIRS` / `ENABLE_IGNORE_FILES`)
6. Compute added and deleted paths as set differences
7. Extract per-file code elements from both trees
8. Compare element maps: diff elements within files present in both versions;
   collect elements from added/removed files
9. Build categorized result with all change types

## Change Summary Format

### Console Banner

When changes are detected, a formatted banner is printed:

```
====================================================================================================
Structure Changes
  Project:   project
  Log:       trellis_20260324_143025.txt
  Summary:   2 API updates · 1 new API · 1 removed · 1 new module
====================================================================================================

Updated API (2):
  module.py
    core/module.py:42  def process_data
      (input: str, limit: int) -> list
          >>
      (input: str, limit: int, offset: int) -> list

  handlers.py
    api/handlers.py:15  def handle_request
      (request: Request) -> Response
          >>
      (request: Request, timeout: float) -> Response

New API (1):
  utils.py
    core/utils.py:30  def compute_checksum
      (data: bytes, algorithm: str) -> str

Removed API (1):
  core/module.py  def old_helper

New Modules (1):
  handlers.py

Removed Files (1):
  legacy_notes.txt
```

**Updated API** entries show the file name header, a clickable `file:line`
link, the function/class name, then old and new signatures separated by `>>`.
Long signatures wrap at comma boundaries, with continuation lines aligned past
the opening parenthesis.

**New API** entries show the clickable link, name, and signature detail.

**Removed API** entries show the file path and name only (no line numbers since
the element no longer exists).

**Path categories** (packages, modules, files) show indented path strings.

The summary line uses `·` separators. When the summary exceeds the line width,
it splits evenly across two lines.

Empty sections are omitted entirely.

### Log Files

Change logs are written to `logs/trellis/` with timestamped
filenames:

```
logs/trellis/trellis_20260324_143025.txt
```

Log files contain the same content as the console banner. Timestamps use UTC.
Files are written atomically with retry logic and direct-write fallback for
environments where transient file locks occur (e.g. Dropbox, antivirus).

Log files are only created when `LOG_STRUCTURE_CHANGES` is `True` and actual
changes are detected. No log file is created on first run or when the structure
is unchanged.

## Configuration-Only Changes

When the tree content is identical between runs but the `tr_meta` footer
differs (e.g. a visibility flag was toggled), this is a configuration-only
change. With `LOG_CONFIG_ONLY_CHANGES` set to `False` (the default), change
detection is skipped entirely and no changes are reported.

Set `LOG_CONFIG_ONLY_CHANGES` to `True` to detect and report changes even when
the difference is caused by a configuration change.

See [Configuration](configuration.md#tr_meta-encoding) for the `tr_meta`
format.

## Filtering During Detection

Both old and new path sets pass through the same filter pipeline during change
detection. This prevents items from appearing as "added" or "removed" when they
were merely excluded or included by a filter toggle.

Hard ignores always apply regardless of settings. Soft ignores apply when their
corresponding toggle is enabled. Filtering is hierarchy-aware: if an ancestor
directory is ignored, all of its children are too.

## Examples

### First Run

No previous structure file exists. The file is created and no changes are
reported.

```
No project_structure.txt found. Generating now.
```

### No Changes

The structure is identical to the previous run.

```
No structure changes detected.
```

### Added Module

A new Python file was added between runs.

```
====================================================================================================
Structure Changes
  Project:   project
  Summary:   1 new module
====================================================================================================

New Modules (1):
  utils.py
```

### Signature Change

A function signature was modified.

```
====================================================================================================
Structure Changes
  Project:   project
  Log:       trellis_20260324_150000.txt
  Summary:   1 API update
====================================================================================================

Updated API (1):
  module.py
    src/module.py:25  def process_data
      (input: str) -> list
          >>
      (input: str, limit: int) -> list
```
