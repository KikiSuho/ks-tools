"""Tests for tr_meta round-trip fidelity (Category 2).

Verify that tr_meta survives the full write-read-parse cycle with all
flag combinations intact.
"""

from __future__ import annotations

import pytest

from trellis.config import Config, build_tr_meta
from trellis.tracking.detector import (
    append_tr_meta,
    parse_tr_meta_line,
    split_tree_and_meta,
)


@pytest.fixture(autouse=True)
def _restore_config():
    """Snapshot and restore all mutable Config attributes."""
    originals = {
        attr: getattr(Config, attr)
        for attr in dir(Config)
        if not attr.startswith("_") and attr.isupper()
    }
    yield
    for attr, value in originals.items():
        setattr(Config, attr, value)


def _set_flags_and_build(
    show_docs: bool,
    enable_ignore_dirs: bool,
    enable_ignore_files: bool,
    show_types: bool,
    show_decorators: bool,
) -> str:
    """Set Config flags for fields still read from Config, pass the rest as params."""
    Config.SHOW_DOCS = show_docs
    Config.ENABLE_IGNORE_DIRS = enable_ignore_dirs
    Config.ENABLE_IGNORE_FILES = enable_ignore_files
    return build_tr_meta(show_types=show_types, show_decorators=show_decorators)


def _roundtrip_meta(meta: str, project: str = "myproject") -> tuple[str, str]:
    """Append tr_meta to tree, split back, return (original, extracted)."""
    tree_content = f"{project}/\n└── main.py\n"
    combined = append_tr_meta(tree_content, meta)
    _, extracted_meta, status = split_tree_and_meta(combined, project)

    assert status == "valid"
    assert extracted_meta is not None
    return meta, extracted_meta


# ---------------------------------------------------------------------------
# Test 2.1
# ---------------------------------------------------------------------------


def test_tr_meta_roundtrip_all_flags_enabled() -> None:
    """All flags True survives the write-read-parse cycle."""
    meta = _set_flags_and_build(True, True, True, True, True)

    original, extracted = _roundtrip_meta(meta)

    assert original == "D1I1F1T1@1C0P1V0U0S0Wsmart"
    assert extracted == original


# ---------------------------------------------------------------------------
# Test 2.2
# ---------------------------------------------------------------------------


def test_tr_meta_roundtrip_all_flags_disabled() -> None:
    """All flags False produces D0I0F0T0@0C0 and survives round-trip."""
    meta = _set_flags_and_build(False, False, False, False, False)

    original, extracted = _roundtrip_meta(meta)

    assert original == "D0I0F0T0@0C0P1V0U0S0Wsmart"
    assert extracted == original


# ---------------------------------------------------------------------------
# Test 2.3
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags, expected_meta",
    [
        pytest.param(
            (True, False, False, False, False),
            "D1I0F0T0@0C0P1V0U0S0Wsmart",
            id="only-show-docs",
        ),
        pytest.param(
            (True, False, True, False, True),
            "D1I0F1T0@1C0P1V0U0S0Wsmart",
            id="alternating-10101",
        ),
        pytest.param(
            (False, True, False, True, False),
            "D0I1F0T1@0C0P1V0U0S0Wsmart",
            id="alternating-01010",
        ),
        pytest.param(
            (True, True, False, False, True),
            "D1I1F0T0@1C0P1V0U0S0Wsmart",
            id="mixed-11001",
        ),
        pytest.param(
            (False, False, True, True, False),
            "D0I0F1T1@0C0P1V0U0S0Wsmart",
            id="mixed-00110",
        ),
        pytest.param(
            (True, True, True, False, False),
            "D1I1F1T0@0C0P1V0U0S0Wsmart",
            id="first-three-on",
        ),
        pytest.param(
            (False, False, False, True, True),
            "D0I0F0T1@1C0P1V0U0S0Wsmart",
            id="last-two-on",
        ),
    ],
)
def test_tr_meta_roundtrip_parametrized_flag_permutations(
    flags: tuple[bool, ...], expected_meta: str
) -> None:
    """Various flag permutations all survive the round-trip cycle."""
    meta = _set_flags_and_build(*flags)

    original, extracted = _roundtrip_meta(meta)

    assert original == expected_meta
    assert extracted == original


# ---------------------------------------------------------------------------
# Test 2.4
# ---------------------------------------------------------------------------


def test_tr_meta_roundtrip_with_multiline_tree_content() -> None:
    """tr_meta survives round-trip with a large, realistic tree."""
    lines = ["myproject/"]
    for depth in range(10):
        prefix = "│   " * depth
        lines.append(f"{prefix}├── level_{depth}/ [pkg]")
        for file_index in range(5):
            child_prefix = "│   " * (depth + 1)
            connector = "└── " if file_index == 4 else "├── "
            lines.append(f"{child_prefix}{connector}module_{file_index}.py")
    tree_content = "\n".join(lines) + "\n"

    meta = build_tr_meta()
    combined = append_tr_meta(tree_content, meta)
    extracted_tree, meta_value, meta_status = split_tree_and_meta(
        combined, "myproject"
    )

    assert meta_status == "valid"
    assert meta_value is not None
    assert meta_value == meta
    # Tree content should be preserved (stripped trailing whitespace may differ).
    assert "level_0/ [pkg]" in extracted_tree
    assert "module_4.py" in extracted_tree


# ---------------------------------------------------------------------------
# Test 2.5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("# tr_meta:D1I1F1T1", id="partial-T-only"),
        pytest.param("# tr_meta:D1I1F1T1@1", id="partial-T-and-at"),
    ],
)
def test_tr_meta_parse_rejects_partial_v2_format(line: str) -> None:
    """Partial v2 extension flags (missing some of T/@/C) must be rejected."""
    result = parse_tr_meta_line(line)

    assert result is None
