# Configuration

## Priority Chain

Configuration values are resolved through a five-level priority chain
(highest to lowest):

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | CLI arguments | Flags passed on the command line |
| 2 | pyproject.toml | `[tool.*]` sections from the project file |
| 3 | Context detection | Values derived from execution environment |
| 4 | Script defaults | `UserDefaults` class attributes |
| 5 | Tool defaults | Built-in fallback values |

When `--pyproject-only` is set, priorities 4 and 5 are skipped so
pyproject.toml is the sole authoritative source (CLI still wins).

## Configuration Tiers

Each tier includes all rules from the tier below it.

### Essential

Core correctness only. Pyflakes undefined names, unused imports,
and basic pycodestyle errors.

**Ruff rules:** `E4`, `E7`, `E9`, `F`
**Mypy:** no strict mode, no unreachable warnings
**Radon:** threshold D (very complex, 21-30)
**Bandit:** HIGH severity, HIGH confidence

### Standard (default)

Quality and correctness. Adds flake8-bugbear, import sorting,
naming conventions, comprehension checks, and more.

**Ruff rules:** Essential + `A`, `B`, `C4`, `I`, `ISC`, `N`, `RET`, `SIM`, `UP`, `YTT`
**Mypy:** warn unreachable
**Radon:** threshold C (complex, 11-20)
**Bandit:** MEDIUM severity, HIGH confidence

### Strict

Maximum rigor. Adds docstring conventions, exception handling
patterns, logging rules, performance checks, and Pylint subsets.

**Ruff rules:** Standard + `D`, `DOC`, `ARG`, `ASYNC`, `BLE`, `DTZ`, `ERA`, `FIX`, `FURB`, `PIE`, `SLF`, `G`, `LOG`, `INP`, `TID`, `PERF`, `T10`, `T20`, `PGH`, `PLE`, `PLW`, `PTH`, `RUF`, cherry-picked `PLR`, `E501`
**Mypy:** strict mode, warn unreachable, disallow untyped globals
**Radon:** threshold B (moderate, 6-10)
**Bandit:** MEDIUM severity, MEDIUM confidence

### Insane

Every available rule. Adds trailing comma enforcement, boolean trap
detection, quote consistency, TODO formatting, and full Pylint.

**Ruff rules:** Strict + `COM`, `EM`, `FBT`, `ICN`, `Q`, `SLOT`, `TD`, `EXE`, `PLC`, `PLR` (full), `E` (full), `W` (full)
**Mypy:** strict + disallow any explicit
**Radon:** threshold A (simple, 1-5)
**Bandit:** LOW severity, MEDIUM confidence

## Tool Settings

### Ruff

| Setting | Default | CLI Flag |
|---------|---------|----------|
| Run formatter | `False` (opt-in) | `--tool ruff_formatter` or `--tool ruff` |
| Run linter | `True` | `--tool ruff_linter` or `--no-ruff` |
| Fix mode | `False` (opt-in) | `--fix` / `--check-only` |
| Unsafe fixes | `False` | `--unsafe-fixes` |
| Line length | 100 | `--line-length` |
| Target version | py39 | `--python-version` |
| Framework rules | none | `--framework` |

### Mypy

Values shown are for the ``strict`` tier; ``essential`` and ``standard``
relax ``strict_mode`` and ``disallow_untyped_globals`` to ``False``.

| Setting | Strict tier | Description |
|---------|-------------|-------------|
| `strict_mode` | `True` | Enable all strict checks |
| `warn_unreachable` | `True` | Flag unreachable code |
| `disallow_untyped_globals` | `True` | Reject untyped module-level variables |
| `ignore_missing_imports` | `True` | Suppress missing stub errors |
| `show_column_numbers` | `True` | Include column in output |
| `show_error_codes` | `True` | Show error code with each issue |

### Radon

| Setting | Strict Default | Description |
|---------|---------------|-------------|
| `minimum_complexity` | B | Maximum acceptable complexity grade |
| `show_average` | `True` | Display average complexity |
| `show_closures` | `True` | Include closures in analysis |

Complexity grades: A (1-5), B (6-10), C (11-20), D (21-30), E (31-40), F (41+).

### Bandit

| Setting | Strict Default | Description |
|---------|---------------|-------------|
| `severity` | medium | Minimum severity threshold |
| `confidence` | medium | Minimum confidence threshold |

## Context Detection

Scrutiny auto-detects the execution environment and adjusts defaults:

| Context | Detection | Adjustments |
|---------|-----------|-------------|
| **CI** | `CI`, `GITHUB_ACTIONS`, `JENKINS_URL`, etc. | Quiet output, no log file, check-only mode |
| **Pre-commit** | `PRE_COMMIT`, parent process name | Same as CI |
| **IDE** | `VSCODE_PID`, `PYCHARM_HOSTED`, parent process | Standard defaults |
| **CLI** | Fallback | Standard defaults |

CI and pre-commit contexts automatically enable `--check-only` and
`--quiet`, and disable log file creation.

## Security Tool Selection

Two security backends are available:

| Tool | Description | Context |
|------|-------------|---------|
| **Bandit** | Full analysis with severity/confidence filtering | IDE/CLI default |
| **Ruff S-rules** | Fast Ruff-native security rules, no filtering | Alternative |

The security tool can differ between IDE/CLI and pipeline contexts:

```bash
python -m scrutiny --security-tool bandit --pipeline-security-tool ruff_security
```

## Exclusions

### Standard Exclusions (always applied)

Directories universally irrelevant to code analysis are always excluded:

`.git`, `__pycache__`, `dist`, `build`, `.venv`, `venv`, `.eggs`,
`site-packages`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`,
`.tox`, `.nox`, `node_modules`, `.idea`, `.vscode`, `.claude`

### Project Exclusions

Add project-specific exclusions via `UserDefaults` or CLI:

```bash
python -m scrutiny --exclude-dir migrations --exclude-file "generated_*.py"
```

Default project exclusion: `tests` directory.

### Radon Exclusions

Radon automatically excludes test directories from complexity analysis:
`test`, `tests`, `spec`, `specs`, `examples`, `example`.

## pyproject.toml Integration

### Reading

Scrutiny reads existing `[tool.*]` sections from pyproject.toml and
maps native TOML keys to internal configuration. Supported sections:

- `[tool.ruff]` - `line-length`, `target-version`, `fix`, `unsafe-fixes`
- `[tool.ruff.lint]` - `select`, `ignore`
- `[tool.mypy]` - `python_version`, `strict`, `warn_unreachable`,
  `ignore_missing_imports`, and more
- `[tool.bandit]` - `exclude_dirs`, `skips`

### Runtime priority

At runtime scrutiny enforces a strict contract when building tool
commands: **CLI override > pyproject.toml > scrutiny defaults**.
If a key appears in pyproject.toml, scrutiny does not emit a CLI
flag that would shadow it. This means `fix = false` in
`[tool.ruff]` actually disables auto-fix, and `exclude = [...]` in
`[tool.ruff]` is read natively by ruff. The same holds for mypy
and bandit.

Additional notes:

- `line-length` accepts any integer in `[40, 500]`; it is not
  restricted to scrutiny's ``LineLength`` enum members.
- Framework rule families (`--framework django`, etc.) are emitted
  via `--extend-select`, so they supplement your pyproject `select`
  rather than replacing it.
- Operational flags with no pyproject equivalent (``--no-cache``,
  JSON output) emit regardless of mode.

### Generation

Generation is opt-in via an explicit flag. Running `scrutiny` by
itself analyses your code without touching pyproject.toml.

| Flag | Generates |
|------|-----------|
| `--generate-config` | `[tool.ruff]`, `[tool.mypy]`, `[tool.bandit]` |
| `--generate-config=test` | Above + `[tool.pytest.ini_options]` + `[tool.coverage.*]` |
| `--generate-config=all` | Above + pytest plugin addopts |
| `--generate-test-config` | Only test sections (no managed tool sections) |
| `--generate-test-config=plugins` | Only test sections with plugin addopts |

`--generate-config` and `--generate-test-config` are mutually
exclusive. Combine either with `--override-config` to replace
existing managed sections instead of merging missing keys.

Managed tool sections: `ruff`, `mypy`, `bandit`. Test sections
(`pytest`, `coverage`) are always merged; `--override-config` does
not apply to them.

## Logging

### Console Levels

| Level | Content |
|-------|---------|
| QUIET | Status, success, and error messages only |
| NORMAL | + summary + single-line issues |
| DETAILED | + metadata (fixable flags, URLs) + source context |
| VERBOSE | + fixed items + subprocess commands |

### File Logging

Log files are placed according to `--log-location` (default: `hybrid`).
File log level defaults to VERBOSE for a complete audit trail.

Log files use UTC timestamps: `scrutiny_YYYYMMDD_HHMMSS.log`.

### Log Placement

| Mode | Behavior |
|------|----------|
| `project_root` | Discovered project root; disables logging if no root found |
| `current_dir` | Invocation directory; always works |
| `hybrid` | Project root if found, otherwise current directory |
