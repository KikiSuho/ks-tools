# Scrutiny

Unified code quality orchestration for Python projects.

Scrutiny runs Ruff (formatter + linter), Mypy, Radon, and Bandit in a
single command with tiered strictness, automatic pyproject.toml
generation, context-aware defaults, and structured logging. Configure
once, enforce everywhere.

## Installation

```bash
# All tools
pip install scrutiny[all]

# Specific tools only
pip install scrutiny[ruff,mypy]

# Core package only (install tools separately)
pip install scrutiny
```

## Quick Start

```bash
# Run with strict tier (default)
python -m scrutiny

# Run on a specific directory
python -m scrutiny src/

# Essential tier (core correctness only)
python -m scrutiny --essential

# Check tool availability
python -m scrutiny --doctor
```

## Output Example

```
======================================================================
Code Quality Analysis
  Project:   my-project
  Tools:     ruff_formatter, ruff_linter, mypy, radon, bandit
  Tier:      strict
  Security:  enabled
  Context:   cli
  Mode:      standard
  Framework: none
  Config:    pyproject.toml unchanged
======================================================================

Running ruff_formatter...
[ruff_formatter]
  Files: 12
  Issues: 0
  Time: 0.02s
  Checked: formatting consistency
  Result: all files formatted

Running ruff_linter...
[ruff_linter]
  Files: 12
  Issues: 0
  Time: 0.03s
  Checked: 54 lint rule groups
  Result: no issues found

Running mypy...
[mypy]
  Files: 12
  Issues: 0
  Time: 0.45s
  Checked: strict type checking, unreachable code, untyped globals
  Result: no type errors

Running radon...
[radon]
  Files: 12
  Issues: 0
  Time: 0.08s
  Checked: cyclomatic complexity (threshold B, max score 10)
  Result: all functions within threshold

Running bandit...
[bandit]
  Files: 12
  Issues: 0
  Time: 0.15s
  Checked: security (MEDIUM+ severity, MEDIUM+ confidence)
  Result: no findings

======================================================================
Script Code: 0
All checks passed (12 files, 0.73s)
  ruff_formatter ... passed
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
| `--standard` | Quality + correctness | Production-ready code |
| `--strict` | Maximum rigor (default) | Enforced style and best practices |
| `--insane` | Every rule enabled | Bulletproof but noisy |

Each tier includes all rules from the tier below it.

## CLI Flags (Summary)

| Flag | Description |
|------|-------------|
| `--tool ruff\|mypy\|radon\|bandit` | Run only specified tool(s) |
| `--fix` / `--check-only` | Enable/disable auto-fix |
| `--parallel` / `--no-parallel` | Parallel tool execution |
| `--generate-config` | Create/merge pyproject.toml |
| `--show-config` | Display effective configuration |
| `--doctor` | Check tool availability |
| `-q` / `-v` / `--detailed` | Output verbosity |

See [docs/cli.md](docs/cli.md) for the complete reference.

## Documentation

- [CLI Reference](docs/cli.md) - All flags with examples
- [Configuration](docs/configuration.md) - Tiers, tool settings, exclusions
- [Architecture](docs/dev/architecture.md) - Package structure and data flow
- [API Reference](docs/dev/api.md) - Public API for programmatic use

## License

See [LICENSE](../../LICENSE).
