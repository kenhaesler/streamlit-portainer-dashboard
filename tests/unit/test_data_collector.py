"""Tests for the data collector module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from portainer_dashboard.models.monitoring import ContainerCapabilities
from portainer_dashboard.services.data_collector import DataCollector
from portainer_dashboard.services.security_scanner import SecurityScanner


class TestDataCollector:
    """Tests for DataCollector class."""

    @pytest.fixture
    def mock_scanner(self) -> MagicMock:
        """Create a mock security scanner."""
        scanner = MagicMock(spec=SecurityScanner)
        scanner.scan_endpoint_containers = AsyncMock(return_value=[])
        return scanner

    @pytest.fixture
    def collector(self, mock_scanner: MagicMock) -> DataCollector:
        """Create a data collector with mock scanner."""
        return DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=True,
            include_image_check=True,
        )

    @pytest.mark.asyncio
    async def test_collect_endpoint_data_online(
        self, collector: DataCollector
    ) -> None:
        """Test collecting data from an online endpoint."""
        mock_client = MagicMock()
        mock_client.list_containers_for_endpoint = AsyncMock(
            return_value=[
                {"Id": "abc123", "Names": ["/app1"], "State": "running"},
                {"Id": "def456", "Names": ["/app2"], "State": "exited"},
            ]
        )

        endpoint = {"Id": 1, "Name": "prod", "Status": 1}

        containers, security_issues = await collector.collect_endpoint_data(
            mock_client, endpoint
        )

        assert len(containers) == 2
        mock_client.list_containers_for_endpoint.assert_called_once_with(
            1, include_stopped=True
        )

    @pytest.mark.asyncio
    async def test_collect_endpoint_data_offline(
        self, collector: DataCollector
    ) -> None:
        """Test collecting data from an offline endpoint returns empty."""
        mock_client = MagicMock()
        mock_client.list_containers_for_endpoint = AsyncMock()

        endpoint = {"Id": 1, "Name": "prod", "Status": 0}

        containers, security_issues = await collector.collect_endpoint_data(
            mock_client, endpoint
        )

        assert len(containers) == 0
        assert len(security_issues) == 0
        mock_client.list_containers_for_endpoint.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_endpoint_data_with_security_scan(
        self, mock_scanner: MagicMock
    ) -> None:
        """Test that security scan is performed when enabled."""
        mock_scanner.scan_endpoint_containers = AsyncMock(
            return_value=[
                ContainerCapabilities(
                    endpoint_id=1,
                    container_id="abc123",
                    container_name="priv-app",
                    privileged=True,
                    elevated_risks=["Container running in privileged mode"],
                )
            ]
        )

        collector = DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=True,
            include_image_check=False,
        )

        mock_client = MagicMock()
        mock_client.list_containers_for_endpoint = AsyncMock(
            return_value=[{"Id": "abc123", "Names": ["/priv-app"], "State": "running"}]
        )

        endpoint = {"Id": 1, "Name": "prod", "Status": 1}

        containers, security_issues = await collector.collect_endpoint_data(
            mock_client, endpoint
        )

        assert len(security_issues) == 1
        assert security_issues[0].container_name == "priv-app"
        mock_scanner.scan_endpoint_containers.assert_called_once()

    @pytest.mark.asyncio
    async def test_collect_endpoint_data_no_security_scan(
        self, mock_scanner: MagicMock
    ) -> None:
        """Test that security scan is skipped when disabled."""
        collector = DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=False,
            include_image_check=False,
        )

        mock_client = MagicMock()
        mock_client.list_containers_for_endpoint = AsyncMock(return_value=[])

        endpoint = {"Id": 1, "Name": "prod", "Status": 1}

        containers, security_issues = await collector.collect_endpoint_data(
            mock_client, endpoint
        )

        assert len(security_issues) == 0
        mock_scanner.scan_endpoint_containers.assert_not_called()

    @pytest.mark.asyncio
    async def test_collect_endpoint_data_handles_error(
        self, collector: DataCollector
    ) -> None:
        """Test handling errors when fetching container data."""
        from portainer_dashboard.services.portainer_client import PortainerAPIError

        mock_client = MagicMock()
        mock_client.list_containers_for_endpoint = AsyncMock(
            side_effect=PortainerAPIError("Connection refused")
        )

        endpoint = {"Id": 1, "Name": "prod", "Status": 1}

        containers, security_issues = await collector.collect_endpoint_data(
            mock_client, endpoint
        )

        assert len(containers) == 0
        assert len(security_issues) == 0


class TestDataCollectorImageStatus:
    """Tests for image status collection."""

    @pytest.fixture
    def mock_scanner(self) -> MagicMock:
        """Create a mock security scanner."""
        scanner = MagicMock(spec=SecurityScanner)
        scanner.scan_endpoint_containers = AsyncMock(return_value=[])
        return scanner

    @pytest.mark.asyncio
    async def test_collect_image_status_disabled(
        self, mock_scanner: MagicMock
    ) -> None:
        """Test image status collection when disabled."""
        collector = DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=False,
            include_image_check=False,
        )

        mock_client = MagicMock()

        result = await collector.collect_image_status(
            mock_client,
            endpoints=[{"Id": 1, "Name": "prod"}],
            stacks_by_endpoint={1: [{"Id": 1, "Name": "web-stack"}]},
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_collect_image_status_outdated(
        self, mock_scanner: MagicMock
    ) -> None:
        """Test collecting outdated image status."""
        collector = DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=False,
            include_image_check=True,
        )

        mock_client = MagicMock()
        mock_client.get_stack_image_status = AsyncMock(
            return_value={
                "Status": [
                    {"Image": "nginx:latest", "Outdated": True},
                    {"Image": "redis:latest", "Outdated": False},
                ]
            }
        )

        result = await collector.collect_image_status(
            mock_client,
            endpoints=[{"Id": 1, "Name": "prod"}],
            stacks_by_endpoint={1: [{"Id": 1, "Name": "web-stack"}]},
        )

        assert len(result) == 1
        assert result[0].image_name == "nginx:latest"
        assert result[0].outdated is True
        assert result[0].stack_name == "web-stack"

    @pytest.mark.asyncio
    async def test_collect_image_status_handles_error(
        self, mock_scanner: MagicMock
    ) -> None:
        """Test handling errors when fetching image status."""
        from portainer_dashboard.services.portainer_client import PortainerAPIError

        collector = DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=False,
            include_image_check=True,
        )

        mock_client = MagicMock()
        mock_client.get_stack_image_status = AsyncMock(
            side_effect=PortainerAPIError("Not found")
        )

        result = await collector.collect_image_status(
            mock_client,
            endpoints=[{"Id": 1, "Name": "prod"}],
            stacks_by_endpoint={1: [{"Id": 1, "Name": "web-stack"}]},
        )

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_collect_image_status_deduplicates_stacks(
        self, mock_scanner: MagicMock
    ) -> None:
        """Test that duplicate stack IDs are not queried multiple times."""
        collector = DataCollector(
            security_scanner=mock_scanner,
            include_security_scan=False,
            include_image_check=True,
        )

        mock_client = MagicMock()
        mock_client.get_stack_image_status = AsyncMock(
            return_value={"Status": []}
        )

        await collector.collect_image_status(
            mock_client,
            endpoints=[
                {"Id": 1, "Name": "prod"},
                {"Id": 2, "Name": "staging"},
            ],
            stacks_by_endpoint={
                1: [{"Id": 1, "Name": "shared-stack"}],
                2: [{"Id": 1, "Name": "shared-stack"}],
            },
        )

        assert mock_client.get_stack_image_status.call_count == 1
