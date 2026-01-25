"""Tests for the security scanner module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from portainer_dashboard.services.security_scanner import (
    DEFAULT_ELEVATED_CAPS,
    SecurityScanner,
)


class TestSecurityScanner:
    """Tests for SecurityScanner class."""

    @pytest.fixture
    def scanner(self) -> SecurityScanner:
        """Create a scanner with default settings."""
        return SecurityScanner()

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock Portainer client."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_scan_privileged_container(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test scanning a privileged container."""
        mock_client.inspect_container = AsyncMock(
            return_value={
                "HostConfig": {
                    "Privileged": True,
                    "CapAdd": None,
                    "CapDrop": None,
                    "SecurityOpt": None,
                }
            }
        )

        result = await scanner.scan_container(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            container_id="abc123",
            container_name="my-app",
        )

        assert result is not None
        assert result.privileged is True
        assert "privileged mode" in result.elevated_risks[0].lower()

    @pytest.mark.asyncio
    async def test_scan_container_with_cap_add(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test scanning a container with elevated capabilities."""
        mock_client.inspect_container = AsyncMock(
            return_value={
                "HostConfig": {
                    "Privileged": False,
                    "CapAdd": ["NET_ADMIN", "SYS_ADMIN"],
                    "CapDrop": None,
                    "SecurityOpt": None,
                }
            }
        )

        result = await scanner.scan_container(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            container_id="abc123",
            container_name="my-app",
        )

        assert result is not None
        assert "NET_ADMIN" in result.cap_add
        assert "SYS_ADMIN" in result.cap_add
        assert len(result.elevated_risks) == 2

    @pytest.mark.asyncio
    async def test_scan_container_with_unconfined_seccomp(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test scanning a container with disabled seccomp."""
        mock_client.inspect_container = AsyncMock(
            return_value={
                "HostConfig": {
                    "Privileged": False,
                    "CapAdd": None,
                    "CapDrop": None,
                    "SecurityOpt": ["seccomp=unconfined"],
                }
            }
        )

        result = await scanner.scan_container(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            container_id="abc123",
            container_name="my-app",
        )

        assert result is not None
        assert "seccomp=unconfined" in result.security_opt
        assert any("seccomp" in r.lower() for r in result.elevated_risks)

    @pytest.mark.asyncio
    async def test_scan_container_with_unconfined_apparmor(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test scanning a container with disabled AppArmor."""
        mock_client.inspect_container = AsyncMock(
            return_value={
                "HostConfig": {
                    "Privileged": False,
                    "CapAdd": None,
                    "CapDrop": None,
                    "SecurityOpt": ["apparmor=unconfined"],
                }
            }
        )

        result = await scanner.scan_container(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            container_id="abc123",
            container_name="my-app",
        )

        assert result is not None
        assert any("apparmor" in r.lower() for r in result.elevated_risks)

    @pytest.mark.asyncio
    async def test_scan_secure_container(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test scanning a container with no security issues."""
        mock_client.inspect_container = AsyncMock(
            return_value={
                "HostConfig": {
                    "Privileged": False,
                    "CapAdd": None,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": None,
                }
            }
        )

        result = await scanner.scan_container(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            container_id="abc123",
            container_name="my-app",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_scan_container_api_error(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test handling API errors during container scan."""
        from portainer_dashboard.services.portainer_client import PortainerAPIError

        mock_client.inspect_container = AsyncMock(
            side_effect=PortainerAPIError("Connection refused")
        )

        result = await scanner.scan_container(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            container_id="abc123",
            container_name="my-app",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_scan_endpoint_containers(
        self, scanner: SecurityScanner, mock_client: MagicMock
    ) -> None:
        """Test scanning all containers on an endpoint."""

        async def mock_inspect(endpoint_id: int, container_id: str) -> dict:
            if container_id == "privileged-container":
                return {
                    "HostConfig": {
                        "Privileged": True,
                        "CapAdd": None,
                        "CapDrop": None,
                        "SecurityOpt": None,
                    }
                }
            return {
                "HostConfig": {
                    "Privileged": False,
                    "CapAdd": None,
                    "CapDrop": None,
                    "SecurityOpt": None,
                }
            }

        mock_client.inspect_container = AsyncMock(side_effect=mock_inspect)

        containers = [
            {"Id": "privileged-container", "Names": ["/priv-app"], "State": "running"},
            {"Id": "normal-container", "Names": ["/normal-app"], "State": "running"},
            {"Id": "stopped-container", "Names": ["/stopped-app"], "State": "exited"},
        ]

        results = await scanner.scan_endpoint_containers(
            mock_client,
            endpoint_id=1,
            endpoint_name="prod",
            containers=containers,
        )

        assert len(results) == 1
        assert results[0].container_name == "priv-app"
        assert results[0].privileged is True


class TestDefaultElevatedCaps:
    """Tests for default elevated capabilities."""

    def test_known_elevated_caps_included(self) -> None:
        """Test that known dangerous capabilities are in the default set."""
        dangerous_caps = [
            "NET_ADMIN",
            "SYS_ADMIN",
            "SYS_PTRACE",
            "SYS_MODULE",
            "DAC_OVERRIDE",
        ]

        for cap in dangerous_caps:
            assert cap in DEFAULT_ELEVATED_CAPS, f"{cap} should be in default set"

    def test_caps_are_uppercase(self) -> None:
        """Test that all capabilities are uppercase."""
        for cap in DEFAULT_ELEVATED_CAPS:
            assert cap == cap.upper(), f"{cap} should be uppercase"
