"""
Platform-specific data and behavior for scrutiny.

This package is the single gate for all platform-dependent logic.
Callers import from ``scrutiny.platforms`` only; never from a specific
OS module. The correct module is selected at import time based on
``sys.platform``.
"""

from __future__ import annotations

import sys

# Select the platform module matching the current OS
if sys.platform == "win32":
    # Windows platform bindings
    from scrutiny.platforms.windows import *  # noqa: F401, F403
elif sys.platform == "darwin":
    # macOS platform bindings
    from scrutiny.platforms.macos import *  # noqa: F401, F403
else:
    # Linux and other POSIX platform bindings
    from scrutiny.platforms.linux import *  # noqa: F401, F403
