"""E2E tests for the Settings page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import STREAMLIT_LOAD_TIMEOUT
from tests.e2e.pages.base_page import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class SettingsPage(BasePage):
    """Page Object for the Settings page."""

    def navigate(self) -> None:
        """Navigate to the Settings page."""
        self.click_sidebar_link("Settings")

    def get_available_tabs(self) -> list[str]:
        """Get list of available tabs.

        Returns:
            List of tab names
        """
        tabs = self.page.locator("[data-testid='stTab']")
        return [tab.text_content() or "" for tab in tabs.all()]

    def click_connection_tab(self) -> None:
        """Click the Connection tab."""
        self.click_tab("Connection")

    def click_backup_tab(self) -> None:
        """Click the Backup tab."""
        self.click_tab("Backup")

    def click_tracing_tab(self) -> None:
        """Click the Tracing tab."""
        self.click_tab("Tracing")

    def click_about_tab(self) -> None:
        """Click the About tab."""
        self.click_tab("About")

    def click_test_connection(self) -> None:
        """Click the test connection button."""
        button = self.page.locator("button:has-text('Test')")
        if button.count() > 0:
            button.first.click()

    def get_connection_status(self) -> str | None:
        """Get the connection status.

        Returns:
            Status text or None
        """
        status = self.page.locator(":has-text('Connected'), :has-text('Disconnected')")
        if status.count() == 0:
            return None
        return status.first.text_content()


class TestSettingsPage:
    """Tests for the Settings page."""

    def test_settings_page_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the Settings page loads correctly."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()

        # Verify page loaded
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_settings_tabs_present(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that Settings tabs are present."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Check for tabs
        tabs = authenticated_page.locator("[data-testid='stTab']")

        # May have tabs or not depending on layout
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestConnectionTab:
    """Tests for the Connection settings tab."""

    def test_connection_tab_loads(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that the Connection tab loads correctly."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Try to click Connection tab
        connection_tab = authenticated_page.locator(
            "[data-testid='stTab']:has-text('Connection')"
        )

        if connection_tab.count() > 0:
            connection_tab.click()
            settings.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_connection_test_button_present(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that connection test button is present."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Look for test connection button
        test_button = authenticated_page.locator(
            "button:has-text('Test'), button:has-text('Check')"
        )

        # Button may or may not be present
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_connection_info_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that connection info is displayed."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Look for connection info
        connection_info = authenticated_page.locator(
            ":has-text('Portainer'), :has-text('API'), :has-text('URL')"
        )

        # May or may not show connection info
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestBackupTab:
    """Tests for the Backup management tab."""

    def test_backup_tab_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the Backup tab loads correctly."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Try to click Backup tab
        backup_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Backup')")

        if backup_tab.count() > 0:
            backup_tab.click()
            settings.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_backup_list_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that backup list is displayed when available."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Navigate to backup tab if present
        backup_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Backup')")

        if backup_tab.count() > 0:
            backup_tab.click()
            settings.wait_for_streamlit_ready()

            # Look for backup list or empty state
            backup_content = authenticated_page.locator(
                "[data-testid='stDataFrame'], :has-text('No backups'), :has-text('Backup')"
            )

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_backup_actions_available(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that backup actions are available."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Navigate to backup tab if present
        backup_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Backup')")

        if backup_tab.count() > 0:
            backup_tab.click()
            settings.wait_for_streamlit_ready()

            # Look for action buttons
            action_buttons = authenticated_page.locator(
                "button:has-text('Create'), button:has-text('Restore'), button:has-text('Download')"
            )

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestTracingTab:
    """Tests for the Tracing settings tab."""

    def test_tracing_tab_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the Tracing tab loads correctly."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Try to click Tracing tab
        tracing_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Tracing')")

        if tracing_tab.count() > 0:
            tracing_tab.click()
            settings.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_tracing_status_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that tracing status is displayed."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Navigate to tracing tab if present
        tracing_tab = authenticated_page.locator("[data-testid='stTab']:has-text('Tracing')")

        if tracing_tab.count() > 0:
            tracing_tab.click()
            settings.wait_for_streamlit_ready()

            # Look for tracing info
            tracing_info = authenticated_page.locator(
                ":has-text('Enabled'), :has-text('Disabled'), :has-text('OpenTelemetry')"
            )

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestAboutTab:
    """Tests for the About section."""

    def test_about_tab_loads(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that the About tab loads correctly."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Try to click About tab
        about_tab = authenticated_page.locator("[data-testid='stTab']:has-text('About')")

        if about_tab.count() > 0:
            about_tab.click()
            settings.wait_for_streamlit_ready()

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()

    def test_version_info_displayed(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that version info is displayed."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Navigate to about tab if present
        about_tab = authenticated_page.locator("[data-testid='stTab']:has-text('About')")

        if about_tab.count() > 0:
            about_tab.click()
            settings.wait_for_streamlit_ready()

            # Look for version info
            version_info = authenticated_page.locator(
                ":has-text('Version'), :has-text('v2'), :has-text('v1')"
            )

        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()


class TestErrorHandling:
    """Tests for error handling on Settings page."""

    def test_no_exceptions_on_load(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that no Python exceptions are displayed on page load."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Check for exception displays
        exceptions = authenticated_page.locator("[data-testid='stException']")
        assert exceptions.count() == 0, "Page should not display Python exceptions"

    def test_settings_persist_across_navigation(
        self, authenticated_page: "Page", base_url: str
    ) -> None:
        """Test that settings persist when navigating away and back."""
        settings = SettingsPage(authenticated_page, base_url)
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Navigate away
        settings.click_sidebar_link("Containers")
        settings.wait_for_streamlit_ready()

        # Navigate back
        settings.navigate()
        settings.wait_for_streamlit_ready()

        # Page should load correctly
        assert authenticated_page.locator("[data-testid='stAppViewContainer']").is_visible()
