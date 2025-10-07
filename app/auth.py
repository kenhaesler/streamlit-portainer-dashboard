"""Authentication utilities for the Streamlit dashboard."""
from __future__ import annotations

import base64
import hashlib
import html
import importlib
import importlib.util
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from secrets import token_urlsafe
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

try:
    _jwt_spec = importlib.util.find_spec("jwt")
except ValueError:  # pragma: no cover - occurs with dynamically installed stubs
    _jwt_spec = None
if _jwt_spec is not None:  # pragma: no cover - exercised in production
    jwt = importlib.import_module("jwt")
    JWTError = getattr(jwt, "InvalidTokenError")
else:  # pragma: no cover - covered when dependency missing
    jwt = None  # type: ignore[assignment]

    class JWTError(Exception):
        """Raised when token validation is attempted without PyJWT installed."""


def _require_jwt():
    """Return the PyJWT module or raise a helpful error when unavailable."""

    if jwt is None:
        raise RuntimeError(
            "PyJWT is required for authentication features. Install the 'PyJWT' package to enable token validation."
        )
    return jwt

USERNAME_ENV_VAR = "DASHBOARD_USERNAME"
KEY_ENV_VAR = "DASHBOARD_KEY"
SESSION_TIMEOUT_ENV_VAR = "DASHBOARD_SESSION_TIMEOUT_MINUTES"
AUTH_PROVIDER_ENV_VAR = "DASHBOARD_AUTH_PROVIDER"
OIDC_ISSUER_ENV_VAR = "DASHBOARD_OIDC_ISSUER"
OIDC_CLIENT_ID_ENV_VAR = "DASHBOARD_OIDC_CLIENT_ID"
OIDC_CLIENT_SECRET_ENV_VAR = "DASHBOARD_OIDC_CLIENT_SECRET"
OIDC_REDIRECT_URI_ENV_VAR = "DASHBOARD_OIDC_REDIRECT_URI"
OIDC_SCOPES_ENV_VAR = "DASHBOARD_OIDC_SCOPES"
OIDC_DISCOVERY_URL_ENV_VAR = "DASHBOARD_OIDC_DISCOVERY_URL"
OIDC_AUDIENCE_ENV_VAR = "DASHBOARD_OIDC_AUDIENCE"
SESSION_COOKIE_NAME = "dashboard_session_token"
DEFAULT_SESSION_COOKIE_DURATION = timedelta(days=30)


@dataclass(frozen=True)
class _OIDCSettings:
    """Configuration required to initiate the OIDC authorisation flow."""

    issuer: str
    client_id: str
    client_secret: Optional[str]
    redirect_uri: str
    scopes: tuple[str, ...]
    audience: Optional[str]
    discovery_url: str


@dataclass(frozen=True)
class _OIDCProviderMetadata:
    """Metadata advertised by the OIDC discovery document."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: Optional[str]


@dataclass
class _PersistentSession:
    """Metadata used to keep track of long-lived authenticated sessions."""

    username: str
    authenticated_at: datetime
    last_active: datetime
    session_timeout: Optional[timedelta]
    auth_method: str = "static"

    def is_expired(self, now: datetime) -> bool:
        """Return ``True`` if the session expired according to the timeout."""
        if self.session_timeout is None:
            return False
        return now - self.last_active >= self.session_timeout


@st.cache_resource(show_spinner=False)
def _get_persistent_sessions() -> Dict[str, _PersistentSession]:
    """Return a process-wide store of persistent session metadata."""

    return {}


def _get_auth_provider() -> str:
    """Return the configured authentication provider identifier."""

    provider = os.getenv(AUTH_PROVIDER_ENV_VAR, "static").strip().lower()
    if not provider:
        return "static"
    return provider


def _build_well_known_url(issuer: str) -> str:
    """Return the OIDC discovery document URL for the given issuer."""

    cleaned = issuer.rstrip("/")
    return f"{cleaned}/.well-known/openid-configuration"


@lru_cache(maxsize=8)
def _load_oidc_provider_metadata(discovery_url: str) -> _OIDCProviderMetadata:
    """Fetch and parse the OIDC provider discovery document."""

    try:
        response = requests.get(discovery_url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(
            "Failed to retrieve OIDC discovery document. Check the issuer URL and network connectivity."
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - defensive programming
        raise ValueError("OIDC discovery response was not valid JSON.") from exc

    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if field not in payload:
            raise ValueError(
                "OIDC discovery document is missing the required "
                f"'{field}' attribute."
            )

    issuer = payload.get("issuer") or discovery_url
    return _OIDCProviderMetadata(
        issuer=issuer,
        authorization_endpoint=payload["authorization_endpoint"],
        token_endpoint=payload["token_endpoint"],
        jwks_uri=payload["jwks_uri"],
        end_session_endpoint=payload.get("end_session_endpoint"),
    )


@lru_cache(maxsize=8)
def _fetch_oidc_jwks(jwks_uri: str) -> dict[str, Any]:
    """Fetch the JSON Web Key Set used to validate ID token signatures."""

    try:
        response = requests.get(jwks_uri, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError("Failed to download OIDC JWKS from the provider.") from exc

    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - defensive programming
        raise ValueError("OIDC JWKS response was not valid JSON.") from exc

    keys = payload.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("OIDC JWKS payload did not include signing keys.")

    return payload


def _normalise_scopes(raw_scopes: str | None) -> tuple[str, ...]:
    """Return a normalised list of scopes ensuring ``openid`` is included."""

    if not raw_scopes:
        scopes: list[str] = ["openid", "profile", "email"]
    else:
        scopes = [scope for scope in raw_scopes.replace(",", " ").split() if scope]
        if "openid" not in scopes:
            scopes.insert(0, "openid")

    seen: set[str] = set()
    deduped: list[str] = []
    for scope in scopes:
        if scope in seen:
            continue
        seen.add(scope)
        deduped.append(scope)
    return tuple(deduped)


def _get_oidc_settings() -> _OIDCSettings:
    """Load the configured OIDC settings from the environment."""

    issuer = os.getenv(OIDC_ISSUER_ENV_VAR, "").strip()
    if not issuer:
        raise ValueError(
            "OIDC authentication is enabled but the issuer URL is missing. "
            f"Set `{OIDC_ISSUER_ENV_VAR}` to your identity provider issuer."
        )

    client_id = os.getenv(OIDC_CLIENT_ID_ENV_VAR, "").strip()
    if not client_id:
        raise ValueError(
            "OIDC authentication is enabled but the client ID is missing. "
            f"Set `{OIDC_CLIENT_ID_ENV_VAR}` to your registered client ID."
        )

    redirect_uri = os.getenv(OIDC_REDIRECT_URI_ENV_VAR, "").strip()
    if not redirect_uri:
        raise ValueError(
            "OIDC authentication requires a redirect URI. Set "
            f"`{OIDC_REDIRECT_URI_ENV_VAR}` to the callback URL configured in your identity provider."
        )

    discovery_url = os.getenv(OIDC_DISCOVERY_URL_ENV_VAR, "").strip()
    if not discovery_url:
        discovery_url = _build_well_known_url(issuer)

    client_secret = os.getenv(OIDC_CLIENT_SECRET_ENV_VAR)
    if client_secret is not None:
        client_secret = client_secret.strip() or None

    scopes = _normalise_scopes(os.getenv(OIDC_SCOPES_ENV_VAR))
    audience = os.getenv(OIDC_AUDIENCE_ENV_VAR, "").strip() or None

    return _OIDCSettings(
        issuer=issuer.rstrip("/"),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        audience=audience,
        discovery_url=discovery_url,
    )


def _select_jwk(jwks: dict[str, Any], *, kid: Optional[str]) -> dict[str, Any]:
    """Return the signing key matching ``kid`` from the JWKS payload."""

    keys = jwks.get("keys", [])
    if not isinstance(keys, list):
        raise ValueError("OIDC JWKS payload is malformed.")

    if kid is None:
        if len(keys) == 1:
            return keys[0]
        raise ValueError("ID token did not specify a key identifier (kid).")

    for key in keys:
        if not isinstance(key, dict):
            continue
        if key.get("kid") == kid:
            return key

    raise ValueError("Unable to find a signing key that matches the ID token.")


def _verify_id_token(settings: _OIDCSettings, id_token: str) -> dict[str, Any]:
    """Validate the ID token signature and required claims."""

    metadata = _load_oidc_provider_metadata(settings.discovery_url)
    jwks = _fetch_oidc_jwks(metadata.jwks_uri)

    jwt_module = _require_jwt()

    try:
        header = jwt_module.get_unverified_header(id_token)
    except JWTError as exc:
        raise ValueError("Unable to parse ID token header.") from exc

    algorithm_name = header.get("alg")
    if not isinstance(algorithm_name, str):
        raise ValueError("ID token is missing the signing algorithm.")

    algorithms = jwt_module.algorithms.get_default_algorithms()
    algorithm = algorithms.get(algorithm_name)
    if algorithm is None:
        raise ValueError(f"Unsupported ID token signing algorithm: {algorithm_name}.")

    key_data = _select_jwk(jwks, kid=header.get("kid"))
    key = algorithm.from_jwk(json.dumps(key_data))

    audience = settings.audience or settings.client_id

    try:
        return jwt_module.decode(
            id_token,
            key,
            algorithms=[algorithm_name],
            audience=audience,
            issuer=settings.issuer,
            options={"require": ["sub", "iss", "aud", "exp", "iat"]},
        )
    except JWTError as exc:
        raise ValueError("The ID token from the provider could not be validated.") from exc


def _build_authorization_url(
    metadata: _OIDCProviderMetadata,
    settings: _OIDCSettings,
    *,
    state: str,
    code_challenge: Optional[str],
) -> str:
    """Construct the OIDC authorisation endpoint URL."""

    params: dict[str, str] = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": " ".join(settings.scopes),
        "state": state,
    }
    if code_challenge is not None:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    query = urlencode(params)
    separator = "&" if "?" in metadata.authorization_endpoint else "?"
    return f"{metadata.authorization_endpoint}{separator}{query}"


def _generate_code_verifier() -> str:
    """Return a cryptographically random code verifier for PKCE."""

    return token_urlsafe(96)


def _create_code_challenge(verifier: str) -> str:
    """Create a S256 code challenge from ``verifier`` suitable for PKCE."""

    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _generate_state_token() -> str:
    """Return a secure random state token for the OIDC flow."""

    return token_urlsafe(32)


def _get_query_param(name: str) -> Optional[str]:
    """Return the first value for the given query parameter, if present."""

    try:
        params = st.query_params  # type: ignore[attr-defined]
        value = params.get(name)
        if value is None:
            return None
        if isinstance(value, list):
            return value[0] if value else None
        return str(value)
    except AttributeError:
        params = st.experimental_get_query_params()
        values = params.get(name)
        if not values:
            return None
        return values[0]


def _clear_query_params() -> None:
    """Remove all query parameters from the current page URL."""

    try:
        st.query_params.clear()  # type: ignore[attr-defined]
    except AttributeError:
        st.experimental_set_query_params()


def _redirect_to_authorization(url: str) -> None:
    """Perform a client-side redirect to the identity provider."""

    escaped = html.escape(url, quote=True)
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={escaped}">',
        unsafe_allow_html=True,
    )
    st.stop()


def _exchange_code_for_tokens(
    metadata: _OIDCProviderMetadata,
    settings: _OIDCSettings,
    *,
    code: str,
    code_verifier: Optional[str],
) -> dict[str, Any]:
    """Exchange the received authorisation code for tokens."""

    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "client_id": settings.client_id,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    auth: Optional[tuple[str, str]] = None
    if settings.client_secret:
        auth = (settings.client_id, settings.client_secret)

    try:
        response = requests.post(
            metadata.token_endpoint,
            data=data,
            auth=auth,
            timeout=10,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError("Failed to exchange the authorisation code for tokens.") from exc

    try:
        token_payload = response.json()
    except ValueError as exc:  # pragma: no cover - defensive programming
        raise ValueError("Token endpoint returned an invalid JSON response.") from exc

    return token_payload


def _extract_display_name(claims: dict[str, Any]) -> str:
    """Return a human-friendly display name from the ID token claims."""

    for key in ("name", "preferred_username", "email", "sub"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "Authenticated user"


def _handle_oidc_callback(
    settings: _OIDCSettings,
    session_timeout: Optional[timedelta],
    now: datetime,
) -> None:
    """Process an authorisation response from the identity provider."""

    code = _get_query_param("code")
    state = _get_query_param("state")
    error = _get_query_param("error")

    if error:
        description = _get_query_param("error_description")
        message = f"OIDC provider returned an error: {error}"
        if description:
            message = f"{message} – {description}"
        st.session_state["auth_error"] = message
        _clear_query_params()
        _trigger_rerun()
        return

    if not code:
        return

    expected_state = st.session_state.get("_oidc_state")
    if not isinstance(expected_state, str) or state != expected_state:
        st.session_state["auth_error"] = "Invalid login response. Please try again."
        _clear_query_params()
        _trigger_rerun()
        return

    code_verifier = st.session_state.get("_oidc_code_verifier")
    if code_verifier is not None and not isinstance(code_verifier, str):
        code_verifier = None

    metadata = _load_oidc_provider_metadata(settings.discovery_url)

    try:
        token_payload = _exchange_code_for_tokens(
            metadata,
            settings,
            code=code,
            code_verifier=code_verifier,
        )
    except ValueError as exc:
        st.session_state["auth_error"] = str(exc)
        _clear_query_params()
        _trigger_rerun()
        return

    id_token = token_payload.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        st.session_state["auth_error"] = (
            "The identity provider response did not include an ID token."
        )
        _clear_query_params()
        _trigger_rerun()
        return

    try:
        claims = _verify_id_token(settings, id_token)
    except ValueError as exc:
        st.session_state["auth_error"] = str(exc)
        _clear_query_params()
        _trigger_rerun()
        return

    display_name = _extract_display_name(claims)

    st.session_state["authenticated"] = True
    st.session_state["authenticated_at"] = now
    st.session_state["last_active"] = now
    st.session_state["auth_method"] = "oidc"
    st.session_state["display_name"] = display_name
    st.session_state["oidc_claims"] = claims
    st.session_state["oidc_id_token"] = id_token
    st.session_state.pop("auth_error", None)
    st.session_state.pop("_oidc_state", None)
    st.session_state.pop("_oidc_code_verifier", None)

    _store_persistent_session(
        display_name,
        now,
        session_timeout,
        auth_method="oidc",
    )

    _clear_query_params()
    _trigger_rerun()


def _render_oidc_login(settings: _OIDCSettings) -> None:
    """Render the OIDC login button and initiate the flow when clicked."""

    st.markdown("### 🔐 Sign in to the Portainer dashboard")
    st.caption("Use your identity provider credentials to continue.")

    error_message = st.session_state.get("auth_error")
    if error_message:
        st.error(error_message)

    if st.button("Continue with single sign-on", key="oidc_sign_in", type="primary"):
        try:
            metadata = _load_oidc_provider_metadata(settings.discovery_url)
        except ValueError as exc:
            st.session_state["auth_error"] = str(exc)
            _trigger_rerun()
            return

        state_token = _generate_state_token()
        code_verifier = _generate_code_verifier()
        code_challenge = _create_code_challenge(code_verifier)
        st.session_state["_oidc_state"] = state_token
        st.session_state["_oidc_code_verifier"] = code_verifier
        st.session_state.pop("auth_error", None)

        authorization_url = _build_authorization_url(
            metadata,
            settings,
            state=state_token,
            code_challenge=code_challenge,
        )
        _redirect_to_authorization(authorization_url)

def _prune_expired_sessions(*, now: Optional[datetime] = None) -> None:
    """Remove expired sessions from the persistent store."""

    reference_time = now or datetime.now(timezone.utc)
    sessions = _get_persistent_sessions()

    for token, session in list(sessions.items()):
        if session.is_expired(reference_time):
            sessions.pop(token, None)


def get_active_session_count(*, now: Optional[datetime] = None) -> int:
    """Return the number of currently active authenticated sessions.

    The count is derived from the persistent session store used for cookie
    based authentication. Expired sessions are discarded based on their
    configured timeout. Active sessions are those which have not expired –
    callers may optionally provide ``now`` to aid deterministic testing.
    """

    reference_time = now or datetime.now(timezone.utc)
    sessions = _get_persistent_sessions()
    _prune_expired_sessions(now=reference_time)
    return len(sessions)


def _trigger_rerun() -> None:
    """Trigger a Streamlit rerun using the available API."""
    try:  # Streamlit < 1.27
        st.experimental_rerun()
    except AttributeError:  # pragma: no cover - Streamlit >= 1.27
        st.rerun()  # type: ignore[attr-defined]


@lru_cache(maxsize=1)
def _get_session_timeout() -> Optional[timedelta]:
    """Return the configured session timeout, if any."""
    timeout_value = os.getenv(SESSION_TIMEOUT_ENV_VAR)
    if timeout_value is None or not timeout_value.strip():
        return None

    try:
        minutes = int(timeout_value)
    except ValueError as exc:  # pragma: no cover - defensive programming
        raise ValueError(
            "Invalid session timeout. Set "
            f"`{SESSION_TIMEOUT_ENV_VAR}` to an integer number of minutes."
        ) from exc

    if minutes <= 0:
        return None

    return timedelta(minutes=minutes)


def _format_remaining_time(delta: timedelta) -> str:
    """Return a human friendly representation of a positive timedelta."""
    total_seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours:d}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes:d}m {seconds:02d}s"
    return f"{seconds:d}s"


def _format_remaining_minutes(delta: timedelta) -> str:
    """Return the remaining time rounded up to the nearest minute."""
    total_seconds = max(0, int(delta.total_seconds()))

    if total_seconds == 0:
        return "0m"

    total_minutes = math.ceil(total_seconds / 60)
    return f"{total_minutes:d}m"


def _get_session_token_from_cookie() -> Optional[str]:
    """Return the persistent session token from the browser cookie, if any."""

    try:
        token = st.experimental_get_cookie(SESSION_COOKIE_NAME)
    except AttributeError:  # pragma: no cover - Streamlit < 1.27 fallback
        return None

    if not token:
        return None
    return token


def _set_session_cookie(
    token: str, *, now: datetime, session_timeout: Optional[timedelta]
) -> None:
    """Persist the session token in a browser cookie."""

    try:
        expires_at = now + (
            session_timeout if session_timeout is not None else DEFAULT_SESSION_COOKIE_DURATION
        )
        st.experimental_set_cookie(
            SESSION_COOKIE_NAME,
            token,
            expires_at=expires_at,
            path="/",
        )
    except AttributeError:  # pragma: no cover - Streamlit < 1.27 fallback
        return


def _delete_session_cookie() -> None:
    """Remove the session token cookie from the browser."""

    try:
        st.experimental_delete_cookie(SESSION_COOKIE_NAME, path="/")
    except AttributeError:  # pragma: no cover - Streamlit < 1.27 fallback
        return


def _clear_persistent_session() -> None:
    """Forget any persisted session token for the active user."""

    token = st.session_state.pop("_session_token", None)
    if token:
        _get_persistent_sessions().pop(token, None)

    _delete_session_cookie()


def _store_persistent_session(
    username: str,
    now: datetime,
    session_timeout: Optional[timedelta],
    *,
    auth_method: str = "static",
) -> None:
    """Create and persist a new session token for the authenticated user."""

    _prune_expired_sessions(now=now)
    token = token_urlsafe(32)
    _get_persistent_sessions()[token] = _PersistentSession(
        username=username,
        authenticated_at=now,
        last_active=now,
        session_timeout=session_timeout,
        auth_method=auth_method,
    )
    st.session_state["_session_token"] = token
    _set_session_cookie(token, now=now, session_timeout=session_timeout)


def _update_persistent_session_activity(
    now: datetime, session_timeout: Optional[timedelta]
) -> None:
    """Update the ``last_active`` timestamp for the stored session token."""

    token = st.session_state.get("_session_token")
    if not isinstance(token, str):
        return

    session = _get_persistent_sessions().get(token)
    if session is None:
        return

    session.last_active = now
    session.session_timeout = session_timeout
    _set_session_cookie(token, now=now, session_timeout=session_timeout)


def _restore_persistent_session(
    expected_username: Optional[str],
    session_timeout: Optional[timedelta],
    now: datetime,
) -> None:
    """Restore an authenticated session based on the persisted token, if present."""

    _prune_expired_sessions(now=now)
    token = _get_session_token_from_cookie()
    if not token:
        return

    sessions = _get_persistent_sessions()
    session = sessions.get(token)
    if session is None:
        sessions.pop(token, None)
        _delete_session_cookie()
        return

    if expected_username is not None and session.username != expected_username:
        sessions.pop(token, None)
        _delete_session_cookie()
        return

    # Ensure we use the most up-to-date timeout configuration.
    session.session_timeout = session_timeout

    if session.is_expired(now):
        sessions.pop(token, None)
        _delete_session_cookie()
        st.session_state.pop("authenticated", None)
        st.session_state.pop("authenticated_at", None)
        st.session_state.pop("last_active", None)
        st.session_state["auth_error"] = "Session expired due to inactivity."
        return

    st.session_state["authenticated"] = True
    st.session_state["authenticated_at"] = session.authenticated_at
    st.session_state["last_active"] = now
    st.session_state["_session_token"] = token
    st.session_state["auth_method"] = session.auth_method
    st.session_state["display_name"] = session.username
    _set_session_cookie(token, now=now, session_timeout=session_timeout)
    session.last_active = now


def require_authentication() -> None:
    """Prompt the user for credentials and block execution until authenticated."""

    provider = _get_auth_provider()
    if provider not in {"static", "oidc"}:
        st.error(
            "Unsupported authentication provider configured. Set "
            f"`{AUTH_PROVIDER_ENV_VAR}` to either 'static' or 'oidc'."
        )
        st.stop()

    try:
        session_timeout = _get_session_timeout()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    now = datetime.now(timezone.utc)
    session_timer_placeholder = st.sidebar.empty()
    auto_refresh_triggered = False

    oidc_settings: Optional[_OIDCSettings] = None
    expected_username: Optional[str] = None
    expected_key: Optional[str] = None

    if provider == "oidc":
        try:
            oidc_settings = _get_oidc_settings()
        except ValueError as exc:
            st.error(str(exc))
            st.stop()

        _restore_persistent_session(None, session_timeout, now)
        _handle_oidc_callback(oidc_settings, session_timeout, now)
    else:
        expected_username = os.getenv(USERNAME_ENV_VAR)
        expected_key = os.getenv(KEY_ENV_VAR)

        if not expected_username or not expected_key:
            st.error(
                "Dashboard credentials are not configured. Set both the "
                f"`{USERNAME_ENV_VAR}` and `{KEY_ENV_VAR}` environment "
                "variables before starting the app."
            )
            st.stop()

        _restore_persistent_session(expected_username, session_timeout, now)

    if st.session_state.get("authenticated") and session_timeout is not None:
        refresh_count = st_autorefresh(interval=30000, key="session_timeout_refresh")
        previous_refresh_count = st.session_state.get("_session_timeout_refresh_count")
        auto_refresh_triggered = (
            previous_refresh_count is not None and refresh_count != previous_refresh_count
        )
        st.session_state["_session_timeout_refresh_count"] = refresh_count
    else:
        st.session_state.pop("_session_timeout_refresh_count", None)

    if st.session_state.get("authenticated"):
        last_active = st.session_state.get("last_active")
        if not isinstance(last_active, datetime):
            last_active = st.session_state.get("authenticated_at")

        if session_timeout is not None and isinstance(last_active, datetime):
            time_remaining = session_timeout - (now - last_active)
            if time_remaining <= timedelta(0):
                st.session_state.pop("authenticated", None)
                st.session_state.pop("authenticated_at", None)
                st.session_state.pop("last_active", None)
                _clear_persistent_session()
                st.session_state["auth_error"] = "Session expired due to inactivity."
                session_timer_placeholder.empty()
            else:
                session_timer_placeholder.info(
                    f"Session expires in {_format_remaining_minutes(time_remaining)}",
                    icon="⏳",
                )

                if timedelta(0) < time_remaining <= timedelta(seconds=30):
                    warning_container = st.empty()
                    with warning_container.container():
                        st.warning(
                            "Your session will expire soon due to inactivity.",
                            icon="⚠️",
                        )
                        st.write(
                            f"Remaining time: {_format_remaining_time(time_remaining)}"
                        )
                        if st.button("Keep me logged in", key="keep_session_active"):
                            st.session_state["last_active"] = datetime.now(timezone.utc)
                            _trigger_rerun()

                if not auto_refresh_triggered:
                    st.session_state["last_active"] = now
                    _update_persistent_session_activity(now, session_timeout)
                return
        else:
            if session_timeout is None:
                session_timer_placeholder.info(
                    "Session timeout is not configured.",
                    icon="🟢",
                )
            else:
                session_timer_placeholder.empty()
            st.session_state["last_active"] = now
            _update_persistent_session_activity(now, session_timeout)
            return

    session_timer_placeholder.empty()

    if provider == "oidc":
        if oidc_settings is None:
            st.error("OIDC settings could not be loaded.")
            st.stop()
        _render_oidc_login(oidc_settings)
        st.stop()

    st.markdown("### 🔐 Sign in to the Portainer dashboard")
    st.caption(
        "Enter the credentials configured through the dashboard environment "
        "variables."
    )

    error_message = st.session_state.get("auth_error")
    if error_message:
        st.error(error_message)

    with st.form("dashboard-authentication"):
        username = st.text_input("Username", placeholder="Dashboard username")
        access_key = st.text_input(
            "Access key",
            placeholder="Dashboard access key",
            type="password",
        )
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if username == expected_username and access_key == expected_key:
            st.session_state["authenticated"] = True
            st.session_state["authenticated_at"] = now
            st.session_state["last_active"] = now
            st.session_state["auth_method"] = "static"
            st.session_state["display_name"] = expected_username
            _store_persistent_session(
                expected_username,
                now,
                session_timeout,
                auth_method="static",
            )
            st.session_state.pop("auth_error", None)
            _trigger_rerun()
        else:
            st.session_state["auth_error"] = "Invalid username or access key."
            _trigger_rerun()

    st.stop()


def render_logout_button() -> None:
    """Display a logout control in the sidebar for authenticated users."""
    if not st.session_state.get("authenticated"):
        return

    display_name = st.session_state.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        st.sidebar.caption(f"Signed in as {display_name}")

    if st.sidebar.button("Log out", width="stretch"):
        _clear_persistent_session()
        for key in (
            "authenticated",
            "auth_error",
            "authenticated_at",
            "last_active",
            "display_name",
            "auth_method",
            "oidc_claims",
            "oidc_id_token",
            "_oidc_state",
            "_oidc_code_verifier",
        ):
            st.session_state.pop(key, None)
        _trigger_rerun()
