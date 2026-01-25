"""OIDC authentication via authlib."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebToken, JWTClaims
from authlib.jose.errors import JoseError

from portainer_dashboard.config import OIDCSettings, get_settings

LOGGER = logging.getLogger(__name__)


class OIDCError(Exception):
    """Raised when OIDC authentication fails."""


@dataclass
class OIDCUserInfo:
    """User information extracted from OIDC tokens."""

    subject: str
    username: str
    email: str | None = None
    name: str | None = None


class OIDCClient:
    """OIDC authentication client using authlib."""

    def __init__(self, settings: OIDCSettings | None = None) -> None:
        if settings is None:
            settings = get_settings().oidc
        self.settings = settings
        self._discovery_doc: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    async def _fetch_discovery_document(self) -> dict[str, Any]:
        """Fetch and cache the OIDC discovery document."""
        if self._discovery_doc is not None:
            return self._discovery_doc

        async with httpx.AsyncClient() as client:
            response = await client.get(self.settings.well_known_url)
            response.raise_for_status()
            self._discovery_doc = response.json()
            return self._discovery_doc

    async def _fetch_jwks(self) -> dict[str, Any]:
        """Fetch and cache the JWKS for token verification."""
        if self._jwks is not None:
            return self._jwks

        discovery = await self._fetch_discovery_document()
        jwks_uri = discovery.get("jwks_uri")
        if not jwks_uri:
            raise OIDCError("JWKS URI not found in discovery document")

        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_uri)
            response.raise_for_status()
            self._jwks = response.json()
            return self._jwks

    async def get_authorization_url(self, state: str, code_verifier: str) -> str:
        """Generate the authorization URL for the OIDC flow."""
        discovery = await self._fetch_discovery_document()
        auth_endpoint = discovery.get("authorization_endpoint")
        if not auth_endpoint:
            raise OIDCError("Authorization endpoint not found in discovery document")

        # Create PKCE code challenge
        import hashlib
        import base64

        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode().rstrip("=")

        client = AsyncOAuth2Client(
            client_id=self.settings.client_id,
            client_secret=self.settings.client_secret,
            redirect_uri=self.settings.redirect_uri,
        )

        url, _ = client.create_authorization_url(
            auth_endpoint,
            state=state,
            scope=" ".join(self.settings.scope_list),
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )

        return url

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
    ) -> tuple[str, str | None]:
        """Exchange authorization code for tokens.

        Returns
        -------
        tuple[str, str | None]
            ID token and optional access token.
        """
        discovery = await self._fetch_discovery_document()
        token_endpoint = discovery.get("token_endpoint")
        if not token_endpoint:
            raise OIDCError("Token endpoint not found in discovery document")

        client = AsyncOAuth2Client(
            client_id=self.settings.client_id,
            client_secret=self.settings.client_secret,
            redirect_uri=self.settings.redirect_uri,
        )

        token = await client.fetch_token(
            token_endpoint,
            code=code,
            code_verifier=code_verifier,
        )

        id_token = token.get("id_token")
        access_token = token.get("access_token")

        if not id_token:
            raise OIDCError("ID token not returned from token endpoint")

        return id_token, access_token

    async def verify_id_token(self, id_token: str) -> OIDCUserInfo:
        """Verify the ID token and extract user information."""
        jwks = await self._fetch_jwks()
        discovery = await self._fetch_discovery_document()

        jwt = JsonWebToken(["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"])

        try:
            claims = jwt.decode(
                id_token,
                jwks,
                claims_options={
                    "iss": {"essential": True, "value": self.settings.issuer},
                    "aud": {"essential": True, "value": self.settings.client_id},
                },
            )
            claims.validate()
        except JoseError as e:
            raise OIDCError(f"Failed to verify ID token: {e}") from e

        # Check audience if configured
        if self.settings.audience:
            aud = claims.get("aud")
            if isinstance(aud, list):
                if self.settings.audience not in aud:
                    raise OIDCError("Token audience mismatch")
            elif aud != self.settings.audience:
                raise OIDCError("Token audience mismatch")

        subject = claims.get("sub")
        if not subject:
            raise OIDCError("Subject claim missing from ID token")

        # Extract username with fallback
        username = (
            claims.get("preferred_username")
            or claims.get("email")
            or claims.get("name")
            or subject
        )

        return OIDCUserInfo(
            subject=subject,
            username=username,
            email=claims.get("email"),
            name=claims.get("name"),
        )


def create_oidc_client() -> OIDCClient:
    """Create an OIDC client with current settings."""
    return OIDCClient()


__all__ = [
    "OIDCClient",
    "OIDCError",
    "OIDCUserInfo",
    "create_oidc_client",
]
