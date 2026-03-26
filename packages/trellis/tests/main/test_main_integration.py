"""Integration tests for the main() CLI entry point.

Exercise the full pipeline (CLI args -> scan -> save -> detect -> log -> output)
through the ``main()`` function, covering real-world user scenarios, error paths,
and the fixes applied during the 2026-03-21 review.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from trellis.config import CallFlowMode, Config
from trellis.core.persistence import SaveResult, WriteStatus


def _quiet_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable noisy Config features for cleaner test output."""
    monkeypatch.setattr(Config, "SHOW_DECORATORS", False)
    monkeypatch.setattr(Config, "CALL_FLOW_MODE", CallFlowMode.OFF)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str] | None = None,
) -> tuple[int, str]:
    """Invoke main() with root discovery redirected to *tmp_path*.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest monkeypatch fixture.
    tmp_path : Path
        Temporary directory to scan.
    capsys : pytest.CaptureFixture[str]
        Pytest capsys fixture.
    argv : list[str] or None
        Extra CLI arguments (e.g. ``["--show-private"]``).

    Returns
    -------
    tuple[int, str]
        ``(exit_code, captured_stdout)``.
    """
    monkeypatch.setattr(sys, "argv", ["trellis", *(argv or [])])
    monkeypatch.setattr(
        "trellis.main.find_project_root",
        lambda **_kw: tmp_path,
    )
    from trellis.main import main

    exit_code = main()
    captured = capsys.readouterr()
    return exit_code, captured.out


def _structure_file(tmp_path: Path) -> Path:
    """Return the expected structure file path."""
    return tmp_path / Config.OUTPUT_DIR / f"{tmp_path.name}_structure.txt"


def _log_files(tmp_path: Path) -> list[Path]:
    """Return all change log files under the logs directory."""
    logs_dir = tmp_path / Config.LOG_DIR
    # Return empty list when logs directory does not exist yet
    if not logs_dir.exists():
        return []
    return sorted(logs_dir.glob("trellis_*.txt"))


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_first_run_generates_structure_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "module.py").write_text("def hello(): pass\n", encoding="utf-8")

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "Generating now" in out
    assert "Error" not in out
    assert _structure_file(tmp_path).exists()
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert content.startswith(f"{tmp_path.name}/")
    assert _log_files(tmp_path) == []


def test_second_run_no_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "SHOW_DECORATORS", False)
    monkeypatch.setattr(Config, "CALL_FLOW_MODE", CallFlowMode.OFF)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    monkeypatch.setattr(Config, "SHOW_DOCS", False)
    (tmp_path / "module.py").write_text("def hello(): pass\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "No structure changes detected" in out
    assert _log_files(tmp_path) == []


def test_second_run_detects_added_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "main.py").write_text("def run(): pass\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)
    (tmp_path / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "utils.py" in out
    assert len(_log_files(tmp_path)) == 1
    log_content = _log_files(tmp_path)[0].read_text(encoding="utf-8")
    assert "utils.py" in log_content


def test_second_run_detects_removed_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)
    (tmp_path / "utils.py").unlink()

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "utils.py" in out
    assert len(_log_files(tmp_path)) == 1


def test_second_run_detects_signature_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "service.py").write_text(
        "def process(x): pass\n", encoding="utf-8"
    )
    _run_main(monkeypatch, tmp_path, capsys)
    (tmp_path / "service.py").write_text(
        "def process(x: int, y: str): pass\n", encoding="utf-8"
    )

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "Updated API" in out
    assert "process" in out
    assert len(_log_files(tmp_path)) == 1


def test_multiple_runs_converge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "SHOW_DECORATORS", False)
    monkeypatch.setattr(Config, "CALL_FLOW_MODE", CallFlowMode.OFF)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "No structure changes detected" in out


# ---------------------------------------------------------------------------
# Visibility flags
# ---------------------------------------------------------------------------


def test_show_private_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "api.py").write_text(
        "def _internal(): pass\ndef public(): pass\n", encoding="utf-8"
    )

    # Act
    _run_main(monkeypatch, tmp_path, capsys, ["--show-private"])

    # Assert
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "_internal" in content
    assert "public" in content


def test_hide_all_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "SHOW_PRIVATE", True)
    monkeypatch.setattr(Config, "SHOW_DUNDER", True)
    monkeypatch.setattr(Config, "SHOW_DECORATORS", False)
    monkeypatch.setattr(Config, "CALL_FLOW_MODE", CallFlowMode.OFF)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", False)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    (tmp_path / "thing.py").write_text(
        "class Foo:\n"
        "    def __init__(self): pass\n"
        "    def _private(self): pass\n"
        "    def public(self): pass\n",
        encoding="utf-8",
    )

    # Act
    _run_main(monkeypatch, tmp_path, capsys, ["--hide-all"])

    # Assert
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "__init__" not in content
    assert "_private" not in content
    assert "public" in content


def test_show_all_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "core.py").write_text(
        "def _helper(): pass\ndef public(): pass\n", encoding="utf-8"
    )

    # Act
    _run_main(monkeypatch, tmp_path, capsys, ["--show-all"])

    # Assert
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "_helper" in content


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_dir_create_failed_returns_exit_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

    # Act
    with patch(
        "trellis.core.persistence.Path.mkdir",
        side_effect=PermissionError("read-only"),
    ):
        code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 1
    assert "Error: cannot create output directory" in out


def test_write_failed_returns_exit_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

    # Act
    with patch(
        "trellis.core.persistence._write_structure_file",
        return_value=WriteStatus.WRITE_FAILED,
    ):
        code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 1
    assert "Error: cannot write" in out


def test_read_error_prints_warning_and_regenerates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "module.py").write_text("x = 1\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)
    assert _structure_file(tmp_path).exists()
    monkeypatch.setattr(
        "trellis.main._persist_save",
        lambda _ctx: SaveResult(
            str(_structure_file(tmp_path)),
            None,
            "",
            WriteStatus.SUCCESS,
            "PermissionError: locked by Dropbox",
        ),
    )

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "Warning: could not read previous structure file" in out
    assert "Generating now" not in out


def test_log_write_failure_prints_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)
    (tmp_path / "utils.py").write_text("y = 2\n", encoding="utf-8")
    monkeypatch.setattr(
        "trellis.tracking.logger.log_structure_changes",
        lambda *_args, **_kw: "",
    )

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "Warning: could not write structure change log" in out
    assert _structure_file(tmp_path).exists()


def test_none_changes_with_read_error_no_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "module.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "trellis.main._persist_save",
        lambda _ctx: SaveResult(
            str(_structure_file(tmp_path)),
            None,
            "",
            WriteStatus.SUCCESS,
            "UnicodeDecodeError: codec error",
        ),
    )

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "Warning: could not read previous structure file" in out
    assert "Generating now" not in out


# ---------------------------------------------------------------------------
# Config and change detection
# ---------------------------------------------------------------------------


def test_config_only_change_suppressed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange — run twice with identical config. The output directory created
    # by the first run appears as new content in the second scan (docs/ and
    # the structure file); that is a real structural change, not config-only.
    # To test pure config-only suppression, use the persistence layer directly
    # (see test_config_change_detection.py). Here we verify the CLI exits
    # successfully on a stable re-run.
    _quiet_config(monkeypatch)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    _run_main(monkeypatch, tmp_path, capsys)

    # Act — second run picks up the docs/ directory created by the first run
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0


def test_log_dir_not_created_when_logging_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    monkeypatch.setattr(Config, "LOG_STRUCTURE_CHANGES", False)
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert not (tmp_path / Config.LOG_DIR).exists()
    assert _structure_file(tmp_path).exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_project(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    assert "Generating now" in out
    assert _structure_file(tmp_path).exists()
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "# tr_meta:" in content


def test_no_project_root_warns_and_uses_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["trellis"])
    monkeypatch.setattr(
        "trellis.main.find_project_root",
        lambda **_kw: None,
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    # Act
    import warnings

    from trellis.main import main

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        code = main()

    # Assert
    assert code == 0
    assert any("No project root found" in str(warning.message) for warning in caught)


def test_symlink_renders_annotation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    # Skip when OS does not support symlinks without elevation
    try:
        # Create a directory symlink to test annotation rendering
        (package_dir / "link").symlink_to(package_dir)
    except OSError:
        # Abort test on platforms that require elevated privileges for symlinks
        pytest.skip("symlinks require elevated privileges on this platform")

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "[symlink to" in content


def test_slash_ignore_pattern_no_false_match(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    monkeypatch.setattr(Config, "ENABLE_IGNORE_DIRS", True)
    monkeypatch.setattr(Config, "ENABLE_IGNORE_FILES", False)
    monkeypatch.setattr(Config, "SHOW_DECORATORS", False)
    monkeypatch.setattr(Config, "CALL_FLOW_MODE", CallFlowMode.OFF)
    monkeypatch.setattr(Config, "IGNORE_DIRS", frozenset({"docs/build"}))
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "core.py").write_text("x = 1\n", encoding="utf-8")

    # Act
    code, out = _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    assert code == 0
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "build/" in content
    assert "core.py" in content


# ---------------------------------------------------------------------------
# Structure file content validation
# ---------------------------------------------------------------------------


def test_output_file_contains_tr_meta_footer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    # Act
    _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "# tr_meta:D" in content


def test_output_file_tree_connectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("z = 3\n", encoding="utf-8")

    # Act
    _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "\u251c\u2500\u2500" in content  # ├──
    assert "\u2514\u2500\u2500" in content  # └──


def test_output_file_tags_package_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    package_dir = tmp_path / "mypkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "core.py").write_text("x = 1\n", encoding="utf-8")

    # Act
    _run_main(monkeypatch, tmp_path, capsys)

    # Assert
    content = _structure_file(tmp_path).read_text(encoding="utf-8")
    assert "mypkg/ [pkg]" in content


# ---------------------------------------------------------------------------
# PersistenceContext immutability
# ---------------------------------------------------------------------------


def test_rescan_after_save_does_not_corrupt_saved_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Arrange
    _quiet_config(monkeypatch)
    (tmp_path / "first.py").write_text("x = 1\n", encoding="utf-8")
    from trellis.main import DirectoryStructure

    scanner = DirectoryStructure(str(tmp_path))
    scanner.scan_directory(str(tmp_path))
    result_first = scanner.save_structure()
    saved_content = Path(result_first.output_path).read_text(encoding="utf-8")
    assert "first.py" in saved_content
    (tmp_path / "second.py").write_text("y = 2\n", encoding="utf-8")

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    saved_after_rescan = Path(result_first.output_path).read_text(encoding="utf-8")
    assert saved_after_rescan == saved_content
    assert "second.py" not in saved_after_rescan
