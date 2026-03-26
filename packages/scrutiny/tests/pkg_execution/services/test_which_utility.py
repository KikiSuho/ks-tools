"""Tests for the ``which()`` path-lookup utility."""

from __future__ import annotations

from pathlib import Path

import pytest

from scrutiny.execution.services import which


# ── which() ── #


@pytest.mark.unit
class TestWhichUtility:
    """Test executable discovery via ``which()``."""

    def test_finds_python(self) -> None:
        """Return a non-None path for the ``python`` executable."""
        # Arrange
        command = "python"

        # Act
        result = which(command)

        # Assert
        assert result is not None

    def test_python_path_exists(self) -> None:
        """Return a path that exists on disk for ``python``."""
        # Arrange
        command = "python"

        # Act
        result = which(command)

        # Assert
        assert result is not None
        assert Path(result).exists()

    def test_returns_none_for_nonexistent(self) -> None:
        """Return ``None`` when the command does not exist."""
        # Arrange
        command = "nonexistent_tool_xyz_12345"

        # Act
        result = which(command)

        # Assert
        assert result is None

    def test_returns_string_type(self) -> None:
        """Return a ``str`` when the command is found."""
        # Arrange
        command = "python"

        # Act
        result = which(command)

        # Assert
        assert isinstance(result, str)

    def test_finds_ruff(self) -> None:
        """Return a non-None path for the ``ruff`` linter."""
        # Arrange
        command = "ruff"

        # Act
        result = which(command)

        # Assert
        assert result is not None
