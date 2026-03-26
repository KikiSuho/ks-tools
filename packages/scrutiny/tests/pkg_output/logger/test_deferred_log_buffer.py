"""Tests for DeferredLogBuffer message buffering and flush behaviour.

Verify that ``DeferredLogBuffer`` correctly captures messages, routes
them to a logger on flush, and operates safely under concurrent access.

Classes
-------
TestDeferredLogBufferCapture : Message storage tests.
TestDeferredLogBufferFlush : Logger dispatch tests.
TestDeferredLogBufferClear : State-reset tests.
TestDeferredLogBufferThreadSafety : Concurrent-access tests.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from unittest.mock import Mock

import pytest

from scrutiny.output.logger import DeferredLogBuffer

# ── Fixtures ── #


@pytest.fixture(autouse=True)
def _clear_buffer() -> Iterator[None]:
    """Clear DeferredLogBuffer state before and after each test."""
    DeferredLogBuffer.clear()
    yield
    DeferredLogBuffer.clear()


# ── Capture ── #


class TestDeferredLogBufferCapture:
    """Test message capture and storage."""

    def test_capture_stores_warning(self) -> None:
        """Store a single warning message."""
        # Arrange
        buf = DeferredLogBuffer

        # Act
        buf.capture("warning", "disk space low")

        # Assert
        assert len(buf._messages) == 1
        assert buf._messages[0] == ("warning", "disk space low")

    def test_capture_stores_error(self) -> None:
        """Store a single error message."""
        # Arrange
        buf = DeferredLogBuffer

        # Act
        buf.capture("error", "connection lost")

        # Assert
        assert len(buf._messages) == 1
        assert buf._messages[0] == ("error", "connection lost")

    def test_capture_preserves_order(self) -> None:
        """Preserve insertion order across multiple captures."""
        # Arrange
        buf = DeferredLogBuffer

        # Act
        buf.capture("warning", "first")
        buf.capture("error", "second")
        buf.capture("warning", "third")

        # Assert
        assert buf._messages == [
            ("warning", "first"),
            ("error", "second"),
            ("warning", "third"),
        ]


# ── Flush ── #


class TestDeferredLogBufferFlush:
    """Test flushing buffered messages to a logger."""

    def test_flush_routes_warnings_to_logger(self) -> None:
        """Dispatch warning messages via ``logger.warning()``."""
        # Arrange
        buf = DeferredLogBuffer
        logger = Mock()
        buf.capture("warning", "warn one")
        buf.capture("warning", "warn two")

        # Act
        buf.flush(logger)

        # Assert
        assert logger.warning.call_count == 2
        logger.warning.assert_any_call("warn one")
        logger.warning.assert_any_call("warn two")

    def test_flush_routes_errors_to_logger(self) -> None:
        """Dispatch error messages via ``logger.error()``."""
        # Arrange
        buf = DeferredLogBuffer
        logger = Mock()
        buf.capture("error", "err one")
        buf.capture("error", "err two")

        # Act
        buf.flush(logger)

        # Assert
        assert logger.error.call_count == 2
        logger.error.assert_any_call("err one")
        logger.error.assert_any_call("err two")

    def test_flush_handles_mixed_levels(self) -> None:
        """Route both warning and error messages to correct logger methods."""
        # Arrange
        buf = DeferredLogBuffer
        logger = Mock()
        buf.capture("warning", "warn msg")
        buf.capture("error", "err msg")

        # Act
        buf.flush(logger)

        # Assert
        logger.warning.assert_called_once_with("warn msg")
        logger.error.assert_called_once_with("err msg")

    def test_flush_clears_messages(self) -> None:
        """Empty the message buffer after flushing."""
        # Arrange
        buf = DeferredLogBuffer
        logger = Mock()
        buf.capture("warning", "temporary")
        buf.capture("error", "also temporary")

        # Act
        buf.flush(logger)

        # Assert
        assert buf._messages == []

    def test_flush_noop_when_empty(self) -> None:
        """Make no logger calls when the buffer is empty."""
        # Arrange
        buf = DeferredLogBuffer
        logger = Mock()

        # Act
        buf.flush(logger)

        # Assert
        logger.warning.assert_not_called()
        logger.error.assert_not_called()


# ── Clear ── #


class TestDeferredLogBufferClear:
    """Test state reset via ``clear()``."""

    def test_clear_removes_messages(self) -> None:
        """Remove all buffered messages."""
        # Arrange
        buf = DeferredLogBuffer
        buf.capture("warning", "msg one")
        buf.capture("error", "msg two")

        # Act
        buf.clear()

        # Assert
        assert buf._messages == []


# ── Thread Safety ── #


class TestDeferredLogBufferThreadSafety:
    """Test concurrent access to the buffer."""

    def test_concurrent_captures(self) -> None:
        """Capture 100 messages from 10 threads without data loss."""
        # Arrange
        buf = DeferredLogBuffer
        messages_per_thread = 10
        thread_count = 10

        def capture_batch(thread_id: int) -> None:
            """Capture a batch of messages for a single thread."""
            for message_index in range(messages_per_thread):
                buf.capture("warning", f"t{thread_id}-m{message_index}")

        # Act
        threads = [
            threading.Thread(target=capture_batch, args=(tid,)) for tid in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Assert
        assert len(buf._messages) == messages_per_thread * thread_count


# ── Flush or Stderr ── #


class TestDeferredLogBufferFlushOrStderr:
    """Test the ``flush_or_stderr()`` dual-path flush method."""

    def test_delegates_to_flush_when_logger_provided(self) -> None:
        """Route messages through ``flush()`` when a logger is available."""
        # Arrange
        buf = DeferredLogBuffer
        logger = Mock()
        buf.capture("warning", "routed warning")
        buf.capture("error", "routed error")

        # Act
        buf.flush_or_stderr(logger)

        # Assert
        logger.warning.assert_called_once_with("routed warning")
        logger.error.assert_called_once_with("routed error")
        assert buf._messages == []

    def test_writes_to_stderr_when_no_logger(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Write messages to stderr when no logger is available."""
        # Arrange
        buf = DeferredLogBuffer
        buf.capture("warning", "fallback warning")
        buf.capture("error", "fallback error")

        # Act
        buf.flush_or_stderr()

        # Assert
        captured = capsys.readouterr()
        assert "[WARNING] fallback warning" in captured.err
        assert "[ERROR] fallback error" in captured.err

    def test_clears_messages_after_stderr_output(self) -> None:
        """Empty the message buffer after writing to stderr."""
        # Arrange
        buf = DeferredLogBuffer
        buf.capture("error", "will be cleared")

        # Act
        buf.flush_or_stderr()

        # Assert
        assert buf._messages == []

    def test_noop_when_empty_and_no_logger(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Produce no stderr output when the buffer is empty."""
        # Arrange
        buf = DeferredLogBuffer

        # Act
        buf.flush_or_stderr()

        # Assert
        captured = capsys.readouterr()
        assert captured.err == ""
