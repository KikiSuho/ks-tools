"""
IDE Run-button entry point for trellis.

Execute this file directly from any IDE (PyCharm, VS Code, etc.)
to run trellis.

For terminal usage, use: ``python -m trellis``
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from trellis.main import main

KEYBOARD_INTERRUPT_EXIT_CODE = 130

# Attempt to run the main entry point
try:
    sys.exit(main())
except KeyboardInterrupt:
    # User pressed Ctrl+C; exit with standard interrupt status code
    print("\nInterrupted.", file=sys.stderr)  # noqa: T201
    sys.exit(KEYBOARD_INTERRUPT_EXIT_CODE)
