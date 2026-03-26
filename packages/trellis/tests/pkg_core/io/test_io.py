"""Tests for trellis.core.io module.

Covers atomic_write_text happy path, temp write failure fallback,
replace retry logic, total failure, and temp file cleanup.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from trellis.core.io import atomic_write_text


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_atomic_write_creates_file_with_correct_content(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")
    content = "hello world\n"

    # Act
    result = atomic_write_text(output, content)

    # Assert
    assert result is True
    assert Path(output).read_text(encoding="utf-8") == content


def test_atomic_write_overwrites_existing_file(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")
    Path(output).write_text("old content", encoding="utf-8")
    new_content = "new content\n"

    # Act
    result = atomic_write_text(output, new_content)

    # Assert
    assert result is True
    assert Path(output).read_text(encoding="utf-8") == new_content


def test_atomic_write_cleans_up_tmp_file(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")

    # Act
    atomic_write_text(output, "content")

    # Assert
    assert not Path(output + ".tmp").exists()


# ---------------------------------------------------------------------------
# Temp write failure — falls back to direct write
# ---------------------------------------------------------------------------


def test_temp_write_failure_falls_back_to_direct_write(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")
    real_open = Path.open

    def _fail_on_tmp(self, *args, **kwargs):
        """Raise OSError only for .tmp files."""
        if str(self).endswith(".tmp"):
            raise OSError("tmp locked")
        return real_open(self, *args, **kwargs)

    # Act
    with patch.object(Path, "open", _fail_on_tmp):
        result = atomic_write_text(output, "fallback content\n")

    # Assert
    assert result is True
    assert Path(output).read_text(encoding="utf-8") == "fallback content\n"


# ---------------------------------------------------------------------------
# Replace retry logic
# ---------------------------------------------------------------------------


def test_first_replace_fails_retry_succeeds(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")
    call_count = {"value": 0}
    real_replace = Path.replace

    def _fail_once(self, target):
        """Fail on first call, succeed on second."""
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise OSError("transient lock")
        return real_replace(self, target)

    # Act
    with patch.object(Path, "replace", _fail_once), patch("time.sleep"):
        result = atomic_write_text(output, "retry content\n")

    # Assert
    assert result is True
    assert Path(output).read_text(encoding="utf-8") == "retry content\n"


def test_both_replaces_fail_falls_back_to_direct_write(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")

    # Act
    with patch.object(Path, "replace", side_effect=OSError("locked")), patch("time.sleep"):
        result = atomic_write_text(output, "direct content\n")

    # Assert
    assert result is True
    assert Path(output).read_text(encoding="utf-8") == "direct content\n"


def test_both_replaces_fail_cleans_up_tmp(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "output.txt")

    # Act
    with patch.object(Path, "replace", side_effect=OSError("locked")), patch("time.sleep"):
        atomic_write_text(output, "content")

    # Assert
    assert not Path(output + ".tmp").exists()


# ---------------------------------------------------------------------------
# Total failure
# ---------------------------------------------------------------------------


def test_total_failure_returns_false(tmp_path: Path) -> None:
    # Arrange
    output = str(tmp_path / "nonexistent_dir" / "output.txt")

    # Act
    with patch.object(Path, "replace", side_effect=OSError("locked")), patch("time.sleep"):
        result = atomic_write_text(output, "content")

    # Assert
    assert result is False
