"""File locking utilities with graceful fallback when ``filelock`` is unavailable."""
from __future__ import annotations

import importlib
import importlib.util
import threading

__all__ = ["FileLock", "Timeout", "is_file_locking_available"]


def is_file_locking_available() -> bool:
    """Return ``True`` when the third-party ``filelock`` package is installed."""

    return importlib.util.find_spec("filelock") is not None


if is_file_locking_available():  # pragma: no cover - exercised in production
    _module = importlib.import_module("filelock")
    FileLock = _module.FileLock  # type: ignore[attr-defined]
    Timeout = _module.Timeout  # type: ignore[attr-defined]
else:  # pragma: no cover - covered by unit tests when dependency missing

    class Timeout(RuntimeError):
        """Raised when acquiring the fallback lock exceeds the timeout."""


    class FileLock:
        """In-process lock that mimics :mod:`filelock` for test environments."""

        _locks: dict[str, threading.RLock] = {}
        _registry_lock = threading.Lock()

        def __init__(self, lock_file: str | bytes | "os.PathLike[str]") -> None:
            self.lock_file = str(lock_file)
            self._lock = self._get_lock(self.lock_file)

        @classmethod
        def _get_lock(cls, lock_file: str) -> threading.RLock:
            with cls._registry_lock:
                existing = cls._locks.get(lock_file)
                if existing is None:
                    existing = threading.RLock()
                    cls._locks[lock_file] = existing
                return existing

        def acquire(self, timeout: float | None = None) -> None:
            if timeout is None:
                acquired = self._lock.acquire()
            else:
                if timeout < 0:
                    timeout = 0
                acquired = self._lock.acquire(timeout=timeout)
            if not acquired:
                raise Timeout(f"Timed out waiting for lock {self.lock_file}")

        def release(self) -> None:
            try:
                self._lock.release()
            except RuntimeError as exc:  # pragma: no cover - defensive guard
                raise RuntimeError("Cannot release an unlocked lock") from exc

        def __enter__(self) -> "FileLock":
            self.acquire()
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self.release()

