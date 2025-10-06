"""Application package for the Streamlit Portainer dashboard."""
from __future__ import annotations

from .logging_setup import configure_logging

configure_logging()

__all__ = ["configure_logging"]

