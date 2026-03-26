"""
IDE Run-button entry point for scrutiny.

Execute this file directly from any IDE (PyCharm, VS Code, etc.)
to run scrutiny with automatic IDE context detection.

For terminal usage, use: ``python -m scrutiny``
"""

from __future__ import annotations

import sys

from scrutiny.main import main

try:
    sys.exit(main())
except KeyboardInterrupt:
    print("\nInterrupted.", file=sys.stderr)  # noqa: T201
    sys.exit(130)
