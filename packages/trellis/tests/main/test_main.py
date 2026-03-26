"""Tests for trellis.main module.

Covers DirectoryStructure class: initialization, directory scanning,
file/directory processing, structure output, and the save workflow.
"""

from __future__ import annotations

from pathlib import Path

from trellis.main import DirectoryStructure


# ---------------------------------------------------------------------------
# DirectoryStructure initialization
# ---------------------------------------------------------------------------


def test_init_sets_project_name(tmp_path: Path) -> None:
    # Arrange
    root_dir = str(tmp_path)

    # Act
    scanner = DirectoryStructure(root_dir)

    # Assert
    assert scanner.project_name == tmp_path.name


def test_init_default_visibility(tmp_path: Path) -> None:
    # Arrange
    root_dir = str(tmp_path)

    # Act
    scanner = DirectoryStructure(root_dir)

    # Assert
    assert scanner.show_private is False
    assert scanner.show_mangled is False
    assert scanner.show_dunder is False


def test_init_custom_visibility(tmp_path: Path) -> None:
    # Arrange
    root_dir = str(tmp_path)

    # Act
    scanner = DirectoryStructure(
        root_dir, show_private=True, show_mangled=True, show_dunder=True
    )

    # Assert
    assert scanner.show_private is True
    assert scanner.show_mangled is True
    assert scanner.show_dunder is True


def test_structure_starts_empty(tmp_path: Path) -> None:
    # Arrange
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    result = scanner.structure

    # Assert
    assert result == ""


# ---------------------------------------------------------------------------
# scan_directory
# ---------------------------------------------------------------------------


def test_scan_empty_directory(tmp_path: Path) -> None:
    # Arrange
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert scanner.structure == ""
    assert scanner.scan_method_used == "os.scandir()"


def test_scan_directory_finds_files(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "hello.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "data.txt").touch()
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert "hello.py" in scanner.structure


def test_scan_directory_finds_subdirectories(tmp_path: Path) -> None:
    # Arrange
    subdir = tmp_path / "subpkg"
    subdir.mkdir()
    (subdir / "__init__.py").write_text("", encoding="utf-8")
    (subdir / "module.py").write_text("def foo(): pass\n", encoding="utf-8")
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    output = scanner.structure
    assert "subpkg/" in output
    assert "[pkg]" in output


def test_scan_directory_marks_package(tmp_path: Path) -> None:
    # Arrange
    pkg_dir = tmp_path / "mypkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").touch()
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert "[pkg]" in scanner.structure


def test_scan_directory_marks_command(tmp_path: Path) -> None:
    # Arrange
    cmd_dir = tmp_path / "mycmd"
    cmd_dir.mkdir()
    (cmd_dir / "__main__.py").touch()
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert "[cmd]" in scanner.structure


def test_scan_directory_marks_typed(tmp_path: Path) -> None:
    # Arrange
    typed_dir = tmp_path / "mylib"
    typed_dir.mkdir()
    (typed_dir / "__init__.py").touch()
    (typed_dir / "py.typed").touch()
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert "[typed]" in scanner.structure


def test_scan_skips_system_files(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "__init__.py").touch()
    (tmp_path / "regular.py").write_text("x = 1\n", encoding="utf-8")
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    output = scanner.structure
    assert "__init__.py" not in output
    assert "regular.py" in output


def test_scan_extracts_python_structure(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "example.py").write_text(
        "class MyClass:\n    pass\n\ndef my_func():\n    pass\n",
        encoding="utf-8",
    )
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    output = scanner.structure
    assert "class MyClass" in output
    assert "def my_func" in output


def test_scan_directories_before_files(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "zzz_file.py").write_text("x = 1\n", encoding="utf-8")
    subdir = tmp_path / "aaa_dir"
    subdir.mkdir()
    (subdir / "mod.py").write_text("y = 2\n", encoding="utf-8")
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    output = scanner.structure
    dir_pos = output.find("aaa_dir/")
    file_pos = output.find("zzz_file.py")
    assert dir_pos < file_pos


def test_scan_python_file_shows_line_count(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "module.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")
    scanner = DirectoryStructure(str(tmp_path))

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert "module.py {3}" in scanner.structure


def test_scan_rescan_clears_previous_state(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "first.py").write_text("x = 1\n", encoding="utf-8")
    scanner = DirectoryStructure(str(tmp_path))
    scanner.scan_directory(str(tmp_path))
    assert "first.py" in scanner.structure
    (tmp_path / "first.py").unlink()
    (tmp_path / "second.py").write_text("y = 2\n", encoding="utf-8")

    # Act
    scanner.scan_directory(str(tmp_path))

    # Assert
    assert "first.py" not in scanner.structure
    assert "second.py" in scanner.structure


# ---------------------------------------------------------------------------
# _separate_dirs_and_files (static method)
# ---------------------------------------------------------------------------


def test_separate_dirs_and_files_partitions_correctly() -> None:
    # Arrange
    items = [("alpha.py", False), ("beta", True), ("gamma.txt", False), ("zebra", True)]

    # Act
    dirs, files = DirectoryStructure._separate_dirs_and_files(items)

    # Assert
    assert dirs == ["beta", "zebra"]
    assert files == ["alpha.py", "gamma.txt"]


def test_separate_dirs_and_files_handles_empty_list() -> None:
    # Arrange
    items: list[tuple[str, bool]] = []

    # Act
    dirs, files = DirectoryStructure._separate_dirs_and_files(items)

    # Assert
    assert dirs == []
    assert files == []


# ---------------------------------------------------------------------------
# save_structure
# ---------------------------------------------------------------------------


def test_save_structure_creates_file(tmp_path: Path) -> None:
    # Arrange
    scanner = DirectoryStructure(str(tmp_path))
    scanner.scan_directory(str(tmp_path))

    # Act
    result = scanner.save_structure()

    # Assert
    assert Path(result.output_path).exists()
    content = Path(result.output_path).read_text(encoding="utf-8")
    assert tmp_path.name in content


def test_save_structure_creates_output_dirs(tmp_path: Path) -> None:
    # Arrange
    scanner = DirectoryStructure(str(tmp_path))
    scanner.scan_directory(str(tmp_path))

    # Act
    scanner.save_structure()

    # Assert
    docs_dir = tmp_path / "docs"
    logs_dir = tmp_path / "logs" / "structure_changes"
    assert docs_dir.is_dir()
    assert logs_dir.is_dir()


def test_save_structure_includes_tr_meta(tmp_path: Path) -> None:
    # Arrange
    scanner = DirectoryStructure(str(tmp_path))
    scanner.scan_directory(str(tmp_path))

    # Act
    result = scanner.save_structure()

    # Assert
    content = Path(result.output_path).read_text(encoding="utf-8")
    assert "# tr_meta:" in content
