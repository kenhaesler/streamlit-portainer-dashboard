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

