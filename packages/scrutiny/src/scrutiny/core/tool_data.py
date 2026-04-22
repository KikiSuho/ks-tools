"""
Rule sets, flag maps, tier settings, and tool registry for scrutiny.

Contain Ruff rule compositions, Mypy/Radon/Bandit CLI flag maps, pyproject.toml
templates and key mappings, coverage and pytest tier settings, and the
``TOOL_REGISTRY`` mapping logical tool names to (executable, package) pairs.

Constants
---------
RUFF_TIER_RULES : Maps each config tier to its Ruff rule set.
RUFF_FRAMEWORK_RULES : Maps each framework to its Ruff rule families.
RUFF_CLI_FLAGS : Ruff configuration fields to CLI flag templates.
RUFF_SECURITY_RULES : Bandit security rules exposed via Ruff.
RUFF_PER_FILE_IGNORES : Per-file rule ignore overrides.
RUFF_RULES_STRICT : Strict-tier Ruff rules (used as default fallback).
RUFF_IGNORE_RULES : Unconditional Ruff ignore rules.
MYPY_TIER_SETTINGS : Maps each config tier to its Mypy settings.
MYPY_CLI_FLAGS : Mypy configuration fields to CLI flag templates.
RADON_TIER_SETTINGS : Maps each config tier to its Radon settings.
RADON_CLI_FLAGS : Radon configuration fields to CLI flag templates.
RADON_COMPLEXITY_GRADES : Complexity grade metadata with score ranges.
RADON_TEST_EXCLUSIONS : Test directory and file exclusions for Radon.
BANDIT_TIER_SETTINGS : Maps each config tier to its Bandit settings.
BANDIT_CLI_FLAGS : Bandit configuration fields to CLI flag templates.
BANDIT_LEVEL_FLAGS : Severity/confidence level to CLI flag character.
BANDIT_SEVERITY_RANK : Numeric ordering for threshold comparison.
PYPROJECT_TEMPLATES : Tool section templates for pyproject.toml generation.
PYPROJECT_KEY_MAP : Tool section key mappings for pyproject.toml reading.
MANAGED_TOOL_NAMES : Top-level tool names managed by this script.
PYTEST_TIER_MAP : Maps test tier labels to pytest settings.
COVERAGE_TIER_MAP : Maps test tier labels to coverage settings.
PYTEST_PLUGIN_ADDOPTS : Additional pytest flags for plugin mode.
PYTEST_REQUIRED_PLUGINS : Required pytest plugins for plugin mode.
TOOL_REGISTRY : Maps logical tool names to (executable, package) pairs.
TOOL_ALIASES : Maps user-facing tool names to logical tool names.

Functions
---------
get_test_config_tier : Map a ConfigTier to the test-config tier label.
build_ruff_rules : Build effective Ruff select and ignore rules from configuration.

Examples
--------
>>> get_test_config_tier(ConfigTier.STANDARD)
'relaxed'

"""

from __future__ import annotations

from typing import Any

from scrutiny.core.enums import ConfigTier, FrameworkSelection, PythonVersion

# ====================================== #
#                RUFF                    #
# ====================================== #


# Rules are composable: each tier includes all rules from tiers below it.
RUFF_RULES_ESSENTIAL: tuple[str, ...] = (
    # Pycodestyle - subset
    "E4",  # Import rules.
    "E7",  # Statement rules.
    "E9",  # Runtime rules.
    # Pyflakes
    "F",  # Undefined names and unused imports.
)

RUFF_RULES_STANDARD: tuple[str, ...] = (
    *RUFF_RULES_ESSENTIAL,
    # Widely adopted, low-noise rules
    "A",  # Flake8-builtins: shadowing builtins.
    "B",  # Flake8-bugbear: likely bugs and design problems.
    "C4",  # Flake8-comprehensions: better comprehensions.
    "I",  # Isort: import sorting.
    "ISC",  # Flake8-implicit-str-concat: concatenation pitfalls.
    "N",  # PEP 8 naming conventions.
    "RET",  # Flake8-return: return patterns.
    "SIM",  # Flake8-simplify: simplifications.
    "UP",  # Pyupgrade: full family, respects target-version.
    "YTT",  # Flake8-2020: sys.version misuse.
)

RUFF_RULES_STRICT: tuple[str, ...] = (
    *RUFF_RULES_STANDARD,
    # Docs and docstring policy
    "D",  # Pydocstyle: docstring conventions.
    "DOC",  # Pydoclint: docstring linting.
    "CPY",  # Flake8-copyright: copyright headers.
    # Arguments and async
    "ARG",  # Flake8-unused-arguments: unused arguments.
    "ASYNC",  # Flake8-async: async correctness.
    # Exception handling
    "BLE",  # Flake8-blind-except: blind except.
    "RSE",  # Flake8-raise: raise patterns.
    "TRY",  # Tryceratops: exception handling patterns.
    # Code quality and style
    "DTZ",  # Flake8-datetimez: timezone-aware datetime.
    "ERA",  # Eradicate: commented-out code.
    "FIX",  # Flake8-fixme: FIXME, HACK, and XXX comments.
    "FLY",  # Flynt: f-string refactors.
    "FURB",  # Refurb: modernization refactors.
    "PIE",  # Flake8-pie: unnecessary patterns.
    "SLF",  # Flake8-self: private member access.
    # Logging
    "G",  # Flake8-logging-format: full family.
    "LOG",  # Flake8-logging: logging best practices.
    # Imports and packages
    "INP",  # Flake8-no-pep420: missing __init__.py files.
    "TID",  # Flake8-tidy-imports: import tidying policy.
    # Performance and debugging
    "PERF",  # Perflint: performance anti-patterns.
    "T10",  # Flake8-debugger: debugger statements.
    "T20",  # Flake8-print: disallowing print statements.
    # Pylint and meta
    "PGH",  # Pygrep-hooks: blanket noqa and similar issues.
    "PLE",  # Pylint: error rules.
    "PLW",  # Pylint: warning rules.
    "PTH",  # Flake8-use-pathlib: pathlib refactoring.
    "RUF",  # Ruff-native rules.
    # Cherry-picked PLR (full family too noisy for strict)
    "PLR0124",  # Comparison of constant with itself.
    "PLR0133",  # Comparison of two constants.
    "PLR1711",  # Useless return.
    "PLR1714",  # Consider merging multiple comparisons.
    "PLR1716",  # Boolean chained comparison.
    "PLR1722",  # Use sys.exit() instead of exit()/quit().
    "PLR1730",  # if/else could be ternary or min/max.
    "PLR1733",  # Unnecessary dict index lookup.
    "PLR1736",  # Unnecessary list index lookup.
    "PLR2004",  # Magic value used in comparison.
    "PLR2044",  # Empty comment.
    "PLR5501",  # Collapsible else-if.
    # Pycodestyle add-on
    "E501",  # Line length (overlaps with formatter).
)

RUFF_RULES_INSANE: tuple[str, ...] = (
    *RUFF_RULES_STRICT,
    # Highly opinionated and policy-driven
    "COM",  # Flake8-commas: trailing comma enforcement.
    "EM",  # Flake8-errmsg: exception message formatting.
    "FBT",  # Flake8-boolean-trap: boolean positional args.
    "ICN",  # Flake8-import-conventions: import naming.
    "Q",  # Flake8-quotes: quote consistency.
    "SLOT",  # Flake8-slots: class slot optimization.
    "TD",  # Flake8-todos: TODO comment formatting.
    "EXE",  # Flake8-executable: file permission checks.
    # Remaining Pylint families
    "PLC",  # Pylint: convention rules.
    "PLR",  # Pylint: refactor rules (full family, replaces strict cherry-picks).
    # Formatter-overlapping style families
    "E",  # Pycodestyle: error rules (full family).
    "W",  # Pycodestyle: warning rules (full family).
)

RUFF_IGNORE_RULES: tuple[str, ...] = (
    # Tryceratops suppressions
    "TRY003",  # Raise-vanilla-args: contextual f-string messages at raise site.
    "TRY300",  # Try-consider-else: noisy for validation and guard patterns.
    "TRY301",  # Raise-within-try: normal in validation patterns.
    "TRY400",  # Logging-error-not-exception: intentional logger.error usage.
    # Logging
    "G004",  # Logging-f-string: SCRLogger uses custom methods, not stdlib lazy formatting.
    # Ruff meta
    "RUF100",
    # Docstring
    "D105",  # Standard-protocol dunders exempt from docstrings
    "D107",  # Missing docstring in __init__.
    "D203",  # Conflicts with D211 (Style choice)
    "D212",  # Conflicts with D213 (Style choice)
)

# Rules to ignore when target Python version is BELOW the key version.
# When the user's python_version >= the key, these rules are allowed through.
RUFF_VERSION_GATED_IGNORES: dict[str, tuple[str, ...]] = {
    "py310": (
        "UP007",  # Non-PEP 604 annotations: X | Y syntax requires py310+ runtime.
        "UP045",  # Non-PEP 604 optional: Optional[X] -> X | None requires py310+.
    ),
}

# Individual ruff rules within included families that overlap with mypy --strict.
# Auto-added to the ignore list when mypy is enabled.
RUFF_MYPY_OVERLAP: tuple[str, ...] = (
    "RUF013",  # Implicit-optional: redundant with mypy no_implicit_optional in strict mode.
)

RUFF_PER_FILE_IGNORES: dict[str, tuple[str, ...]] = {
    "scripts/*.py": ("INP001",),  # Scripts directory is a tools folder, not a package.
}

# Bandit security rules exposed via ruff.
RUFF_SECURITY_RULES: tuple[str, ...] = ("S",)

# Each tier maps to its corresponding rule set.
RUFF_TIER_RULES: dict[str, tuple[str, ...]] = {
    "essential": RUFF_RULES_ESSENTIAL,
    "standard": RUFF_RULES_STANDARD,
    "strict": RUFF_RULES_STRICT,
    "insane": RUFF_RULES_INSANE,
}

# Each framework maps to its Ruff rule families.
RUFF_FRAMEWORK_RULES: dict[str, tuple[str, ...]] = {
    "none": (),
    "django": ("DJ",),  # Flake8-django: Django-specific rules.
    "fastapi": ("FAST",),  # FastAPI-specific rules.
    "airflow": ("AIR",),  # Airflow-specific rules.
    "numpy": ("NPY",),  # NumPy.md-specific rules.
    "pandas": ("PD",),  # Pandas-vet: pandas-specific rules.
}

# Configuration fields map to CLI flag templates.
RUFF_CLI_FLAGS: dict[str, str] = {
    "select_rules": "--select={value}",
    "ignore_rules": "--ignore={value}",
    "extend_select_rules": "--extend-select={value}",
    "line_length": "--line-length={value}",
    "target_version": "--target-version={value}",
    "output_format": "--output-format={value}",
    "fix": "--fix",
    "unsafe_fixes": "--unsafe-fixes",
    "no_cache": "--no-cache",
    "check": "--check",
}

# ====================================== #
#                MYPY                    #
# ====================================== #


# Mypy settings vary by tier; higher tiers enable stricter type checking.
MYPY_TIER_SETTINGS: dict[str, dict[str, Any]] = {
    "essential": {
        "strict_mode": False,
        "warn_unreachable": False,
        "disallow_untyped_globals": False,
        "disallow_any_explicit": False,
        "ignore_missing_imports": True,
        "disable_error_code_import_untyped": True,
    },
    "standard": {
        "strict_mode": False,
        "warn_unreachable": True,
        "disallow_untyped_globals": False,
        "disallow_any_explicit": False,
        "ignore_missing_imports": True,
        "disable_error_code_import_untyped": True,
    },
    "strict": {
        "strict_mode": True,
        "warn_unreachable": True,
        "disallow_untyped_globals": True,
        "disallow_any_explicit": False,
        "ignore_missing_imports": True,
        "disable_error_code_import_untyped": True,
    },
    "insane": {
        "strict_mode": True,
        "warn_unreachable": True,
        "disallow_untyped_globals": True,
        "disallow_any_explicit": True,
        "ignore_missing_imports": True,
        "disable_error_code_import_untyped": True,
    },
}

# Configuration fields map to CLI flag templates.
MYPY_CLI_FLAGS: dict[str, str] = {
    "strict_mode": "--strict",
    "warn_unreachable": "--warn-unreachable",
    "disallow_untyped_globals": "--disallow-untyped-globals",
    "disallow_any_explicit": "--disallow-any-explicit",
    "ignore_missing_imports": "--ignore-missing-imports",
    "disable_error_code_import_untyped": "--disable-error-code=import-untyped",
    "show_column_numbers": "--show-column-numbers",
    "show_error_codes": "--show-error-codes",
    "output": "--output={value}",
    "python_version": "--python-version={value}",
}


# ====================================== #
#               RADON                    #
# ====================================== #


# Radon complexity thresholds vary by tier; higher tiers flag simpler functions.
RADON_TIER_SETTINGS: dict[str, dict[str, Any]] = {
    "essential": {"minimum_complexity": "D"},
    "standard": {"minimum_complexity": "C"},
    "strict": {"minimum_complexity": "B"},
    "insane": {"minimum_complexity": "A"},
}

# Complexity grade metadata defines score ranges and descriptions.
RADON_COMPLEXITY_GRADES: dict[str, dict[str, Any]] = {
    "A": {"max_score": 5, "description": "Simple (1-5)"},
    "B": {"max_score": 10, "description": "Moderate (6-10)"},
    "C": {"max_score": 20, "description": "Complex (11-20)"},
    "D": {"max_score": 30, "description": "Very complex (21-30)"},
    "E": {"max_score": 40, "description": "Extremely complex (31-40)"},
    "F": {"max_score": 999, "description": "Unmaintainable (41+)"},
}

# Configuration fields map to CLI flag templates.
RADON_CLI_FLAGS: dict[str, str] = {
    "minimum_complexity": "-n={value}",
    "show_average": "-a",
    "show_closures": "--show-closures",
    "json_output": "-j",
    "exclude": "-e={value}",
}

# Radon excludes test code from complexity analysis.
RADON_TEST_EXCLUSIONS: dict[str, tuple[str, ...]] = {
    "dirs": ("test", "tests", "spec", "specs", "examples", "example"),
    "files": ("test_*.py", "*_test.py", "*_tests.py", "*_spec.py"),
}


# ====================================== #
#               BANDIT                   #
# ====================================== #


# Bandit severity and confidence thresholds vary by tier.
BANDIT_TIER_SETTINGS: dict[str, dict[str, Any]] = {
    "essential": {"severity": "high", "confidence": "high"},
    "standard": {"severity": "medium", "confidence": "high"},
    "strict": {"severity": "medium", "confidence": "medium"},
    "insane": {"severity": "low", "confidence": "medium"},
}

# Severity / confidence level -> CLI flag character
BANDIT_LEVEL_FLAGS: dict[str, str] = {
    "low": "l",
    "medium": "m",
    "high": "h",
}

# Configuration fields map to CLI flag templates.
BANDIT_CLI_FLAGS: dict[str, str] = {
    "format": "-f={value}",
    "severity": "--severity-level={value}",
    "confidence": "--confidence-level={value}",
    "quiet": "-q",
    "exclude": "-x={value}",
    "skip_tests": "-s={value}",
}

# Severity and confidence levels are ordered for threshold comparison.
BANDIT_SEVERITY_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


# ====================================== #
#         PYTEST AND COVERAGE            #
# ====================================== #

PYTEST_RELAXED_SETTINGS: dict[str, Any] = {
    "minversion": '"6.0"',
    "testpaths": ["tests"],
    "addopts": ["-ra"],
    "markers": [
        "unit: Unit tests",
        "integration: Integration tests",
        "slow: Slow tests",
    ],
}

PYTEST_STRICT_SETTINGS: dict[str, Any] = {
    "minversion": '"6.0"',
    "testpaths": ["tests"],
    "addopts": [
        "-ra",
        "--import-mode=importlib",
        "--strict-markers",
        "--strict-config",
    ],
    "xfail_strict": "true",
    "filterwarnings": ["error"],
    "markers": [
        "unit: Unit tests",
        "integration: Integration tests",
        "slow: Slow tests",
    ],
}

PYTEST_PLUGIN_ADDOPTS: tuple[str, ...] = (
    "--durations=10",
    "-n auto",
    "--dist=loadscope",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=xml",
)

PYTEST_REQUIRED_PLUGINS: tuple[str, ...] = ("pytest-cov", "pytest-xdist")

COVERAGE_RELAXED_SETTINGS: dict[str, dict[str, Any]] = {
    "run": {"branch": "true", "source": ["src"], "omit": ["*/tests/*"]},
    "report": {
        "show_missing": "true",
        "precision": "1",
        "exclude_also": ["if TYPE_CHECKING:"],
    },
}

COVERAGE_STRICT_SETTINGS: dict[str, dict[str, Any]] = {
    "run": {"branch": "true", "source": ["src"], "omit": ["*/tests/*"]},
    "report": {
        "show_missing": "true",
        "precision": "1",
        "exclude_also": [
            "raise NotImplementedError",
            "if TYPE_CHECKING:",
        ],
    },
}

PYTEST_TIER_MAP: dict[str, dict[str, Any]] = {
    "relaxed": PYTEST_RELAXED_SETTINGS,
    "strict": PYTEST_STRICT_SETTINGS,
}

COVERAGE_TIER_MAP: dict[str, dict[str, dict[str, Any]]] = {
    "relaxed": COVERAGE_RELAXED_SETTINGS,
    "strict": COVERAGE_STRICT_SETTINGS,
}


def get_test_config_tier(config_tier: ConfigTier) -> str:
    """
    Map a ``ConfigTier`` to the test-config tier label.

    Parameters
    ----------
    config_tier : ConfigTier
        Active quality tier.

    Returns
    -------
    str
        ``"relaxed"`` for essential/standard, ``"strict"`` for strict/insane.

    """
    # Map lower tiers to relaxed test configuration
    if config_tier in (ConfigTier.ESSENTIAL, ConfigTier.STANDARD):
        return "relaxed"
    return "strict"


# ====================================== #
#       VERSION-AWARE HELPERS            #
# ====================================== #


def _build_effective_ignore_rules(python_version: PythonVersion) -> tuple[str, ...]:
    """
    Build the effective ignore list from unconditional and version-gated rules.

    Rules in ``RUFF_VERSION_GATED_IGNORES`` are added when the target
    Python version is below the key version. Comparison uses enum
    member ordering, not lexicographic string order.

    Parameters
    ----------
    python_version : PythonVersion
        Target Python version.

    Returns
    -------
    tuple[str, ...]
        Combined ignore rules.

    """
    # Build ordered member list for reliable version comparison.
    ordered_members = list(PythonVersion)
    current_index = ordered_members.index(python_version)

    # Start with unconditional ignores, then add version-gated ones.
    ignore_rules: list[str] = list(RUFF_IGNORE_RULES)
    # Add version-gated rules when the target is below the required minimum
    for min_version_str, rules in RUFF_VERSION_GATED_IGNORES.items():
        min_version = PythonVersion(min_version_str)
        min_index = ordered_members.index(min_version)
        # Add rules when target version is below the required minimum.
        if current_index < min_index:
            ignore_rules.extend(rules)
    return tuple(ignore_rules)


def build_ruff_rules(
    tier: ConfigTier,
    framework: FrameworkSelection,
    python_version: PythonVersion,
    run_mypy: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """
    Build effective Ruff select and ignore rules from configuration.

    Parameters
    ----------
    tier : ConfigTier
        Quality tier controlling base rule selection.
    framework : FrameworkSelection
        Optional framework for additional rule families.
    python_version : PythonVersion
        Target Python version for version-gated ignores.
    run_mypy : bool
        Whether Mypy is enabled (adds overlap ignores).

    Returns
    -------
    tuple[tuple[str, ...], tuple[str, ...]]
        ``(select_rules, ignore_rules)`` pair.

    """
    # Start with tier-based rules, then merge framework-specific families.
    select_rules = RUFF_TIER_RULES.get(tier.value, RUFF_RULES_STRICT)
    framework_rules = RUFF_FRAMEWORK_RULES.get(framework.value, ())
    # Append framework-specific rule families when a framework is selected
    if framework_rules:
        select_rules = (*select_rules, *framework_rules)
    # Build ignore list from version-gated rules plus mypy overlap.
    ignore_rules = _build_effective_ignore_rules(python_version)
    # Suppress rules that overlap with mypy strict checks when mypy is active
    if run_mypy:
        ignore_rules = (*ignore_rules, *RUFF_MYPY_OVERLAP)
    return select_rules, ignore_rules


# ====================================== #
#        PYPROJECT TEMPLATES             #
# ====================================== #

# Used by PyProjectGenerator to create / merge tool config sections.

PYPROJECT_TEMPLATES: dict[str, dict[str, Any]] = {
    "ruff": {
        "line-length": "{line_length}",
        "target-version": "{python_version}",
        "fix": "{fix}",
    },
    "ruff.lint": {
        "select": "{select_rules}",
        "ignore": "{ignore_rules}",
    },
    "ruff.format": {},
    "mypy": {
        "python_version": "{python_version_dotted}",
        "strict": "{strict_mode}",
        "warn_unreachable": "{warn_unreachable}",
        "ignore_missing_imports": "{ignore_missing_imports}",
        "show_column_numbers": "true",
        "show_error_codes": "true",
    },
    "bandit": {
        "exclude_dirs": "{exclude_dirs}",
        "skips": "{skip_tests}",
    },
}

# Top-level tool names managed by this script.
# Derived from PYPROJECT_TEMPLATES keys; subsections like "ruff.lint"
# fall under their parent "ruff".
MANAGED_TOOL_NAMES: frozenset[str] = frozenset(key.split(".")[0] for key in PYPROJECT_TEMPLATES)


# ====================================== #
#       PYPROJECT KEY MAPPING            #
# ====================================== #

# Used by PyProjectLoader when reading existing [tool.*] sections.

PYPROJECT_KEY_MAP: dict[str, dict[str, str]] = {
    "ruff": {
        "line-length": "line_length",
        "target-version": "python_version",
        "fix": "fix",
        "unsafe-fixes": "unsafe_fixes",
    },
    "ruff.lint": {
        "select": "select_rules",
        "ignore": "ignore_rules",
    },
    "mypy": {
        "python_version": "python_version_dotted",
        "strict": "strict_mode",
        "warn_unreachable": "warn_unreachable",
        "ignore_missing_imports": "ignore_missing_imports",
        "disallow_untyped_globals": "disallow_untyped_globals",
        "disallow_any_explicit": "disallow_any_explicit",
        "disable_error_code_import_untyped": "disable_error_code_import_untyped",
    },
    "bandit": {
        "exclude_dirs": "exclude_dirs",
        "skips": "skip_tests",
    },
}


# ====================================== #
#           TOOL REGISTRY                #
# ====================================== #

# Maps logical tool names used by the orchestrator to the executable
# binary name and the install package name.

TOOL_REGISTRY: dict[str, tuple[str, str]] = {
    "ruff_formatter": ("ruff", "ruff"),
    "ruff_linter": ("ruff", "ruff"),
    "ruff_security": ("ruff", "ruff"),
    "mypy": ("mypy", "mypy"),
    "radon": ("radon", "radon"),
    "radon_mi": ("radon", "radon"),
    "bandit": ("bandit", "bandit"),
}

TOOL_ALIASES: dict[str, list[str]] = {
    "ruff": ["ruff_formatter", "ruff_linter"],
    "mypy": ["mypy"],
    "radon": ["radon"],
    "bandit": ["bandit"],
    "ruff_security": ["ruff_security"],
}
