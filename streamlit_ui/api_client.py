"""HTTP client to communicate with the FastAPI backend.

Features:
- Connection pooling via session state for better performance
- Streamlit caching for reduced API calls
- Batch endpoint support for dashboard overview
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import streamlit as st

LOGGER = logging.getLogger(__name__)

# Backend URL - can be overridden by environment variable
BACKEND_URL = os.getenv("FASTAPI_BACKEND_URL", "http://localhost:8000")

# API timeout settings (in seconds)
# Default increased to 60s to handle slow external API responses (Portainer, LLM)
API_TIMEOUT = float(os.getenv("STREAMLIT_API_TIMEOUT", "60.0"))
API_TIMEOUT_LOGIN = float(os.getenv("STREAMLIT_API_TIMEOUT_LOGIN", "30.0"))
API_TIMEOUT_SESSION = float(os.getenv("STREAMLIT_API_TIMEOUT_SESSION", "10.0"))

# Streamlit cache TTL (in seconds) - how long to cache API responses in Streamlit
# This provides instant page navigation while backend cache handles freshness
STREAMLIT_CACHE_TTL = int(os.getenv("STREAMLIT_CACHE_TTL_SECONDS", "60"))

# HTTP connection pool settings
_HTTP_POOL_MAX_CONNECTIONS = 10
_HTTP_POOL_MAX_KEEPALIVE = 5

SESSION_COOKIE_NAME = "dashboard_session_token"


def _get_shared_client() -> httpx.Client:
    """Get or create a shared HTTP client stored in session state.

    This provides connection pooling across Streamlit reruns for better
    performance by reusing TCP connections.
    """
    if "_http_client" not in st.session_state:
        limits = httpx.Limits(
            max_connections=_HTTP_POOL_MAX_CONNECTIONS,
            max_keepalive_connections=_HTTP_POOL_MAX_KEEPALIVE,
        )
        st.session_state._http_client = httpx.Client(
            base_url=BACKEND_URL,
            timeout=API_TIMEOUT,
            limits=limits,
        )
        LOGGER.debug("Created shared HTTP client with connection pooling")
    return st.session_state._http_client


def _make_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """Make an HTTP request using the shared client with cookies."""
    client = _get_shared_client()
    cookies = {}
    session_cookie = get_session_cookie()
    if session_cookie:
        cookies[SESSION_COOKIE_NAME] = session_cookie

    return client.request(
        method,
        path,
        params=params,
        json=json,
        cookies=cookies,
        timeout=timeout or API_TIMEOUT,
    )


# Cached API call functions
# These use st.cache_data with TTL to avoid redundant API calls during page navigation

@st.cache_data(ttl=STREAMLIT_CACHE_TTL, show_spinner=False)
def _cached_get_dashboard_overview(_session_cookie: str | None) -> dict | None:
    """Cached fetch for dashboard overview (batch endpoint).

    Fetches endpoints, containers, and stacks in a single API call
    for better performance.
    """
    try:
        response = _make_request("GET", "/api/v1/dashboard/overview")
        if response.status_code == 401:
            return None
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        LOGGER.warning("Cached dashboard overview fetch failed: %s", e)
        return None


@st.cache_data(ttl=STREAMLIT_CACHE_TTL, show_spinner=False)
def _cached_get_endpoints(_session_cookie: str | None) -> list[dict]:
    """Cached fetch for endpoints."""
    try:
        response = _make_request("GET", "/api/v1/endpoints/")
        if response.status_code == 401:
            return []
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, list) else []
    except httpx.HTTPError as e:
        LOGGER.warning("Cached endpoints fetch failed: %s", e)
        return []


@st.cache_data(ttl=STREAMLIT_CACHE_TTL, show_spinner=False)
def _cached_get_containers(
    _session_cookie: str | None,
    include_stopped: bool = True,
) -> list[dict]:
    """Cached fetch for containers."""
    try:
        params = {"include_stopped": str(include_stopped).lower()}
        response = _make_request("GET", "/api/v1/containers/", params=params)
        if response.status_code == 401:
            return []
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, list) else []
    except httpx.HTTPError as e:
        LOGGER.warning("Cached containers fetch failed: %s", e)
        return []


@st.cache_data(ttl=STREAMLIT_CACHE_TTL, show_spinner=False)
def _cached_get_stacks(_session_cookie: str | None) -> list[dict]:
    """Cached fetch for stacks."""
    try:
        response = _make_request("GET", "/api/v1/stacks/")
        if response.status_code == 401:
            return []
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, list) else []
    except httpx.HTTPError as e:
        LOGGER.warning("Cached stacks fetch failed: %s", e)
        return []


def get_session_cookie() -> str | None:
    """Get the session cookie from Streamlit session state."""
    return st.session_state.get("session_cookie")


def set_session_cookie(cookie: str) -> None:
    """Store the session cookie in Streamlit session state."""
    st.session_state["session_cookie"] = cookie


def clear_session() -> None:
    """Clear the session."""
    if "session_cookie" in st.session_state:
        del st.session_state["session_cookie"]
    if "authenticated" in st.session_state:
        del st.session_state["authenticated"]
    if "username" in st.session_state:
        del st.session_state["username"]
    if "_session_restore_attempted" in st.session_state:
        del st.session_state["_session_restore_attempted"]


def extract_cookie_from_browser() -> str | None:
    """Extract the session cookie from browser request headers.

    Streamlit's st.context.headers contains the HTTP headers from the browser
    request, including the Cookie header with all cookies.
    """
    try:
        # st.context.headers is available in Streamlit 1.37+
        headers = st.context.headers
        cookie_header = headers.get("Cookie", "")

        if not cookie_header:
            return None

        # Parse cookies from the Cookie header
        # Format: "name1=value1; name2=value2; ..."
        for cookie_pair in cookie_header.split(";"):
            cookie_pair = cookie_pair.strip()
            if "=" in cookie_pair:
                name, value = cookie_pair.split("=", 1)
                if name.strip() == SESSION_COOKIE_NAME:
                    return value.strip()

        return None
    except Exception as e:
        LOGGER.debug("Could not extract cookie from browser: %s", e)
        return None


class APIClient:
    """Client for FastAPI backend communication."""

    def __init__(self, base_url: str = BACKEND_URL):
        self.base_url = base_url.rstrip("/")
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client with session cookie."""
        cookies = {}
        session_cookie = get_session_cookie()
        if session_cookie:
            cookies[SESSION_COOKIE_NAME] = session_cookie

        return httpx.Client(
            base_url=self.base_url,
            cookies=cookies,
            timeout=API_TIMEOUT,
        )

    def login(self, username: str, password: str, remember_me: bool = False) -> bool:
        """Authenticate with the backend.

        Args:
            username: The username to authenticate.
            password: The user's password.
            remember_me: If True, creates an extended session (30 days) that
                        survives browser restarts.
        """
        try:
            with httpx.Client(base_url=self.base_url, timeout=API_TIMEOUT_LOGIN) as client:
                form_data = {
                    "username": username,
                    "password": password,
                }
                if remember_me:
                    form_data["remember_me"] = "on"

                response = client.post(
                    "/auth/login",
                    data=form_data,
                    follow_redirects=False,
                )

                # Check for session cookie in response
                if SESSION_COOKIE_NAME in response.cookies:
                    set_session_cookie(response.cookies[SESSION_COOKIE_NAME])
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    return True

                # Check if redirect to home (successful login)
                if response.status_code in (302, 303) and SESSION_COOKIE_NAME in response.cookies:
                    set_session_cookie(response.cookies[SESSION_COOKIE_NAME])
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    return True

                return False
        except httpx.HTTPError as e:
            st.error(f"Login failed: {e}")
            return False

    def logout(self) -> None:
        """Logout from the backend."""
        try:
            with self._get_client() as client:
                client.get("/auth/logout", follow_redirects=False)
        except httpx.HTTPError:
            pass
        finally:
            clear_session()

    def is_authenticated(self) -> bool:
        """Check if the current session is authenticated."""
        return st.session_state.get("authenticated", False)

    def try_restore_session(self) -> bool:
        """Attempt to restore session from browser cookie.

        This method extracts the session cookie from the browser request headers
        and validates it with the backend. If valid, restores the session state.

        Returns True if session was restored, False otherwise.
        """
        # Only attempt restore once per Streamlit script run to avoid loops
        if st.session_state.get("_session_restore_attempted"):
            return False

        st.session_state["_session_restore_attempted"] = True

        # Extract cookie from browser headers
        cookie_value = extract_cookie_from_browser()
        if not cookie_value:
            LOGGER.debug("No session cookie found in browser")
            return False

        # Validate the cookie with backend
        try:
            with httpx.Client(
                base_url=self.base_url,
                cookies={SESSION_COOKIE_NAME: cookie_value},
                timeout=API_TIMEOUT_SESSION,
            ) as client:
                response = client.get("/auth/validate")

                if response.status_code == 200:
                    data = response.json()
                    if data.get("valid"):
                        # Restore session state
                        set_session_cookie(cookie_value)
                        st.session_state["authenticated"] = True
                        st.session_state["username"] = data.get("username", "User")
                        LOGGER.info("Session restored for user: %s", data.get("username"))
                        return True

                LOGGER.debug("Session validation failed: %s", response.status_code)
                return False
        except httpx.HTTPError as e:
            LOGGER.debug("Session restore failed: %s", e)
            return False

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict | list | None:
        """Make an authenticated request to the backend."""
        try:
            with self._get_client() as client:
                response = client.request(method, path, **kwargs)

                if response.status_code == 401:
                    clear_session()
                    st.warning("Session expired. Please login again.")
                    st.rerun()

                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            st.error(f"API request failed: {e}")
            return None

    def get(self, path: str, **kwargs: Any) -> dict | list | None:
        """Make a GET request."""
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> dict | list | None:
        """Make a POST request."""
        return self._request("POST", path, **kwargs)

    # API Methods

    def get_dashboard_overview(self, use_cache: bool = True) -> dict | None:
        """Get dashboard overview data (endpoints, containers, stacks) in a single request.

        This is more efficient than calling get_endpoints(), get_containers(),
        and get_stacks() separately as it uses a single API call with parallel
        backend fetching.

        Args:
            use_cache: If True, use Streamlit's cache for faster response.

        Returns:
            Dictionary containing endpoints, containers, stacks, and metadata.
        """
        if use_cache:
            return _cached_get_dashboard_overview(get_session_cookie())

        result = self.get("/api/v1/dashboard/overview")
        return result if isinstance(result, dict) else None

    def get_endpoints(self, use_cache: bool = True) -> list[dict]:
        """Get all endpoints.

        Args:
            use_cache: If True, use Streamlit's cache for faster response.
                      Set to False to force a fresh fetch.
        """
        if use_cache:
            return _cached_get_endpoints(get_session_cookie())

        result = self.get("/api/v1/endpoints/")
        return result if isinstance(result, list) else []

    def get_containers(
        self,
        endpoint_id: int | None = None,
        include_stopped: bool = True,
        use_cache: bool = True,
    ) -> list[dict]:
        """Get all containers.

        Args:
            endpoint_id: Filter by specific endpoint ID.
            include_stopped: Include stopped containers in results.
            use_cache: If True, use Streamlit's cache for faster response.
        """
        if use_cache and endpoint_id is None:
            # Use cache for the common case (all containers)
            containers = _cached_get_containers(get_session_cookie(), include_stopped)
            return containers

        # Non-cached path for filtered requests
        params = {"include_stopped": str(include_stopped).lower()}
        if endpoint_id is not None:
            params["endpoint_id"] = str(endpoint_id)
        result = self.get("/api/v1/containers/", params=params)
        return result if isinstance(result, list) else []

    def get_stacks(self, endpoint_id: int | None = None, use_cache: bool = True) -> list[dict]:
        """Get all stacks.

        Args:
            endpoint_id: Filter by specific endpoint ID.
            use_cache: If True, use Streamlit's cache for faster response.
        """
        if use_cache and endpoint_id is None:
            # Use cache for the common case (all stacks)
            return _cached_get_stacks(get_session_cookie())

        # Non-cached path for filtered requests
        params = {}
        if endpoint_id is not None:
            params["endpoint_id"] = str(endpoint_id)
        result = self.get("/api/v1/stacks/", params=params)
        return result if isinstance(result, list) else []

    def get_container_details(
        self, endpoint_id: int, container_id: str
    ) -> dict | None:
        """Get detailed container information."""
        result = self.get(f"/api/v1/containers/{endpoint_id}/{container_id}")
        return result if isinstance(result, dict) else None

    def get_container_logs(
        self,
        endpoint_id: int,
        container_id: str,
        *,
        tail: int = 500,
        timestamps: bool = True,
        since_minutes: int | None = None,
    ) -> dict | None:
        """Get container logs from Docker API via Portainer."""
        params = {
            "tail": str(tail),
            "timestamps": str(timestamps).lower(),
        }
        if since_minutes is not None:
            params["since_minutes"] = str(since_minutes)
        result = self.get(f"/api/v1/containers/{endpoint_id}/{container_id}/logs", params=params)
        return result if isinstance(result, dict) else None

    def get_host_metrics(self, endpoint_id: int) -> dict | None:
        """Get host metrics for an endpoint."""
        result = self.get(f"/api/v1/endpoints/{endpoint_id}/host-metrics")
        return result if isinstance(result, dict) else None

    def trigger_backup(self, environment: str | None = None) -> dict | None:
        """Trigger a backup."""
        params = {}
        if environment:
            params["environment"] = environment
        result = self.post("/api/v1/backup/create", params=params)
        return result if isinstance(result, dict) else None

    def get_session_status(self) -> dict | None:
        """Get current session status including time remaining."""
        result = self.get("/auth/session")
        return result if isinstance(result, dict) else None

    # Metrics API

    def get_metrics_status(self) -> dict | None:
        """Get metrics collection status."""
        result = self.get("/api/v1/metrics/status")
        return result if isinstance(result, dict) else None

    def get_metrics_dashboard(self) -> dict | None:
        """Get metrics dashboard overview."""
        result = self.get("/api/v1/metrics/dashboard")
        return result if isinstance(result, dict) else None

    def get_container_metrics(
        self,
        container_id: str,
        metric_type: str | None = None,
        hours: int = 24,
        limit: int = 1000,
    ) -> list[dict]:
        """Get historical metrics for a container."""
        params = {"hours": str(hours), "limit": str(limit)}
        if metric_type:
            params["metric_type"] = metric_type
        result = self.get(f"/api/v1/metrics/containers/{container_id}", params=params)
        return result if isinstance(result, list) else []

    def get_container_metrics_summary(
        self,
        container_id: str,
        metric_type: str = "cpu_percent",
        hours: int = 24,
    ) -> dict | None:
        """Get metrics summary for a container."""
        params = {"metric_type": metric_type, "hours": str(hours)}
        result = self.get(f"/api/v1/metrics/containers/{container_id}/summary", params=params)
        return result if isinstance(result, dict) else None

    def get_anomalies(
        self,
        hours: int = 24,
        limit: int = 100,
        only_anomalies: bool = True,
    ) -> list[dict]:
        """Get anomaly detections."""
        params = {
            "hours": str(hours),
            "limit": str(limit),
            "only_anomalies": str(only_anomalies).lower(),
        }
        result = self.get("/api/v1/metrics/anomalies", params=params)
        return result if isinstance(result, list) else []

    # Remediation API

    def get_remediation_status(self) -> dict | None:
        """Get remediation service status."""
        result = self.get("/api/v1/remediation/status")
        return result if isinstance(result, dict) else None

    def get_pending_actions(self, limit: int = 100) -> list[dict]:
        """Get pending remediation actions."""
        result = self.get("/api/v1/remediation/actions/pending", params={"limit": str(limit)})
        return result if isinstance(result, list) else []

    def get_approved_actions(self, limit: int = 100) -> list[dict]:
        """Get approved remediation actions."""
        result = self.get("/api/v1/remediation/actions/approved", params={"limit": str(limit)})
        return result if isinstance(result, list) else []

    def get_actions_history(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get action history."""
        params: dict[str, str] = {"limit": str(limit)}
        if status:
            params["status"] = status
        result = self.get("/api/v1/remediation/actions/history", params=params)
        return result if isinstance(result, list) else []

    def get_actions_summary(self) -> dict | None:
        """Get actions summary statistics."""
        result = self.get("/api/v1/remediation/actions/summary")
        return result if isinstance(result, dict) else None

    def approve_action(self, action_id: str, approved_by: str) -> dict | None:
        """Approve a pending action."""
        result = self.post(
            f"/api/v1/remediation/actions/{action_id}/approve",
            json={"approved_by": approved_by},
        )
        return result if isinstance(result, dict) else None

    def reject_action(
        self, action_id: str, rejected_by: str, reason: str | None = None
    ) -> dict | None:
        """Reject a pending action."""
        payload: dict[str, str | None] = {"rejected_by": rejected_by}
        if reason:
            payload["reason"] = reason
        result = self.post(
            f"/api/v1/remediation/actions/{action_id}/reject",
            json=payload,
        )
        return result if isinstance(result, dict) else None

    def execute_action(self, action_id: str) -> dict | None:
        """Execute an approved action."""
        result = self.post(f"/api/v1/remediation/actions/{action_id}/execute")
        return result if isinstance(result, dict) else None

    # Traces API

    def get_tracing_status(self) -> dict | None:
        """Get tracing status."""
        result = self.get("/api/v1/traces/status")
        return result if isinstance(result, dict) else None

    def get_traces_summary(self) -> dict | None:
        """Get traces summary statistics."""
        result = self.get("/api/v1/traces/summary")
        return result if isinstance(result, dict) else None

    def list_traces(
        self,
        hours: int = 1,
        limit: int = 100,
        http_method: str | None = None,
        http_route: str | None = None,
        has_errors: bool | None = None,
    ) -> list[dict]:
        """List traces with optional filtering."""
        params: dict[str, str] = {"hours": str(hours), "limit": str(limit)}
        if http_method:
            params["http_method"] = http_method
        if http_route:
            params["http_route"] = http_route
        if has_errors is not None:
            params["has_errors"] = str(has_errors).lower()
        result = self.get("/api/v1/traces/", params=params)
        return result if isinstance(result, list) else []

    def get_trace(self, trace_id: str) -> dict | None:
        """Get a specific trace with all spans."""
        result = self.get(f"/api/v1/traces/{trace_id}")
        return result if isinstance(result, dict) else None

    def get_service_map(self, hours: int = 1) -> dict | None:
        """Get the service dependency map."""
        result = self.get("/api/v1/traces/service-map", params={"hours": str(hours)})
        return result if isinstance(result, dict) else None

    def get_route_stats(self, hours: int = 1, limit: int = 50) -> list[dict]:
        """Get route statistics."""
        params = {"hours": str(hours), "limit": str(limit)}
        result = self.get("/api/v1/traces/routes/stats", params=params)
        return result if isinstance(result, list) else []


# Singleton instance
_client: APIClient | None = None


def get_api_client() -> APIClient:
    """Get the API client singleton."""
    global _client
    if _client is None:
        _client = APIClient()
    return _client
