"""
Demo script for change detection output.

Generate a temporary Python project, scan it twice with code changes in
between, then print the change summary. The temp directory is cleaned up
automatically when the script exits. To experiment, change settings in
``trellis/config.py`` and re-run; the demo reads
``Config`` directly with no CLI flags needed.

Relevant Config settings: ``SHOW_DECORATORS``, ``SHOW_PRIVATE``,
``SHOW_DUNDER``, ``SHOW_MANGLED``, ``SHOW_TYPES``, ``CALL_FLOW_MODE``,
``MAX_LINE_WIDTH``.

The demo covers API changes (short, medium, and very long signatures),
class inheritance changes, new and removed API, new and removed modules,
non-Python files, decorator rendering, call flow, wrapper collapse,
private/dunder/mangled members, nested classes, multiple inheritance,
keyword-only params, ``**kwargs``, and directory tags.

Constants
---------
EXIT_SUCCESS : Exit code for successful execution.
EXIT_FAILURE : Exit code when v2 changes were not detected.
SEPARATOR_WIDTH : Character width for section separator banners.

Functions
---------
main : Run the three-step demo (v1 scan, v2 scan, no-change rescan).

Examples
--------
::

    python scripts/demo_trellis.py

"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
SEPARATOR_WIDTH = 70


def _build_v1(root: Path) -> None:
    """Write version 1 of the demo project."""
    package_dir = root / "demo_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")

    # app.py; orchestration entry point with call flow
    (package_dir / "app.py").write_text(
        '''\
"""Application entry point with orchestration."""

from demo_pkg.core import process_data, validate
from demo_pkg.db.connection import create_engine


def main() -> int:
    """Run the application pipeline."""
    engine = create_engine("sqlite", "localhost", 5432, "mydb", "user", "pass")
    data = process_data("input.csv", 100, 0, False)
    validate(data)
    return 0
''',
        encoding="utf-8",
    )

    (package_dir / "core.py").write_text(
        '''\
"""Core module."""


class Config:
    """Application configuration."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    @property
    def address(self) -> str:
        """Full host:port address."""
        return f"{self.host}:{self.port}"

    def _resolve_host(self) -> str:
        """Private: resolve hostname to IP."""
        return self.host

    def __repr__(self) -> str:
        return f"Config({self.host!r}, {self.port!r})"


def process_data(
    source: str, limit: int, offset: int, reverse: bool,
) -> list:
    """Process data from source."""
    return []


def validate(data: dict) -> bool:
    """Validate input data."""
    return True


def old_helper(x: int, y: int) -> str:
    """Helper that will be removed in v2."""
    return str(x + y)


def deprecated_loader(path: str) -> dict:
    """Old loader being replaced."""
    return {}
''',
        encoding="utf-8",
    )

    (package_dir / "utils.py").write_text(
        '''\
"""Utility functions."""

import functools


def format_output(items: list, separator: str) -> str:
    """Format a list of items."""
    return separator.join(str(i) for i in items)


def merge_dicts(base: dict, override: dict) -> dict:
    """Merge two dictionaries."""
    return {**base, **override}


def cached_lookup(func):
    """Cache decorator for expensive lookups."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
''',
        encoding="utf-8",
    )

    # Add __main__.py and py.typed for [cmd] and [typed] tags.
    (package_dir / "__main__.py").write_text(
        "from demo_pkg.app import main\nraise SystemExit(main())\n",
        encoding="utf-8",
    )
    (package_dir / "py.typed").write_text("", encoding="utf-8")

    # models.py; nested class, name-mangled, multiple inheritance, **kwargs
    (package_dir / "models.py").write_text(
        '''\
"""Data models with advanced Python patterns."""

from typing import Any


class Serializable:
    """Mixin for JSON serialization."""

    def to_dict(self) -> dict:
        return vars(self)


class Validatable:
    """Mixin for field validation."""

    def is_valid(self) -> bool:
        return True


class User(Serializable, Validatable):
    """User model with nested Address and advanced patterns."""

    def __init__(self, name: str, *, email: str, **extra: Any) -> None:
        self.name = name
        self.email = email
        self.extra = extra

    def __secret_token(self) -> str:
        """Name-mangled: only visible with SHOW_MANGLED."""
        return "token"

    class Address:
        """Nested class for user addresses."""

        def __init__(self, street: str, city: str) -> None:
            self.street = street
            self.city = city

        def format(self) -> str:
            return f"{self.street}, {self.city}"
''',
        encoding="utf-8",
    )

    # A file in a sub-package to test nested paths.
    database_dir = package_dir / "db"
    database_dir.mkdir()
    (database_dir / "__init__.py").write_text("", encoding="utf-8")

    (database_dir / "connection.py").write_text(
        '''\
"""Database connection management."""


class ConnectionPool:
    """Manage a pool of database connections."""

    def acquire(self) -> object:
        """Acquire a connection from the pool."""
        return object()

    def release(self, conn: object) -> None:
        """Release a connection back to the pool."""
        pass


def create_engine(
    dialect: str, host: str, port: int, database: str,
    username: str, password: str,
) -> object:
    """Create a database engine."""
    return object()
''',
        encoding="utf-8",
    )

    # A non-Python file that will be removed.
    (package_dir / "legacy_notes.txt").write_text("old notes\n", encoding="utf-8")

    # A module that will be entirely deleted.
    (package_dir / "compat.py").write_text(
        '''\
"""Compatibility shims for old API."""


def legacy_transform(data: list) -> list:
    """Old transform function."""
    return data


def legacy_validate(schema: str, payload: dict) -> bool:
    """Old validation function."""
    return True
''',
        encoding="utf-8",
    )


def _build_v2(root: Path) -> None:
    """Write version 2; simulate a full range of code changes."""
    package_dir = root / "demo_pkg"

    # === app.py: updated orchestration with more calls ===
    (package_dir / "app.py").write_text(
        '''\
"""Application entry point with orchestration — v2."""

from demo_pkg.core import configure_pipeline, process_data, validate
from demo_pkg.db.connection import create_engine
from demo_pkg.handlers import RequestHandler


def main() -> int:
    """Run the application pipeline."""
    engine = create_engine("sqlite", "localhost", 5432, "mydb", "user", "pass")
    configure_pipeline("localhost", 5432, 30.0, 3, 1.5, True)
    handler = RequestHandler()
    data = process_data("input.csv", 100, 0, False, 50, False)
    validate(data, strict=True)
    handler.handle({"method": "GET"})
    return 0
''',
        encoding="utf-8",
    )

    # === models.py: User gains a keyword-only param change ===
    (package_dir / "models.py").write_text(
        '''\
"""Data models with advanced Python patterns — v2."""

from typing import Any, Optional


class Serializable:
    """Mixin for JSON serialization."""

    def to_dict(self) -> dict:
        return vars(self)


class Validatable:
    """Mixin for field validation."""

    def is_valid(self) -> bool:
        return True


class User(Serializable, Validatable):
    """User model with nested Address and advanced patterns."""

    def __init__(self, name: str, *, email: str, role: str = "user", **extra: Any) -> None:
        self.name = name
        self.email = email
        self.role = role
        self.extra = extra

    def __secret_token(self) -> str:
        """Name-mangled: only visible with SHOW_MANGLED."""
        return "token"

    def avatar_url(self, size: Optional[int] = None) -> str:
        """Get avatar URL. NEW in v2."""
        return f"/avatars/{self.name}"

    class Address:
        """Nested class for user addresses."""

        def __init__(self, street: str, city: str, zip_code: str = "") -> None:
            self.street = street
            self.city = city
            self.zip_code = zip_code

        def format(self) -> str:
            return f"{self.street}, {self.city}"
''',
        encoding="utf-8",
    )

    # === core.py: multiple signature changes + removals + additions ===
    (package_dir / "core.py").write_text(
        '''\
"""Core module — v2 with expanded API."""

from typing import Optional


class BaseConfig:
    """Base class for configuration. NEW in v2."""

    pass


class Config(BaseConfig):
    """Application configuration with extended options."""

    def __init__(
        self, host: str, port: int, timeout: float = 30.0,
        max_retries: int = 3, ssl_enabled: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.ssl_enabled = ssl_enabled

    @property
    def address(self) -> str:
        """Full host:port address."""
        return f"{self.host}:{self.port}"

    def _resolve_host(self) -> str:
        """Private: resolve hostname to IP."""
        return self.host

    def __repr__(self) -> str:
        return f"Config({self.host!r}, {self.port!r})"

    @staticmethod
    def from_env() -> "Config":
        """Create Config from environment variables. NEW in v2."""
        return Config("localhost", 8080)


def process_data(
    source: str, limit: int, offset: int, reverse: bool,
    batch_size: int, dry_run: bool,
) -> list:
    """Process data from source with batching support."""
    return []


def validate(data: dict, strict: bool = False) -> bool:
    """Validate input data with optional strict mode."""
    return True


def configure_pipeline(
    host: str, port: int, timeout: float, retries: int,
    backoff: float, verbose: bool,
) -> Optional[bool]:
    """Configure the processing pipeline. NEW in v2."""
    return None


def initialize_system(
    config_path: str,
    environment: str,
    log_level: str,
    enable_metrics: bool,
    metrics_endpoint: str,
    cache_backend: str,
    cache_ttl: int,
    worker_count: int,
    graceful_shutdown_timeout: float,
) -> dict:
    """Initialize the entire system with full configuration.

    This function has a very long signature that should trigger
    multi-line wrapping in the change summary.
    """
    return {}
''',
        encoding="utf-8",
    )

    # === utils.py: short change + addition ===
    (package_dir / "utils.py").write_text(
        '''\
"""Utility functions — v2."""

from pathlib import Path
from typing import Optional


def format_output(items: list, separator: str, max_items: Optional[int] = None) -> str:
    """Format a list of items with optional truncation."""
    if max_items is not None:
        items = items[:max_items]
    return separator.join(str(i) for i in items)


def merge_dicts(base: dict, override: dict) -> dict:
    """Merge two dictionaries."""
    return {**base, **override}


def resolve_path(base: str, relative: str) -> Path:
    """Resolve a relative path against a base directory. NEW in v2."""
    return Path(base) / relative


def compute_checksum(data: bytes, algorithm: str = "sha256") -> str:
    """Compute a checksum for binary data. NEW in v2."""
    import hashlib
    return hashlib.new(algorithm, data).hexdigest()
''',
        encoding="utf-8",
    )

    # === handlers.py: brand new file with classes ===
    (package_dir / "handlers.py").write_text(
        '''\
"""Request handlers — NEW in v2."""

from typing import Optional


class BaseHandler:
    """Abstract base for request handling."""

    def before_handle(self, request: dict) -> None:
        """Pre-processing hook."""
        pass

    def after_handle(self, request: dict, response: dict) -> None:
        """Post-processing hook."""
        pass


class RequestHandler(BaseHandler):
    """Handle incoming HTTP requests."""

    def handle(self, request: dict) -> dict:
        """Process a single request."""
        return {}

    def batch_handle(self, requests: list) -> list:
        """Process multiple requests in sequence."""
        return [self.handle(r) for r in requests]


class WebSocketHandler(BaseHandler):
    """Handle WebSocket connections."""

    def on_connect(self, client_id: str, headers: dict) -> bool:
        """Handle new WebSocket connection."""
        return True

    def on_message(
        self, client_id: str, message: bytes,
        compression: Optional[str] = None,
    ) -> Optional[bytes]:
        """Handle incoming WebSocket message."""
        return None

    def on_disconnect(self, client_id: str, code: int) -> None:
        """Handle WebSocket disconnection."""
        pass
''',
        encoding="utf-8",
    )

    # === db/connection.py: signature change on create_engine (very long) ===
    database_dir = package_dir / "db"
    (database_dir / "connection.py").write_text(
        '''\
"""Database connection management — v2 with async support."""

from typing import Optional


class ConnectionPool:
    """Manage a pool of database connections."""

    def acquire(self, timeout: Optional[float] = None) -> object:
        """Acquire a connection from the pool with optional timeout."""
        return object()

    def release(self, conn: object) -> None:
        """Release a connection back to the pool."""
        pass


async def create_engine(
    dialect: str, host: str, port: int, database: str,
    username: str, password: str,
    pool_size: int = 5, max_overflow: int = 10,
    pool_timeout: float = 30.0, echo: bool = False,
    ssl_context: Optional[object] = None,
) -> object:
    """Create a database engine with connection pooling.

    Signature grew significantly — should wrap across multiple lines.
    Also changed from sync to async.
    """
    return object()
''',
        encoding="utf-8",
    )

    # === db/migrations.py: new file in existing sub-package ===
    (database_dir / "migrations.py").write_text(
        '''\
"""Database migration utilities — NEW in v2."""


class Migration:
    """Represents a single database migration."""

    def __init__(self, version: str, description: str) -> None:
        self.version = version
        self.description = description

    def up(self) -> None:
        """Apply the migration."""
        pass

    def down(self) -> None:
        """Revert the migration."""
        pass


def run_migrations(
    connection: object, target_version: str, dry_run: bool = False,
) -> list:
    """Run all pending migrations up to target version."""
    return []
''',
        encoding="utf-8",
    )

    # === middleware/ : brand new package ===
    middleware_dir = package_dir / "middleware"
    middleware_dir.mkdir()
    (middleware_dir / "__init__.py").write_text("", encoding="utf-8")

    (middleware_dir / "auth.py").write_text(
        '''\
"""Authentication middleware — NEW in v2."""

from typing import Optional


class AuthMiddleware:
    """JWT-based authentication middleware."""

    def __init__(self, secret_key: str, algorithm: str = "HS256") -> None:
        self.secret_key = secret_key
        self.algorithm = algorithm

    def authenticate(self, token: str) -> Optional[dict]:
        """Validate a JWT token and return the payload."""
        return None
''',
        encoding="utf-8",
    )

    (middleware_dir / "logging.py").write_text(
        '''\
"""Request logging middleware — NEW in v2."""


class LoggingMiddleware:
    """Log all incoming requests and outgoing responses."""

    def log_request(self, method: str, path: str, headers: dict) -> None:
        """Log an incoming request."""
        pass

    def log_response(self, status_code: int, body_size: int) -> None:
        """Log an outgoing response."""
        pass
''',
        encoding="utf-8",
    )

    # === Delete compat.py (entire module removed) ===
    (package_dir / "compat.py").unlink()

    # === Delete legacy_notes.txt (non-Python file removed) ===
    (package_dir / "legacy_notes.txt").unlink()

    # === Add a non-Python file ===
    (package_dir / "schema.json").write_text('{"type": "object"}\n', encoding="utf-8")


def _print_structure_file(result_path: str) -> None:
    """Print the contents of a structure file with a header."""
    content = Path(result_path).read_text(encoding="utf-8")
    # Show tree content only (strip tr_meta footer for readability).
    lines = content.splitlines()
    tree_lines = []
    # Collect lines until we hit the metadata footer marker
    for line in lines:
        # Stop collecting when the metadata footer begins
        if line.startswith("# tr_meta:"):
            break
        # Append each line from the tree structure
        tree_lines.append(line)
    print("\n".join(tree_lines).rstrip())  # noqa: T201


def _describe_active_settings() -> str:
    """Build a human-readable summary of active Config settings."""
    from trellis.config import CallFlowMode, Config

    parts = []
    # Append each non-default visibility setting to the description
    if Config.SHOW_DECORATORS:
        parts.append("decorators")
    if Config.SHOW_PRIVATE:
        parts.append("private")
    if Config.SHOW_MANGLED:
        parts.append("mangled")
    if Config.SHOW_DUNDER:
        parts.append("dunder")
    if not Config.SHOW_TYPES:
        parts.append("types=OFF")
    if Config.CALL_FLOW_MODE != CallFlowMode.OFF:
        parts.append(f"call_flow={Config.CALL_FLOW_MODE.value}")
    return ", ".join(parts) if parts else "defaults only"


def main() -> int:
    """
    Run the three-step demo (v1 scan, v2 scan, no-change rescan).

    Reads all settings directly from ``Config``. To experiment,
    edit the class attributes in ``trellis/config.py``
    and re-run::

        python -m trellis.demo_run

    Returns
    -------
    int
        Exit code: 0 on success, 1 if v2 changes were not detected.

    """
    from trellis.config import Config
    from trellis.main import DirectoryStructure

    tmp_dir = tempfile.mkdtemp(prefix="tr_demo_")
    project_root = Path(tmp_dir) / "demo_project"
    project_root.mkdir()

    # Run the full demo inside a try/finally to guarantee temp cleanup
    try:
        # Keep output inside the temp dir so it doesn't pollute the real project
        Config.OUTPUT_DIR = "../src/trellis/output"
        Config.LOG_DIR = "output/logs"

        def _scan(root_path: Path) -> DirectoryStructure:
            """Build a scanner from current Config and scan."""
            scanner = DirectoryStructure(
                str(root_path),
                show_private=Config.SHOW_PRIVATE,
                show_mangled=Config.SHOW_MANGLED,
                show_dunder=Config.SHOW_DUNDER,
                show_types=Config.SHOW_TYPES,
                show_decorators=Config.SHOW_DECORATORS,
                call_flow_mode=Config.CALL_FLOW_MODE,
            )
            scanner.scan_directory(str(root_path))
            return scanner

        features = _describe_active_settings()

        # Step 1: build v1 project and perform initial scan
        print("=" * SEPARATOR_WIDTH)  # noqa: T201
        print("Step 1: Building v1 and scanning")  # noqa: T201
        print(f"        Active: {features}")  # noqa: T201
        print("=" * SEPARATOR_WIDTH)  # noqa: T201
        _build_v1(project_root)

        scanner_v1 = _scan(project_root)
        result_v1 = scanner_v1.save_structure()

        print()  # noqa: T201
        _print_structure_file(result_v1.output_path)
        print()  # noqa: T201

        # Step 2: apply v2 changes and re-scan to show change detection
        print()  # noqa: T201
        print("=" * SEPARATOR_WIDTH)  # noqa: T201
        print("Step 2: Applying v2 changes and re-scanning")  # noqa: T201
        print("=" * SEPARATOR_WIDTH)  # noqa: T201
        _build_v2(project_root)

        scanner_v2 = _scan(project_root)
        result_v2 = scanner_v2.save_structure()

        # Bail out if change detection failed to find expected differences
        if result_v2.changes is None:
            print("No changes detected (unexpected).")  # noqa: T201
            return EXIT_FAILURE

        from trellis.output.console import format_change_summary

        print()  # noqa: T201
        output = format_change_summary(
            result_v2.changes,
            "demo_project",
            "",
            Config.MAX_LINE_WIDTH,
        )
        print(output)  # noqa: T201

        # Step 3: identical re-scan to confirm no false positives
        print()  # noqa: T201
        print("=" * SEPARATOR_WIDTH)  # noqa: T201
        print("Step 3: Re-scanning without changes")  # noqa: T201
        print("=" * SEPARATOR_WIDTH)  # noqa: T201

        scanner_v3 = _scan(project_root)
        result_v3 = scanner_v3.save_structure()

        # Report any spurious changes or confirm stability
        if result_v3.changes is not None:
            # Unexpected changes found; display them for debugging
            output_v3 = format_change_summary(
                result_v3.changes,
                "demo_project",
                "",
                Config.MAX_LINE_WIDTH,
            )
            print(f"\n{output_v3}")  # noqa: T201
        else:
            # Confirm that the identical rescan produced no diff
            print("\nNo structure changes detected.")  # noqa: T201

        return EXIT_SUCCESS

    finally:
        # Clean up temporary directory regardless of success or failure
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
