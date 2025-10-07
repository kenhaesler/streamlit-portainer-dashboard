from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


if importlib.util.find_spec("jwt") is None:
    from app._jwt_stub import install_jwt_stub

    install_jwt_stub()

