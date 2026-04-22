# Changelog

All notable changes to `ks-scrutiny` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.1] - 2026-04-21

Patch release. Adds the missing positive form of `--current-dir-as-root`,
fixes `--override-config` so it covers test sections, and retires an
internal constant that no longer has a caller.

### Added

- **`--current-dir-as-root` CLI flag** (positive form). Previously only
  `--no-current-dir-as-root` existed, which was a no-op given the
  `False` default and left users no CLI path to enable CWD-as-root for
  a single invocation. The two flags now live in a mutually exclusive
  argparse group, so passing both raises an argparse error at parse
  time rather than letting extractor precedence silently decide the
  winner.

### Fixed

- **`scrutiny --generate-config=all --override-config` now overwrites
  `[tool.pytest.ini_options]` and `[tool.coverage.*]` sections.**
  Previously `PyProjectGenerator._override_key_level` iterated a
  hard-coded set of managed tools (`ruff`, `mypy`, `bandit`) and
  skipped pytest and coverage entirely. Stale test settings were
  preserved on override and `[tool.coverage.report]` was dropped when
  absent from the existing file. The override now walks whatever
  top-level `[tool.*]` sections appear in the generated TOML, so test
  sections are included iff the user asked for them via
  `--generate-config=test` / `=all` or
  `--generate-test-config[=plugins]`. Non-generated tool sections
  (including any unmanaged `[tool.*]`) remain untouched.

### Internal

- Removed the unused `MANAGED_TOOL_NAMES` constant from
  `core/tool_data.py`. `PyProjectGenerator._render_templates` is now
  the authoritative scope of what `--override-config` will replace.
  See `ROADMAP.md` Phase 2 blocker #3 for how this interacts with a
  future `[tool.scrutiny]` section.


## [4.0.0] - 2026-04-22

Major release with **breaking behaviour changes**, a fix for a priority-chain
bug that let scrutiny silently override user pyproject.toml settings, and a
hardening pass against subprocess flag injection from crafted pyproject.toml
files. Users upgrading from 3.1.x should read the Migration section below.

### Changed (breaking)

- **Default tier is now `STANDARD`** (was `STRICT`). Running `scrutiny` with
  no flags now enables the production-ready rule set rather than the full
  strict rule set including docstrings and Pylint. Pass `--strict` to keep
  the previous default.
- **Auto-fix is now opt-in**. `RUFF_FIX` default is `False`. Running
  `scrutiny` no longer rewrites source files. Pass `--fix` to enable the
  three-pass fix strategy.
- **Ruff formatter is opt-in**. `RUN_RUFF_FORMATTER` default is `False`.
  A plain `scrutiny` run no longer invokes `ruff format`. Pass
  `--tool ruff_formatter` or `--tool ruff` to include it.
- **pyproject.toml auto-generation is opt-in**. `SCR_GENERATE_CONFIG`
  default is `False`. A plain `scrutiny` run no longer creates or merges
  any `pyproject.toml` sections. Use `--generate-config[=test|all]` or
  `--generate-test-config[=plugins]` to bootstrap or update config.
- **CLI flags `--include-test-config` and `--include-test-plugins` removed.**
  Replaced by the mode-valued forms:
  - `--generate-config=test` (equivalent to old `--generate-config
    --include-test-config`)
  - `--generate-config=all` (equivalent to old `--generate-config
    --include-test-config --include-test-plugins`)
  - `--generate-test-config` (new; generates only test sections)
  - `--generate-test-config=plugins` (new; test sections plus plugin addopts)
- **`--generate-config` and `--generate-test-config` are mutually exclusive**.
  Passing both raises an argparse error.
- **`GlobalConfig.line_length` is now `int`, not `LineLength` enum**.
  Values from pyproject.toml are no longer rejected for not matching an
  enum member; any integer in `[40, 500]` is accepted. Programmatic
  callers constructing `GlobalConfig` with a `LineLength` member still
  work (it is an `IntEnum`) but the stored attribute is a plain `int`.
- **Log listing of discovered files moved to the DETAILED log level**.
  Terminal output at the default verbosity no longer includes the
  two-column file listing; it now appears at `--detailed` or `--verbose`,
  and is always present in the per-run log file.

### Fixed

- **Priority-chain bug (critical)**: scrutiny now honours pyproject.toml
  settings at runtime. Previously `[tool.ruff] fix = false` and
  `[tool.ruff] exclude = [...]` were silently overridden because scrutiny
  emitted its own `--fix` and `--exclude` flags on every run. The new
  contract is: explicit scrutiny CLI overrides win over everything,
  then pyproject.toml, then scrutiny's own defaults fill gaps.
  Implemented via `GlobalConfig.should_emit` gating every flag emission
  in the execution handlers.
- **`_FieldSpec` entries for `fix` and `unsafe_fixes` previously lacked
  pyproject mappings**, causing their resolver path to ignore pyproject
  values and always fall through to script defaults.
- **Framework rule families are now additive**. Passing `--framework django`
  no longer replaces the user's pyproject `select` list; it emits the
  framework rules via `--extend-select` so they supplement rather than
  override the pyproject configuration.
- **`pyproject_only` mode consistency**. `GlobalConfig.pyproject_only` now
  tracks the resolver's actual mode rather than resolving independently
  through the field-spec chain; handlers see a consistent state.

### Added

- **Argv-safety validators** (`_check_argv_safe` / `_check_path_safe` in
  `configs/dataclasses.py`) reject pyproject.toml values that could
  inject additional CLI flags into the downstream tool through
  comma-joined or `=`-joined flag templates. Tokens cannot start with
  `-`, contain `=`, `,`, whitespace, or null bytes; path entries cannot
  start with `-`, contain null bytes, or newlines. Applied to every
  subprocess-bound field on `RuffConfig`, `MypyConfig`, `RadonConfig`,
  `BanditConfig`.
- **`__version__` attribute** on `scrutiny` package, sourced via
  `importlib.metadata.version("ks-scrutiny")` with a fallback for
  development checkouts.
- **`--generate-test-config[=plugins]` flag** for scoped test-config
  generation on projects that already have their ruff/mypy/bandit
  sections in place.
- **"No config found" hint** printed at the end of a run when no managed
  pyproject section is detected and the user did not generate on this
  invocation; pointing at `scrutiny --generate-config`.
- **New provenance fields on `GlobalConfig`**: `cli_override_keys` and
  `pyproject_native_pairs` track the origin of every resolved value so
  handlers can make suppression decisions. `GlobalConfig.should_emit`
  exposes the decision function for downstream consumers.
- **`PyProjectLoader.collect_native_keys`** returns the raw native keys
  present in each managed tool section, enabling suppression of
  scrutiny-built flags when the user has expressed the equivalent
  native setting.
- **Regression test coverage**: 11 priority-chain tests
  (`test_pyproject_priority.py`), 16 handler suppression tests
  (`test_pyproject_suppression.py`), 27 argv-safety tests
  (`test_argv_safety.py`).

### Migration from 3.1.x to 4.0.0

1. **Auto-fix stops on upgrade.** If your workflow relied on
   `scrutiny` running `ruff check --fix` by default, add `--fix` to
   your invocations, or set `RUFF_FIX = True` in a future
   `[tool.scrutiny]` block (see Roadmap).
2. **Formatter stops on upgrade.** Same treatment: add
   `--tool ruff_formatter` (or `--tool ruff` to run both capabilities)
   or set `RUN_RUFF_FORMATTER = True`.
3. **Config auto-generation stops on upgrade.** Run
   `scrutiny --generate-config` once to re-bootstrap, or pass the flag
   on each invocation if you prefer tier-matched regeneration.
4. **Default rule set shrinks.** If you want strict rules, add `--strict`
   to your invocations.
5. **`--include-test-config` / `--include-test-plugins` removed.**
   Replace with `--generate-config=test` / `--generate-config=all`, or
   `--generate-test-config[=plugins]` for test-only scoping.
6. **Crafted pyproject values may now be rejected.** Any rule token,
   version string, or exclusion path that starts with `-` or contains
   `=`, `,`, or whitespace will raise `SCRConfigurationError` at
   resolver-boundary time. This is a security feature; legitimate
   tokens are unaffected.


## [3.1.3] - prior release

See git history for prior versions.
