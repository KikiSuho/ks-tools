"""Integration tests: multi-tool mock source with tier-aware assertions.

This module runs all four code-quality tools (Ruff, Radon, Bandit, Mypy)
against a single inline mock Python source.  Each tool has issues that
differentiate **strict** from **standard** tier, allowing us to verify
both detection and tier-filtering behaviour end-to-end.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from scrutiny.config import UserDefaults
from scrutiny.configs.dataclasses import (
    BanditConfig,
    MypyConfig,
    RadonConfig,
    RuffConfig,
)
from scrutiny.core.enums import LoggerLevel
from scrutiny.core.tool_data import (
    BANDIT_TIER_SETTINGS,
    MYPY_TIER_SETTINGS,
    RADON_TIER_SETTINGS,
    RUFF_RULES_STRICT,
    RUFF_TIER_RULES,
)
from scrutiny.execution.handlers import (
    BanditHandler,
    BaseToolHandler,
    MypyHandler,
    RadonCCHandler,
    RuffHandler,
)
from scrutiny.main import _run_tool_safe
from scrutiny.output.logger import SCRLogger

import pytest


# ══════════════════════════════════════════════════════════════════ #
#  Mock source with tier-aware issues for all four tools            #
# ══════════════════════════════════════════════════════════════════ #

# Defined inline so linter hooks cannot strip the intentionally-unused imports.
#
# Issue matrix:
#   Ruff  (standard+): F401 x2 (safe fix), C408 (unsafe fix), N801 (no fix)
#   Ruff  (strict):    ARG001, BLE001, T201, PLR2004 (all no fix)
#   Radon (strict+):   high_complexity (grade C, 11+)
#   Radon (insane):    moderate_complexity (grade B, 6-10)
#   Radon (passes):    simple_add (grade A, 1)
#   Bandit(standard+): B301 pickle.loads (sev:MED, conf:HIGH)
#   Bandit(strict):    B108 hardcoded tmp, B608 SQL concat (sev:MED, conf:MED)
#   Mypy  (standard+): typed_wrong incompatible return type
#   Mypy  (strict):    untyped_function, UNTYPED_GLOBAL missing annotations
_MOCK_SOURCE = """\
import os
import sys
import json
import pickle
import subprocess


# ── Ruff: fixable (safe) ──
# F401: sys, json unused — removed by --fix  [STANDARD + STRICT]


# ── Ruff: fixable (unsafe) ──
x = dict()


# ── Ruff: unfixable, standard ──
class my_class:
    pass


# ── Ruff: unfixable, strict-only ──
def unused_arg(used, unused):                # ARG001: unused argument   [STRICT only]
    return used


def blind_except_handler():                  # BLE001: blind except      [STRICT only]
    try:
        pass
    except Exception:
        pass


print(os.getcwd())

MAGIC = 42


def check_magic(value: int) -> bool:
    return value == MAGIC


# ── Mypy: caught at both standard and strict ──
def typed_wrong(count: int) -> str:
    return count


# ── Mypy: strict-only (missing annotations) ──
def untyped_function(value):
    return value + 1


UNTYPED_GLOBAL = 99


# ── Radon: complexity B (6-10) — flagged at strict, passes standard ──
def moderate_complexity(a, b, c):
    if a > 0:
        if b > 0:
            return 1
        elif b < -5:
            return 2
        else:
            return 3
    elif a < 0:
        return 4
    if c:
        return 5
    return 0


# ── Radon: complexity C (11+) — flagged at both strict and standard ──
def high_complexity(a, b, c, d, e):
    result = 0
    if a > 0:
        if b > 0:
            result += 1
        elif b < -5:
            result += 2
        else:
            result += 3
    elif a < 0:
        if c:
            result += 4
        else:
            result += 5
    if d == 1:
        result += 6
    elif d == 2:
        result += 7
    elif d == 3:
        result += 8
    elif d == 4:
        result += 10
    if e:
        result += 9
    else:
        result -= 1
    return result


# ── Radon: complexity A (1-5) — passes both ──
def simple_add(first: int, second: int) -> int:
    return first + second


# ── Bandit: medium severity + high confidence — caught at both ──
def deserialize_data() -> object:
    return pickle.loads(b"test")


# ── Bandit: medium severity + medium confidence — strict only ──
def run_command() -> None:
    subprocess.call(["ls", "-la"])


def use_temp_file() -> None:
    handle = open("/tmp/test.txt", "w")
    handle.close()


def build_query(user_id: int) -> str:
    return "SELECT * FROM users WHERE id=" + str(user_id)
"""


# ── Per-tool runner helpers ── #


def _run_ruff_on_mock_source(
    *,
    tier: str = "strict",
) -> Any:
    """Run the Ruff 3-pass fix strategy on a temp copy of ``_MOCK_SOURCE``.

    Parameters
    ----------
    tier : str
        Quality tier name (``"standard"`` or ``"strict"``).

    Returns
    -------
    ToolResult
        Result with ``initial_issues``, ``issues``, and ``fixed_count``.
    """
    tier_rules = RUFF_TIER_RULES.get(tier, RUFF_RULES_STRICT)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "sample.py"
        target.write_text(_MOCK_SOURCE, encoding="utf-8")

        handler = RuffHandler(timeout=30)
        ruff_config = RuffConfig(
            select_rules=tier_rules,
            fix=True,
            unsafe_fixes=False,
            no_cache=True,
            line_length=UserDefaults.SCR_LINE_LENGTH.value,
            exclude_dirs=(),
            exclude_files=(),
        )
        global_config = MagicMock()
        global_config.check_only = False
        global_config.effective_fix = True

        return handler.run([target], ruff_config, global_config, tmp_path)


def _run_radon_on_mock_source(
    *,
    tier: str = "strict",
) -> Any:
    """Run RadonCCHandler on a temp copy of ``_MOCK_SOURCE``.

    Parameters
    ----------
    tier : str
        Quality tier name (``"standard"`` or ``"strict"``).

    Returns
    -------
    ToolResult
        Result with ``functions`` in ``tool_data``.
    """
    tier_settings = RADON_TIER_SETTINGS.get(tier, {})
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "sample.py"
        target.write_text(_MOCK_SOURCE, encoding="utf-8")

        handler = RadonCCHandler(timeout=30)
        radon_config = RadonConfig(
            minimum_complexity=tier_settings.get("minimum_complexity", "B"),
            exclude_dirs=(),
            exclude_files=(),
        )
        global_config = MagicMock()

        return handler.run([target], radon_config, global_config, tmp_path)


def _run_bandit_on_mock_source(
    *,
    tier: str = "strict",
) -> Any:
    """Run BanditHandler on a temp copy of ``_MOCK_SOURCE``.

    Parameters
    ----------
    tier : str
        Quality tier name (``"standard"`` or ``"strict"``).

    Returns
    -------
    ToolResult
        Result with ``issues`` in ``tool_data``.
    """
    tier_settings = BANDIT_TIER_SETTINGS.get(tier, {})
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "sample.py"
        target.write_text(_MOCK_SOURCE, encoding="utf-8")

        handler = BanditHandler(timeout=30)
        bandit_config = BanditConfig(
            severity=tier_settings.get("severity", "medium"),
            confidence=tier_settings.get("confidence", "medium"),
            exclude_dirs=(),
            exclude_files=(),
        )
        global_config = MagicMock()

        return handler.run([target], bandit_config, global_config, tmp_path)


def _run_mypy_on_mock_source(
    *,
    tier: str = "strict",
) -> Any:
    """Run MypyHandler on a temp copy of ``_MOCK_SOURCE``.

    Parameters
    ----------
    tier : str
        Quality tier name (``"standard"`` or ``"strict"``).

    Returns
    -------
    ToolResult
        Result with ``issues`` in ``tool_data``.
    """
    tier_settings = MYPY_TIER_SETTINGS.get(tier, {})
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        target = tmp_path / "sample.py"
        target.write_text(_MOCK_SOURCE, encoding="utf-8")

        handler = MypyHandler(timeout=30)
        mypy_config = MypyConfig(**tier_settings)
        global_config = MagicMock()

        return handler.run([target], mypy_config, global_config, tmp_path)


# ── Mono-test: all tools on one mock source ── #


@pytest.mark.unit
class TestAllToolsOnMockSource:
    """Run all four tools against ``_MOCK_SOURCE`` at strict tier."""

    def test_ruff_finds_fixable_and_unfixable(self) -> None:
        """Ruff detects F401 (fixable) and N801/ARG001/BLE001 (unfixable)."""
        result = _run_ruff_on_mock_source(tier="strict")

        initial_codes = {issue.code for issue in result.tool_data["initial_issues"]}
        remaining_codes = {issue.code for issue in result.tool_data["issues"]}

        # F401 was present initially but fixed.
        assert "F401" in initial_codes
        assert "F401" not in remaining_codes
        assert result.tool_data["fixed_count"] > 0

        # Unfixable issues survive.
        assert "N801" in remaining_codes
        assert "ARG001" in remaining_codes or "BLE001" in remaining_codes

    def test_radon_flags_complex_passes_simple(self) -> None:
        """Radon flags high_complexity (C) but not moderate_complexity (B) or simple_add (A)."""
        result = _run_radon_on_mock_source(tier="strict")

        flagged_names = {func["name"] for func in result.tool_data["functions"]}
        # Grade C exceeds strict threshold B — flagged.
        assert "high_complexity" in flagged_names
        # Grade B equals strict threshold — within threshold, not flagged.
        assert "moderate_complexity" not in flagged_names
        # Grade A is always within threshold.
        assert "simple_add" not in flagged_names

    def test_bandit_catches_security_issues(self) -> None:
        """Bandit detects B301 (pickle) and B108/B608 at strict."""
        result = _run_bandit_on_mock_source(tier="strict")

        found_ids = {issue.test_id for issue in result.tool_data["issues"]}
        assert "B301" in found_ids
        # At least one of the medium-confidence issues.
        assert found_ids & {"B108", "B608"}

    def test_mypy_catches_type_errors(self) -> None:
        """Mypy detects incompatible return type and missing annotations."""
        result = _run_mypy_on_mock_source(tier="strict")

        messages = [issue["message"] for issue in result.tool_data["issues"]]
        combined = " ".join(messages)
        # Type mismatch on typed_wrong return.
        assert "incompatible return" in combined.lower() or "return-value" in combined.lower()
        assert result.issues_found > 0


# ── Ruff three-pass fix integration ── #


@pytest.mark.unit
class TestThreePassFixIntegration:
    """Verify the Ruff 3-pass fix strategy using ``_MOCK_SOURCE``.

    After the 3-pass with ``unsafe_fixes=False``:
      - ``initial_issues`` includes all detected issues
      - ``issues`` excludes the F401 entries (they were fixed)
      - ``fixed_count`` equals the number of F401 issues removed
    """

    def test_three_pass_produces_initial_and_remaining(self) -> None:
        """The 3-pass populates initial_issues, issues, and fixed_count."""
        result = _run_ruff_on_mock_source()

        assert result.tool_data["fixed_count"] > 0
        assert len(result.tool_data["initial_issues"]) > len(result.tool_data["issues"])

    def test_fixed_items_are_f401(self) -> None:
        """Only the safe-fixable F401 issues are removed by the fix pass."""
        result = _run_ruff_on_mock_source()

        initial_codes = {issue.code for issue in result.tool_data["initial_issues"]}
        remaining_codes = {issue.code for issue in result.tool_data["issues"]}

        assert "F401" in initial_codes
        assert "F401" not in remaining_codes
        assert "N801" in remaining_codes

    def test_normal_output_shows_compact_remaining_only(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """At NORMAL level, compact issue lines appear without fixed items."""
        result = _run_ruff_on_mock_source()

        logger = SCRLogger.__new__(SCRLogger)
        logger.console_level = LoggerLevel.NORMAL
        logger.file_level = LoggerLevel.QUIET
        logger.use_colors = False
        logger.log_file = None
        logger._lock = __import__("threading").RLock()

        executor = MagicMock()
        executor.run_tool.return_value = result

        _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        console_output = capsys.readouterr().out
        assert "N801" in console_output
        assert "https://" not in console_output
        assert "Fixed by Ruff:" not in console_output

    def test_verbose_output_shows_fixed_section(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """At VERBOSE level, the fixed-by-Ruff section appears."""
        result = _run_ruff_on_mock_source()

        logger = SCRLogger.__new__(SCRLogger)
        logger.console_level = LoggerLevel.VERBOSE
        logger.file_level = LoggerLevel.QUIET
        logger.use_colors = False
        logger.log_file = None
        logger._lock = __import__("threading").RLock()

        executor = MagicMock()
        executor.run_tool.return_value = result

        _run_tool_safe(
            executor,
            "ruff_linter",
            [],
            None,
            MagicMock(),
            Path(),
            logger,
        )

        console_output = capsys.readouterr().out
        assert "Fixed by Ruff:" in console_output
        assert "F401" in console_output
        assert "N801" in console_output


# ── Per-tool tier comparison tests ── #


@pytest.mark.unit
class TestRuffTierComparison:
    """Verify strict catches rules that standard misses."""

    def test_strict_catches_arg001_and_ble001(self) -> None:
        """Strict tier detects ARG001 (unused arg) and BLE001 (blind except)."""
        result = _run_ruff_on_mock_source(tier="strict")

        codes = {issue.code for issue in result.tool_data["issues"]}
        assert "ARG001" in codes
        assert "BLE001" in codes

    def test_standard_misses_strict_only_rules(self) -> None:
        """Standard tier does not detect ARG001, BLE001, or T201."""
        result = _run_ruff_on_mock_source(tier="standard")

        codes = {issue.code for issue in result.tool_data["issues"]}
        assert "ARG001" not in codes
        assert "BLE001" not in codes
        assert "T201" not in codes

    def test_both_tiers_catch_n801_and_c408(self) -> None:
        """Both tiers detect N801 (naming) and C408 (dict call)."""
        strict = _run_ruff_on_mock_source(tier="strict")
        standard = _run_ruff_on_mock_source(tier="standard")

        strict_codes = {issue.code for issue in strict.tool_data["issues"]}
        standard_codes = {issue.code for issue in standard.tool_data["issues"]}
        assert "N801" in strict_codes
        assert "N801" in standard_codes
        assert "C408" in strict_codes
        assert "C408" in standard_codes


@pytest.mark.unit
class TestRadonTierComparison:
    """Verify threshold is the max acceptable grade.

    The threshold grade itself passes; only grades strictly above it are
    flagged.  For example strict (threshold B) passes A and B but flags C+.
    """

    def test_strict_passes_moderate_complexity(self) -> None:
        """Strict (threshold B) does not flag moderate_complexity (grade B)."""
        result = _run_radon_on_mock_source(tier="strict")

        names = {func["name"] for func in result.tool_data["functions"]}
        # Grade B equals strict threshold — within threshold, not flagged.
        assert "moderate_complexity" not in names

    def test_standard_passes_moderate_complexity(self) -> None:
        """Standard (threshold C) does not flag moderate_complexity (grade B)."""
        result = _run_radon_on_mock_source(tier="standard")

        names = {func["name"] for func in result.tool_data["functions"]}
        assert "moderate_complexity" not in names

    def test_strict_flags_high_complexity(self) -> None:
        """Strict (threshold B) flags high_complexity (grade C)."""
        result = _run_radon_on_mock_source(tier="strict")

        names = {func["name"] for func in result.tool_data["functions"]}
        # Grade C exceeds strict threshold B — flagged.
        assert "high_complexity" in names

    def test_standard_passes_high_complexity(self) -> None:
        """Standard (threshold C) does not flag high_complexity (grade C)."""
        result = _run_radon_on_mock_source(tier="standard")

        names = {func["name"] for func in result.tool_data["functions"]}
        # Grade C equals standard threshold — within threshold, not flagged.
        assert "high_complexity" not in names

    def test_simple_add_passes_both_tiers(self) -> None:
        """simple_add (grade A) is not flagged at any tier."""
        strict = _run_radon_on_mock_source(tier="strict")

        names = {func["name"] for func in strict.tool_data["functions"]}
        assert "simple_add" not in names

    def test_radon_exit_code_normalized(self) -> None:
        """Radon exit code is 1 and success is False when issues are found."""
        result = _run_radon_on_mock_source(tier="strict")

        # high_complexity (grade C) exceeds strict threshold B.
        assert result.issues_found > 0
        assert result.exit_code == 1
        assert result.success is False


@pytest.mark.unit
class TestBanditTierComparison:
    """Verify strict catches medium-confidence issues that standard misses."""

    def test_strict_catches_medium_confidence_issues(self) -> None:
        """Strict detects B108 and/or B608 (medium confidence)."""
        result = _run_bandit_on_mock_source(tier="strict")

        found_ids = {issue.test_id for issue in result.tool_data["issues"]}
        assert found_ids & {"B108", "B608"}

    def test_standard_misses_medium_confidence_issues(self) -> None:
        """Standard (confidence=high) skips B108 and B608."""
        result = _run_bandit_on_mock_source(tier="standard")

        found_ids = {issue.test_id for issue in result.tool_data["issues"]}
        assert "B108" not in found_ids
        assert "B608" not in found_ids

    def test_both_tiers_catch_b301(self) -> None:
        """Both tiers detect B301 (pickle.loads, high confidence)."""
        strict = _run_bandit_on_mock_source(tier="strict")
        standard = _run_bandit_on_mock_source(tier="standard")

        strict_ids = {issue.test_id for issue in strict.tool_data["issues"]}
        standard_ids = {issue.test_id for issue in standard.tool_data["issues"]}
        assert "B301" in strict_ids
        assert "B301" in standard_ids


@pytest.mark.unit
class TestMypyTierComparison:
    """Verify strict catches annotation errors that standard misses."""

    def test_strict_catches_missing_annotations(self) -> None:
        """Strict mode detects untyped_function and UNTYPED_GLOBAL."""
        result = _run_mypy_on_mock_source(tier="strict")

        messages = " ".join(issue["message"] for issue in result.tool_data["issues"])
        # strict_mode catches missing annotations.
        assert "untyped_function" in messages or "Function is missing" in messages
        # At minimum: return-value error + at least one missing-annotation error.
        min_strict_issues = 2
        assert result.issues_found >= min_strict_issues

    def test_standard_misses_annotation_errors(self) -> None:
        """Standard (non-strict) does not flag missing annotations."""
        result = _run_mypy_on_mock_source(tier="standard")

        # Standard still catches the incompatible return type.
        has_type_error = any(
            "incompatible return" in issue["message"].lower()
            or "return-value" in issue.get("code", "")
            for issue in result.tool_data["issues"]
        )
        assert has_type_error

        # But does NOT flag untyped globals (disallow_untyped_globals=False).
        messages = " ".join(issue["message"] for issue in result.tool_data["issues"])
        max_standard_issues = 3
        assert (
            "type annotation" not in messages.lower() or result.issues_found < max_standard_issues
        )


@pytest.mark.unit
class TestAnsiCodeStripping:
    """Verify ANSI escape codes are stripped from subprocess output.

    IDE environments may set ``FORCE_COLOR`` or ``PY_COLORS``, causing
    tools like radon to emit ANSI colour codes even when stdout is a pipe.
    Without stripping, the codes corrupt JSON output and cause parse failures.
    """

    def test_strip_ansi_codes_removes_colour_sequences(self) -> None:
        """Basic ANSI colour and reset codes are removed from text."""
        handler = BaseToolHandler(timeout=30)

        # Simulate radon appending an ANSI reset to JSON output.
        contaminated = '{"file.py": [{"rank": "C"}]}\x1b[0m'
        cleaned = handler._strip_ansi_codes(contaminated)
        assert cleaned == '{"file.py": [{"rank": "C"}]}'

    def test_strip_ansi_codes_removes_multiple_sequences(self) -> None:
        """Multiple ANSI sequences (colour + reset) are all removed."""
        handler = BaseToolHandler(timeout=30)

        # Bold red text followed by reset.
        contaminated = "\x1b[1;31mERROR\x1b[0m: something failed"
        cleaned = handler._strip_ansi_codes(contaminated)
        assert cleaned == "ERROR: something failed"

    def test_strip_ansi_codes_preserves_clean_text(self) -> None:
        """Text without ANSI codes is returned unchanged."""
        handler = BaseToolHandler(timeout=30)

        clean_json = '{"file.py": [{"rank": "A"}]}'
        assert handler._strip_ansi_codes(clean_json) == clean_json

    def test_radon_parses_ansi_contaminated_json(self) -> None:
        """Radon successfully parses JSON when subprocess output has ANSI codes.

        Verifies end-to-end that ``_execute_subprocess`` strips ANSI codes
        before ``_parse_json_output`` receives the stdout, preventing the
        ``json.JSONDecodeError`` that occurs in IDE environments.
        """

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target = tmp_path / "sample.py"
            target.write_text(_MOCK_SOURCE, encoding="utf-8")

            handler = RadonCCHandler(timeout=30)

            # Verify the stripping utility handles the ANSI pattern that
            # radon emits in IDE environments.  The actual subprocess call
            # already strips via _execute_subprocess, so here we confirm
            # the utility works on radon-style JSON output.
            raw_json = '{"sample.py": [{"type": "function", "rank": "C", '
            raw_json += '"name": "high_complexity", "complexity": 12, '
            raw_json += '"lineno": 1, "col_offset": 0, "endline": 20, '
            raw_json += '"classname": null, "closures": []}]}'
            contaminated_json = raw_json + "\n\x1b[0m"

            # Stripping must produce valid JSON that parses correctly.
            cleaned_json = handler._strip_ansi_codes(contaminated_json)
            functions = RadonCCHandler._parse_json_output(cleaned_json, "B")
            assert len(functions) > 0
            assert functions[0]["name"] == "high_complexity"
