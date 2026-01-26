"""Containers Page Object for Streamlit dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class ContainersPage(BasePage):
    """Page Object for the Containers page."""

    PAGE_PATH = "Containers"

    def __init__(self, page: "Page", base_url: str) -> None:
        """Initialize the containers page.

        Args:
            page: Playwright page object
            base_url: Base URL of the Streamlit application
        """
        super().__init__(page, base_url)

    def navigate(self) -> None:
        """Navigate to the containers page."""
        self.click_sidebar_link("Containers")

    def get_containers_table(self) -> "Locator":
        """Get the containers data table.

        Returns:
            Locator for the containers table
        """
        return self.get_dataframe(0)

    def get_container_count(self) -> int:
        """Get the number of containers displayed in the table.

        Returns:
            Number of container rows
        """
        table = self.get_containers_table()
        # Count rows in the table (excluding header)
        rows = table.locator("tr")
        return rows.count() - 1 if rows.count() > 0 else 0

    def filter_by_state(self, state: str) -> None:
        """Filter containers by state.

        Args:
            state: State to filter by (e.g., "running", "stopped")
        """
        self.select_option("State", state)
        self.wait_for_data_loaded()

    def search_container(self, search_term: str) -> None:
        """Search for containers by name or image.

        Args:
            search_term: Search term to filter containers
        """
        search_input = self.page.locator("input[aria-label='Search containers']")
        if search_input.count() > 0:
            search_input.fill(search_term)
            self.wait_for_data_loaded()

    def click_container_row(self, container_name: str) -> None:
        """Click on a container row to view details.

        Args:
            container_name: Name of the container to click
        """
        row = self.page.locator(f"tr:has-text('{container_name}')")
        if row.count() > 0:
            row.first.click()

    def is_container_details_visible(self) -> bool:
        """Check if container details panel is visible.

        Returns:
            True if details panel is displayed
        """
        # Look for details section indicators
        return (
            self.page.locator(":has-text('Environment')").count() > 0
            or self.page.locator(":has-text('Networks')").count() > 0
            or self.page.locator(":has-text('Mounts')").count() > 0
        )

    def get_container_details_tabs(self) -> list[str]:
        """Get available tabs in container details.

        Returns:
            List of tab names
        """
        tabs = self.page.locator("[data-testid='stTab']")
        return [tab.text_content() or "" for tab in tabs.all()]

    def click_details_tab(self, tab_name: str) -> None:
        """Click a tab in the container details section.

        Args:
            tab_name: Name of the tab to click
        """
        self.click_tab(tab_name)

    def get_health_alerts_count(self) -> int:
        """Get the number of health alerts displayed.

        Returns:
            Number of health alerts
        """
        alerts = self.page.locator("[data-testid='stAlert']")
        return alerts.count()

    def has_running_containers(self) -> bool:
        """Check if there are running containers displayed.

        Returns:
            True if running containers are present
        """
        return self.page.locator(":has-text('running')").count() > 0

    def has_stopped_containers(self) -> bool:
        """Check if there are stopped containers displayed.

        Returns:
            True if stopped containers are present
        """
        return (
            self.page.locator(":has-text('stopped')").count() > 0
            or self.page.locator(":has-text('exited')").count() > 0
        )

    def get_endpoint_filter_options(self) -> list[str]:
        """Get available endpoint filter options.

        Returns:
            List of endpoint names in the filter
        """
        selectbox = self.page.locator("[data-testid='stSelectbox']:has-text('Endpoint')")
        if selectbox.count() == 0:
            return []
        selectbox.click()
        options = self.page.locator("[role='option']")
        option_texts = [opt.text_content() or "" for opt in options.all()]
        # Close dropdown by clicking elsewhere
        self.page.keyboard.press("Escape")
        return option_texts

    def filter_by_endpoint(self, endpoint_name: str) -> None:
        """Filter containers by endpoint.

        Args:
            endpoint_name: Name of the endpoint to filter by
        """
        self.select_option("Endpoint", endpoint_name)
        self.wait_for_data_loaded()

    def get_container_image(self, container_name: str) -> str | None:
        """Get the image name for a specific container.

        Args:
            container_name: Name of the container

        Returns:
            Image name or None if not found
        """
        row = self.page.locator(f"tr:has-text('{container_name}')")
        if row.count() == 0:
            return None
        # Image is typically in the second column
        cells = row.first.locator("td")
        if cells.count() >= 2:
            return cells.nth(1).text_content()
        return None
