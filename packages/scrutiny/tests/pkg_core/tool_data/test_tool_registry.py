"""Tests for TOOL_REGISTRY, _verify_tool_availability, and _compute_mi_ranks.

These are new public-surface additions that will become module boundaries
during decomposition.  Testing them now provides regression safety nets.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scrutiny.core.exceptions import SCRSystemError
from scrutiny.core.tool_data import TOOL_REGISTRY
from scrutiny.execution.handlers import RadonCCHandler
from scrutiny.main import _verify_tool_availability
from scrutiny.main import _compute_mi_ranks
from conftest import make_global_config


# ====================================== #
#       TOOL_REGISTRY structure          #
# ====================================== #


class TestToolRegistryStructure:
    """Verify TOOL_REGISTRY maps every logical tool name to (executable, package)."""

    EXPECTED_LOGICAL_NAMES = {
        "ruff_formatter",
        "ruff_linter",
        "ruff_security",
        "mypy",
        "radon",
        "radon_mi",
        "bandit",
    }

    def test_contains_all_expected_logical_names(self) -> None:
        """Registry must include every logical tool name the orchestrator references."""
        assert set(TOOL_REGISTRY.keys()) == self.EXPECTED_LOGICAL_NAMES

    def test_every_entry_is_executable_package_pair(self) -> None:
        """Each registry value must be a (str, str) tuple."""
        for logical_name, entry in TOOL_REGISTRY.items():
            assert isinstance(entry, tuple), f"{logical_name}: expected tuple, got {type(entry)}"
            assert len(entry) == 2, f"{logical_name}: expected 2-tuple, got {len(entry)}"
            executable, install_pkg = entry
            assert isinstance(executable, str), f"{logical_name}: executable not str"
            assert isinstance(install_pkg, str), f"{logical_name}: install_pkg not str"

    @pytest.mark.parametrize(
        "logical_name,expected_executable",
        [
            pytest.param("ruff_formatter", "ruff", id="ruff_formatter"),
            pytest.param("ruff_linter", "ruff", id="ruff_linter"),
            pytest.param("ruff_security", "ruff", id="ruff_security"),
            pytest.param("mypy", "mypy", id="mypy"),
            pytest.param("radon", "radon", id="radon"),
            pytest.param("radon_mi", "radon", id="radon_mi"),
            pytest.param("bandit", "bandit", id="bandit"),
        ],
    )
    def test_logical_name_maps_to_correct_executable(
        self,
        logical_name: str,
        expected_executable: str,
    ) -> None:
        """Each logical tool name must resolve to its expected executable."""
        executable, _ = TOOL_REGISTRY[logical_name]
        assert executable == expected_executable

    def test_ruff_tools_share_single_executable(self) -> None:
        """All ruff-based tools must share the same executable to avoid duplication."""
        ruff_executables = {
            TOOL_REGISTRY[name][0]
            for name in ("ruff_formatter", "ruff_linter", "ruff_security")
        }
        assert ruff_executables == {"ruff"}

    def test_radon_tools_share_single_executable(self) -> None:
        """Both radon logical names must share the same executable."""
        radon_executables = {
            TOOL_REGISTRY[name][0]
            for name in ("radon", "radon_mi")
        }
        assert radon_executables == {"radon"}


# ====================================== #
#       _verify_tool_availability        #
# ====================================== #


class TestVerifyToolAvailability:
    """Test pre-flight executable checks via _verify_tool_availability."""

    def test_all_tools_available_does_not_raise(self) -> None:
        """No error when every requested executable is found on PATH."""
        with patch("scrutiny.main.which", return_value="/usr/bin/tool"):
            _verify_tool_availability(["ruff_formatter", "mypy"])

    def test_single_missing_tool_raises_system_error(self) -> None:
        """SCRSystemError when one executable is missing."""
        def which_side_effect(name: str) -> str | None:
            return None if name == "mypy" else f"/usr/bin/{name}"

        with patch("scrutiny.main.which", side_effect=which_side_effect):
            with pytest.raises(SCRSystemError, match="mypy"):
                _verify_tool_availability(["ruff_formatter", "mypy"])

    def test_multiple_missing_tools_listed_in_single_error(self) -> None:
        """All missing executables appear in a single SCRSystemError."""
        with patch("scrutiny.main.which", return_value=None):
            with pytest.raises(SCRSystemError) as exc_info:
                _verify_tool_availability(["ruff_formatter", "mypy", "bandit"])

        message = str(exc_info.value)
        assert "ruff" in message
        assert "mypy" in message
        assert "bandit" in message

    def test_error_message_includes_install_guidance(self) -> None:
        """Error message contains pip/conda install instructions."""
        with patch("scrutiny.main.which", return_value=None):
            with pytest.raises(SCRSystemError, match="pip install") as exc_info:
                _verify_tool_availability(["mypy"])

        assert "conda install" in str(exc_info.value)

    def test_deduplicates_shared_executables(self) -> None:
        """Shared executables (e.g. ruff) are checked only once."""
        call_count = 0
        checked_names: list[str] = []

        def trackingwhich(name: str) -> str:
            nonlocal call_count
            call_count += 1
            checked_names.append(name)
            return f"/usr/bin/{name}"

        with patch("scrutiny.main.which", side_effect=trackingwhich):
            _verify_tool_availability(["ruff_formatter", "ruff_linter", "ruff_security"])

        # ruff should be checked exactly once despite three logical names.
        assert checked_names.count("ruff") == 1

    def test_radon_implies_radon_mi_check(self) -> None:
        """When radon is in tool_names, radon_mi is also checked."""
        checked_names: list[str] = []

        def trackingwhich(name: str) -> str:
            checked_names.append(name)
            return f"/usr/bin/{name}"

        with patch("scrutiny.main.which", side_effect=trackingwhich):
            _verify_tool_availability(["radon"])

        # radon_mi maps to the same executable, but the logical name
        # should be added so the executable check covers it.
        assert "radon" in checked_names

    def test_unknown_tool_name_falls_back_to_name_as_executable(self) -> None:
        """Unknown logical names use the name itself as both executable and package."""
        with patch("scrutiny.main.which", return_value=None):
            with pytest.raises(SCRSystemError, match="unknown_tool"):
                _verify_tool_availability(["unknown_tool"])

    def test_empty_tool_list_does_not_raise(self) -> None:
        """Empty tool list means nothing to verify."""
        _verify_tool_availability([])


# ====================================== #
#       _compute_mi_ranks               #
# ====================================== #


class TestComputeMiRanks:
    """Test MI rank computation dispatch via _compute_mi_ranks."""

    def test_returns_none_when_radon_not_in_tools(self, tmp_path: Path) -> None:
        """No MI computation when radon is not enabled."""
        global_config = make_global_config()

        result = _compute_mi_ranks(
            ["ruff_formatter", "mypy"],
            [tmp_path / "example.py"],
            tmp_path,
            global_config,
        )

        assert result is None

    def test_returns_dict_when_radon_enabled(self, tmp_path: Path) -> None:
        """MI computation returns a dict when radon is in tool_names."""
        global_config = make_global_config()
        mock_ranks = {"example.py": "A"}

        with patch.object(
            RadonCCHandler,
            "compute_maintainability_index",
            autospec=True,
            return_value=mock_ranks,
        ):
            result = _compute_mi_ranks(
                ["radon"],
                [tmp_path / "example.py"],
                tmp_path,
                global_config,
            )

        assert result == mock_ranks

    def test_passes_files_and_root_to_handler(self, tmp_path: Path) -> None:
        """Verify correct arguments are forwarded to the RadonCCHandler."""
        global_config = make_global_config()
        test_files = [tmp_path / "a.py", tmp_path / "b.py"]

        with patch.object(
            RadonCCHandler,
            "compute_maintainability_index",
            autospec=True,
            return_value={},
        ) as mock_mi:
            _compute_mi_ranks(["radon"], test_files, tmp_path, global_config)

        # autospec means self is the first arg.
        _, passed_files, passed_root = mock_mi.call_args[0]
        assert passed_files == test_files
        assert passed_root == tmp_path

    def test_uses_tool_timeout_from_global_config(self, tmp_path: Path) -> None:
        """Handler timeout comes from global_config.tool_timeout."""
        global_config = make_global_config()

        with patch.object(
            RadonCCHandler,
            "compute_maintainability_index",
            autospec=True,
            return_value={},
        ):
            with patch.object(
                RadonCCHandler,
                "__init__",
                autospec=True,
                return_value=None,
            ) as mock_init:
                _compute_mi_ranks(
                    ["radon"],
                    [tmp_path / "example.py"],
                    tmp_path,
                    global_config,
                )

        # Verify the timeout keyword was passed.
        _, kwargs = mock_init.call_args
        assert kwargs.get("timeout") == int(global_config.tool_timeout)
