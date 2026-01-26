"""SQLite connection pool with WAL mode for improved performance.

Provides thread-safe connection pooling for SQLite databases,
with WAL (Write-Ahead Logging) mode for better concurrent access.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOGGER = logging.getLogger(__name__)

# Default pool settings
_DEFAULT_POOL_SIZE = 5
_DEFAULT_TIMEOUT = 30.0


class SQLiteConnectionPool:
    """Thread-safe SQLite connection pool with WAL mode.

    Features:
    - Thread-local connections for safe concurrent access
    - WAL mode for better read/write concurrency
    - Automatic connection cleanup on thread exit
    - Connection reuse to avoid repeated open/close overhead
    """

    def __init__(
        self,
        database_path: Path | str,
        *,
        pool_size: int = _DEFAULT_POOL_SIZE,
        timeout: float = _DEFAULT_TIMEOUT,
        check_same_thread: bool = False,
    ) -> None:
        """Initialize the connection pool.

        Args:
            database_path: Path to the SQLite database file.
            pool_size: Maximum number of connections (not enforced, for documentation).
            timeout: Default timeout for acquiring locks.
            check_same_thread: If False, allows connections to be used across threads.
        """
        self._database_path = Path(database_path)
        self._pool_size = pool_size
        self._timeout = timeout
        self._check_same_thread = check_same_thread
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False

        # Initialize database on first use
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Initialize the database with WAL mode if not already done."""
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            # Ensure directory exists
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            # Configure database with WAL mode
            conn = sqlite3.connect(
                self._database_path,
                timeout=self._timeout,
                check_same_thread=self._check_same_thread,
            )
            try:
                # Enable WAL mode for better concurrent access
                conn.execute("PRAGMA journal_mode=WAL")
                # Use NORMAL synchronous mode (faster than FULL, still safe with WAL)
                conn.execute("PRAGMA synchronous=NORMAL")
                # Increase cache size for better performance (negative = KB)
                conn.execute("PRAGMA cache_size=-8000")  # 8MB cache
                # Enable memory-mapped I/O for faster reads
                conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
                conn.commit()
                LOGGER.debug(
                    "SQLite database initialized with WAL mode: %s",
                    self._database_path,
                )
            finally:
                conn.close()

            self._initialized = True

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimal settings."""
        conn = sqlite3.connect(
            self._database_path,
            timeout=self._timeout,
            check_same_thread=self._check_same_thread,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row

        # Per-connection optimizations
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")

        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Get a connection for the current thread.

        Returns a thread-local connection, creating one if necessary.
        This connection should NOT be closed manually - it will be
        reused for subsequent calls from the same thread.
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = self._create_connection()
            LOGGER.debug(
                "Created new SQLite connection for thread %s",
                threading.current_thread().name,
            )
        return self._local.connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for getting a pooled connection.

        Usage:
            with pool.connection() as conn:
                conn.execute("SELECT ...")

        The connection is NOT closed after the context - it's returned
        to the thread-local pool for reuse.
        """
        conn = self.get_connection()
        try:
            yield conn
        except Exception:
            # Rollback on error
            conn.rollback()
            raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager for a transaction with automatic commit/rollback.

        Usage:
            with pool.transaction() as conn:
                conn.execute("INSERT ...")
                conn.execute("UPDATE ...")
            # Automatically commits on success, rolls back on exception
        """
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close_thread_connection(self) -> None:
        """Close the connection for the current thread.

        Call this when a thread is done with database operations.
        """
        if hasattr(self._local, "connection") and self._local.connection is not None:
            try:
                self._local.connection.close()
            except Exception as exc:
                LOGGER.warning("Error closing thread connection: %s", exc)
            finally:
                self._local.connection = None

    def close_all(self) -> None:
        """Close the current thread's connection.

        Note: Due to thread-local storage, this only closes the
        calling thread's connection. Other threads must call
        close_thread_connection() themselves.
        """
        self.close_thread_connection()


# Global pool registry for shared access
_pools: dict[str, SQLiteConnectionPool] = {}
_pools_lock = threading.Lock()


def get_pool(database_path: Path | str) -> SQLiteConnectionPool:
    """Get or create a connection pool for the given database path.

    This allows multiple modules to share the same pool for a database.
    """
    path_str = str(Path(database_path).resolve())

    with _pools_lock:
        if path_str not in _pools:
            _pools[path_str] = SQLiteConnectionPool(database_path)
        return _pools[path_str]


def close_all_pools() -> None:
    """Close all connection pools. Call during application shutdown."""
    with _pools_lock:
        for path, pool in _pools.items():
            try:
                pool.close_all()
                LOGGER.debug("Closed pool for %s", path)
            except Exception as exc:
                LOGGER.warning("Error closing pool for %s: %s", path, exc)
        _pools.clear()


__all__ = [
    "SQLiteConnectionPool",
    "close_all_pools",
    "get_pool",
]
