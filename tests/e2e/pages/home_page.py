"""Home Page Object for Streamlit dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class HomePage(BasePage):
    """Page Object for the Home/Dashboard page."""

    def __init__(self, page: "Page", base_url: str) -> None:
        """Initialize the home page.

        Args:
            page: Playwright page object
            base_url: Base URL of the Streamlit application
        """
        super().__init__(page, base_url)

    def navigate(self) -> None:
        """Navigate to the home page."""
        self.navigate_to()

    def get_total_endpoints(self) -> str | None:
        """Get the total endpoints metric value.

        Returns:
            The endpoints count as string, or None if not found
        """
        return self.get_metric_value("Total Endpoints")

    def get_total_containers(self) -> str | None:
        """Get the total containers metric value.

        Returns:
            The containers count as string, or None if not found
        """
        return self.get_metric_value("Containers")

    def get_total_stacks(self) -> str | None:
        """Get the total stacks metric value.

        Returns:
            The stacks count as string, or None if not found
        """
        return self.get_metric_value("Stacks")

    def get_running_containers(self) -> str | None:
        """Get the running containers metric value.

        Returns:
            The running containers count as string, or None if not found
        """
        return self.get_metric_value("Running")

    def get_endpoint_status_chart(self) -> "Locator":
        """Get the endpoint status chart.

        Returns:
            Locator for the endpoint status chart
        """
        return self.get_chart(0)

    def get_container_states_chart(self) -> "Locator":
        """Get the container states chart.

        Returns:
            Locator for the container states chart
        """
        return self.get_chart(1)

    def is_dashboard_loaded(self) -> bool:
        """Check if the dashboard has fully loaded.

        Returns:
            True if dashboard is loaded with metrics
        """
        # Check for presence of key dashboard elements
        has_title = self.is_element_visible("text=Portainer Dashboard")
        has_metrics = self.page.locator("[data-testid='stMetric']").count() > 0
        return has_title and has_metrics

    def click_download_csv(self) -> None:
        """Click the Download CSV button if available."""
        download_button = self.page.locator("button:has-text('Download CSV')")
        if download_button.count() > 0:
            download_button.click()

    def get_endpoints_table(self) -> "Locator":
        """Get the endpoints data table.

        Returns:
            Locator for the endpoints table
        """
        return self.get_dataframe(0)

    def has_endpoint_status_indicators(self) -> bool:
        """Check if endpoint status indicators are displayed.

        Returns:
            True if status indicators are present
        """
        # Look for status badges or indicators
        return (
            self.page.locator(":has-text('Online')").count() > 0
            or self.page.locator(":has-text('Offline')").count() > 0
        )

    def get_sidebar_session_info(self) -> str | None:
        """Get session information from the sidebar.

        Returns:
            Session timeout info text or None
        """
        sidebar = self.page.locator("[data-testid='stSidebar']")
        session_info = sidebar.locator(":has-text('Session')")
        if session_info.count() == 0:
            return None
        return session_info.first.text_content()

    def click_logout(self) -> None:
        """Click the logout button in the sidebar."""
        sidebar = self.page.locator("[data-testid='stSidebar']")
        logout_button = sidebar.locator("button:has-text('Logout')")
        logout_button.click()

    def wait_for_metrics_loaded(self, timeout: int = 15000) -> None:
        """Wait for metrics to be loaded.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        self.page.wait_for_selector("[data-testid='stMetric']", timeout=timeout)
        self.wait_for_data_loaded(timeout)
