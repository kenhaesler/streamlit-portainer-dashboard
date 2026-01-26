"""Base Page Object for Streamlit E2E testing."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Locator, Page


class BasePage:
    """Base class for Page Object Model pattern.

    Provides common methods for interacting with Streamlit applications.
    """

    def __init__(self, page: "Page", base_url: str) -> None:
        """Initialize the base page.

        Args:
            page: Playwright page object
            base_url: Base URL of the Streamlit application
        """
        self.page = page
        self.base_url = base_url
        self.default_timeout = 15000
        self.load_timeout = 30000

    def navigate_to(self, path: str = "") -> None:
        """Navigate to a specific path.

        Args:
            path: Path relative to base URL (e.g., "/Containers")
        """
        url = f"{self.base_url}/{path}" if path else self.base_url
        self.page.goto(url)
        self.wait_for_streamlit_ready()

    def wait_for_streamlit_ready(self, timeout: int | None = None) -> None:
        """Wait for Streamlit app to be fully loaded and interactive.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        timeout = timeout or self.load_timeout

        # Wait for main container
        self.page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=timeout,
        )

        # Wait for spinners to disappear
        self.page.wait_for_selector(".stSpinner", state="hidden", timeout=timeout)

    def wait_for_data_loaded(self, timeout: int | None = None) -> None:
        """Wait for data loading to complete.

        Args:
            timeout: Maximum time to wait in milliseconds
        """
        timeout = timeout or self.load_timeout

        # Wait for skeleton loaders
        self.page.wait_for_selector(
            "[data-testid='stSkeleton']",
            state="hidden",
            timeout=timeout,
        )

        # Wait for any spinners
        self.page.wait_for_selector(".stSpinner", state="hidden", timeout=timeout)

    def click_sidebar_link(self, link_text: str) -> None:
        """Click a link in the sidebar navigation.

        Args:
            link_text: Text of the sidebar link to click
        """
        sidebar = self.page.locator("[data-testid='stSidebar']")
        link = sidebar.locator(f"a:has-text('{link_text}')")
        link.click()
        self.wait_for_streamlit_ready()

    def click_tab(self, tab_name: str) -> None:
        """Click a Streamlit tab.

        Args:
            tab_name: Name of the tab to click
        """
        self.page.click(f"[data-testid='stTab']:has-text('{tab_name}')")
        self.wait_for_streamlit_ready()

    def get_metric_value(self, label: str) -> str | None:
        """Get the value of a Streamlit metric component.

        Args:
            label: Label text of the metric

        Returns:
            The metric value as text, or None if not found
        """
        metric = self.page.locator(f"[data-testid='stMetric']:has-text('{label}')")
        if metric.count() == 0:
            return None
        value_element = metric.locator("[data-testid='stMetricValue']")
        return value_element.text_content()

    def get_metric_delta(self, label: str) -> str | None:
        """Get the delta value of a Streamlit metric component.

        Args:
            label: Label text of the metric

        Returns:
            The metric delta as text, or None if not found
        """
        metric = self.page.locator(f"[data-testid='stMetric']:has-text('{label}')")
        if metric.count() == 0:
            return None
        delta_element = metric.locator("[data-testid='stMetricDelta']")
        if delta_element.count() == 0:
            return None
        return delta_element.text_content()

    def get_dataframe(self, index: int = 0) -> "Locator":
        """Get a Streamlit dataframe element.

        Args:
            index: Index of the dataframe (0-based)

        Returns:
            Locator for the dataframe
        """
        return self.page.locator("[data-testid='stDataFrame']").nth(index)

    def get_chart(self, index: int = 0) -> "Locator":
        """Get a Plotly chart element.

        Args:
            index: Index of the chart (0-based)

        Returns:
            Locator for the chart
        """
        return self.page.locator(".js-plotly-plot").nth(index)

    def fill_text_input(self, label: str, value: str) -> None:
        """Fill a Streamlit text input.

        Args:
            label: aria-label of the input
            value: Value to fill
        """
        input_field = self.page.locator(f"input[aria-label='{label}']")
        input_field.fill(value)

    def click_button(self, text: str) -> None:
        """Click a button by its text content.

        Args:
            text: Button text
        """
        self.page.click(f"button:has-text('{text}')")

    def select_option(self, label: str, option: str) -> None:
        """Select an option from a Streamlit selectbox.

        Args:
            label: Label of the selectbox
            option: Option text to select
        """
        # Click the selectbox to open dropdown
        selectbox = self.page.locator(f"[data-testid='stSelectbox']:has-text('{label}')")
        selectbox.click()

        # Select the option from dropdown
        self.page.click(f"[role='option']:has-text('{option}')")

    def get_toast_message(self, timeout: int = 5000) -> str | None:
        """Wait for and return a toast message.

        Args:
            timeout: Maximum time to wait in milliseconds

        Returns:
            Toast message text or None if no toast appears
        """
        try:
            toast = self.page.wait_for_selector("[data-testid='stToast']", timeout=timeout)
            return toast.text_content() if toast else None
        except Exception:
            return None

    def get_alert_message(self, alert_type: str = "error") -> str | None:
        """Get an alert/message displayed on the page.

        Args:
            alert_type: Type of alert ("error", "warning", "info", "success")

        Returns:
            Alert message text or None if not found
        """
        testid_map = {
            "error": "stAlert",
            "warning": "stAlert",
            "info": "stAlert",
            "success": "stAlert",
        }
        testid = testid_map.get(alert_type, "stAlert")
        alert = self.page.locator(f"[data-testid='{testid}']")
        if alert.count() == 0:
            return None
        return alert.first.text_content()

    def is_element_visible(self, selector: str, timeout: int = 5000) -> bool:
        """Check if an element is visible.

        Args:
            selector: CSS selector for the element
            timeout: Maximum time to wait in milliseconds

        Returns:
            True if element is visible, False otherwise
        """
        try:
            self.page.wait_for_selector(selector, state="visible", timeout=timeout)
            return True
        except Exception:
            return False

    def take_screenshot(self, name: str) -> bytes:
        """Take a screenshot of the current page.

        Args:
            name: Name for the screenshot file

        Returns:
            Screenshot bytes
        """
        return self.page.screenshot(path=f"test-results/{name}.png")
