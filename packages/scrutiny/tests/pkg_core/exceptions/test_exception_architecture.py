"""Tests for exception architecture hardening.

Verify that file I/O in PyProjectGenerator wraps OSError as
SCRConfigurationError, and that _run_config_generation,
_build_preliminary_config, and _build_resolved_config are
decorated with @handle_errors.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scrutiny.config import UserDefaults
from scrutiny.configs.dataclasses import GlobalConfig
from scrutiny.configs.pyproject import PyProjectGenerator
from scrutiny.configs.resolver import ConfigResolver, ContextDetection
from scrutiny.core.enums import ConfigTier
from scrutiny.core.exceptions import (
    SCRConfigurationError,
    SCRError,
    SCRSystemError,
    SCRUnexpectedError,
    ExitCode,
    format_scr_error,
)
from scrutiny.execution.services import ProjectRootService
from scrutiny.main import (
    _build_preliminary_config,
    _build_resolved_config,
    _run_config_generation,
)


def _gen_config(**overrides: object) -> object:
    """Build a GlobalConfig for generation testing."""
    return GlobalConfig(**overrides)


# ── generate_or_merge: OSError wrapping ── #


@pytest.mark.unit
class TestGenerateOrMergeOSErrorWrapping:
    """Verify generate_or_merge wraps OSError as SCRConfigurationError."""

    def test_write_oserror_raises_configuration_error(
        self,
        tmp_path: Path,
    ) -> None:
        """OSError on initial write_text raises SCRConfigurationError."""
        config = _gen_config()
        # Make the target directory read-only by patching write_text.
        with (
            patch.object(
                Path,
                "write_text",
                side_effect=OSError("Permission denied"),
            ),
            pytest.raises(SCRConfigurationError, match="generation failed"),
        ):
            PyProjectGenerator.generate_or_merge(tmp_path, config)

    def test_read_oserror_raises_configuration_error(
        self,
        tmp_path: Path,
    ) -> None:
        """OSError on read_text of existing file raises SCRConfigurationError."""
        config = _gen_config()
        # Create an existing file so the read branch is triggered.
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\n", encoding="utf-8")

        with (
            patch.object(
                Path,
                "read_text",
                side_effect=OSError("I/O error"),
            ),
            pytest.raises(SCRConfigurationError, match="generation failed"),
        ):
            PyProjectGenerator.generate_or_merge(tmp_path, config)

    def test_configuration_error_passes_through(
        self,
        tmp_path: Path,
    ) -> None:
        """Existing SCRConfigurationError is not double-wrapped."""
        config = _gen_config()
        inner_error = SCRConfigurationError("inner TOML error")

        with (
            patch.object(
                Path,
                "write_text",
                side_effect=inner_error,
            ),
            pytest.raises(SCRConfigurationError, match="inner TOML error"),
        ):
            PyProjectGenerator.generate_or_merge(tmp_path, config)

    def test_oserror_preserves_original_cause(
        self,
        tmp_path: Path,
    ) -> None:
        """Wrapped SCRConfigurationError chains the original OSError."""
        config = _gen_config()
        original = PermissionError("read-only filesystem")

        with patch.object(Path, "write_text", side_effect=original):
            with pytest.raises(SCRConfigurationError) as exc_info:
                PyProjectGenerator.generate_or_merge(tmp_path, config)

        assert exc_info.value.__cause__ is original

    def test_oserror_message_includes_path(
        self,
        tmp_path: Path,
    ) -> None:
        """Wrapped error message includes the pyproject.toml path."""
        config = _gen_config()

        with (
            patch.object(
                Path,
                "write_text",
                side_effect=OSError("disk full"),
            ),
            pytest.raises(SCRConfigurationError) as exc_info,
        ):
            PyProjectGenerator.generate_or_merge(tmp_path, config)

        assert "pyproject.toml" in str(exc_info.value)


# ── @handle_errors decorator presence ── #


@pytest.mark.unit
class TestHandleErrorsDecoratorPresence:
    """Verify @handle_errors decorates key orchestration functions."""

    def test_run_config_generation_wraps_unexpected_errors(self) -> None:
        """_run_config_generation wraps non-SCR exceptions as SCRUnexpectedError."""
        with patch.object(
            ProjectRootService,
            "get_project_root",
            side_effect=RuntimeError("unexpected"),
        ):
            config = _gen_config(generate_config=True)
            with pytest.raises(SCRUnexpectedError) as exc_info:
                _run_config_generation(Path("/nonexistent"), config)

        assert exc_info.value.operation == "_run_config_generation"

    def test_run_config_generation_passes_cq_errors(self) -> None:
        """_run_config_generation passes SCRError subclasses through."""
        with patch.object(
            ProjectRootService,
            "get_project_root",
            side_effect=SCRConfigurationError("config issue"),
        ):
            config = _gen_config(generate_config=True)
            with pytest.raises(SCRConfigurationError, match="config issue"):
                _run_config_generation(Path("/nonexistent"), config)

    def test_run_config_generation_returns_none_when_disabled(self) -> None:
        """_run_config_generation returns None when generate_config is False."""
        config = _gen_config(generate_config=False)

        result = _run_config_generation(Path("/nonexistent"), config)

        assert result is None

    def test_build_preliminary_config_wraps_unexpected_errors(self) -> None:
        """_build_preliminary_config wraps non-SCR exceptions as SCRUnexpectedError."""
        snapshot = UserDefaults.to_frozen()

        with (
            patch.object(
                ConfigResolver,
                "build_global_config",
                side_effect=RuntimeError("resolver crash"),
            ),
            pytest.raises(SCRUnexpectedError) as exc_info,
        ):
            _build_preliminary_config(
                Path("/nonexistent"),
                {},
                snapshot,
                ConfigTier.STANDARD,
            )

        assert exc_info.value.operation == "_build_preliminary_config"

    def test_build_preliminary_config_passes_cq_errors(self) -> None:
        """_build_preliminary_config passes SCRError subclasses through."""
        snapshot = UserDefaults.to_frozen()

        with (
            patch.object(
                ConfigResolver,
                "build_global_config",
                side_effect=SCRConfigurationError("bad config"),
            ),
            pytest.raises(SCRConfigurationError, match="bad config"),
        ):
            _build_preliminary_config(
                Path("/nonexistent"),
                {},
                snapshot,
                ConfigTier.STANDARD,
            )

    def test_build_resolved_config_wraps_unexpected_errors(self) -> None:
        """_build_resolved_config wraps non-SCR exceptions as SCRUnexpectedError."""
        snapshot = UserDefaults.to_frozen()

        with (
            patch.object(
                ContextDetection,
                "detect",
                side_effect=RuntimeError("detection crash"),
            ),
            pytest.raises(SCRUnexpectedError) as exc_info,
        ):
            _build_resolved_config(
                Path("/nonexistent"),
                {},
                snapshot,
                ConfigTier.STANDARD,
            )

        assert exc_info.value.operation == "_build_resolved_config"

    def test_build_resolved_config_passes_cq_errors(self) -> None:
        """_build_resolved_config passes SCRError subclasses through."""
        snapshot = UserDefaults.to_frozen()

        with (
            patch.object(
                ContextDetection,
                "detect",
                side_effect=SCRConfigurationError("context fail"),
            ),
            pytest.raises(SCRConfigurationError, match="context fail"),
        ):
            _build_resolved_config(
                Path("/nonexistent"),
                {},
                snapshot,
                ConfigTier.STANDARD,
            )


# ── format_scr_error helper ── #


def test_format_scr_error_produces_canonical_string() -> None:
    """format_scr_error includes tag, message, code, and symbolic name."""
    error = SCRSystemError("tools missing")
    result = format_scr_error(error)
    assert "[SYSTEM]" in result
    assert "tools missing" in result
    assert str(ExitCode.SYSTEM) in result
    assert "SYSTEM" in result
