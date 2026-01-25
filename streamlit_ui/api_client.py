"""HTTP client to communicate with the FastAPI backend."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

# Backend URL - can be overridden by environment variable
BACKEND_URL = os.getenv("FASTAPI_BACKEND_URL", "http://localhost:8000")


SESSION_COOKIE_NAME = "dashboard_session_token"


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
            timeout=30.0,
        )

    def login(self, username: str, password: str) -> bool:
        """Authenticate with the backend."""
        try:
            with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
                response = client.post(
                    "/auth/login",
                    data={"username": username, "password": password},
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

    def get_endpoints(self) -> list[dict]:
        """Get all endpoints."""
        result = self.get("/api/v1/endpoints/")
        return result if isinstance(result, list) else []

    def get_containers(
        self,
        endpoint_id: int | None = None,
        include_stopped: bool = True,
    ) -> list[dict]:
        """Get all containers."""
        params = {"include_stopped": str(include_stopped).lower()}
        if endpoint_id is not None:
            params["endpoint_id"] = str(endpoint_id)
        result = self.get("/api/v1/containers/", params=params)
        return result if isinstance(result, list) else []

    def get_stacks(self, endpoint_id: int | None = None) -> list[dict]:
        """Get all stacks."""
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

    def get_host_metrics(self, endpoint_id: int) -> dict | None:
        """Get host metrics for an endpoint."""
        result = self.get(f"/api/v1/endpoints/{endpoint_id}/host-metrics")
        return result if isinstance(result, dict) else None

    def trigger_backup(self, environment: str | None = None) -> dict | None:
        """Trigger a backup."""
        params = {}
        if environment:
            params["environment"] = environment
        result = self.post("/api/v1/backup/trigger", params=params)
        return result if isinstance(result, dict) else None

    def get_session_status(self) -> dict | None:
        """Get current session status including time remaining."""
        result = self.get("/auth/session")
        return result if isinstance(result, dict) else None


# Singleton instance
_client: APIClient | None = None


def get_api_client() -> APIClient:
    """Get the API client singleton."""
    global _client
    if _client is None:
        _client = APIClient()
    return _client
