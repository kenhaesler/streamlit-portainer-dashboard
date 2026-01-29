"""WebSocket per-user connection limiter."""

from __future__ import annotations

import threading

from fastapi import WebSocket


class WebSocketConnectionTracker:
    """Thread-safe per-user WebSocket connection tracker.

    Tracks active connections per username and enforces a configurable
    maximum connections-per-user limit.
    """

    def __init__(self, max_per_user: int = 5) -> None:
        self._max_per_user = max_per_user
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = threading.Lock()

    def can_connect(self, username: str) -> bool:
        """Return True if the user has room for another connection."""
        with self._lock:
            current = self._connections.get(username, set())
            return len(current) < self._max_per_user

    def on_connect(self, username: str, ws: WebSocket) -> None:
        """Register a new connection for the user."""
        with self._lock:
            if username not in self._connections:
                self._connections[username] = set()
            self._connections[username].add(ws)

    def on_disconnect(self, username: str, ws: WebSocket) -> None:
        """Remove a connection for the user."""
        with self._lock:
            if username in self._connections:
                self._connections[username].discard(ws)
                if not self._connections[username]:
                    del self._connections[username]

    def get_connection_count(self, username: str) -> int:
        """Return current connection count for a user."""
        with self._lock:
            return len(self._connections.get(username, set()))


_tracker: WebSocketConnectionTracker | None = None


def get_ws_tracker() -> WebSocketConnectionTracker:
    """Get or create the global WebSocket connection tracker."""
    global _tracker
    if _tracker is None:
        from portainer_dashboard.config import get_settings
        settings = get_settings()
        _tracker = WebSocketConnectionTracker(
            max_per_user=settings.websocket.max_connections_per_user,
        )
    return _tracker


def reset_ws_tracker() -> None:
    """Reset the tracker (for testing)."""
    global _tracker
    _tracker = None


__all__ = [
    "WebSocketConnectionTracker",
    "get_ws_tracker",
    "reset_ws_tracker",
]
