"""Tests for ToolResult, RuffIssue, and BanditIssue data model behaviour."""

from __future__ import annotations

import pytest

from scrutiny.core.enums import PythonVersion
from scrutiny.execution.issues import BanditIssue
from scrutiny.execution.results import ToolResult


# ── BanditIssue.meets_threshold() ── #


@pytest.mark.unit
class TestBanditIssueMeetsThreshold:
    """Test BanditIssue severity and confidence threshold evaluation."""

    @pytest.mark.parametrize(
        ("severity", "confidence", "min_severity", "min_confidence", "expected"),
        [
            pytest.param(
                "HIGH",
                "HIGH",
                "low",
                "low",
                True,
                id="high_severity_high_confidence_vs_low_thresholds",
            ),
            pytest.param(
                "LOW",
                "LOW",
                "high",
                "high",
                False,
                id="low_severity_low_confidence_vs_high_thresholds",
            ),
            pytest.param(
                "MEDIUM",
                "HIGH",
                "medium",
                "medium",
                True,
                id="medium_severity_high_confidence_vs_medium_thresholds",
            ),
            pytest.param(
                "LOW",
                "HIGH",
                "medium",
                "low",
                False,
                id="low_severity_below_medium_threshold",
            ),
            pytest.param(
                "HIGH",
                "LOW",
                "low",
                "medium",
                False,
                id="low_confidence_below_medium_threshold",
            ),
        ],
    )
    def test_meets_threshold_evaluates_correctly(
        self,
        severity: str,
        confidence: str,
        min_severity: str,
        min_confidence: str,
        expected: bool,
    ) -> None:
        """Verify threshold comparison logic for various severity/confidence combinations."""
        issue = BanditIssue(
            {
                "test_id": "B101",
                "test_name": "assert_used",
                "issue_severity": severity,
                "issue_confidence": confidence,
                "line_number": 1,
                "filename": "test.py",
                "issue_text": "Use of assert detected.",
                "more_info": "",
                "code": "",
            },
        )
        assert issue.meets_threshold(min_severity, min_confidence) is expected


# ── ToolResult.error_code ── #


@pytest.mark.unit
class TestToolResultErrorCode:
    """Test the ``error_code`` field on ToolResult."""

    def test_error_code_defaults_to_zero(self) -> None:
        """Default ``error_code`` is 0 (no SCRError occurred)."""
        # Arrange / Act
        result = ToolResult(
            tool="ruff_linter",
            success=True,
            exit_code=0,
            execution_time=1.0,
            files_processed=5,
            stdout="",
            stderr="",
        )

        # Assert
        assert result.error_code == 0

    def test_error_code_stores_nonzero_value(self) -> None:
        """Store a non-zero ``error_code`` from a SCRError exit code."""
        # Arrange / Act
        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=2,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="timed out",
            error_code=4,
        )

        # Assert
        assert result.error_code == 4


# ── PythonVersion.to_dotted ── #


@pytest.mark.unit
class TestPythonVersionToDotted:
    """Test the to_dotted property converts compact to dotted format."""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            pytest.param(PythonVersion.PY39, "3.9", id="py39"),
            pytest.param(PythonVersion.PY310, "3.10", id="py310"),
            pytest.param(PythonVersion.PY311, "3.11", id="py311"),
            pytest.param(PythonVersion.PY312, "3.12", id="py312"),
            pytest.param(PythonVersion.PY313, "3.13", id="py313"),
        ],
    )
    def test_to_dotted_converts_correctly(
        self,
        version: object,
        expected: str,
    ) -> None:
        """Verify each PythonVersion member produces the correct dotted string."""
        # Act / Assert
        assert version.to_dotted == expected
