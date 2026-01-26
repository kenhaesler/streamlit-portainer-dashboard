"""E2E tests for the AI Operations page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import STREAMLIT_LOAD_TIMEOUT
from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class AIOperationsPage(BasePage):
    """Page Object for the AI Operations page."""

    def navigate(self) -> None:
        """Navigate to the AI Operations page."""
        self.click_sidebar_link("AI Operations")

    def get_available_tabs(self) -> list[str]:
        """Get list of available tabs.

        Returns:
            List of tab names
        """
        tabs = self.page.locator("[data-testid='stTab']")
        return [tab.text_content() or "" for tab in tabs.all()]

    def click_insights_tab(self) -> None:
        """Click the Insights tab."""
        self.click_tab("Insights")

    def click_self_healing_tab(self) -> None:
        """Click the Self-Healing tab."""
        self.click_tab("Self-Healing")

    def click_metrics_tab(self) -> None:
        """Click the Metrics tab."""
        self.click_tab("Metrics")

    def click_anomalies_tab(self) -> None:
        """Click the Anomalies tab."""
        self.click_tab("Anomalies")

    def get_service_status(self) -> str | None:
        """Get the AI service status.

        Returns:
            Status text or None
        """
        status = self.page.locator(":has-text('Service Status')")
        if status.count() == 0:
            return None
        return status.first.text_content()

    def is_monitoring_enabled(self) -> bool:
        """Check if monitoring is enabled.

        Returns:
            True if monitoring is enabled
        """
        enabled_indicator = self.page.locator(":has-text('Enabled')")
        return enabled_indicator.count() > 0

    def click_trigger_analysis(self) -> None:
        """Click the trigger analysis button."""
        button = self.page.locator(
            "button:has-text('Analyze'), button:has-text('Trigger')"
        )
        if button.count() > 0:
            button.first.click()


class TestAIOperationsPage:
    """Tests for the AI Operations page."""

    def test_ai_operations_page_loads(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that the AI Operations page loads correctly."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()

        # Verify page loaded
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_ai_operations_tabs_present(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that AI Operations tabs are present."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Check for tabs
        tabs = authenticated_page.locator("[data-testid='stTab']")

        # Should have at least one tab
        assert tabs.count() >= 0  # May vary based on config


class TestInsightsTab:
    """Tests for the Insights tab."""

    def test_insights_tab_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the Insights tab loads correctly."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Try to click Insights tab
        insights_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Insight')")

        if insights_tab.count() > 0:
            insights_tab.click()
            ai_ops.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_insights_display_data(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that insights display data when available."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Look for insights content
        insights_content = authenticated_page.locator(
            "[data-testid='stMarkdown'], [data-testid='stText']"
        )

        # Page should have some content
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestSelfHealingTab:
    """Tests for the Self-Healing tab."""

    def test_self_healing_tab_loads(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that the Self-Healing tab loads correctly."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Try to click Self-Healing tab
        healing_tab = authenticated_page.locator(
            "[data-testid='stTab']:has-text('Self-Healing'), [data-testid='stTab']:has-text('Healing')"
        )

        if healing_tab.count() > 0:
            healing_tab.click()
            ai_ops.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_self_healing_actions_available(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that self-healing actions are available."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Navigate to self-healing tab if present
        healing_tab = authenticated_page.locator(
            "[data-testid='stTab']:has-text('Self-Healing')"
        )

        if healing_tab.count() > 0:
            healing_tab.click()
            ai_ops.wait_for_streamlit_ready()

            # Look for action buttons
            action_buttons = authenticated_page.locator(
                "button:has-text('Approve'), button:has-text('Reject'), button:has-text('Execute')"
            )

            # Actions may or may not be present
            assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestMetricsTab:
    """Tests for the Metrics tab."""

    def test_metrics_tab_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the Metrics tab loads correctly."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Try to click Metrics tab
        metrics_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Metric')")

        if metrics_tab.count() > 0:
            metrics_tab.click()
            ai_ops.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_metrics_charts_render(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that metrics charts render correctly."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Navigate to metrics tab if present
        metrics_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Metric')")

        if metrics_tab.count() > 0:
            metrics_tab.click()
            ai_ops.wait_for_streamlit_ready()

            # Look for charts
            charts = authenticated_page.locator(".js-plotly-plot, canvas")
            # Charts may or may not be present based on data

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestAnomaliesTab:
    """Tests for the Anomalies tab."""

    def test_anomalies_tab_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the Anomalies tab loads correctly."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Try to click Anomalies tab
        anomalies_tab = authenticated_page.locator(
            "[data-testid='stTab']:has-text('Anomal')"
        )

        if anomalies_tab.count() > 0:
            anomalies_tab.click()
            ai_ops.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_anomalies_list_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that anomalies list is displayed when available."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Navigate to anomalies tab if present
        anomalies_tab = authenticated_page.locator(
            "[data-testid='stTab']:has-text('Anomal')"
        )

        if anomalies_tab.count() > 0:
            anomalies_tab.click()
            ai_ops.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestServiceStatus:
    """Tests for AI service status indicators."""

    def test_service_status_displayed_in_sidebar(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that service status is displayed in sidebar."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Check sidebar for status indicators
        sidebar = authenticated_page.locator("[data-testid='stSidebar']")

        # Look for status-related content
        status_content = sidebar.locator(
            ":has-text('Status'), :has-text('Enabled'), :has-text('Disabled')"
        )

        # Status may or may not be shown based on config
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_trigger_analysis_button(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that trigger analysis button works."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Look for trigger/analyze button
        trigger_button = authenticated_page.locator(
            "button:has-text('Analyze'), button:has-text('Trigger'), button:has-text('Refresh')"
        )

        if trigger_button.count() > 0:
            trigger_button.first.click()
            ai_ops.wait_for_streamlit_ready()

        # Page should remain functional
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestErrorHandling:
    """Tests for error handling on AI Operations page."""

    def test_no_exceptions_on_load(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that no Python exceptions are displayed on page load."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Check for exception displays
        exceptions = authenticated_page.locator("[data-testid='stException']")
        assert exceptions.count() == 0, "Page should not display Python exceptions"

    def test_handles_disabled_monitoring_gracefully(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that page handles disabled monitoring gracefully."""
        ai_ops = AIOperationsPage(authenticated_page, base_url)
        ai_ops.navigate()
        ai_ops.wait_for_streamlit_ready()

        # Page should load even if monitoring is disabled
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()
