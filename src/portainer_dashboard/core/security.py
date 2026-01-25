"""Security utilities for token generation and CSRF protection."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Final

from itsdangerous import BadSignature, URLSafeTimedSerializer

_SECRET_KEY: Final = secrets.token_hex(32)
_CSRF_TOKEN_MAX_AGE: Final = 3600  # 1 hour


def generate_token(length: int = 32) -> str:
    """Generate a cryptographically secure random token."""
    return secrets.token_urlsafe(length)


def _get_serializer() -> URLSafeTimedSerializer:
    """Return a serializer for CSRF tokens."""
    return URLSafeTimedSerializer(_SECRET_KEY, salt="csrf-token")


def generate_csrf_token(session_token: str | None = None) -> str:
    """Generate a CSRF token optionally bound to a session.

    Parameters
    ----------
    session_token
        Optional session identifier to bind the CSRF token to.
        If provided, the CSRF token will only validate for this session.

    Returns
    -------
    str
        A signed CSRF token.
    """
    serializer = _get_serializer()
    data = {
        "ts": time.time(),
        "nonce": secrets.token_hex(8),
    }
    if session_token:
        data["session_hash"] = hashlib.sha256(session_token.encode()).hexdigest()[:16]
    return serializer.dumps(data)


def verify_csrf_token(
    token: str,
    session_token: str | None = None,
    max_age: int = _CSRF_TOKEN_MAX_AGE,
) -> bool:
    """Verify a CSRF token.

    Parameters
    ----------
    token
        The CSRF token to verify.
    session_token
        Optional session identifier the token should be bound to.
    max_age
        Maximum age of the token in seconds.

    Returns
    -------
    bool
        True if the token is valid, False otherwise.
    """
    serializer = _get_serializer()
    try:
        data = serializer.loads(token, max_age=max_age)
    except BadSignature:
        return False

    if not isinstance(data, dict):
        return False

    if session_token:
        expected_hash = hashlib.sha256(session_token.encode()).hexdigest()[:16]
        if data.get("session_hash") != expected_hash:
            return False

    return True


__all__ = [
    "generate_csrf_token",
    "generate_token",
    "verify_csrf_token",
]
