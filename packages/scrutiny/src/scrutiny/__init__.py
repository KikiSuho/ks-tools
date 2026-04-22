"""
Code quality orchestrator with multi-tool execution and reporting.

Constants
---------
__version__ : Distribution version string sourced from installed metadata.

"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

# Resolve the installed distribution version so users can introspect which
# scrutiny they are running without reading pyproject.toml directly.  When
# the package is imported from a working-tree checkout (not installed via
# pip), ``importlib.metadata`` raises; fall back to a development marker
# so import still succeeds.
try:
    __version__ = version("ks-scrutiny")
except PackageNotFoundError:
    # Running from a development checkout; the installed distribution is
    # absent, so no authoritative version is available.
    __version__ = "0.0.0+dev"


__all__ = ["__version__"]
