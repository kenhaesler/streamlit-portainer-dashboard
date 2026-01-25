"""Integration tests for API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """Test the health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_login_page_renders(client: AsyncClient) -> None:
    """Test that the login page renders."""
    response = await client.get("/auth/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


@pytest.mark.asyncio
async def test_login_with_valid_credentials(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test login with valid credentials."""
    monkeypatch.setenv("DASHBOARD_USERNAME", "testuser")
    monkeypatch.setenv("DASHBOARD_KEY", "testpass")

    from portainer_dashboard.config import reload_settings
    reload_settings()

    response = await client.post(
        "/auth/login",
        data={"username": "testuser", "password": "testpass", "next": "/"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers.get("location") == "/"
    assert "dashboard_session_token" in response.cookies


@pytest.mark.asyncio
async def test_login_with_invalid_credentials(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test login with invalid credentials."""
    monkeypatch.setenv("DASHBOARD_USERNAME", "testuser")
    monkeypatch.setenv("DASHBOARD_KEY", "testpass")

    from portainer_dashboard.config import reload_settings
    reload_settings()

    response = await client.post(
        "/auth/login",
        data={"username": "wrong", "password": "wrong", "next": "/"},
    )

    assert response.status_code == 401
    assert "Invalid username or password" in response.text


@pytest.mark.asyncio
async def test_protected_page_redirects_to_login(client: AsyncClient) -> None:
    """Test that protected pages redirect to login."""
    response = await client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert "/auth/login" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_logout(authenticated_client: AsyncClient) -> None:
    """Test logout functionality."""
    response = await authenticated_client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 303
    assert "/auth/login" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_api_requires_auth(client: AsyncClient) -> None:
    """Test that API endpoints require authentication."""
    response = await client.get("/api/v1/endpoints/")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_endpoints_with_auth(
    authenticated_client: AsyncClient,
    mock_portainer_endpoints: list[dict],
) -> None:
    """Test API endpoints with authentication."""
    with patch(
        "portainer_dashboard.api.v1.endpoints.create_portainer_client"
    ) as mock_client:
        # Create mock client
        mock_instance = AsyncMock()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=None)
        mock_instance.list_all_endpoints = AsyncMock(
            return_value=mock_portainer_endpoints
        )
        mock_client.return_value = mock_instance

        response = await authenticated_client.get("/api/v1/endpoints/")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["endpoint_name"] == "test-endpoint-1"
