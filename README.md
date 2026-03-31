# Tools

A collection of Python developer tools for code quality and project visualization.

## Packages

### [Scrutiny](packages/scrutiny/)

Unified code quality orchestration for Python projects. Runs Ruff (formatter +
linter), Mypy, Radon, and Bandit in a single command with tiered strictness,
automatic `pyproject.toml` generation, and context-aware defaults.

```bash
pip install 'ks-scrutiny[all]'
scrutiny
```

**Highlights:**
- Four strictness tiers: essential, standard, strict, insane
- Parallel tool execution
- Auto-detects IDE, CLI, and CI/pipeline contexts
- Generates and manages `pyproject.toml` configuration

### [Trellis](packages/trellis/)

Project structure tree visualizer with Python AST analysis and change tracking.
Scans a directory tree and produces a text representation including classes,
functions, signatures, decorators, and call flow analysis.

```bash
pip install ks-trellis
trellis
```

**Highlights:**
- Python AST extraction: classes, functions, type annotations, decorators
- Call flow analysis for orchestration functions
- Structural change detection between runs
- Zero external dependencies (stdlib only)

## Repository Structure

```
tools/
├── packages/
│   ├── scrutiny/       # Code quality orchestrator
│   └── trellis/        # Project structure visualizer
├── docs/               # Shared coding standards
├── pyproject.toml      # Root linting and test config
└── LICENSE
```

## Requirements

- Python 3.9+

## License

[MIT](LICENSE)
