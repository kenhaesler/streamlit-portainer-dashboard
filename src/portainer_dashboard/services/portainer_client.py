"""Async Portainer API client -- backward-compatible re-exports.

This module has been split into:
- portainer_http: Client, pool, error classes
- portainer_normalizers: DataFrame/dict normalisation functions
- portainer_utils: Internal utility functions
"""
from portainer_dashboard.services.portainer_http import *  # noqa: F401,F403
from portainer_dashboard.services.portainer_normalizers import *  # noqa: F401,F403
from portainer_dashboard.services.portainer_utils import *  # noqa: F401,F403

# Preserve existing __all__ for backward compatibility
from portainer_dashboard.services.portainer_http import __all__ as _http_all
from portainer_dashboard.services.portainer_normalizers import __all__ as _norm_all
from portainer_dashboard.services.portainer_utils import __all__ as _util_all

__all__ = [*_http_all, *_norm_all, *_util_all]
