# API Reference

Public API surface for programmatic use of scrutiny.

## Entry Point

### `main() -> int`

**Module:** `scrutiny.main`

Orchestrate the full scrutiny pipeline: argument parsing, configuration
resolution, file discovery, tool execution, and result reporting.

```python
from scrutiny.main import main

exit_code = main()
```

Returns 0 on success, 10 when issues are found, 11 on tool failure.

## Configuration

### `UserDefaults`

**Module:** `scrutiny.config`

Mutable class-level defaults controlling script behavior. Edit these
to change defaults without modifying execution logic.

```python
from scrutiny.config import UserDefaults

UserDefaults.SCR_CONFIG_TIER = ConfigTier.STANDARD
UserDefaults.RUN_RADON = False
```

### `UserDefaultsSnapshot`

**Module:** `scrutiny.config`

Frozen dataclass snapshot of `UserDefaults`, created at bootstrap via
`UserDefaults.to_frozen()`. Downstream code reads from the snapshot
without risk of mutation.

```python
snapshot = UserDefaults.to_frozen()
snapshot.scr_config_tier  # ConfigTier.STRICT
```

### `GlobalConfig`

**Module:** `scrutiny.configs.dataclasses`

Frozen dataclass containing all resolved configuration. Populated by
`ConfigResolver` or constructed directly in tests.

```python
from scrutiny.configs.dataclasses import GlobalConfig

config = GlobalConfig(config_tier=ConfigTier.ESSENTIAL)
config.get_enabled_tools(context)  # ["ruff_formatter", "ruff_linter", ...]
config.effective_fix  # True when fix=True and check_only=False
```

### `ConfigResolver`

**Module:** `scrutiny.configs.resolver`

Five-level priority resolver that combines CLI arguments, pyproject.toml,
context detection, script defaults, and tool defaults.

```python
from scrutiny.configs.resolver import ConfigResolver

resolver = ConfigResolver(
    cli_args={"config_tier": ConfigTier.STRICT},
    pyproject_config={},
    context=ContextDetection.CLI,
    tier=ConfigTier.STRICT,
)
global_config = resolver.build_global_config()
ruff_config = resolver.build_ruff_config(global_config)
```

**Builder methods:**
- `build_global_config() -> GlobalConfig`
- `build_ruff_config(global_config) -> RuffConfig`
- `build_mypy_config(global_config) -> MypyConfig`
- `build_radon_config(global_config) -> RadonConfig`
- `build_bandit_config(global_config) -> BanditConfig`
- `build_ruff_security_config(global_config) -> RuffConfig`

### `ContextDetection`

**Module:** `scrutiny.configs.resolver`

Enum with auto-detection classmethod.

```python
from scrutiny.configs.resolver import ContextDetection

context = ContextDetection.detect()  # CI, PRECOMMIT, IDE, or CLI
```

**Members:** `CI`, `PRECOMMIT`, `IDE`, `CLI`

## Tool Configuration Dataclasses

**Module:** `scrutiny.configs.dataclasses`

All are frozen dataclasses with post-init validation.

- `RuffConfig` — select_rules, ignore_rules, line_length, target_version, fix, unsafe_fixes, no_cache, exclude_dirs, exclude_files
- `MypyConfig` — strict_mode, warn_unreachable, disallow_untyped_globals, python_version, exclude_dirs, exclude_files
- `RadonConfig` — minimum_complexity, show_average, show_closures, json_output, exclude_dirs, exclude_files
- `BanditConfig` — severity, confidence, quiet, skip_tests, exclude_dirs, exclude_files

## Execution

### `ToolExecutor`

**Module:** `scrutiny.execution.handlers`

Dispatcher that lazily creates tool handlers and routes execution.

```python
from scrutiny.execution.handlers import ToolExecutor

executor = ToolExecutor(timeout=120)
result = executor.run_tool("mypy", files, mypy_config, global_config, root)
```

### `ToolResult`

**Module:** `scrutiny.execution.results`

Dataclass returned by every tool execution.

```python
result.tool            # "mypy"
result.success         # True/False
result.exit_code       # subprocess exit code
result.issues_found    # number of issues detected
result.issues_fixed    # number of issues auto-fixed
result.execution_time  # wall-clock seconds
result.tool_data       # dict with parsed issues, command, etc.
result.error_code      # SCRError exit code (0 = no error)
```

### `FileDiscoveryService`

**Module:** `scrutiny.execution.services`

Recursive `.py` file discovery with exclusion filtering.

```python
from scrutiny.execution.services import FileDiscoveryService

files = FileDiscoveryService.discover_files([Path("src/")], global_config)
```

### `ProjectRootService`

**Module:** `scrutiny.execution.services`

Upward-search project root discovery.

```python
from scrutiny.execution.services import ProjectRootService

root = ProjectRootService.get_project_root(Path("."), global_config)
```

**Markers:** `.git`, `pyproject.toml`, `setup.py`, `setup.cfg`,
`requirements.txt`, `Pipfile`, `.hg`, `.svn`

### `which(command_name) -> Optional[str]`

**Module:** `scrutiny.execution.services`

PATH-aware executable locator. Checks the interpreter's directory first
so conda/venv tools are found even without activation.

```python
from scrutiny.execution.services import which

path = which("ruff")  # "/path/to/ruff" or None
```

## Issue Data Classes

**Module:** `scrutiny.execution.issues`

### `RuffIssue`

Parsed from Ruff JSON output.

```python
issue.code        # "F401"
issue.message     # "unused import"
issue.line        # 42
issue.column      # 1
issue.filename    # "/path/to/file.py"
issue.fixable     # True/False
issue.url         # "https://docs.astral.sh/ruff/rules/F401"
```

### `BanditIssue`

Parsed from Bandit JSON output.

```python
issue.test_id      # "B201"
issue.severity     # "HIGH"
issue.confidence   # "MEDIUM"
issue.line_number  # 15
issue.filename     # "/path/to/file.py"
issue.issue_text   # "Use of exec detected"
issue.meets_threshold("medium", "medium")  # True/False
```

## Output

### `SCRLogger`

**Module:** `scrutiny.output.logger`

Thread-safe, dual-level logger with console and file output.

```python
from scrutiny.output.logger import SCRLogger

logger = SCRLogger(project_root, global_config)
with logger:
    logger.status("Running analysis...")
    logger.error("Something failed")
    logger.debug("Verbose detail")
```

**Methods by level:**
- QUIET: `status()`, `success()`, `error()`
- NORMAL: `warning()`, `result()`, `header()`, `issue()`
- DETAILED: `detail()`
- VERBOSE: `info()`, `debug()`

### `DeferredLogBuffer`

**Module:** `scrutiny.output.logger`

Class-level message buffer for pre-logger messages.

```python
from scrutiny.output.logger import DeferredLogBuffer

DeferredLogBuffer.capture("warning", "No project root found")
DeferredLogBuffer.flush(logger)  # or flush_or_stderr() without a logger
```

### `OutputFormatter`

**Module:** `scrutiny.output.formatting`

Static methods for formatting tool output at multiple verbosity tiers.

```python
from scrutiny.output.formatting import OutputFormatter

summary = OutputFormatter.generate_summary("mypy", 10, 2, 0, 0.45)
issues = OutputFormatter.format_at_level("mypy", tool_data, LoggerLevel.DETAILED, root)
checked, result_msg = OutputFormatter.get_tool_context("mypy", mypy_config)
```

## Enums

**Module:** `scrutiny.core.enums`

| Enum | Members |
|------|---------|
| `ConfigTier` | ESSENTIAL, STANDARD, STRICT, INSANE |
| `SecurityTool` | BANDIT, RUFF |
| `LogLocation` | PROJECT_ROOT, CURRENT_DIR, HYBRID |
| `LoggerLevel` | QUIET (1), NORMAL (2), DETAILED (3), VERBOSE (4) |
| `PythonVersion` | PY39, PY310, PY311, PY312, PY313 |
| `LineLength` | PEP8 (79), BLACK (88), STANDARD (100), RELAXED (120) |
| `SearchDepth` | SHALLOW (3), MODERATE (5), DEFAULT (8), DEEP (10) |
| `ToolTimeout` | QUICK (30), STANDARD (60), PATIENT (120), GENEROUS (300), EXTENDED (600) |
| `FrameworkSelection` | NONE, DJANGO, FASTAPI, AIRFLOW, NUMPY, PANDAS |
| `ConfigSource` | CLI, PYPROJECT, CONTEXT, SCRIPT, TOOL_DEFAULT |

## Exceptions

**Module:** `scrutiny.core.exceptions`

All exceptions derive from `SCRError`. Each maps to an `ExitCode`.

| Exception | Exit Code | Tag |
|-----------|-----------|-----|
| `SCRError` | 1 (GENERAL) | [ERROR] |
| `SCRSystemError` | 2 | [SYSTEM] |
| `SCRProjectRootError` | 3 | [PROJECT] |
| `SCRToolExecutionError` | 4 | [TOOL] |
| `SCRTimeoutError` | 4 | [TIMEOUT] |
| `SCRUserInputError` | 5 | [INPUT] |
| `SCRConfigurationError` | 6 | [CONFIG] |
| `SCRLoggerError` | 7 | [LOGGER] |
| `SCRLoggerLevelError` | 7 | [LOGGER] |
| `SCRLoggerFileError` | 7 | [LOGGER] |
| `SCRUnexpectedError` | 8 | [UNEXPECTED] |
