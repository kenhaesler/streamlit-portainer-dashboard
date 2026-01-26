"""Pytest configuration for the dashboard test-suite."""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from portainer_dashboard.core.session import SessionStorage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add src directory to path for the new FastAPI application
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _load_jwt_stub() -> ModuleType:
    """Load the lightweight JWT stub used during tests.

    The production dependency is optional, so when it is not installed we load
    a local shim that exposes the minimal surface required by the test suite.
    """
    stub_path = Path(__file__).with_name("_jwt_stub.py")
    spec = importlib.util.spec_from_file_location("jwt", stub_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("Unable to load JWT stub for tests")

    module = importlib.util.module_from_spec(spec)
    sys.modules["jwt"] = module
    spec.loader.exec_module(module)
    return module


try:  # pragma: no cover - exercised indirectly when dependency is present
    import jwt  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on environment
    jwt_module = _load_jwt_stub()
    sys.modules.setdefault("jwt", jwt_module)
    sys.modules.setdefault("jwt.algorithms", jwt_module)
else:
    sys.modules.setdefault("jwt.algorithms", jwt)


# -----------------------------------------------------------------------------
# FastAPI Test Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Use asyncio as the backend for async tests."""
    return "asyncio"


@pytest.fixture
def test_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Configure test environment variables."""
    # Auth settings
    monkeypatch.setenv("DASHBOARD_USERNAME", "testuser")
    monkeypatch.setenv("DASHBOARD_KEY", "testpass")
    monkeypatch.setenv("DASHBOARD_AUTH_PROVIDER", "static")

    # Session settings
    monkeypatch.setenv("DASHBOARD_SESSION_BACKEND", "memory")
    monkeypatch.setenv("DASHBOARD_SESSION_TIMEOUT_MINUTES", "60")

    # Cache settings - use temp directory
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("PORTAINER_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("PORTAINER_CACHE_ENABLED", "false")

    # Portainer settings (optional for most tests)
    monkeypatch.setenv("PORTAINER_API_URL", "http://localhost:9000")
    monkeypatch.setenv("PORTAINER_API_KEY", "test-api-key")

    # Reload settings to pick up test environment
    from portainer_dashboard.config import reload_settings

    reload_settings()


@pytest_asyncio.fixture
async def app(test_settings: None) -> AsyncGenerator:
    """Create FastAPI application for testing."""
    from portainer_dashboard.main import create_app

    application = create_app()
    yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def authenticated_client(app, test_settings: None) -> AsyncGenerator[AsyncClient, None]:
    """Create authenticated async HTTP client for testing."""
    from datetime import datetime, timedelta, timezone

    from portainer_dashboard.core.session import InMemorySessionStorage, SessionRecord
    from portainer_dashboard.dependencies import get_session_storage

    # Create a test session
    storage = InMemorySessionStorage()
    now = datetime.now(timezone.utc)
    session = SessionRecord(
        token="test-session-token",
        username="testuser",
        authenticated_at=now,
        last_active=now,
        session_timeout=timedelta(hours=1),
        auth_method="static",
    )
    storage.create(session)

    # Override the session storage dependency
    app.dependency_overrides[get_session_storage] = lambda: storage

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"dashboard_session_token": "test-session-token"},
    ) as ac:
        yield ac

    # Clean up override
    app.dependency_overrides.pop(get_session_storage, None)


@pytest.fixture
def mock_portainer_endpoints() -> list[dict]:
    """Sample Portainer endpoint data for testing."""
    import time

    # Use current timestamp for LastCheckInDate to simulate online edge agents
    now = int(time.time())

    return [
        {
            "Id": 1,
            "Name": "test-endpoint-1",
            "Type": 4,
            "URL": "https://edge-1.example.com",
            "EdgeID": "edge-id-1",
            "EdgeKey": "edge-key-1",
            "Status": 1,
            "LastCheckInDate": now,  # Recent check-in = online
            "EdgeCheckinInterval": 5,
            "Snapshots": [
                {
                    "DockerSnapshotRaw": {
                        "Containers": 5,
                        "Images": 3,
                    }
                }
            ],
            "TagIds": [1, 2],
            "UserAccessPolicies": {},
            "TeamAccessPolicies": {},
        },
        {
            "Id": 2,
            "Name": "test-endpoint-2",
            "Type": 4,
            "URL": "https://edge-2.example.com",
            "EdgeID": "edge-id-2",
            "EdgeKey": "edge-key-2",
            "Status": 1,
            "LastCheckInDate": now,  # Recent check-in = online
            "EdgeCheckinInterval": 5,
            "Snapshots": [
                {
                    "DockerSnapshotRaw": {
                        "Containers": 10,
                        "Images": 5,
                    }
                }
            ],
            "TagIds": [1],
            "UserAccessPolicies": {},
            "TeamAccessPolicies": {},
        },
    ]


@pytest.fixture
def mock_containers() -> list[dict]:
    """Sample container data for testing."""
    return [
        {
            "Id": "container-1",
            "Names": ["/test-container-1"],
            "Image": "nginx:latest",
            "ImageID": "sha256:abc123",
            "State": "running",
            "Status": "Up 2 hours",
            "Created": 1704067200,
            "Ports": [{"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"}],
            "Labels": {"com.docker.compose.service": "web"},
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.2"}}},
        },
        {
            "Id": "container-2",
            "Names": ["/test-container-2"],
            "Image": "redis:7",
            "ImageID": "sha256:def456",
            "State": "running",
            "Status": "Up 1 hour",
            "Created": 1704070800,
            "Ports": [{"PrivatePort": 6379, "Type": "tcp"}],
            "Labels": {"com.docker.compose.service": "cache"},
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.3"}}},
        },
    ]


@pytest.fixture
def mock_stacks() -> list[dict]:
    """Sample stack data for testing."""
    return [
        {
            "Id": 1,
            "Name": "test-stack-1",
            "Type": 2,
            "EndpointId": 1,
            "Status": 1,
            "CreationDate": "2024-01-01T00:00:00Z",
            "UpdateDate": "2024-01-02T00:00:00Z",
            "Env": [{"name": "ENV", "value": "test"}],
        },
        {
            "Id": 2,
            "Name": "test-stack-2",
            "Type": 2,
            "EndpointId": 1,
            "Status": 1,
            "CreationDate": "2024-01-01T00:00:00Z",
            "UpdateDate": "2024-01-03T00:00:00Z",
            "Env": [],
        },
    ]
