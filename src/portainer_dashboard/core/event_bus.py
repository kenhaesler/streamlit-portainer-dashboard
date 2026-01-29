"""Simple async event bus for decoupling services."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

LOGGER = logging.getLogger(__name__)

EventCallback = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """Lightweight async publish/subscribe event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventCallback]] = {}

    def subscribe(self, event_type: str, callback: EventCallback) -> None:
        """Register a callback for an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: EventCallback) -> None:
        """Remove a callback for an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb is not callback
            ]

    async def publish(self, event_type: str, data: Any = None) -> None:
        """Publish an event to all subscribers."""
        callbacks = self._subscribers.get(event_type, [])
        if not callbacks:
            return

        for callback in callbacks:
            try:
                await callback(data)
            except Exception as exc:
                LOGGER.warning(
                    "Event handler error for %s: %s", event_type, exc
                )


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get or create the global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset the event bus (for testing)."""
    global _event_bus
    _event_bus = None


__all__ = [
    "EventBus",
    "get_event_bus",
    "reset_event_bus",
]
