"""Initialise the Streamlit Portainer dashboard package."""
from __future__ import annotations

from .logging_config import setup_logging as _setup_logging

_setup_logging()

__all__: list[str] = []
