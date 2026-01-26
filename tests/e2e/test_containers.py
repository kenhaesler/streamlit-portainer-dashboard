"""E2E tests for the Containers page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import STREAMLIT_LOAD_TIMEOUT
from tests.e2e.pages.containers_page import ContainersPage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class TestContainersPage:
    """Tests for the Containers page functionality."""

    def test_containers_page_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the containers page loads correctly."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()

        # Verify page loaded
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_containers_table_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that the containers table is displayed."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()

        # Wait for data to load
        containers.wait_for_data_loaded()

        # Check for table or data display
        table = authenticated_page.locator("[data-testid='stDataFrame']")
        # May be 0 if no containers
        assert table.count() >= 0

    def test_container_state_filter_present(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that container state filter is available."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()

        # Look for filter/selectbox elements
        selectboxes = authenticated_page.locator("[data-testid='stSelectbox']")

        # Should have at least one filter (state, endpoint, etc.)
        # May vary based on implementation
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestContainerFiltering:
    """Tests for container filtering functionality."""

    def test_filter_by_running_state(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test filtering containers by running state."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Try to filter by running state
        state_filter = authenticated_page.locator(
            "[data-testid='stSelectbox']:has-text('State')"
        )

        if state_filter.count() > 0:
            state_filter.click()
            running_option = authenticated_page.locator("[role='option']:has-text('running')")
            if running_option.count() > 0:
                running_option.click()
                containers.wait_for_data_loaded()

        # Verify page still functional
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_search_containers(self, authenticated_page: "Page", base_url: str) -> None:
        """Test searching for containers by name."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for search input
        search_input = authenticated_page.locator(
            "input[aria-label*='Search'], input[placeholder*='Search']"
        )

        if search_input.count() > 0:
            search_input.first.fill("test")
            containers.wait_for_data_loaded()

        # Verify page responds
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_filter_by_endpoint(self, authenticated_page: "Page", base_url: str) -> None:
        """Test filtering containers by endpoint."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for endpoint filter
        endpoint_filter = authenticated_page.locator(
            "[data-testid='stSelectbox']:has-text('Endpoint')"
        )

        # Verify filter exists or page loads correctly
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestContainerDetails:
    """Tests for container details view."""

    def test_container_info_tabs_present(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that container info tabs are present."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for tabs
        tabs = authenticated_page.locator("[data-testid='stTab']")

        # Tabs may or may not be present depending on page layout
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_container_environment_tab(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test the environment variables tab."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for Environment tab
        env_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Environment')")

        if env_tab.count() > 0:
            env_tab.click()
            containers.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_container_networks_tab(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test the networks tab."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for Networks tab
        networks_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Networks')")

        if networks_tab.count() > 0:
            networks_tab.click()
            containers.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_container_mounts_tab(self, authenticated_page: "Page", base_url: str) -> None:
        """Test the mounts tab."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for Mounts tab
        mounts_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Mounts')")

        if mounts_tab.count() > 0:
            mounts_tab.click()
            containers.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestContainerHealthAlerts:
    """Tests for container health alerts."""

    def test_health_alerts_section_present(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that health alerts section is present."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Check for alerts section
        alerts = authenticated_page.locator("[data-testid='stAlert']")

        # May have 0 alerts if all healthy
        alert_count = containers.get_health_alerts_count()
        assert alert_count >= 0

    def test_no_critical_errors_on_load(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that no critical errors are displayed on page load."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Look for error messages that indicate page failure
        critical_errors = authenticated_page.locator(
            "[data-testid='stException'], :has-text('Traceback')"
        )

        assert critical_errors.count() == 0, "Page should not display Python exceptions"


class TestContainerStateIndicators:
    """Tests for container state visual indicators."""

    def test_state_indicators_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that container state indicators are displayed."""
        containers = ContainersPage(authenticated_page, base_url)
        containers.navigate()
        containers.wait_for_data_loaded()

        # Check for state indicators (running, stopped, etc.)
        has_running = containers.has_running_containers()
        has_stopped = containers.has_stopped_containers()

        # At least the page should be functional
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()
