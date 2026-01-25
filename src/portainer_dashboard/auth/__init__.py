"""Authentication module for static and OIDC authentication."""

from portainer_dashboard.auth.dependencies import get_current_user, get_optional_user
from portainer_dashboard.auth.router import router

__all__ = [
    "get_current_user",
    "get_optional_user",
    "router",
]
