"""Test environment customisations."""
from __future__ import annotations

import importlib.util


def _ensure_jwt_available() -> None:
    if importlib.util.find_spec("jwt") is not None:
        return
    from app._jwt_stub import install_jwt_stub

    install_jwt_stub()


_ensure_jwt_available()

