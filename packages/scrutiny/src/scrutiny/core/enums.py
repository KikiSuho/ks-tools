"""
Enumeration types for scrutiny configuration.

All enums are leaf types with no internal dependencies beyond the
standard library.

Classes
-------
ConfigTier : Quality tier controlling rule strictness across all tools.
SecurityTool : Security analysis tool selection.
LogLocation : Controls where log files are placed.
LoggerLevel : Log levels for controlling output verbosity.
PythonVersion : Supported Python target versions for tools.
LineLength : Common maximum line-length settings for formatters and linters.
SearchDepth : Maximum upward directory search depth for finding pyproject.toml.
ToolTimeout : Per-tool execution timeout in seconds.
FrameworkSelection : Optional framework for additional ruff rule families.
ConfigSource : Source from which a configuration value originated.

Examples
--------
>>> ConfigTier.STANDARD.value
'standard'

>>> PythonVersion.PY313.to_dotted
'3.13'

"""

from __future__ import annotations

from enum import Enum, IntEnum


class ConfigTier(Enum):
    """
    Quality tier controlling rule strictness across all tools.

    Each tier includes everything from the tier below it.

    Attributes
    ----------
    ESSENTIAL : str
        Core correctness only; catches real bugs.
    STANDARD : str
        Quality and correctness; production-ready code.
    STRICT : str
        Maximum rigor; enforces style and best practices.
    INSANE : str
        Maximum strictness across all tools; sadistic but bulletproof.

    """

    ESSENTIAL = "essential"
    STANDARD = "standard"
    STRICT = "strict"
    INSANE = "insane"


class SecurityTool(Enum):
    """
    Security analysis tool selection.

    Attributes
    ----------
    BANDIT : str
        Full Bandit analysis with severity/confidence filtering.
    RUFF : str
        Ruff S-category rules (fast, no severity filtering).

    """

    BANDIT = "bandit"
    RUFF = "ruff_security"


class LogLocation(str, Enum):
    """
    Control where log files are placed.

    Attributes
    ----------
    PROJECT_ROOT : str
        Discovered project root (upward marker search).
        Disables logging with a message if no root is found.
    CURRENT_DIR : str
        Invocation directory (no search required).
    HYBRID : str
        Project root if found, otherwise current directory.

    """

    PROJECT_ROOT = "project_root"
    CURRENT_DIR = "current_dir"
    HYBRID = "hybrid"


class LoggerLevel(IntEnum):
    """
    Log levels for controlling output verbosity.

    Attributes
    ----------
    QUIET : int
        Status, success, and error messages only.
    NORMAL : int
        QUIET + summary + single-line issues (no metadata, no source).
    DETAILED : int
        NORMAL + metadata (fixable flags, URLs, error codes) + source
        code context around each issue.
    VERBOSE : int
        DETAILED + items fixed by Ruff + subprocess commands and exit
        metadata.

    """

    QUIET = 1
    NORMAL = 2
    DETAILED = 3
    VERBOSE = 4


class PythonVersion(str, Enum):
    """
    Supported Python target versions for tools.

    Values use the compact ``"pyXY"`` format consumed by Ruff.
    Use the ``to_dotted`` property for Mypy's ``"X.Y"`` format.

    Attributes
    ----------
    PY39 : str
        Python 3.9.
    PY310 : str
        Python 3.10.
    PY311 : str
        Python 3.11.
    PY312 : str
        Python 3.12.
    PY313 : str
        Python 3.13.

    """

    PY39 = "py39"
    PY310 = "py310"
    PY311 = "py311"
    PY312 = "py312"
    PY313 = "py313"

    @property
    def to_dotted(self) -> str:
        """
        Convert compact format to dotted format.

        Returns
        -------
        str
            Dotted version string (e.g. ``"3.9"``).

        """
        return f"{self.value[2]}.{self.value[3:]}"


class LineLength(IntEnum):
    """
    Common maximum line-length settings for formatters and linters.

    Attributes
    ----------
    PEP8 : int
        PEP 8 standard (79 characters).
    BLACK : int
        Black formatter default (88 characters).
    STANDARD : int
        Google style / project default (100 characters).
    RELAXED : int
        Relaxed setting for wide monitors (120 characters).

    """

    PEP8 = 79
    BLACK = 88
    STANDARD = 100
    RELAXED = 120


class SearchDepth(IntEnum):
    """
    Maximum upward directory search depth for finding pyproject.toml.

    Attributes
    ----------
    SHALLOW : int
        Small or flat projects (3 levels).
    MODERATE : int
        Mid-size projects (5 levels).
    DEFAULT : int
        Standard monorepo depth (8 levels).
    DEEP : int
        Deeply nested repositories (10 levels).

    """

    SHALLOW = 3
    MODERATE = 5
    DEFAULT = 8
    DEEP = 10


class ToolTimeout(IntEnum):
    """
    Per-tool execution timeout in seconds.

    Attributes
    ----------
    QUICK : int
        Fast tools or small file sets (30 seconds).
    STANDARD : int
        Comfortable for most projects (60 seconds).
    PATIENT : int
        Comfortable for most projects (120 seconds).
    GENEROUS : int
        Large codebases (300 seconds).
    EXTENDED : int
        Very large or slow tools (600 seconds).

    """

    QUICK = 30
    STANDARD = 60
    PATIENT = 120
    GENEROUS = 300
    EXTENDED = 600


class FrameworkSelection(str, Enum):
    """
    Optional framework for additional ruff rule families.

    When set, the framework's ruff rules are appended to the
    tier-selected rules. ``NONE`` disables framework-specific rules.

    Attributes
    ----------
    NONE : str
        No framework (default).
    DJANGO : str
        Django web framework.
    FASTAPI : str
        FastAPI async web framework.
    AIRFLOW : str
        Apache Airflow workflow orchestration.
    NUMPY : str
        NumPy.md numerical computing.
    PANDAS : str
        pandas data analysis.

    """

    NONE = "none"
    DJANGO = "django"
    FASTAPI = "fastapi"
    AIRFLOW = "airflow"
    NUMPY = "numpy"
    PANDAS = "pandas"


class ConfigSource(Enum):
    """
    Source from which a configuration value originated.

    Ordered by priority (highest to lowest).

    Attributes
    ----------
    CLI : str
        Value provided via command-line argument.
    PYPROJECT : str
        Value loaded from pyproject.toml [tool.*] sections.
    CONTEXT : str
        Value determined by execution context (CI / IDE / etc.).
    SCRIPT : str
        Value from UserDefaults.
    TOOL_DEFAULT : str
        Tool's built-in default value.

    """

    CLI = "cli"
    PYPROJECT = "pyproject.toml"
    CONTEXT = "context_detection"
    SCRIPT = "script_config"
    TOOL_DEFAULT = "tool_default"

    def __str__(self) -> str:
        return self.value
