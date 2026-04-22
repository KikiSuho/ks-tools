# Roadmap

Planned work beyond the 4.0.0 release. Each section lists concrete
items with enough context to pick them up cold. File/line references
are current as of 4.0.0 and may drift; re-locate by symbol when
starting the work.

---

## Phase 2: `[tool.scrutiny]` pyproject section

Let users persist scrutiny's own defaults (`UserDefaults` equivalents)
per project via a `[tool.scrutiny]` section instead of editing the
installed package source.

### Blockers to resolve before it can land cleanly

1. **`_FieldSpec` cannot source the same field from two pyproject sections.**
   `configs/resolver.py::_GLOBAL_CONFIG_FIELDS` binds each field to exactly
   one `pyproject_tool`. A scrutiny-level override of `line_length` would
   want to consult `[tool.scrutiny]` AND still fall through to `[tool.ruff]
   line-length` for the native case. Options:
   - Add a second `scrutiny_pyproject_key: Optional[str]` slot on
     `_FieldSpec` checked before the existing `pyproject_tool`/`pyproject_key`.
   - Insert a new priority layer (3.5) between context and script defaults
     in `ConfigResolver.resolve` for the scrutiny section specifically.
   - Generalise `_FieldSpec.pyproject_tool` to accept a tuple of sections
     consulted in order.
   Recommend option 1; minimal intrusion.

2. **`PYPROJECT_KEY_MAP` conflates two concerns.** Today it maps native
   tool-vocabulary keys (`"line-length"` → `"line_length"`). A scrutiny
   section would map scrutiny-internal keys (`"tier"` → `"config_tier"`),
   which is not really translation; more like "this pyproject key is
   authoritative for this scrutiny field." Consider splitting into
   `PYPROJECT_NATIVE_KEY_MAP` vs a derived `SCRUTINY_PYPROJECT_KEYS`
   (auto-generated from `UserDefaultsSnapshot` fields to prevent drift).

3. **`MANAGED_TOOL_NAMES` comes from `PYPROJECT_TEMPLATES.keys()`**
   (`core/tool_data.py:569`). If `[tool.scrutiny]` is added to templates
   for generation, it also becomes subject to `--override-config` logic
   in `PyProjectGenerator._override_key_level`, which is probably undesired.
   Decouple the "what we manage" set from the "what we can override"
   set.

4. **`_SharedConfigValidator` needs enum-string coercion.**
   `validate_enum_field` checks `isinstance`; a raw string `"standard"`
   from pyproject would fail. The resolver already does enum construction
   via `_safe_enum_construct` for CLI-sourced values; the same path must
   run for pyproject-sourced scrutiny-section values. Add an enum-coerce
   step inside the scrutiny-section resolution path.

5. **Every `_FieldSpec` needs an optional scrutiny-section key** (~30
   fields). At minimum: `config_tier`, `python_version`, `line_length`,
   `parallel`, `no_cache`, `create_log`, `log_level`, `exclude_dirs`,
   `exclude_files`, `framework`, `check_only`, `run_ruff_formatter`,
   `run_mypy`, `tool_timeout`. Drive from a single mapping to avoid a
   30-way edit.

### Out of scope for phase 2

- Renaming any existing CLI flag.
- Changing `PyProjectGenerator` output format.
- Changing the default tier or any other 4.0.0-era defaults.

---

## Phase 3: Tool-registration API

Adding a new tool (e.g. `pyright`) currently requires ~9 synchronised
edits across `TOOL_REGISTRY`, `TOOL_ALIASES`, `PYPROJECT_KEY_MAP`,
`PYPROJECT_TEMPLATES`, a new `*Config` dataclass, a new handler,
`ToolExecutor._get_handler` factory, `ConfigResolver.build_*_config`,
`UserDefaults` run-flag + snapshot + `_FieldSpec`, plus tests.

### Proposed deliverables

1. **`ToolSpec` registration object** that bundles: logical name,
   executable, install package, CLI-flag template map, pyproject key
   map, config-dataclass factory, handler class, tier settings.
   Register via a module-level `register_tool(spec)` call or
   entry-point declaration.
2. **`_HANDLER_FACTORIES` promoted to module scope** (currently
   `execution/handlers.py::ToolExecutor._get_handler` embeds the
   factory dict in a method body). Decorator `@register_handler(name)`
   on handler classes populates it at import time.
3. **Data-driven handler flag emission.** Replace the ~22 hard-coded
   `global_config.should_emit(scrutiny_key, section, native_key)` call
   sites in `execution/handlers.py` with per-tool `_FlagSpec` tuples
   iterated by a generic emit loop. Also catches native-key typos
   (e.g. handlers.py uses `"disable_error_code"` but
   `PYPROJECT_KEY_MAP["mypy"]` uses `"disable_error_code_import_untyped"`
   today; only a grep catches drift).
4. **Three-place synchronisation drift test.** Add a test that
   enumerates `_GLOBAL_CONFIG_FIELDS` and asserts every GlobalConfig
   field (minus runtime provenance and computed properties) is covered
   by a `_FieldSpec`. Parallels the existing `test_config_parity.py`.

---

## Near-term quality wins (can land any time)

- **Collapse ruff / ruff-formatter shared flag emission.** `RuffHandler`
  and `RuffFormatterHandler` both emit `--line-length`, `--target-version`,
  and `--exclude` with identical gating. Extract
  `_append_shared_ruff_flags(command, ruff_config, global_config)`.
- **Parametrise `test_pyproject_suppression.py::TestRuffHandlerPyprojectAware`.**
  The line_length / select / ignore suppression tests have near-identical
  bodies; a single `@pytest.mark.parametrize` over
  `(scrutiny_key, section, native_key, config_kwargs, forbidden_prefix)`
  shrinks the file by roughly half without losing coverage.
- **Publish `__all__` per package.** `configs/__init__.py`,
  `execution/__init__.py`, `core/__init__.py` are currently empty.
  With no `_` prefix on module names and lots of underscore functions
  inside, pip users cannot tell what is stable. Declare a minimal
  public surface: likely `ContextDetection`, `ConfigResolver`,
  `GlobalConfig`, `PyProjectLoader`.
- **Update `config.py` docstring to mention the four-place drift.**
  The snapshot-class docstring still says "three places"
  (`config.py` around UserDefaultsSnapshot); `_FieldSpec` is the fourth.

---

## Test-tier relaxations for tests/ directory

Currently `SCR_EXCLUDE_DIRS = ("tests",)` skips tests entirely rather
than applying relaxed rules. When `[tool.scrutiny]` lands, default
`SCR_EXCLUDE_DIRS = ()` and populate `RUFF_PER_FILE_IGNORES` with
test-appropriate relaxations:

```python
RUFF_PER_FILE_IGNORES = {
    # existing
    "scripts/*.py": ("INP001",),
    # proposed additions
    "tests/**/*.py": ("D", "DOC", "ANN", "S101", "PLR2004", "ARG"),
    "test_*.py": ("D", "DOC", "ANN", "S101", "PLR2004", "ARG"),
}
```

Users who disagree can override via `[tool.scrutiny] exclude_dirs = [...]`
once that exists.

---

## Hardening follow-ups (low priority, defense-in-depth)

- **Whitelist subprocess env in `_execute_subprocess`**
  (`execution/handlers.py:243-254`). Today tools inherit the caller's
  full env including `RUFF_CONFIG`, `MYPY_CONFIG`, etc. A hostile env
  could point the tool at an attacker-controlled config. Consider a
  curated passthrough list.
- **ANSI-strip logged paths** (`main.py` `_show_effective_config` line
  emitting `pyproject_path`; `configs/pyproject.py` `SCRConfigurationError`
  including the path). Paths from a hostile working tree may carry
  ANSI escapes; `_strip_ansi_codes` today only runs on subprocess
  output.
- **Bound `find_pyproject_toml` to the same filesystem.** Upward walk
  currently crosses mount points. A device-id check would prevent
  unintended searches through chroots / container volumes.

---

## Housekeeping

- CHANGELOG is authoritative going forward; every user-visible change
  lands under an unreleased heading before release.
- Version bumps follow semver: breaking → major, feature → minor,
  fix-only → patch. The 3.1.3 → 4.0.0 jump explicitly acknowledged
  silent default flips that were under-classified as a minor bump.
