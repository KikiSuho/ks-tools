# Scrutiny

Unified code quality orchestration for Python projects.

Scrutiny runs Ruff (formatter + linter), Mypy, Radon, and Bandit in a
single command with tiered strictness, opt-in pyproject.toml
generation, context-aware defaults, and structured logging. Scrutiny
respects your pyproject.toml as the authoritative source and never
modifies it unless you explicitly ask. Configure once, enforce
everywhere.

## Installation

```bash
# All tools
pip install ks-scrutiny[all]

# Specific tools only
pip install ks-scrutiny[ruff,mypy]

# Core package only (install tools separately)
pip install ks-scrutiny
```

## Configuration Precedence

Scrutiny follows a strict priority contract when building tool
commands:

1. **Explicit scrutiny CLI overrides** win over everything.
2. **`pyproject.toml`** is authoritative when the CLI is silent.
3. **Scrutiny's own defaults** only fill in keys neither source has expressed.

Concretely: if you set `fix = false` under `[tool.ruff]`, scrutiny
will **not** pass `--fix` to ruff. If you set `exclude = [...]` under
`[tool.ruff]`, scrutiny will not emit its own `--exclude` flags,
letting ruff read the pyproject list natively. The equivalent rule
holds for mypy and bandit. Operational concerns that have no
pyproject equivalent (`--no-cache`, JSON output formatting) still
emit regardless.

Use `--pyproject-only` to suppress scrutiny defaults entirely;
tools then run with only your CLI overrides and pyproject settings.

Framework-specific rule families (`--framework django`, etc.) are
emitted as `--extend-select` so they supplement rather than replace
your pyproject `select` list when it exists.

## pyproject.toml Management

Running `scrutiny` does **not** modify your `pyproject.toml`. It reads
whatever is there, respects it, and analyses your code. Config
generation is an explicit, one-time action via an opt-in flag.

**Managed sections:** `[tool.ruff]`, `[tool.mypy]`, `[tool.bandit]`,
and optionally `[tool.pytest.ini_options]` + `[tool.coverage.*]`. All
other tool sections are never touched.

### Generation flags

| Flag | Generates |
|---|---|
| `--generate-config` | `[tool.ruff]`, `[tool.mypy]`, `[tool.bandit]` |
| `--generate-config=test` | Above + `[tool.pytest.ini_options]` + `[tool.coverage.*]` |
| `--generate-config=all` | Above + pytest plugin addopts (pytest-cov, pytest-xdist) |
| `--generate-test-config` | Only `[tool.pytest.ini_options]` + `[tool.coverage.*]` |
| `--generate-test-config=plugins` | Only test sections with plugin addopts |

`--generate-config` and `--generate-test-config` are mutually
exclusive. Combine either with `--override-config` to replace
existing managed sections instead of merging.

### Merge vs override

| Scenario | Default (merge) | With `--override-config` |
|----------|-----------------|--------------------------|
| Key exists in your file | Preserved | Replaced with generated |
| Key missing from your file | Added | Added |
| Unmanaged tool sections | Untouched | Untouched |

Generated settings are tier-aware; the rules, strictness, and
thresholds written to your config match your selected tier (essential,
standard, strict, or insane).

## Quick Start

```bash
# Run analysis with the standard tier (default); read-only, does not modify files
scrutiny

# Bootstrap managed [tool.*] sections on first use
scrutiny --generate-config

# Run on a specific directory
scrutiny src/

# Opt into auto-fix and formatting
scrutiny --fix --tool ruff

# Strict tier for maximum rigor
scrutiny --strict

# Check tool availability
scrutiny --doctor
```

## Output Example

```
======================================================================
Code Quality Analysis
  Project:   my-project
  Tools:     ruff_linter, mypy, radon, bandit
  Tier:      standard
  Security:  enabled
  Context:   cli
  Mode:      standard
  Framework: none
======================================================================

Running ruff_linter...
[ruff_linter]
  Files: 12
  Issues: 0
  Time: 0.03s
  Checked: 22 lint rule groups
  Result: no issues found

Running mypy...
[mypy]
  Files: 12
  Issues: 0
  Time: 0.45s
  Checked: warn unreachable, ignore missing imports
  Result: no type errors

Running radon...
[radon]
  Files: 12
  Issues: 0
  Time: 0.08s
  Checked: cyclomatic complexity (threshold C, max score 20)
  Result: all functions within threshold

Running bandit...
[bandit]
  Files: 12
  Issues: 0
  Time: 0.15s
  Checked: security (MEDIUM+ severity, HIGH+ confidence)
  Result: no findings

======================================================================
Script Code: 0
All checks passed (12 files, 0.73s)
  ruff_linter    ... passed
  mypy           ... passed
  radon          ... passed
  bandit         ... passed
======================================================================
```

## Configuration Tiers

| Tier | Description | Use Case |
|------|-------------|----------|
| `--essential` | Core correctness only | Legacy codebases, quick checks |
| `--standard` | Quality + correctness (default) | Production-ready code |
| `--strict` | Maximum rigor | Enforced style and best practices |
| `--insane` | Every rule enabled | Bulletproof but noisy |

Each tier includes all rules from the tier below it.

## CLI Flags (Summary)

| Flag | Description |
|------|-------------|
| `--tool ruff\|mypy\|radon\|bandit` | Run only specified tool(s) |
| `--essential` / `--standard` / `--strict` / `--insane` | Select quality tier |
| `--fix` / `--check-only` | Enable/disable auto-fix |
| `--parallel` / `--no-parallel` | Parallel tool execution |
| `--generate-config[=test\|all]` | Create/merge managed pyproject sections |
| `--generate-test-config[=plugins]` | Create/merge only test sections |
| `--override-config` | Replace (not merge) managed sections on generation |
| `--pyproject-only` | Use pyproject + CLI only; bypass scrutiny defaults |
| `--show-config` | Display effective configuration |
| `--doctor` | Check tool availability |
| `-q` / `-v` / `--detailed` | Output verbosity |

See [CLI Reference](https://github.com/KikiSuho/ks-tools/blob/main/packages/scrutiny/docs/cli.md) for the complete reference.

## Documentation

- [CLI Reference](https://github.com/KikiSuho/ks-tools/blob/main/packages/scrutiny/docs/cli.md) - All flags with examples
- [Configuration](https://github.com/KikiSuho/ks-tools/blob/main/packages/scrutiny/docs/configuration.md) - Tiers, tool settings, exclusions
- [Architecture](https://github.com/KikiSuho/ks-tools/blob/main/packages/scrutiny/docs/dev/architecture.md) - Package structure and data flow
- [API Reference](https://github.com/KikiSuho/ks-tools/blob/main/packages/scrutiny/docs/dev/api.md) - Public API for programmatic use

## License

See [LICENSE](https://github.com/KikiSuho/ks-tools/blob/main/LICENSE).
