"""Tests filling coverage gaps identified by py-pipeline-d test review.

Covers _FieldSpec declarative mapping in configs/resolver.py, _build_resolved_config
and _run_analysis_phase in main.py, execution/issues.py edge cases, execution/results.py
edge cases, and cross-module _FieldSpec -> build_global_config -> tool dispatch chain.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scrutiny.config import UserDefaults
from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.configs.resolver import (
    _GLOBAL_CONFIG_FIELDS,
    ConfigResolver,
    ContextDetection,
    _FieldSpec,
)
from scrutiny.core.enums import (
    ConfigTier,
    LineLength,
    PythonVersion,
)
from scrutiny.core.exceptions import (
    SCRLoggerLevelError,
    SCRSystemError,
    ExitCode,
)
from scrutiny.execution.issues import BanditIssue, RuffIssue
from scrutiny.execution.results import ResultTotals, ToolResult
from scrutiny.main import (
    _build_resolved_config,
    _run_analysis_phase,
)
from conftest import make_global_config

_EXPECTED_FIELD_SPEC_COUNT_MIN = 30
_EXPECTED_CONTEXT_FIELDS = 3
_RUFF_ISSUE_LINE = 42
_RUFF_ISSUE_COLUMN = 5
_RUFF_ISSUE_REPR_LINE = 10
_RUFF_ISSUE_REPR_COLUMN = 100
_BANDIT_LINE_NUMBER = 55
_RESULT_ISSUES_FOUND = 7
_RESULT_ISSUES_FIXED = 3
_RESULT_ERROR_CODE = 5
_RESULT_FILES_PROCESSED = 10
_PYPROJECT_LINE_LENGTH = 120


@pytest.mark.unit
class TestFieldSpecStructure:
    """Tests for _FieldSpec dataclass and _GLOBAL_CONFIG_FIELDS tuple."""

    def test_field_spec_has_required_attributes(self) -> None:
        """_FieldSpec instances expose gc_field, cli_key, snapshot_attr."""
        spec = _FieldSpec("test_field", "test_cli", "test_snap")
        assert spec.gc_field == "test_field"
        assert spec.cli_key == "test_cli"
        assert spec.snapshot_attr == "test_snap"
        assert spec.enum_class is None
        assert spec.exception_class is None
        assert spec.pyproject_tool is None
        assert spec.pyproject_key is None
        assert spec.context_key is None

    def test_global_config_fields_has_expected_minimum_count(self) -> None:
        """_GLOBAL_CONFIG_FIELDS has at least 30 entries covering all config fields."""
        assert len(_GLOBAL_CONFIG_FIELDS) >= _EXPECTED_FIELD_SPEC_COUNT_MIN

    def test_all_gc_fields_are_unique(self) -> None:
        """Each _FieldSpec.gc_field is unique (no duplicates in the mapping)."""
        gc_fields = [spec.gc_field for spec in _GLOBAL_CONFIG_FIELDS]
        assert len(gc_fields) == len(set(gc_fields))

    def test_all_gc_fields_match_global_config_constructor(self) -> None:
        """Every gc_field in _GLOBAL_CONFIG_FIELDS is a valid GlobalConfig field."""
        import dataclasses

        valid_fields = {f.name for f in dataclasses.fields(GlobalConfig)}
        for spec in _GLOBAL_CONFIG_FIELDS:
            assert spec.gc_field in valid_fields, (
                f"_FieldSpec.gc_field={spec.gc_field!r} not in GlobalConfig fields"
            )

    def test_all_snapshot_attrs_exist_on_snapshot(self) -> None:
        """Every snapshot_attr in _GLOBAL_CONFIG_FIELDS exists on UserDefaultsSnapshot."""
        snapshot = UserDefaults.to_frozen()
        for spec in _GLOBAL_CONFIG_FIELDS:
            assert hasattr(snapshot, spec.snapshot_attr), (
                f"_FieldSpec.snapshot_attr={spec.snapshot_attr!r} not on snapshot"
            )

    def test_enum_fields_have_valid_enum_classes(self) -> None:
        """Every _FieldSpec with enum_class references a real enum type."""
        for spec in _GLOBAL_CONFIG_FIELDS:
            if spec.enum_class is not None:
                assert hasattr(spec.enum_class, "__members__"), (
                    f"{spec.gc_field}: enum_class={spec.enum_class} is not an enum"
                )

    def test_context_fields_have_context_key(self) -> None:
        """Context-aware fields have non-None context_key."""
        context_specs = [s for s in _GLOBAL_CONFIG_FIELDS if s.context_key is not None]
        assert len(context_specs) == _EXPECTED_CONTEXT_FIELDS
        for spec in context_specs:
            assert spec.context_key.startswith("ctx_")


@pytest.mark.unit
class TestFieldSpecBuildGlobalConfig:
    """Tests that build_global_config's _FieldSpec loop produces valid config."""

    def test_default_config_via_field_spec_loop(self) -> None:
        """build_global_config with no overrides produces defaults from snapshot."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.parallel == snapshot.scr_parallel
        assert config.python_version == PythonVersion(snapshot.scr_python_version)
        assert config.line_length == LineLength(snapshot.scr_line_length)

    def test_cli_override_flows_through_field_spec_loop(self) -> None:
        """CLI args override snapshot defaults via the _FieldSpec loop."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={"parallel": False, "no_cache": True},
            pyproject_config={},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.parallel is False
        assert config.no_cache is True

    def test_pyproject_override_flows_through_field_spec_loop(self) -> None:
        """Pyproject values override defaults for fields with pyproject mappings."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": _PYPROJECT_LINE_LENGTH}},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.line_length == LineLength(_PYPROJECT_LINE_LENGTH)

    def test_enum_construction_error_raises_correct_exception(self) -> None:
        """Invalid enum value in CLI raises the specified exception type."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={"file_logger_level": "INVALID_LEVEL"},
            pyproject_config={},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        with pytest.raises(SCRLoggerLevelError, match="Invalid value"):
            resolver.build_global_config()

    def test_context_key_delivers_context_value(self) -> None:
        """Context-aware field receives value from ContextDetection."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            context=ContextDetection.CI,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.check_only is True

    def test_config_tier_handled_as_special_case(self) -> None:
        """config_tier is resolved from self._tier, not the snapshot."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={},
            context=None,
            tier=ConfigTier.ESSENTIAL,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.config_tier == ConfigTier.ESSENTIAL


@pytest.mark.unit
class TestBuildResolvedConfig:
    """Tests for _build_resolved_config orchestration."""

    def test_returns_resolved_config_with_all_fields(self, tmp_path: Path) -> None:
        """Returns _ResolvedConfig with all required fields populated."""
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        snapshot = UserDefaults.to_frozen()
        cli_dict: dict[str, Any] = {}
        tier = snapshot.scr_config_tier

        with patch(
            "scrutiny.main.ContextDetection.detect",
            autospec=True,
            return_value=ContextDetection.CLI,
        ):
            result = _build_resolved_config(tmp_path, cli_dict, snapshot, tier)

        assert result.resolver is not None
        assert isinstance(result.global_config, GlobalConfig)
        assert result.context == ContextDetection.CLI
        assert result.effective_root is not None
        assert isinstance(result.pyproject_has_config, bool)

    def test_detects_pyproject_config_flag(self, tmp_path: Path) -> None:
        """pyproject_has_config is True when pyproject.toml has tool config."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.ruff]\nline-length = 120\n",
            encoding="utf-8",
        )
        snapshot = UserDefaults.to_frozen()

        with patch(
            "scrutiny.main.ContextDetection.detect",
            autospec=True,
            return_value=ContextDetection.CLI,
        ):
            result = _build_resolved_config(tmp_path, {}, snapshot, snapshot.scr_config_tier)

        assert result.pyproject_has_config is True


@pytest.mark.unit
class TestRunAnalysisPhaseErrorHandling:
    """Tests for _run_analysis_phase error paths."""

    def test_cqerror_during_analysis_returns_error_exit_code(self) -> None:
        """SCRError raised during tool verification returns the error's exit code."""
        args = argparse.Namespace(
            paths=None,
            show_config=False,
            tools=["mypy"],
        )
        config = make_global_config()
        context = ContextDetection.CLI
        root = Path("/project")

        with (
            patch(
                "scrutiny.main._determine_tool_names",
                autospec=True,
                return_value=["mypy"],
            ),
            patch(
                "scrutiny.main._verify_tool_availability",
                autospec=True,
                side_effect=SCRSystemError("missing mypy"),
            ),
        ):
            exit_code = _run_analysis_phase(
                args,
                gen_status=None,
                resolver=MagicMock(),
                global_config=config,
                context=context,
                effective_root=root,
                pyproject_path=None,
                log_root=None,
            )

        assert exit_code == ExitCode.SYSTEM

    def test_show_config_mode_returns_zero(self) -> None:
        """Show-config mode returns 0 without running tools."""
        args = argparse.Namespace(
            paths=None,
            show_config=True,
            tools=None,
        )
        config = make_global_config()
        context = ContextDetection.CLI
        root = Path("/project")

        with patch(
            "scrutiny.main._show_effective_config",
            autospec=True,
            return_value=0,
        ):
            exit_code = _run_analysis_phase(
                args,
                gen_status=None,
                resolver=MagicMock(),
                global_config=config,
                context=context,
                effective_root=root,
                pyproject_path=None,
                log_root=None,
            )

        assert exit_code == 0

    def test_no_tools_enabled_returns_zero(self) -> None:
        """Returns 0 when no tools are enabled."""
        args = argparse.Namespace(
            paths=None,
            show_config=False,
            tools=None,
        )
        config = make_global_config()
        context = ContextDetection.CLI
        root = Path("/project")

        with patch(
            "scrutiny.main._determine_tool_names",
            autospec=True,
            return_value=[],
        ):
            exit_code = _run_analysis_phase(
                args,
                gen_status=None,
                resolver=MagicMock(),
                global_config=config,
                context=context,
                effective_root=root,
                pyproject_path=None,
                log_root=None,
            )

        assert exit_code == 0

    def test_no_files_found_returns_zero(self) -> None:
        """Returns 0 when file discovery finds no Python files."""
        args = argparse.Namespace(
            paths=None,
            show_config=False,
            tools=None,
        )
        config = make_global_config()
        context = ContextDetection.CLI
        root = Path("/project")

        with (
            patch(
                "scrutiny.main._determine_tool_names",
                autospec=True,
                return_value=["mypy"],
            ),
            patch(
                "scrutiny.main._verify_tool_availability",
                autospec=True,
            ),
            patch(
                "scrutiny.main.FileDiscoveryService.discover_files",
                autospec=True,
                return_value=[],
            ),
        ):
            exit_code = _run_analysis_phase(
                args,
                gen_status=None,
                resolver=MagicMock(),
                global_config=config,
                context=context,
                effective_root=root,
                pyproject_path=None,
                log_root=None,
            )

        assert exit_code == 0


@pytest.mark.unit
class TestRuffIssueEdgeCases:
    """Edge-case tests for RuffIssue construction from JSON data."""

    def test_empty_data_dict_uses_defaults(self) -> None:
        """RuffIssue from empty dict fills fields with defaults."""
        issue = RuffIssue({})
        assert issue.code == ""
        assert issue.message == ""
        assert issue.line == 0
        assert issue.column == 0
        assert issue.filename == ""
        assert issue.fixable is False
        assert issue.url == ""

    def test_fixable_when_fix_key_present(self) -> None:
        """RuffIssue.fixable is True when 'fix' key is not None."""
        issue = RuffIssue({"fix": {"applicability": "safe"}})
        assert issue.fixable is True

    def test_fixable_false_when_fix_is_none(self) -> None:
        """RuffIssue.fixable is False when 'fix' key is None."""
        issue = RuffIssue({"fix": None})
        assert issue.fixable is False

    def test_location_extracted_correctly(self) -> None:
        """RuffIssue extracts line/column from nested location dict."""
        data = {
            "code": "F401",
            "message": "unused import",
            "location": {"row": _RUFF_ISSUE_LINE, "column": _RUFF_ISSUE_COLUMN},
            "filename": "test.py",
            "url": "https://docs.astral.sh/ruff/rules/F401",
        }
        issue = RuffIssue(data)
        assert issue.code == "F401"
        assert issue.line == _RUFF_ISSUE_LINE
        assert issue.column == _RUFF_ISSUE_COLUMN
        assert issue.filename == "test.py"

    def test_repr_format(self) -> None:
        """RuffIssue repr includes code, filename, line, and column."""
        issue = RuffIssue(
            {
                "code": "E501",
                "location": {"row": _RUFF_ISSUE_REPR_LINE, "column": _RUFF_ISSUE_REPR_COLUMN},
                "filename": "module.py",
            }
        )
        result = repr(issue)
        assert "E501" in result
        assert "module.py" in result
        assert str(_RUFF_ISSUE_REPR_LINE) in result


@pytest.mark.unit
class TestBanditIssueEdgeCases:
    """Edge-case tests for BanditIssue construction and threshold logic."""

    def test_empty_data_dict_uses_defaults(self) -> None:
        """BanditIssue from empty dict fills fields with safe defaults."""
        issue = BanditIssue({})
        assert issue.test_id == ""
        assert issue.test_name == ""
        assert issue.severity == "LOW"
        assert issue.confidence == "LOW"
        assert issue.line_number == 0
        assert issue.filename == ""

    def test_severity_uppercased(self) -> None:
        """BanditIssue uppercases severity from JSON."""
        issue = BanditIssue({"issue_severity": "medium"})
        assert issue.severity == "MEDIUM"

    @pytest.mark.parametrize(
        ("severity", "confidence", "min_sev", "min_conf", "expected"),
        [
            pytest.param("HIGH", "HIGH", "low", "low", True, id="high_meets_low"),
            pytest.param("LOW", "LOW", "high", "high", False, id="low_fails_high"),
            pytest.param("MEDIUM", "HIGH", "medium", "medium", True, id="medium_meets_medium"),
            pytest.param("HIGH", "LOW", "high", "medium", False, id="high_sev_low_conf_fails"),
        ],
    )
    def test_meets_threshold_parametrized(
        self,
        severity: str,
        confidence: str,
        min_sev: str,
        min_conf: str,
        expected: bool,
    ) -> None:
        """Parametrized threshold checks for severity and confidence."""
        issue = BanditIssue(
            {
                "issue_severity": severity,
                "issue_confidence": confidence,
            }
        )
        assert issue.meets_threshold(min_sev, min_conf) is expected

    def test_repr_format(self) -> None:
        """BanditIssue repr includes test_id, severity, confidence, filename."""
        issue = BanditIssue(
            {
                "test_id": "B201",
                "issue_severity": "HIGH",
                "issue_confidence": "MEDIUM",
                "filename": "app.py",
                "line_number": _BANDIT_LINE_NUMBER,
            }
        )
        result = repr(issue)
        assert "B201" in result
        assert "HIGH" in result
        assert "MEDIUM" in result
        assert "app.py" in result


@pytest.mark.unit
class TestToolResultEdgeCases:
    """Edge-case tests for ToolResult dataclass behavior."""

    def test_tool_data_default_factory_independent(self) -> None:
        """Each ToolResult gets its own tool_data dict (no shared mutable default)."""
        r1 = ToolResult(
            tool="a",
            success=True,
            exit_code=0,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="",
        )
        r2 = ToolResult(
            tool="b",
            success=True,
            exit_code=0,
            execution_time=0.0,
            files_processed=0,
            stdout="",
            stderr="",
        )
        r1.tool_data["key"] = "value"
        assert "key" not in r2.tool_data

    def test_explicit_field_values_override_defaults(self) -> None:
        """Explicit issues_found, issues_fixed, error_code override defaults."""
        result = ToolResult(
            tool="mypy",
            success=False,
            exit_code=1,
            execution_time=2.5,
            files_processed=_RESULT_FILES_PROCESSED,
            stdout="output",
            stderr="error",
            issues_found=_RESULT_ISSUES_FOUND,
            issues_fixed=_RESULT_ISSUES_FIXED,
            error_code=_RESULT_ERROR_CODE,
        )
        assert result.issues_found == _RESULT_ISSUES_FOUND
        assert result.issues_fixed == _RESULT_ISSUES_FIXED
        assert result.error_code == _RESULT_ERROR_CODE


@pytest.mark.unit
class TestResultTotalsEdgeCases:
    """Edge-case tests for ResultTotals dataclass."""

    def test_stores_zero_values(self) -> None:
        """ResultTotals correctly stores all-zero values."""
        totals = ResultTotals(
            worst_error_code=0,
            total_issues=0,
            total_fixed=0,
            total_time=0.0,
            max_name_len=0,
        )
        assert totals.worst_error_code == 0
        assert totals.total_time == 0.0


@pytest.mark.integration
class TestFieldSpecToToolDispatchChain:
    """Integration: snapshot -> _FieldSpec loop -> config -> tool dispatch."""

    def test_snapshot_through_fieldspec_to_enabled_tools(self) -> None:
        """Full chain: UserDefaults -> resolver (FieldSpec loop) -> enabled tools."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={"run_mypy": False},
            pyproject_config={},
            context=ContextDetection.CLI,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.run_mypy is False
        tools = config.get_enabled_tools(ContextDetection.CLI)
        assert "mypy" not in tools

    def test_pyproject_enum_override_through_fieldspec(self) -> None:
        """Pyproject line_length override flows through _FieldSpec enum construction."""
        snapshot = UserDefaults.to_frozen()
        resolver = ConfigResolver(
            cli_args={},
            pyproject_config={"ruff": {"line_length": _PYPROJECT_LINE_LENGTH}},
            context=None,
            tier=snapshot.scr_config_tier,
            snapshot=snapshot,
        )
        config = resolver.build_global_config()

        assert config.line_length == LineLength(_PYPROJECT_LINE_LENGTH)
        assert config.line_length.value == _PYPROJECT_LINE_LENGTH


@pytest.mark.integration
class TestBuildResolvedConfigIntegration:
    """Integration: _build_resolved_config with real file system."""

    def test_build_resolved_config_with_pyproject(self, tmp_path: Path) -> None:
        """_build_resolved_config reads pyproject.toml and sets pyproject_has_config."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[tool.ruff]\nline-length = 120\n",
            encoding="utf-8",
        )
        snapshot = UserDefaults.to_frozen()

        with patch(
            "scrutiny.main.ContextDetection.detect",
            autospec=True,
            return_value=ContextDetection.CLI,
        ):
            result = _build_resolved_config(
                tmp_path,
                {},
                snapshot,
                snapshot.scr_config_tier,
            )

        assert result.pyproject_has_config is True
        assert isinstance(result.global_config, GlobalConfig)

    def test_build_resolved_config_without_pyproject(self, tmp_path: Path) -> None:
        """_build_resolved_config with no pyproject.toml sets flag to False."""
        (tmp_path / ".git").mkdir()
        snapshot = UserDefaults.to_frozen()

        with patch(
            "scrutiny.main.ContextDetection.detect",
            autospec=True,
            return_value=ContextDetection.CLI,
        ):
            result = _build_resolved_config(
                tmp_path,
                {},
                snapshot,
                snapshot.scr_config_tier,
            )

        assert result.pyproject_has_config is False


@pytest.mark.integration
class TestRunAnalysisPhaseLifecycle:
    """Integration: _run_analysis_phase with mocked tool execution."""

    def test_full_analysis_phase_clean_run(self, tmp_path: Path) -> None:
        """Full analysis phase: discover files, run tools, report success."""
        py_file = tmp_path / "example.py"
        py_file.write_text("x = 1\n", encoding="utf-8")

        args = argparse.Namespace(
            paths=[tmp_path],
            show_config=False,
            tools=["mypy"],
        )
        config = make_global_config(parallel=False)
        resolver_mock = MagicMock()
        resolver_mock.build_mypy_config.return_value = MagicMock()
        resolver_mock.build_ruff_config.return_value = MagicMock()
        resolver_mock.build_radon_config.return_value = MagicMock()
        resolver_mock.build_bandit_config.return_value = MagicMock()
        resolver_mock.build_ruff_security_config.return_value = MagicMock()

        clean_result = ToolResult(
            tool="mypy",
            success=True,
            exit_code=0,
            execution_time=0.5,
            files_processed=1,
            stdout="",
            stderr="",
        )

        with (
            patch(
                "scrutiny.main._determine_tool_names",
                autospec=True,
                return_value=["mypy"],
            ),
            patch(
                "scrutiny.main._verify_tool_availability",
                autospec=True,
            ),
            patch(
                "scrutiny.main.FileDiscoveryService.discover_files",
                autospec=True,
                return_value=[py_file],
            ),
            patch(
                "scrutiny.main._compute_mi_ranks",
                autospec=True,
                return_value=None,
            ),
            patch(
                "scrutiny.main.print_header",
                autospec=True,
            ),
            patch(
                "scrutiny.main._dispatch_tool_execution",
                autospec=True,
                return_value=[clean_result],
            ),
        ):
            exit_code = _run_analysis_phase(
                args,
                gen_status=None,
                resolver=resolver_mock,
                global_config=config,
                context=ContextDetection.CLI,
                effective_root=tmp_path,
                pyproject_path=None,
                log_root=None,
            )

        assert exit_code == 0
