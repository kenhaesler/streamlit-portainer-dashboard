"""Scheduler module for periodic background tasks."""

from portainer_dashboard.scheduler.setup import (
    create_scheduler,
    get_scheduler,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    "create_scheduler",
    "get_scheduler",
    "shutdown_scheduler",
    "start_scheduler",
]
