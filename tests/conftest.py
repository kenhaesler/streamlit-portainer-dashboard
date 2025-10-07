"""Pytest configuration for the dashboard test-suite."""

from __future__ import annotations

"""Pytest configuration for the dashboard test-suite."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_jwt_stub() -> ModuleType:
    """Load the lightweight JWT stub used during tests.

    The production dependency is optional, so when it is not installed we load
    a local shim that exposes the minimal surface required by the test suite.
    """

if importlib.util.find_spec("jwt") is None:
    stub_path = Path(__file__).with_name("_jwt_stub.py")
    spec = importlib.util.spec_from_file_location("jwt", stub_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("Unable to load JWT stub for tests")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

try:  # pragma: no cover - exercised indirectly when dependency is present
    import jwt  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on environment
    from importlib.util import module_from_spec, spec_from_file_location

    stub_path = Path(__file__).with_name("_jwt_stub.py")
    spec = spec_from_file_location("_jwt_stub", stub_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise
    module = module_from_spec(spec)
    sys.modules.setdefault("_jwt_stub", module)
    spec.loader.exec_module(module)  # type: ignore[arg-type]

    module.__name__ = "jwt"
    module.__package__ = "jwt"
    return module


if importlib.util.find_spec("jwt") is None:  # pragma: no cover - depends on env
    jwt_module = _load_jwt_stub()
    sys.modules.setdefault("jwt", jwt_module)
    sys.modules.setdefault("jwt.algorithms", jwt_module)
