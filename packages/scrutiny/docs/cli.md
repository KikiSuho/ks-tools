# CLI Reference

## Usage

```bash
python -m scrutiny [paths...] [options]
```

When no paths are given, the current directory is analyzed.

## Mode Selection

Mutually exclusive flags that set the quality tier.

### `--essential`

Core correctness only. Catches real bugs with minimal noise.

```bash
python -m scrutiny --essential src/
```

### `--standard`

Quality and correctness. Production-ready rule set.

```bash
python -m scrutiny --standard src/
```

### `--strict` (default)

Maximum rigor. Enforces style conventions and best practices.

```bash
python -m scrutiny --strict src/
```

### `--insane`

Every available rule across all tools. Sadistic but bulletproof.

```bash
python -m scrutiny --insane src/
```

## Tool Selection

### `--tool <name>`

Run only the specified tool. Repeatable for multiple tools.

```bash
# Ruff only (formatter + linter)
python -m scrutiny --tool ruff

# Mypy and Radon only
python -m scrutiny --tool mypy --tool radon
```

Valid names: `ruff`, `mypy`, `radon`, `bandit`, `ruff_security`.

### `--no-ruff` / `--no-mypy` / `--no-radon` / `--no-security`

Disable individual tools while keeping the rest.

```bash
# Everything except Mypy
python -m scrutiny --no-mypy
```

### `--security-tool <bandit|ruff_security>`

Override the security tool for IDE/CLI contexts. Default: `bandit`.

### `--pipeline-security-tool <bandit|ruff_security>`

Override the security tool for CI/pipeline contexts. Default: `bandit`.

## Execution

### `--fix`

Enable Ruff auto-fix. Runs a three-pass strategy: check, fix, check remaining.

```bash
python -m scrutiny --fix
```

### `--check-only`

Disable auto-fix and run the formatter in check mode. Automatically
enabled in CI and pre-commit contexts.

### `--unsafe-fixes`

Allow Ruff fixes that may change code semantics.

### `--parallel` / `--no-parallel`

Control parallel tool execution. When enabled (default), file-modifying
tools (ruff_formatter, ruff_linter) run sequentially first, then
read-only analyzers (mypy, radon, bandit) run in parallel.

### `--timeout <seconds>`

Override per-tool execution timeout. Default: 120 seconds.

### `--no-cache`

Disable tool caching entirely for the current run.

### `--clear-cache`

Delete tool cache directories (`.mypy_cache`, `.ruff_cache`,
`__pycache__`) before execution.

## Path Behavior

### `--no-current-dir-as-root`

Disable treating the invocation directory as the project root. Instead,
search upward for project markers (`.git`, `pyproject.toml`, etc.).

### `--max-search-depth <n>`

Maximum parent directories to search for project markers. Default: 8.

### `--follow-symlinks`

Follow symbolic links during file discovery.

### `--exclude-dir <dir>`

Add a directory name to the exclusion list. Repeatable.

```bash
python -m scrutiny --exclude-dir migrations --exclude-dir generated
```

### `--exclude-file <pattern>`

Add a file pattern to the exclusion list. Repeatable.

## Configuration Generation

### `--generate-config`

Create or merge a `pyproject.toml` with tool configuration sections
matching the active tier.

```bash
# Generate config at strict tier
python -m scrutiny --strict --generate-config
```

### `--override-config`

With `--generate-config`: overwrite existing `[tool.*]` sections
instead of merging missing keys only.

### `--config-in-cwd`

With `--generate-config`: write to the current directory instead of
the discovered project root.

### `--include-test-config`

Include `[tool.pytest.ini_options]` and `[tool.coverage.*]` sections
in the generated pyproject.toml.

### `--include-test-plugins`

With `--include-test-config`: add pytest-cov, pytest-xdist,
required_plugins, and duration reporting.

### `--pyproject-only`

Use pyproject.toml as the sole configuration source, bypassing script
defaults (priorities 4-5 in the resolution chain). CLI arguments still
take precedence.

## Code Style

### `--line-length <n>`

Override the maximum line length. Default: 100.

### `--python-version <ver>`

Override the target Python version (e.g., `py39`, `py312`). Default: `py39`.

### `--framework <name>`

Enable framework-specific Ruff rules.

Valid names: `none`, `django`, `fastapi`, `airflow`, `numpy`, `pandas`.

## Output

### `-q` / `--quiet`

Minimal terminal output. Status, success, and error messages only.

### `--detailed`

Issues with metadata (fixable flags, URLs, error codes) and source
code context around each issue.

### `-v` / `--verbose`

Everything from `--detailed` plus items fixed by Ruff, subprocess
commands, and exit code metadata.

## File Logging

### `--no-log`

Disable log file creation entirely.

### `--log-location <project_root|current_dir|hybrid>`

Control where log files are placed.

| Value | Behavior |
|-------|----------|
| `project_root` | Discovered project root. Disables logging if no root found. |
| `current_dir` | Invocation directory. Always works. |
| `hybrid` | Project root if found, otherwise current directory. Default. |

### `--log-dir <dir>`

Override the log file directory (relative to log location root).
Default: `logs/scrutiny/`.

### `--file-log-level <quiet|normal|detailed|verbose>`

Set file log verbosity independently of console output.

## Diagnostics

### `--show-config`

Display effective configuration and exit without running analysis.

```bash
python -m scrutiny --show-config
```

### `--doctor`

Check availability and versions of all required tools.

```bash
python -m scrutiny --doctor
```

### `--version`

Print version and exit.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | General error |
| 2 | System requirements not met |
| 3 | Cannot determine project root |
| 4 | Tool execution failure |
| 5 | Invalid user input |
| 6 | Invalid configuration |
| 7 | Logger error |
| 8 | Unexpected error |
| 10 | Issues found (all tools ran) |
| 11 | Tool execution failure during analysis |

## Examples

### CI pipeline gate

```bash
python -m scrutiny --strict --check-only --no-log -q src/
```

### Generate pyproject.toml for a new project

```bash
python -m scrutiny --strict --generate-config --include-test-config
```

### Debug a single file with full output

```bash
python -m scrutiny -v --tool mypy src/module.py
```
