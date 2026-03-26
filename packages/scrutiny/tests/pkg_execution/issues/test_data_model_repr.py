"""Tests for data model __repr__ methods, field extraction, and threshold edge cases."""

from __future__ import annotations

import pytest

from scrutiny.configs.resolver import EffectiveValue
from scrutiny.core.enums import ConfigSource
from scrutiny.execution.issues import BanditIssue, RuffIssue


# ── RuffIssue ── #


@pytest.mark.unit
class TestRuffIssueFieldExtraction:
    """Test RuffIssue construction from JSON data dicts."""

    def test_extracts_all_fields_from_complete_data(self) -> None:
        """Verify all fields are extracted from a complete JSON dict."""
        data = {
            "code": "F401",
            "message": "unused import",
            "location": {"row": 10, "column": 5},
            "filename": "app.py",
            "fix": {"applicability": "safe"},
            "url": "https://docs.astral.sh/ruff/rules/F401",
        }

        issue = RuffIssue(data)

        assert issue.code == "F401"
        assert issue.message == "unused import"
        assert issue.line == 10
        assert issue.column == 5
        assert issue.filename == "app.py"
        assert issue.fixable is True
        assert issue.url == "https://docs.astral.sh/ruff/rules/F401"

    def test_defaults_on_missing_fields(self) -> None:
        """Verify sensible defaults when JSON dict has missing keys."""
        issue = RuffIssue({})

        assert issue.code == ""
        assert issue.message == ""
        assert issue.line == 0
        assert issue.column == 0
        assert issue.filename == ""
        assert issue.fixable is False
        assert issue.url == ""

    def test_fixable_is_false_when_fix_is_none(self) -> None:
        """Verify fixable is False when fix key is explicitly None."""
        data = {
            "code": "N801",
            "message": "class name",
            "location": {"row": 1, "column": 1},
            "filename": "test.py",
            "fix": None,
            "url": "",
        }

        issue = RuffIssue(data)

        assert issue.fixable is False

    def test_repr_format(self) -> None:
        """Verify __repr__ includes code, filename, line, and column."""
        data = {
            "code": "E501",
            "message": "line too long",
            "location": {"row": 42, "column": 80},
            "filename": "long_file.py",
            "fix": None,
            "url": "",
        }

        issue = RuffIssue(data)

        assert repr(issue) == "RuffIssue(E501 at long_file.py:42:80)"


# ── BanditIssue ── #


@pytest.mark.unit
class TestBanditIssueFieldExtraction:
    """Test BanditIssue construction and edge cases."""

    def test_extracts_all_fields_from_complete_data(self) -> None:
        """Verify all fields are extracted from a complete Bandit JSON dict."""
        data = {
            "test_id": "B301",
            "test_name": "pickle",
            "issue_severity": "HIGH",
            "issue_confidence": "MEDIUM",
            "line_number": 15,
            "filename": "loader.py",
            "issue_text": "Pickle usage detected.",
            "more_info": "https://bandit.readthedocs.io/",
            "code": "import pickle\npickle.loads(data)\n",
        }

        issue = BanditIssue(data)

        assert issue.test_id == "B301"
        assert issue.test_name == "pickle"
        assert issue.severity == "HIGH"
        assert issue.confidence == "MEDIUM"
        assert issue.line_number == 15
        assert issue.filename == "loader.py"
        assert issue.issue_text == "Pickle usage detected."
        assert issue.more_info == "https://bandit.readthedocs.io/"
        assert "pickle.loads" in issue.source_code

    def test_defaults_on_missing_fields(self) -> None:
        """Verify defaults when JSON dict is empty."""
        issue = BanditIssue({})

        assert issue.test_id == ""
        assert issue.severity == "LOW"
        assert issue.confidence == "LOW"
        assert issue.line_number == 0

    def test_severity_uppercased(self) -> None:
        """Verify severity is always uppercased from raw data."""
        data = {
            "test_id": "B101",
            "test_name": "assert_used",
            "issue_severity": "medium",
            "issue_confidence": "high",
            "line_number": 1,
            "filename": "t.py",
            "issue_text": "",
            "more_info": "",
            "code": "",
        }

        issue = BanditIssue(data)

        assert issue.severity == "MEDIUM"
        assert issue.confidence == "HIGH"

    def test_repr_format(self) -> None:
        """Verify __repr__ includes test_id, severity/confidence, filename, and line."""
        data = {
            "test_id": "B101",
            "test_name": "assert_used",
            "issue_severity": "LOW",
            "issue_confidence": "HIGH",
            "line_number": 7,
            "filename": "tests/test_x.py",
            "issue_text": "assert used",
            "more_info": "",
            "code": "",
        }

        issue = BanditIssue(data)

        assert repr(issue) == "BanditIssue(B101 [LOW/HIGH] at tests/test_x.py:7)"

    def test_meets_threshold_unknown_severity_defaults_to_zero(self) -> None:
        """Unknown severity/confidence values default to rank 0 via .get(, 0)."""
        data = {
            "test_id": "B999",
            "test_name": "custom",
            "issue_severity": "CRITICAL",
            "issue_confidence": "EXTREME",
            "line_number": 1,
            "filename": "t.py",
            "issue_text": "",
            "more_info": "",
            "code": "",
        }
        issue = BanditIssue(data)

        # Unknown severity ("CRITICAL") gets rank 0, which is < LOW's rank 0
        # Actually LOW also maps to 0, so 0 >= 0 is True for "low" threshold
        assert issue.meets_threshold("low", "low") is True
        # But 0 < 1 (MEDIUM), so fails medium threshold
        assert issue.meets_threshold("medium", "low") is False
        assert issue.meets_threshold("low", "medium") is False


# ── EffectiveValue ── #


@pytest.mark.unit
class TestEffectiveValueRepr:
    """Test EffectiveValue.__repr__ output format."""

    def test_repr_shows_value_and_source(self) -> None:
        """Verify repr includes value and source name."""
        effective = EffectiveValue(120, ConfigSource.CLI)

        result = repr(effective)

        assert "120" in result
        assert "source=" in result
        assert "EffectiveValue" in result

    def test_repr_with_none_value(self) -> None:
        """Verify repr handles None value correctly."""
        effective = EffectiveValue(None, ConfigSource.TOOL_DEFAULT)

        result = repr(effective)

        assert "None" in result
        assert "tool_default" in result

    def test_repr_with_string_value(self) -> None:
        """Verify repr quotes string values."""
        effective = EffectiveValue("strict", ConfigSource.PYPROJECT)

        result = repr(effective)

        assert "'strict'" in result
