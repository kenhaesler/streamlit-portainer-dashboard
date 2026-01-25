"""Static username/password authentication."""

from __future__ import annotations

import secrets

from portainer_dashboard.config import get_settings


def verify_credentials(username: str, password: str) -> bool:
    """Verify static credentials against configuration.

    Uses constant-time comparison to prevent timing attacks.
    """
    settings = get_settings()
    static_config = settings.static_auth

    if not static_config.username or not static_config.key:
        return False

    username_match = secrets.compare_digest(
        username.encode("utf-8"),
        static_config.username.encode("utf-8"),
    )
    password_match = secrets.compare_digest(
        password.encode("utf-8"),
        static_config.key.encode("utf-8"),
    )

    return username_match and password_match


__all__ = ["verify_credentials"]
