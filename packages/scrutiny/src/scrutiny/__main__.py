"""Entry point for ``python -m scrutiny``."""

from __future__ import annotations

import sys
import traceback

from scrutiny.core.exceptions import ExitCode, SCRError
from scrutiny.main import main

_KEYBOARD_INTERRUPT_EXIT_CODE = 130

# Execute main and translate exceptions to exit codes
try:
    # Normal exit path; main() returns an integer exit code
    sys.exit(main())
except KeyboardInterrupt:
    # User pressed Ctrl+C; exit with the conventional signal code
    print("\nInterrupted.", file=sys.stderr)  # noqa: T201
    sys.exit(_KEYBOARD_INTERRUPT_EXIT_CODE)
except SCRError as unhandled_main_error:
    # SCRError escaped main(); print diagnostics and exit with its code
    print(  # noqa: T201
        f"\n  {unhandled_main_error.display_tag} {unhandled_main_error}"
        f"\n  Error Code: {unhandled_main_error.exit_code}"
        f" ({ExitCode(unhandled_main_error.exit_code).name})\n",
        file=sys.stderr,
    )
    traceback.print_exc(file=sys.stderr)
    sys.exit(unhandled_main_error.exit_code)
