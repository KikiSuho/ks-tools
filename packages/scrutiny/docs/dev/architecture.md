# Architecture

## Package Layout

```
src/scrutiny/
├── __init__.py
├── __main__.py              # Entry point for python -m scrutiny
├── config.py                # UserDefaults, UserDefaultsSnapshot
├── main.py                  # Orchestration: bootstrap, analysis, reporting
│
├── core/
│   ├── cli.py               # Argument parser, CLI-to-dict, doctor mode
│   ├── enums.py             # ConfigTier, LoggerLevel, PythonVersion, etc.
│   ├── exceptions.py        # SCRError hierarchy, handle_errors decorator
│   └── tool_data.py         # Rule sets, flag maps, tier settings, registry
│
├── configs/
│   ├── dataclasses.py       # GlobalConfig, RuffConfig, MypyConfig, etc.
│   ├── pyproject.py         # PyProjectLoader, PyProjectGenerator
│   └── resolver.py          # ContextDetection, ConfigResolver (5-level)
│
├── execution/
│   ├── handlers.py          # BaseToolHandler + 5 concrete handlers + ToolExecutor
│   ├── issues.py            # RuffIssue, BanditIssue data classes
│   ├── results.py           # ToolResult, ResultTotals
│   └── services.py          # ProjectRootService, FileDiscoveryService, which()
│
├── output/
│   ├── __init__.py          # relative_display_path utility
│   ├── formatting.py        # SourceReader, OutputFormatter, format_and_log_tool_output
│   ├── header.py            # Banner and discovered-files listing
│   ├── logger.py            # DeferredLogBuffer, SCRLogger
│   ├── reporting.py         # Exit code logic and final status table
│   └── run_logging.py       # Per-tool post-execution log output
│
└── platforms/
    ├── __init__.py           # Platform dispatcher
    ├── linux.py              # Linux-specific: setsid, IDE detection
    ├── macos.py              # macOS-specific: setsid, IDE detection
    └── windows.py            # Windows-specific: CREATE_NEW_PROCESS_GROUP
```

## Data Flow

```
CLI arguments
     │
     ▼
 create_argument_parser()  ──►  parse_cli_to_dict()
     │                                │
     │                                ▼
     │                    ┌── ConfigResolver ──┐
     │                    │   5-level chain:   │
     │                    │   CLI              │
     │                    │   pyproject.toml   │
     │                    │   ContextDetection │
     │                    │   UserDefaults     │
     │                    │   Tool defaults    │
     │                    └────────┬───────────┘
     │                             │
     │                             ▼
     │                       GlobalConfig
     │                             │
     ▼                             ▼
 ProjectRootService    FileDiscoveryService
     │                             │
     ▼                             ▼
 effective_root            discovered_files
     │                             │
     └──────────┬──────────────────┘
                │
                ▼
        ToolExecutor.run_tool()
                │
     ┌──────────┼──────────────┐
     ▼          ▼              ▼
  Sequential  Parallel     (per tool)
  ruff_fmt    mypy          BaseToolHandler
  ruff_lint   radon           └── _execute_subprocess()
              bandit              └── ToolResult
                │
                ▼
        log_completed_result()
                │
                ▼
        report_final_status()
                │
                ▼
           exit code
```

## Key Design Patterns

### Double-Build Config Strategy

Configuration resolution uses a two-phase approach:

1. **Preliminary config** — built from CLI args + UserDefaults only (no
   pyproject.toml). Used to run `--generate-config` before the resolver
   reads the file it is about to create.
2. **Full config** — reads the now-fresh pyproject.toml and builds the
   complete five-level GlobalConfig.

This prevents the resolver from reading a stale or nonexistent
pyproject.toml when generation is requested.

### Deferred Log Buffer

Messages captured before the logger exists are stored in
`DeferredLogBuffer` (class-level list with thread lock). Once the
logger is initialized inside a `with` block, buffered messages are
flushed. If the logger never initializes (pre-logger crash), messages
are written to stderr.

### Context-Aware Defaults

`ContextDetection.detect()` checks environment variables and parent
process names to classify the execution environment as CI, pre-commit,
IDE, or CLI. Context-specific defaults (quiet output, no log file,
check-only mode) are injected at priority 3 in the resolution chain.

### Parallel Execution with Sequential Guard

File-modifying tools (ruff_formatter, ruff_linter) run sequentially
first to avoid race conditions on file writes. Read-only analyzers
(mypy, radon, bandit) then run in parallel via `ThreadPoolExecutor`.

### Platform Abstraction

Platform-specific behavior (subprocess creation flags, process
termination, IDE detection data) is isolated in `platforms/`. The
`__init__.py` dispatcher selects the correct module at import time
based on `sys.platform`.

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `main.py` | Top-level orchestration: bootstrap, analysis phase, error boundaries |
| `config.py` | Mutable `UserDefaults` and frozen `UserDefaultsSnapshot` |
| `core/cli.py` | Argument parser, namespace-to-dict conversion, `--doctor` mode |
| `core/enums.py` | All configuration enums (tiers, levels, versions, timeouts) |
| `core/exceptions.py` | `SCRError` hierarchy with exit codes, `@handle_errors` decorator |
| `core/tool_data.py` | Rule sets, CLI flag maps, tier settings, pyproject templates |
| `configs/dataclasses.py` | Frozen config dataclasses with post-init validation |
| `configs/pyproject.py` | TOML loading, key mapping, generation, and merging |
| `configs/resolver.py` | Five-level priority resolution, context detection |
| `execution/handlers.py` | Subprocess execution, JSON parsing, per-tool handlers |
| `execution/services.py` | Project root discovery, file discovery, `which()` |
| `output/formatting.py` | Issue formatting at multiple verbosity tiers |
| `output/logger.py` | Thread-safe dual-level logger with ANSI color support |
| `output/reporting.py` | Exit code computation and final status summary |

## Module Dependency Graph

```
main
 ├── core/cli
 ├── core/exceptions
 ├── core/tool_data
 ├── configs/resolver
 │    ├── config
 │    ├── configs/dataclasses
 │    ├── core/enums
 │    ├── core/exceptions
 │    ├── core/tool_data
 │    └── platforms
 ├── configs/pyproject
 │    ├── core/exceptions
 │    └── core/tool_data
 ├── execution/handlers
 │    ├── core/exceptions
 │    ├── core/tool_data
 │    ├── execution/results
 │    ├── execution/services
 │    ├── execution/issues
 │    ├── output/formatting
 │    └── platforms
 ├── execution/services
 │    ├── core/exceptions
 │    └── platforms
 ├── output/header
 ├── output/logger
 ├── output/reporting
 └── output/run_logging
```

## Testing Structure

Tests mirror the source layout. Source packages get a `pkg_` prefix
to distinguish them from module-level test directories.

```
tests/
├── conftest.py                        # Shared helpers
│
├── test_coverage_gaps.py              # Lifecycle: multi-module pipelines
├── test_cross_module_integration.py   # Lifecycle: config→dispatch→report
├── test_logger_output.py              # Lifecycle: logger→formatter chain
├── test_pipeline_d_coverage.py        # Lifecycle: config→tool dispatch
├── test_stage2_fixes.py               # Lifecycle: bootstrap→analysis
├── test_stage3_coverage.py            # Lifecycle: full pipeline
│
├── config/                            # config.py tests
├── main/                              # main.py tests
├── pkg_core/                          # core/ package tests
│   ├── cli/
│   ├── exceptions/
│   └── tool_data/
├── pkg_configs/                       # configs/ package tests
│   ├── dataclasses/
│   ├── pyproject/
│   └── resolver/
├── pkg_execution/                     # execution/ package tests
│   ├── handlers/
│   ├── issues/
│   └── services/
├── pkg_output/                        # output/ package tests
│   ├── formatting/
│   ├── header/
│   ├── logger/
│   ├── reporting/
│   └── run_logging/
└── pkg_platforms/                     # platforms/ package tests
```

Lifecycle/integration tests that exercise multi-module handoffs remain
at the test root.
