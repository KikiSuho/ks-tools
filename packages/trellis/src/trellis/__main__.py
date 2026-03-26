"""Allow running the package as ``python -m trellis``."""

from __future__ import annotations

from trellis.main import main

# Exit with the status code returned by main()
raise SystemExit(main())
