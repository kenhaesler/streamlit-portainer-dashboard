from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


if importlib.util.find_spec("jwt") is None:
    stub_path = Path(__file__).with_name("_jwt_stub.py")
    spec = importlib.util.spec_from_file_location("jwt", stub_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load JWT stub for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules["jwt"] = module
    spec.loader.exec_module(module)

"""Pytest configuration for the dashboard test-suite."""
from __future__ import annotations

import sys

try:  # pragma: no cover - exercised indirectly when dependency is present
    import jwt  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on environment
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from types import ModuleType

    stub_path = Path(__file__).with_name("_jwt_stub.py")
    spec = spec_from_file_location("_jwt_stub", stub_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise
    module = module_from_spec(spec)
    sys.modules.setdefault("_jwt_stub", module)
    spec.loader.exec_module(module)  # type: ignore[arg-type]

    module.__name__ = "jwt"
    module.__package__ = "jwt"

    jwt_module: ModuleType = module
    sys.modules.setdefault("jwt", jwt_module)
    sys.modules.setdefault("jwt.algorithms", jwt_module)
