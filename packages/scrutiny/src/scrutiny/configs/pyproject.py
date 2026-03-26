"""
Load and generate pyproject.toml configuration for scrutiny tools.

Provide ``PyProjectLoader`` for locating, parsing, and mapping pyproject.toml
sections, and ``PyProjectGenerator`` for creating or merging tool configuration
into pyproject.toml files.

Classes
-------
PyProjectLoader : Locate, parse, and map pyproject.toml sections.
PyProjectGenerator : Create or merge tool configuration into pyproject.toml files.

Examples
--------
>>> isinstance(PyProjectLoader, type)
True

"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from scrutiny.core.exceptions import SCRConfigurationError
from scrutiny.core.tool_data import (
    COVERAGE_TIER_MAP,
    MANAGED_TOOL_NAMES,
    MYPY_TIER_SETTINGS,
    PYPROJECT_KEY_MAP,
    PYPROJECT_TEMPLATES,
    PYTEST_PLUGIN_ADDOPTS,
    PYTEST_REQUIRED_PLUGINS,
    PYTEST_TIER_MAP,
    RUFF_PER_FILE_IGNORES,
    build_ruff_rules,
    get_test_config_tier,
)
from scrutiny.output.logger import DeferredLogBuffer

if TYPE_CHECKING:
    from scrutiny.configs.dataclasses import GlobalConfig

# TOML library for pyproject.toml parsing.  Availability is checked at first
# use in PyProjectLoader.load_from_path(); no import-time side effect needed.
try:
    import tomllib  # type: ignore[import-not-found,unused-ignore]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef,unused-ignore]
    except ImportError:
        tomllib = None  # type: ignore[assignment,unused-ignore]

# TOML writing library for key-level pyproject.toml merging.  Methods that
# need this fall back to section-level merging when it is unavailable.
try:
    import tomli_w  # type: ignore[import-not-found,unused-ignore]
except ImportError:
    tomli_w = None  # type: ignore[assignment]


class PyProjectLoader:
    """
    Load and parse configuration from pyproject.toml files.

    Provides static methods to locate, parse, and extract
    tool-specific sections from pyproject.toml, mapping native
    TOML keys to internal configuration keys via
    ``PYPROJECT_KEY_MAP``.
    """

    @staticmethod
    def find_pyproject_toml(
        start_path: Path,
        max_depth: int = 5,
    ) -> Optional[Path]:
        """
        Search upward from *start_path* for pyproject.toml.

        Parameters
        ----------
        start_path : Path
            Directory (or file whose parent is used) to begin searching.
        max_depth : int
            Maximum number of parent directories to check.

        Returns
        -------
        Optional[Path]
            Absolute path to pyproject.toml if found, else None.

        """
        # Resolve the starting directory; bail on unresolvable paths.
        try:
            current = (start_path if start_path.is_dir() else start_path.parent).resolve()
        except (OSError, RuntimeError):
            return None

        # Walk up parent directories looking for pyproject.toml.
        for _ in range(max_depth):
            candidate = current / "pyproject.toml"
            try:
                if candidate.is_file():
                    return candidate
            except (OSError, PermissionError):
                # Inaccessible candidate; skip to next parent directory.
                pass

            # Stop at filesystem root where parent equals current.
            parent = current.parent
            if parent == current:
                break
            current = parent

        return None

    @staticmethod
    def load_from_path(pyproject_path: Path) -> dict[str, Any]:
        """
        Parse a pyproject.toml file and return nested dicts.

        Parameters
        ----------
        pyproject_path : Path
            Path to the TOML file.

        Returns
        -------
        dict[str, Any]
            Parsed TOML data.

        Raises
        ------
        SCRConfigurationError
            If the TOML library is unavailable or the file cannot be parsed.

        """
        # Ensure the TOML parsing library is available before attempting load.
        if tomllib is None:
            raise SCRConfigurationError(
                "TOML library not available. Install tomli for Python <3.11: pip install tomli",
            )
        # Read and parse the TOML file, re-wrapping errors as SCRConfigurationError.
        try:
            with pyproject_path.open("rb") as file_handle:
                data: dict[str, Any] = tomllib.load(file_handle)
                return data
        except FileNotFoundError as file_not_found_error:
            raise SCRConfigurationError(
                f"pyproject.toml not found: {pyproject_path}"
            ) from file_not_found_error
        except (
            tomllib.TOMLDecodeError,
            OSError,
            ValueError,
            TypeError,
            UnicodeDecodeError,
        ) as toml_parse_error:
            raise SCRConfigurationError(
                f"Failed to parse {pyproject_path}: {toml_parse_error}"
            ) from toml_parse_error

    @staticmethod
    def extract_tool_config(
        pyproject_data: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """
        Extract a tool section from parsed TOML data.

        Supports dotted tool names (e.g. ``"ruff.lint"``) by walking
        nested dicts.

        Parameters
        ----------
        pyproject_data : dict[str, Any]
            Parsed pyproject.toml data.
        tool_name : str
            Tool section name (e.g. ``"ruff"``, ``"ruff.lint"``).

        Returns
        -------
        dict[str, Any]
            Tool configuration dict, empty if not found.

        """
        tool_section = pyproject_data.get("tool", {})
        parts = tool_name.split(".")
        # Walk into nested dicts following each dotted segment.
        current: Any = tool_section
        # Walk into nested dicts following each dotted segment
        for part in parts:
            # Continue traversal only when the current level is a dict
            if isinstance(current, dict):
                current = current.get(part, {})
            else:
                return {}
        return current if isinstance(current, dict) else {}

    @staticmethod
    def map_to_internal_keys(
        tool_name: str,
        native_config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Map native pyproject.toml keys to internal config keys.

        Uses ``PYPROJECT_KEY_MAP`` to translate keys.  Unknown keys
        are silently ignored.

        Parameters
        ----------
        tool_name : str
            Tool section name (e.g. ``"ruff"``, ``"mypy"``).
        native_config : dict[str, Any]
            Raw config dict from TOML with native key names.

        Returns
        -------
        dict[str, Any]
            Dict with internal key names.

        """
        key_map = PYPROJECT_KEY_MAP.get(tool_name, {})
        # Translate only recognised native keys to their internal equivalents.
        mapped: dict[str, Any] = {}
        for native_key, value in native_config.items():
            internal_key = key_map.get(native_key)
            # Include only keys that have a known internal mapping
            if internal_key is not None:
                mapped[internal_key] = value
        return mapped


class PyProjectGenerator:
    """
    Generate or merge pyproject.toml tool configuration sections.

    Creates new pyproject.toml files from ``PYPROJECT_TEMPLATES``,
    or merges missing keys into existing files.  When ``override``
    is True, existing ``[tool.*]`` sections are overwritten.
    """

    # Possible outcomes reported after generation.
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped (override requires tomli_w)"

    @staticmethod
    def _to_toml_array(
        items: Sequence[str],
        max_inline_length: int = 80,
    ) -> str:
        """
        Format a sequence of strings as a valid TOML array literal.

        Short arrays are rendered inline.  When the inline representation
        exceeds *max_inline_length* characters the array is rendered with
        one item per line for readability.

        Parameters
        ----------
        items : Sequence[str]
            Strings to include in the array.
        max_inline_length : int
            Character threshold above which the array switches to
            multi-line format.  Default is 80.

        Returns
        -------
        str
            TOML-formatted array, e.g. ``["a", "b", "c"]`` or a
            multi-line equivalent for longer arrays.

        """
        # Try inline format first; switch to multi-line if too wide.
        inline = "[" + ", ".join(f'"{item}"' for item in items) + "]"
        if len(inline) <= max_inline_length:
            return inline
        # Multi-line format with one item per line.
        inner = ",\n".join(f'    "{item}"' for item in items)
        return "[\n" + inner + ",\n]"

    @staticmethod
    def generate_or_merge(
        project_root: Path,
        global_config: GlobalConfig,
    ) -> str:
        """
        Create or update pyproject.toml in *project_root*.

        Parameters
        ----------
        project_root : Path
            Directory containing (or receiving) pyproject.toml.
        global_config : GlobalConfig
            Resolved configuration used for template rendering and
            override/merge decisions.

        Returns
        -------
        str
            One of ``"created"``, ``"updated"``, ``"skipped"``,
            or ``"unchanged"``.

        """
        pyproject_path = project_root / "pyproject.toml"

        # Build the full TOML string from templates.
        generated_content = PyProjectGenerator._render_templates(global_config)

        try:
            if not pyproject_path.exists():
                # No existing file -> write from scratch.
                pyproject_path.write_text(generated_content, encoding="utf-8")
                return PyProjectGenerator.CREATED

            # File exists -- decide merge vs override.
            existing_text = pyproject_path.read_text(encoding="utf-8")

            if global_config.override_config:
                # Override only managed tool sections, preserving unmanaged ones.
                if tomllib is not None and tomli_w is not None:
                    return PyProjectGenerator._override_key_level(
                        pyproject_path,
                        existing_text,
                        generated_content,
                    )
                # Cannot safely override without tomli_w — risk damaging
                # unmanaged tool sections.
                return PyProjectGenerator.SKIPPED

            # Merge: add missing keys to existing [tool.*] sections.
            if tomllib is not None and tomli_w is not None:
                # Key-level merge using TOML libraries.
                return PyProjectGenerator._merge_key_level(
                    pyproject_path,
                    existing_text,
                    generated_content,
                )

            # Section-level fallback when tomli_w is unavailable.
            return PyProjectGenerator._merge_section_level(
                pyproject_path,
                existing_text,
                generated_content,
            )
        except OSError as file_write_error:
            raise SCRConfigurationError(
                f"pyproject.toml generation failed for {pyproject_path}: {file_write_error}"
            ) from file_write_error

    @staticmethod
    def _merge_key_level(
        pyproject_path: Path,
        existing_text: str,
        generated_content: str,
    ) -> str:
        """
        Merge generated tool keys into an existing pyproject.toml.

        Parse both the existing file and the generated content as TOML,
        then add any missing keys to existing ``[tool.*]`` sections
        without overwriting keys that already exist.

        Parameters
        ----------
        pyproject_path : Path
            Path to the existing pyproject.toml file.
        existing_text : str
            Current content of pyproject.toml.
        generated_content : str
            Rendered TOML string from ``_render_templates``.

        Returns
        -------
        str
            One of ``"updated"`` or ``"unchanged"``.

        """
        # Parse both existing and generated TOML for structured merging
        try:
            existing_data = tomllib.loads(existing_text)
            generated_data = tomllib.loads(generated_content)
        except (tomllib.TOMLDecodeError, ValueError, TypeError) as toml_error:
            # Malformed TOML prevents safe merging
            raise SCRConfigurationError(
                f"Cannot merge {pyproject_path}: malformed TOML: {toml_error}",
            ) from toml_error

        # Deep-merge generated tool sections into existing data.
        changed = PyProjectGenerator._deep_merge_tool_sections(
            existing_data,
            generated_data,
        )

        # Skip writing when no new keys were merged.
        if not changed:
            return PyProjectGenerator.UNCHANGED

        # Write back with tomli_w.
        with pyproject_path.open("wb") as toml_file:
            tomli_w.dump(existing_data, toml_file)
        return PyProjectGenerator.UPDATED

    @staticmethod
    def _override_key_level(
        pyproject_path: Path,
        existing_text: str,
        generated_content: str,
    ) -> str:
        """
        Override only managed tool sections, preserving unmanaged ones.

        Parse both the existing file and generated content as TOML.
        Replace managed tool sections entirely with generated versions
        while keeping all unmanaged tool sections and non-tool content
        intact.

        Parameters
        ----------
        pyproject_path : Path
            Path to the existing pyproject.toml file.
        existing_text : str
            Current content of pyproject.toml.
        generated_content : str
            Rendered TOML string from ``_render_templates``.

        Returns
        -------
        str
            One of ``"updated"`` or ``"unchanged"``.

        """
        # Parse both existing and generated TOML for structured override
        try:
            existing_data = tomllib.loads(existing_text)
            generated_data = tomllib.loads(generated_content)
        except (tomllib.TOMLDecodeError, ValueError, TypeError) as toml_error:
            # Malformed TOML prevents safe override
            raise SCRConfigurationError(
                f"Cannot merge {pyproject_path}: malformed TOML: {toml_error}",
            ) from toml_error

        gen_tools = generated_data.get("tool", {})
        ext_tools = existing_data.setdefault("tool", {})

        # Overwrite each managed tool section if it differs from generated.
        changed = False
        for tool_name in MANAGED_TOOL_NAMES:
            # Skip tools not present in the generated config
            if tool_name not in gen_tools:
                continue
            # Overwrite when the existing section differs from generated
            if ext_tools.get(tool_name) != gen_tools[tool_name]:
                ext_tools[tool_name] = gen_tools[tool_name]
                changed = True

        # Skip writing when no managed sections were changed.
        if not changed:
            return PyProjectGenerator.UNCHANGED

        # Write back with tomli_w.
        with pyproject_path.open("wb") as toml_file:
            tomli_w.dump(existing_data, toml_file)
        return PyProjectGenerator.UPDATED

    @staticmethod
    def _merge_section_level(
        pyproject_path: Path,
        existing_text: str,
        generated_content: str,
    ) -> str:
        """
        Merge at section level, adding only entirely new sections.

        Fallback used when ``tomli_w`` is not available.

        Parameters
        ----------
        pyproject_path : Path
            Path to the existing pyproject.toml file.
        existing_text : str
            Current content of pyproject.toml.
        generated_content : str
            Rendered TOML string from ``_render_templates``.

        Returns
        -------
        str
            One of ``"updated"`` or ``"unchanged"``.

        """
        sections_added = 0
        result_lines = existing_text.rstrip("\n").split("\n")

        # Append only entirely new sections not already in the file.
        for section_header, section_body in PyProjectGenerator._iter_sections(
            generated_content,
        ):
            # Add sections that do not already exist in the file
            if section_header not in existing_text:
                result_lines.append("")
                result_lines.append(section_header)
                result_lines.extend(section_body)
                sections_added += 1

        # Skip writing when no new sections were appended.
        if sections_added == 0:
            return PyProjectGenerator.UNCHANGED

        pyproject_path.write_text(
            "\n".join(result_lines) + "\n",
            encoding="utf-8",
        )
        return PyProjectGenerator.UPDATED

    @staticmethod
    def _merge_section_keys(
        ext_section: dict[str, Any],
        gen_section: dict[str, Any],
    ) -> bool:
        """
        Merge keys from a generated section into an existing section.

        Handles one level of nesting (e.g. ``tool.ruff.lint``).
        Existing keys are never overwritten.

        Parameters
        ----------
        ext_section : dict[str, Any]
            Existing section (modified in place).
        gen_section : dict[str, Any]
            Generated section to merge from.

        Returns
        -------
        bool
            True if any keys were added.

        """
        added = False
        for key, value in gen_section.items():
            # Recursively merge nested dicts (e.g. ruff.lint sub-keys).
            if isinstance(value, dict) and isinstance(ext_section.get(key), dict):
                for sub_key, sub_value in value.items():
                    if sub_key not in ext_section[key]:
                        ext_section[key][sub_key] = sub_value
                        added = True
            # Add top-level keys that are entirely absent.
            elif key not in ext_section:
                ext_section[key] = value
                added = True
        return added

    @staticmethod
    def _deep_merge_tool_sections(
        existing: dict[str, Any],
        generated: dict[str, Any],
    ) -> bool:
        """
        Merge generated tool keys into existing, keeping existing values.

        Walk the ``[tool.*]`` hierarchy and add any keys from *generated*
        that are absent in *existing*.  Existing keys are never
        overwritten.

        Parameters
        ----------
        existing : dict[str, Any]
            Parsed existing pyproject.toml (modified in place).
        generated : dict[str, Any]
            Parsed generated TOML content.

        Returns
        -------
        bool
            True if any keys were added, False otherwise.

        """
        added = False
        gen_tools = generated.get("tool", {})
        ext_tools = existing.setdefault("tool", {})

        for section_name, section_value in gen_tools.items():
            # Entirely new tool section -- insert wholesale.
            if section_name not in ext_tools:
                ext_tools[section_name] = section_value
                added = True
            # Existing tool section -- merge missing keys only.
            elif isinstance(section_value, dict) and isinstance(ext_tools[section_name], dict):
                if PyProjectGenerator._merge_section_keys(ext_tools[section_name], section_value):
                    added = True

        return added

    @staticmethod
    def _render_templates(config: GlobalConfig) -> str:
        """
        Render ``PYPROJECT_TEMPLATES`` into a TOML string.

        Tier-selected rules are merged with any framework-specific
        rules before substitution.  Ignore rules are version-aware
        via ``_build_effective_ignore_rules`` and include mypy overlap
        rules when mypy is enabled.

        A ``[tool.ruff.lint.per-file-ignores]`` section is appended
        when ``RUFF_PER_FILE_IGNORES`` is non-empty.

        Parameters
        ----------
        config : GlobalConfig
            Resolved configuration providing tier, framework, line
            length, Python version, fix mode, mypy toggle, and
            exclusion directories for variable substitution.

        Returns
        -------
        str
            Complete TOML string with ``[tool.*]`` sections.

        """
        # Build substitution values from global configuration.
        tier = config.config_tier.value
        ruff_rules, effective_ignores = build_ruff_rules(
            config.config_tier,
            config.framework,
            config.python_version,
            config.run_mypy,
        )
        mypy_settings = MYPY_TIER_SETTINGS.get(tier, {})

        substitutions: dict[str, str] = {
            "line_length": str(config.line_length.value),
            "python_version": f'"{config.python_version.value}"',
            "python_version_dotted": f'"{config.python_version.to_dotted}"',
            "fix": str(config.effective_fix).lower(),
            "select_rules": PyProjectGenerator._to_toml_array(ruff_rules),
            "ignore_rules": PyProjectGenerator._to_toml_array(effective_ignores),
            "strict_mode": str(mypy_settings.get("strict_mode", False)).lower(),
            "warn_unreachable": str(mypy_settings.get("warn_unreachable", True)).lower(),
            "ignore_missing_imports": str(
                mypy_settings.get("ignore_missing_imports", True),
            ).lower(),
            "exclude_dirs": PyProjectGenerator._to_toml_array(
                config.exclude_dirs,
            ),
            "skip_tests": "[]",
        }

        # Render each tool section from its template, substituting placeholders.
        lines: list[str] = []
        for tool_name, template in PYPROJECT_TEMPLATES.items():
            if not template:
                continue
            lines.append(f"[tool.{tool_name}]")
            for key, value_template in template.items():
                rendered = value_template
                for var_name, var_value in substitutions.items():
                    rendered = rendered.replace(f"{{{var_name}}}", var_value)
                lines.append(f"{key} = {rendered}")
            lines.append("")

        # Per-file-ignores (dict-of-arrays, handled separately from
        # key-value templates because TOML inline tables differ).
        lines.extend(PyProjectGenerator._render_per_file_ignores())

        if config.include_test_config:
            lines.extend(PyProjectGenerator._render_test_config(config))

        return "\n".join(lines)

    @staticmethod
    def _render_per_file_ignores() -> list[str]:
        """
        Render the ``[tool.ruff.lint.per-file-ignores]`` TOML section.

        Returns
        -------
        list[str]
            TOML lines for per-file-ignores, or empty list when there
            are no overrides.

        """
        # Return empty when there are no per-file overrides to render.
        if not RUFF_PER_FILE_IGNORES:
            return []
        # Emit each glob pattern and its suppressed rule array.
        lines: list[str] = ["[tool.ruff.lint.per-file-ignores]"]
        for pattern, rules in RUFF_PER_FILE_IGNORES.items():
            rules_array = PyProjectGenerator._to_toml_array(rules)
            lines.append(f'"{pattern}" = {rules_array}')
        lines.append("")
        return lines

    @staticmethod
    def _check_coverage_version() -> None:
        """
        Emit a deferred warning when coverage lacks exclude_also support.

        Check the installed ``coverage`` version and capture a
        ``DeferredLogBuffer`` warning if it is older than 7.2 (the
        minimum version supporting ``exclude_also``).  A warning is
        also emitted when ``coverage`` is not installed at all.

        Silently ignores unparseable version strings.
        """
        try:
            coverage_version_str = __import__("coverage").__version__
            coverage_version = tuple(int(part) for part in coverage_version_str.split(".")[:2])
            if coverage_version < (7, 2):
                DeferredLogBuffer.capture(
                    "warning",
                    f"[COVERAGE] Installed coverage {coverage_version_str} "
                    "does not support exclude_also (requires >= 7.2). "
                    "Generated config uses exclude_also for best practice. "
                    "Upgrade: pip install --upgrade coverage | conda update coverage",
                )
        except ImportError:
            DeferredLogBuffer.capture(
                "warning",
                "[COVERAGE] coverage is not installed — cannot verify "
                "exclude_also support (requires >= 7.2). "
                "Install: pip install coverage | conda install coverage",
            )
        except (AttributeError, ValueError):
            # Coverage version could not be parsed; skip check.
            pass

    @staticmethod
    def _render_coverage_sections(
        coverage_settings: dict[str, dict[str, Any]],
    ) -> list[str]:
        """
        Render ``[tool.coverage.run]`` and ``[tool.coverage.report]`` TOML.

        Iterate the *run* and *report* sub-sections, formatting list
        values as TOML arrays and scalars as bare values.

        Parameters
        ----------
        coverage_settings : dict[str, dict[str, Any]]
            Mapping of section key (``"run"``, ``"report"``) to its
            key-value pairs.

        Returns
        -------
        list[str]
            TOML lines for both coverage sections.

        """
        lines: list[str] = []
        for section_key in ("run", "report"):
            section_data = coverage_settings[section_key]
            lines.append(f"[tool.coverage.{section_key}]")
            for key, value in section_data.items():
                # Lists render as TOML arrays; scalars as bare values.
                if isinstance(value, list):
                    lines.append(f"{key} = {PyProjectGenerator._to_toml_array(value)}")
                else:
                    lines.append(f"{key} = {value}")
            lines.append("")
        return lines

    @staticmethod
    def _render_test_config(config: GlobalConfig) -> list[str]:
        """
        Render pytest and coverage TOML sections.

        Determines the test-config tier (relaxed or strict) from the active
        ``ConfigTier`` and optionally merges plugin flags when
        ``config.include_test_plugins`` is set.

        Uses ``exclude_also`` (coverage 7.2+) for coverage report exclusion
        patterns.  A deferred warning is emitted at render time if the
        installed coverage version is older than 7.2 or is not installed.

        Parameters
        ----------
        config : GlobalConfig
            Resolved configuration providing tier and plugin flags.

        Returns
        -------
        list[str]
            TOML lines for ``[tool.pytest.ini_options]`` and
            ``[tool.coverage.*]`` sections.

        """
        # Warn when the installed coverage lacks exclude_also support.
        PyProjectGenerator._check_coverage_version()

        tier_label = get_test_config_tier(config.config_tier)
        pytest_settings = PYTEST_TIER_MAP[tier_label]
        coverage_settings = COVERAGE_TIER_MAP[tier_label]

        # Deep-copy addopts so plugin merging does not mutate the constant.
        addopts: list[str] = list(pytest_settings["addopts"])
        extra_keys: dict[str, Any] = {}
        # Merge plugin-specific addopts and required_plugins when enabled.
        if config.include_test_plugins:
            addopts.extend(PYTEST_PLUGIN_ADDOPTS)
            extra_keys["required_plugins"] = list(PYTEST_REQUIRED_PLUGINS)

        lines: list[str] = [
            "[tool.pytest.ini_options]",
            f"minversion = {pytest_settings['minversion']}",
            f"testpaths = {PyProjectGenerator._to_toml_array(pytest_settings['testpaths'])}",
            f"addopts = {PyProjectGenerator._to_toml_array(addopts)}",
        ]

        # Strict-only pytest settings (xfail_strict and filterwarnings).
        if pytest_settings.get("xfail_strict"):
            lines.append(f"xfail_strict = {pytest_settings['xfail_strict']}")
        if pytest_settings.get("filterwarnings"):
            lines.append(
                "filterwarnings = "
                f"{PyProjectGenerator._to_toml_array(pytest_settings['filterwarnings'])}"
            )

        lines.append(f"markers = {PyProjectGenerator._to_toml_array(pytest_settings['markers'])}")
        # Plugin-only: append required_plugins when test plugins are enabled.
        if extra_keys.get("required_plugins"):
            lines.append(
                "required_plugins = "
                f"{PyProjectGenerator._to_toml_array(extra_keys['required_plugins'])}"
            )
        lines.append("")

        # Render coverage sections from tier-specific settings.
        lines.extend(PyProjectGenerator._render_coverage_sections(coverage_settings))

        return lines

    @staticmethod
    def _iter_sections(
        toml_text: str,
    ) -> list[tuple[str, list[str]]]:
        """
        Split rendered TOML text into (header, body_lines) pairs.

        Parameters
        ----------
        toml_text : str
            TOML text with ``[tool.*]`` sections.

        Returns
        -------
        list[tuple[str, list[str]]]
            Each tuple is (section_header_line, list_of_body_lines).

        """
        sections: list[tuple[str, list[str]]] = []
        current_header: Optional[str] = None
        current_body: list[str] = []

        for line in toml_text.split("\n"):
            stripped_line = line.strip()
            # Start a new section when a [tool.*] header is encountered.
            if stripped_line.startswith("[tool."):
                if current_header is not None:
                    sections.append((current_header, current_body))
                current_header = stripped_line
                current_body = []
            # Accumulate non-blank body lines under the current header.
            elif current_header is not None:
                if stripped_line:
                    current_body.append(line)

        # Flush the last section.
        if current_header is not None:
            sections.append((current_header, current_body))

        return sections
