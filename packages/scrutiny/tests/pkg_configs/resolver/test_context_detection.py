"""Tests for the ContextDetection enum and its detection / policy methods."""

from __future__ import annotations

import pytest

from scrutiny.config import UserDefaults, UserDefaultsSnapshot
from scrutiny.configs.resolver import (
    CI_ENV_VARS,
    PRECOMMIT_ENV_VARS,
    IDE_ENV_VARS,
    ContextDetection,
)
from scrutiny.core.enums import LoggerLevel

_DEFAULT_SNAPSHOT = UserDefaults.to_frozen()


# ── Helpers ── #


@pytest.fixture()
def _clean_detection_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var that ContextDetection inspects.

    This prevents the real test-runner environment (e.g. CI=true in
    GitHub Actions) from leaking into detection tests.
    """
    for var in CI_ENV_VARS | PRECOMMIT_ENV_VARS | IDE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# ====================================================================== #
#  detect() — environment-variable routing                                #
# ====================================================================== #


@pytest.mark.unit
@pytest.mark.usefixtures("_clean_detection_env")
class TestDetect:
    """Test ContextDetection.detect() priority chain."""

    def test_detect_ci_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return CI when the generic CI variable is set."""
        # Arrange
        monkeypatch.setenv("CI", "1")

        # Act
        result = ContextDetection.detect()

        # Assert
        assert result is ContextDetection.CI

    def test_detect_github_actions_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return CI when GITHUB_ACTIONS is set."""
        # Arrange
        monkeypatch.setenv("GITHUB_ACTIONS", "true")

        # Act
        result = ContextDetection.detect()

        # Assert
        assert result is ContextDetection.CI

    def test_detect_precommit_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return PRECOMMIT when PRE_COMMIT is set."""
        # Arrange
        monkeypatch.setenv("PRE_COMMIT", "1")

        # Act
        result = ContextDetection.detect()

        # Assert
        assert result is ContextDetection.PRECOMMIT

    def test_detect_ide_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return IDE when VSCODE_PID is set."""
        # Arrange
        monkeypatch.setenv("VSCODE_PID", "12345")

        # Act
        result = ContextDetection.detect()

        # Assert
        assert result is ContextDetection.IDE

    def test_detect_cli_fallback(self) -> None:
        """Return CLI when no detection env vars are present."""
        # Arrange — fixture already cleared all vars

        # Act
        result = ContextDetection.detect()

        # Assert
        assert result is ContextDetection.CLI

    def test_ci_takes_priority_over_precommit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Return CI when both CI and pre-commit env vars are set."""
        # Arrange
        monkeypatch.setenv("CI", "1")
        monkeypatch.setenv("PRE_COMMIT", "1")

        # Act
        result = ContextDetection.detect()

        # Assert
        assert result is ContextDetection.CI


# ====================================================================== #
#  get_console_logger_level()                                             #
# ====================================================================== #


@pytest.mark.unit
class TestGetConsoleLoggerLevel:
    """Test console-logger-level policy per context."""

    def test_get_console_logger_level_ci(self) -> None:
        """Return QUIET for CI context."""
        # Arrange
        context = ContextDetection.CI

        # Act
        level = ContextDetection.get_console_logger_level(context, _DEFAULT_SNAPSHOT)

        # Assert
        assert level is LoggerLevel.QUIET

    def test_get_console_logger_level_precommit(self) -> None:
        """Return QUIET for PRECOMMIT context."""
        # Arrange
        context = ContextDetection.PRECOMMIT

        # Act
        level = ContextDetection.get_console_logger_level(context, _DEFAULT_SNAPSHOT)

        # Assert
        assert level is LoggerLevel.QUIET

    def test_get_console_logger_level_cli(self) -> None:
        """Return UserDefaults value for CLI context."""
        # Arrange
        context = ContextDetection.CLI

        # Act
        level = ContextDetection.get_console_logger_level(context, _DEFAULT_SNAPSHOT)

        # Assert
        assert level is UserDefaults.SCR_CONSOLE_LOGGER_LEVEL

    def test_get_console_logger_level_ide(self) -> None:
        """Return UserDefaults value for IDE context."""
        # Arrange
        context = ContextDetection.IDE

        # Act
        level = ContextDetection.get_console_logger_level(context, _DEFAULT_SNAPSHOT)

        # Assert
        assert level is UserDefaults.SCR_CONSOLE_LOGGER_LEVEL


# ======================================================================
#  Parametrized edge-case coverage                                        #
# ====================================================================== #


@pytest.mark.unit
@pytest.mark.usefixtures("_clean_detection_env")
@pytest.mark.parametrize(
    "env_var",
    sorted(CI_ENV_VARS),
    ids=lambda v: f"CI-{v}",
)
def test_all_ci_env_vars_detected(env_var: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify every member of CI_ENV_VARS triggers CI detection."""
    # Arrange
    monkeypatch.setenv(env_var, "1")

    # Act
    result = ContextDetection.detect()

    # Assert
    assert result is ContextDetection.CI


@pytest.mark.unit
@pytest.mark.usefixtures("_clean_detection_env")
@pytest.mark.parametrize(
    "env_var",
    sorted(PRECOMMIT_ENV_VARS),
    ids=lambda v: f"PRECOMMIT-{v}",
)
def test_all_precommit_env_vars_detected(env_var: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify every member of PRECOMMIT_ENV_VARS triggers PRECOMMIT detection."""
    # Arrange
    monkeypatch.setenv(env_var, "1")

    # Act
    result = ContextDetection.detect()

    # Assert
    assert result is ContextDetection.PRECOMMIT


@pytest.mark.unit
@pytest.mark.usefixtures("_clean_detection_env")
@pytest.mark.parametrize(
    "env_var",
    sorted(IDE_ENV_VARS),
    ids=lambda v: f"IDE-{v}",
)
def test_all_ide_env_vars_detected(env_var: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify every member of IDE_ENV_VARS triggers IDE detection."""
    # Arrange
    monkeypatch.setenv(env_var, "1")

    # Act
    result = ContextDetection.detect()

    # Assert
    assert result is ContextDetection.IDE


@pytest.mark.unit
@pytest.mark.parametrize(
    "context,expected",
    [
        (ContextDetection.CI, False),
        (ContextDetection.PRECOMMIT, False),
        (ContextDetection.CLI, UserDefaults.SCR_CREATE_LOG),
        (ContextDetection.IDE, UserDefaults.SCR_CREATE_LOG),
    ],
    ids=["CI", "PRECOMMIT", "CLI", "IDE"],
)
def test_should_create_log_all_contexts(context: object, expected: bool) -> None:
    """Verify should_create_log for every context variant."""
    # Act
    result = ContextDetection.should_create_log(context, _DEFAULT_SNAPSHOT)

    # Assert
    assert result is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "context,expected",
    [
        (ContextDetection.CI, True),
        (ContextDetection.PRECOMMIT, True),
        (ContextDetection.CLI, UserDefaults.RUFF_CHECK_ONLY),
        (ContextDetection.IDE, UserDefaults.RUFF_CHECK_ONLY),
    ],
    ids=["CI", "PRECOMMIT", "CLI", "IDE"],
)
def test_should_check_only_all_contexts(context: object, expected: bool) -> None:
    """Verify should_check_only for every context variant."""
    # Act
    result = ContextDetection.should_check_only(context, _DEFAULT_SNAPSHOT)

    # Assert
    assert result is expected
