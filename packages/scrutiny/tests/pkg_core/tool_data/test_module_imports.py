"""Direct-import smoke tests for decomposed scrutiny modules.

Each test imports all public symbols from the new module location
directly, NOT through the scrutiny.py re-export shim.  This
ensures the extracted modules are independently importable.
"""

from __future__ import annotations


# ===== Pass 1: Foundation Modules ===== #


def test_core_enums_imports() -> None:
    """All 10 enum classes import from core.enums."""
    from scrutiny.core.enums import (
        ConfigSource,
        ConfigTier,
        FrameworkSelection,
        LineLength,
        LoggerLevel,
        LogLocation,
        PythonVersion,
        SearchDepth,
        SecurityTool,
        ToolTimeout,
    )

    assert ConfigTier.STRICT.value == "strict"
    assert LoggerLevel.NORMAL == 2
    assert PythonVersion.PY39.to_dotted == "3.9"
    assert str(ConfigSource.CLI) == "cli"
    assert LineLength.STANDARD == 100
    assert SearchDepth.DEFAULT == 8
    assert ToolTimeout.PATIENT == 120
    assert SecurityTool.BANDIT.value == "bandit"
    assert LogLocation.HYBRID.value == "hybrid"
    assert FrameworkSelection.NONE.value == "none"


def test_core_exceptions_imports() -> None:
    """ExitCode, all SCRError subclasses, handle_errors import from core.exceptions."""
    from scrutiny.core.exceptions import (
        SCRConfigurationError,
        SCRError,
        SCRLoggerError,
        SCRLoggerFileError,
        SCRLoggerLevelError,
        SCRProjectRootError,
        SCRSystemError,
        SCRTimeoutError,
        SCRToolExecutionError,
        SCRUnexpectedError,
        SCRUserInputError,
        ExitCode,
        EnumT,
        _FuncT,
        handle_errors,
    )

    assert ExitCode.GENERAL == 1
    assert issubclass(SCRSystemError, SCRError)
    assert issubclass(SCRTimeoutError, SCRToolExecutionError)
    assert SCRError.display_tag == "[ERROR]"
    assert SCRUnexpectedError.display_tag == "[UNEXPECTED]"
    assert callable(handle_errors)
    # TypeVars exist
    assert EnumT is not None
    assert _FuncT is not None
    # Verify subclass chain
    assert issubclass(SCRLoggerLevelError, SCRLoggerError)
    assert issubclass(SCRLoggerFileError, SCRLoggerError)
    assert issubclass(SCRProjectRootError, SCRError)
    assert issubclass(SCRConfigurationError, SCRError)
    assert issubclass(SCRUserInputError, SCRError)


def test_core_tool_data_imports() -> None:
    """Key tool data constants and functions import from core.tool_data."""
    from scrutiny.core.tool_data import (
        BANDIT_CLI_FLAGS,
        BANDIT_TIER_SETTINGS,
        MYPY_TIER_SETTINGS,
        PYPROJECT_TEMPLATES,
        RADON_TIER_SETTINGS,
        RUFF_RULES_ESSENTIAL,
        RUFF_RULES_STRICT,
        RUFF_TIER_RULES,
        TOOL_REGISTRY,
        build_ruff_rules,
        get_test_config_tier,
    )

    assert "ruff_linter" in TOOL_REGISTRY
    assert isinstance(RUFF_RULES_ESSENTIAL, tuple)
    assert len(RUFF_RULES_STRICT) > len(RUFF_RULES_ESSENTIAL)
    assert "essential" in RUFF_TIER_RULES
    assert "essential" in MYPY_TIER_SETTINGS
    assert "essential" in RADON_TIER_SETTINGS
    assert "essential" in BANDIT_TIER_SETTINGS
    assert "ruff" in PYPROJECT_TEMPLATES
    assert callable(build_ruff_rules)
    assert callable(get_test_config_tier)
    assert "format" in BANDIT_CLI_FLAGS


def test_config_imports() -> None:
    """UserDefaults and UserDefaultsSnapshot import from config."""
    from scrutiny.config import UserDefaults, UserDefaultsSnapshot

    snapshot = UserDefaults.to_frozen()
    assert isinstance(snapshot, UserDefaultsSnapshot)
    assert snapshot.scr_config_tier.value == "strict"


def test_output_logger_imports() -> None:
    """DeferredLogBuffer and SCRLogger import from output.logger."""
    from scrutiny.output.logger import SCRLogger, DeferredLogBuffer

    assert hasattr(DeferredLogBuffer, "capture")
    assert hasattr(DeferredLogBuffer, "flush")
    assert hasattr(DeferredLogBuffer, "flush_or_stderr")
    assert hasattr(DeferredLogBuffer, "clear")
    assert hasattr(SCRLogger, "close")
    assert hasattr(SCRLogger, "get_log_info")


def test_configs_dataclasses_imports() -> None:
    """Config dataclasses import from configs.dataclasses."""
    from scrutiny.configs.dataclasses import (
        BanditConfig,
        GlobalConfig,
        MypyConfig,
        RadonConfig,
        RuffConfig,
        _SharedConfigValidator,
        _ToolConfigMixin,
    )

    assert hasattr(_SharedConfigValidator, "validate_enum_field")
    assert hasattr(GlobalConfig, "get_enabled_tools")
    assert issubclass(RuffConfig, _ToolConfigMixin)
    assert issubclass(MypyConfig, _ToolConfigMixin)
    assert issubclass(RadonConfig, _ToolConfigMixin)
    assert issubclass(BanditConfig, _ToolConfigMixin)


def test_configs_resolver_imports() -> None:
    """ContextDetection, EffectiveValue, ConfigResolver import from configs.resolver."""
    from scrutiny.configs.resolver import (
        CI_ENV_VARS,
        IDE_ENV_VARS,
        IDE_PROCESSES,
        PRECOMMIT_ENV_VARS,
        ConfigResolver,
        ContextDetection,
        EffectiveValue,
    )

    assert ContextDetection.CLI.value == "cli"
    assert isinstance(CI_ENV_VARS, frozenset)
    assert isinstance(PRECOMMIT_ENV_VARS, frozenset)
    assert isinstance(IDE_ENV_VARS, frozenset)
    assert isinstance(IDE_PROCESSES, frozenset)
    assert hasattr(ConfigResolver, "resolve")
    assert hasattr(EffectiveValue, "__dataclass_fields__")


# ===== Pass 2: Middle-Layer Modules ===== #


def test_configs_pyproject_imports() -> None:
    """PyProjectLoader and PyProjectGenerator import from configs.pyproject."""
    from scrutiny.configs.pyproject import (
        PyProjectGenerator,
        PyProjectLoader,
    )

    assert hasattr(PyProjectLoader, "load_from_path")
    assert hasattr(PyProjectGenerator, "generate_or_merge")


def test_output_formatting_imports() -> None:
    """SourceReader, OutputFormatter, format_and_log_tool_output import from output.formatting."""
    from scrutiny.output.formatting import (
        OutputFormatter,
        SourceReader,
        format_and_log_tool_output,
    )

    assert hasattr(SourceReader, "read_source_context")
    assert hasattr(OutputFormatter, "generate_summary")
    assert callable(format_and_log_tool_output)


def test_execution_services_imports() -> None:
    """Services import from execution.services."""
    from scrutiny.execution.services import (
        FileDiscoveryService,
        ProjectRootService,
        _CACHE_DIR_NAMES,
        _STANDARD_EXCLUDE_DIRS,
        clear_tool_caches,
        which,
    )

    assert isinstance(_STANDARD_EXCLUDE_DIRS, frozenset)
    assert isinstance(_CACHE_DIR_NAMES, frozenset)
    assert hasattr(ProjectRootService, "get_project_root")
    assert hasattr(FileDiscoveryService, "discover_files")
    assert callable(clear_tool_caches)
    assert callable(which)


def test_execution_handlers_imports() -> None:
    """Handler classes and issue types import from execution.handlers."""
    from scrutiny.execution.handlers import (
        BaseToolHandler,
        BanditIssue,
        RuffIssue,
        _ANSI_ESCAPE_PATTERN,
    )

    assert hasattr(RuffIssue, "__slots__")
    assert callable(BaseToolHandler)
    assert isinstance(_ANSI_ESCAPE_PATTERN.pattern, str)
    assert hasattr(BanditIssue, "meets_threshold")


def test_execution_results_imports() -> None:
    """Result data types import from execution.results."""
    from scrutiny.execution.results import ResultTotals, ToolResult

    assert hasattr(ToolResult, "__dataclass_fields__")
    assert "tool" in ToolResult.__dataclass_fields__
    assert hasattr(ResultTotals, "__dataclass_fields__")


# ===== Pass 3: Main Module ===== #


def test_cli_module_imports() -> None:
    """CLI parsing and doctor mode import from cli."""
    from scrutiny.core.cli import (
        _VERSION,
        parse_cli_to_dict,
        run_doctor,
        create_argument_parser,
    )

    assert _VERSION == "1.0.0"
    assert callable(create_argument_parser)
    assert callable(run_doctor)
    assert callable(parse_cli_to_dict)


def test_main_orchestration_imports() -> None:
    """Orchestration functions import from main."""
    from scrutiny.main import (
        _build_preliminary_config,
        _build_resolved_config,
        _create_logger,
        _dispatch_tool_execution,
        _resolve_start_path,
        _run_analysis_phase,
        _run_tool_safe,
        _verify_tool_availability,
        main,
    )
    from scrutiny.output.reporting import (
        report_final_status,
        determine_exit_code,
    )

    assert callable(determine_exit_code)
    assert callable(_run_tool_safe)
    assert callable(_build_preliminary_config)
    assert callable(_build_resolved_config)
    assert callable(_dispatch_tool_execution)
    assert callable(report_final_status)
    assert callable(_resolve_start_path)
    assert callable(_run_analysis_phase)
    assert callable(_verify_tool_availability)
    assert callable(_create_logger)
    assert callable(main)


def test_main_leaf_helpers_imports() -> None:
    """Leaf helpers import from their new modules."""
    from scrutiny.core.cli import (
        _extract_enum_args,
        _extract_toggle_overrides,
        _extract_valued_args,
    )
    from scrutiny.main import _compute_mi_ranks
    from scrutiny.output.header import (
        _format_header_normal,
        _format_header_verbose,
        _log_discovered_files,
    )
    from scrutiny.output.reporting import (
        _compute_result_totals,
        _format_tool_status_line,
    )
    from scrutiny.output.run_logging import (
        _build_fatal_error_summary,
        _extract_error_message,
        log_completed_result,
        _log_verbose_command,
    )

    assert callable(_extract_error_message)
    assert callable(_build_fatal_error_summary)
    assert callable(_log_verbose_command)
    assert callable(log_completed_result)
    assert callable(_extract_valued_args)
    assert callable(_extract_enum_args)
    assert callable(_extract_toggle_overrides)
    assert callable(_format_header_verbose)
    assert callable(_format_header_normal)
    assert callable(_log_discovered_files)
    assert callable(_compute_result_totals)
    assert callable(_format_tool_status_line)
    assert callable(_compute_mi_ranks)


def test_main_module_is_main() -> None:
    """main() is callable from scrutiny.main."""
    from scrutiny.main import main

    assert main.__module__ == "scrutiny.main"
