"""
Parsed issue data classes for tool output.

Provide lightweight containers for issues parsed from tool JSON output.
These are consumed by output formatters and tool handlers.

Classes
-------
RuffIssue : A single Ruff linting issue.
BanditIssue : A single Bandit security issue.

Examples
--------
>>> issue = RuffIssue({"code": "F401", "message": "unused", "location": {"row": 1, "column": 1}})
>>> issue.code
'F401'

"""

from __future__ import annotations

from typing import Any

from scrutiny.core.tool_data import BANDIT_SEVERITY_RANK


class RuffIssue:
    """
    A single Ruff linting issue parsed from JSON output.

    Parameters
    ----------
    data : dict[str, Any]
        Raw JSON dict from Ruff ``--output-format json``.

    Attributes
    ----------
    code : str
        Rule code (e.g. ``"F401"``).
    message : str
        Human-readable description.
    line : int
        1-indexed line number.
    column : int
        1-indexed column number.
    filename : str
        File path string.
    fixable : bool
        Whether Ruff can auto-fix this issue.
    url : str
        Documentation URL for the rule.

    """

    __slots__ = (
        "code",
        "column",
        "filename",
        "fixable",
        "line",
        "message",
        "url",
    )

    def __init__(self, data: dict[str, Any]) -> None:
        # Extract fields from Ruff's JSON output format.
        self.code: str = data.get("code", "")
        self.message: str = data.get("message", "")
        location = data.get("location", {})
        self.line: int = location.get("row", 0)
        self.column: int = location.get("column", 0)
        self.filename: str = data.get("filename", "")
        self.fixable: bool = data.get("fix") is not None
        self.url: str = data.get("url", "")

    def __repr__(self) -> str:
        return f"RuffIssue({self.code} at {self.filename}:{self.line}:{self.column})"


class BanditIssue:
    """
    A single Bandit security issue parsed from JSON output.

    Parameters
    ----------
    data : dict[str, Any]
        Raw JSON dict from Bandit ``-f json``.

    Attributes
    ----------
    test_id : str
        Bandit test identifier (e.g. ``"B201"``).
    test_name : str
        Human-readable test name.
    severity : str
        Severity level string (``"LOW"``, ``"MEDIUM"``, ``"HIGH"``).
    confidence : str
        Confidence level string.
    line_number : int
        1-indexed line number.
    filename : str
        File path string.
    issue_text : str
        Full issue description.
    more_info : str
        URL to further information.
    source_code : str
        Source code context from Bandit JSON ``code`` field.

    """

    __slots__ = (
        "confidence",
        "filename",
        "issue_text",
        "line_number",
        "more_info",
        "severity",
        "source_code",
        "test_id",
        "test_name",
    )

    def __init__(self, data: dict[str, Any]) -> None:
        # Extract fields from Bandit's JSON output format.
        self.test_id: str = data.get("test_id", "")
        self.test_name: str = data.get("test_name", "")
        self.severity: str = data.get("issue_severity", "LOW").upper()
        self.confidence: str = data.get("issue_confidence", "LOW").upper()
        self.line_number: int = data.get("line_number", 0)
        self.filename: str = data.get("filename", "")
        self.issue_text: str = data.get("issue_text", "")
        self.more_info: str = data.get("more_info", "")
        self.source_code: str = data.get("code", "")

    def meets_threshold(
        self,
        min_severity: str,
        min_confidence: str,
    ) -> bool:
        """
        Check if this issue meets minimum thresholds.

        Ordering: LOW < MEDIUM < HIGH.

        Parameters
        ----------
        min_severity : str
            Minimum severity (``"low"``, ``"medium"``, ``"high"``).
        min_confidence : str
            Minimum confidence (``"low"``, ``"medium"``, ``"high"``).

        Returns
        -------
        bool
            True if both thresholds are met.

        """
        # Compare numeric ranks: higher rank = more severe/confident.
        is_severity_sufficient = BANDIT_SEVERITY_RANK.get(
            self.severity,
            0,
        ) >= BANDIT_SEVERITY_RANK.get(min_severity.upper(), 0)
        is_confidence_sufficient = BANDIT_SEVERITY_RANK.get(
            self.confidence,
            0,
        ) >= BANDIT_SEVERITY_RANK.get(min_confidence.upper(), 0)
        return is_severity_sufficient and is_confidence_sufficient

    def __repr__(self) -> str:
        return (
            f"BanditIssue({self.test_id} "
            f"[{self.severity}/{self.confidence}] "
            f"at {self.filename}:{self.line_number})"
        )
