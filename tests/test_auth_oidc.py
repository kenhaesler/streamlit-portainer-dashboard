"""Tests covering the OIDC helpers in :mod:`app.auth`."""
from __future__ import annotations

import base64
import time

import pytest
import jwt

from app import auth


def _clear_oidc_caches() -> None:
    """Reset cached network lookups between tests."""

    auth._load_oidc_provider_metadata.cache_clear()
    auth._fetch_oidc_jwks.cache_clear()


def test_build_well_known_url_handles_trailing_slashes() -> None:
    assert (
        auth._build_well_known_url("https://issuer.example.com/")
        == "https://issuer.example.com/.well-known/openid-configuration"
    )


def test_get_oidc_settings_requires_mandatory_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        auth.OIDC_ISSUER_ENV_VAR,
        auth.OIDC_CLIENT_ID_ENV_VAR,
        auth.OIDC_REDIRECT_URI_ENV_VAR,
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ValueError):
        auth._get_oidc_settings()


def test_get_oidc_settings_injects_openid_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(auth.OIDC_ISSUER_ENV_VAR, "https://issuer.example.com")
    monkeypatch.setenv(auth.OIDC_CLIENT_ID_ENV_VAR, "client-id")
    monkeypatch.setenv(auth.OIDC_REDIRECT_URI_ENV_VAR, "https://app.example.com/callback")
    monkeypatch.setenv(auth.OIDC_SCOPES_ENV_VAR, "profile email")

    settings = auth._get_oidc_settings()

    assert settings.scopes[0] == "openid"
    assert "profile" in settings.scopes
    assert "email" in settings.scopes


def test_verify_id_token_uses_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_oidc_caches()

    settings = auth._OIDCSettings(
        issuer="https://issuer.example.com",
        client_id="client-id",
        client_secret=None,
        redirect_uri="https://app.example.com/callback",
        scopes=("openid",),
        audience=None,
        discovery_url="https://issuer.example.com/.well-known/openid-configuration",
    )

    metadata = auth._OIDCProviderMetadata(
        issuer="https://issuer.example.com",
        authorization_endpoint="https://issuer.example.com/auth",
        token_endpoint="https://issuer.example.com/token",
        jwks_uri="https://issuer.example.com/jwks",
        end_session_endpoint=None,
    )

    monkeypatch.setattr(auth, "_load_oidc_provider_metadata", lambda _: metadata)

    jwk = {
        "kid": "kid-1",
        "kty": "oct",
        "k": base64.urlsafe_b64encode(b"super-secret").rstrip(b"=").decode("ascii"),
        "alg": "HS256",
    }
    monkeypatch.setattr(auth, "_fetch_oidc_jwks", lambda _: {"keys": [jwk]})

    now = int(time.time())
    id_token = jwt.encode(
        {
            "sub": "user-123",
            "iss": "https://issuer.example.com",
            "aud": "client-id",
            "exp": now + 300,
            "iat": now,
        },
        "super-secret",
        algorithm="HS256",
        headers={"kid": "kid-1"},
    )

    claims = auth._verify_id_token(settings, id_token)

    assert claims["sub"] == "user-123"

