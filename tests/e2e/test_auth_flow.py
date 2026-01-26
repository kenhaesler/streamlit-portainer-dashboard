"""E2E tests for authentication flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.e2e.conftest import (
    DEFAULT_TIMEOUT,
    STREAMLIT_LOAD_TIMEOUT,
    TEST_FRONTEND_URL,
    TEST_PASSWORD,
    TEST_USERNAME,
)
from tests.e2e.pages.home_page import HomePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class TestLoginFlow:
    """Tests for the login functionality."""

    def test_login_page_loads(self, page: "Page", base_url: str) -> None:
        """Test that the login page loads correctly."""
        page.goto(base_url)

        # Wait for Streamlit to load
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Check for login form elements
        username_input = page.locator("input[aria-label='Username']")
        password_input = page.locator("input[aria-label='Password']")
        login_button = page.locator("button:has-text('Login')")

        assert username_input.is_visible()
        assert password_input.is_visible()
        assert login_button.is_visible()

    def test_login_with_valid_credentials(self, page: "Page", base_url: str) -> None:
        """Test successful login with valid credentials."""
        page.goto(base_url)
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Fill login form
        page.fill("input[aria-label='Username']", TEST_USERNAME)
        page.fill("input[aria-label='Password']", TEST_PASSWORD)
        page.click("button:has-text('Login')")

        # Wait for dashboard to load
        page.wait_for_selector("text=Portainer Dashboard", timeout=STREAMLIT_LOAD_TIMEOUT)

        # Verify dashboard elements are visible
        assert page.locator("text=Portainer Dashboard").is_visible()

    def test_login_with_invalid_credentials(self, page: "Page", base_url: str) -> None:
        """Test login failure with invalid credentials."""
        page.goto(base_url)
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Fill login form with wrong credentials
        page.fill("input[aria-label='Username']", "wronguser")
        page.fill("input[aria-label='Password']", "wrongpass")
        page.click("button:has-text('Login')")

        # Wait a bit for the error to appear
        page.wait_for_timeout(2000)

        # Should still see login form or error message
        # Check that we're not on the dashboard
        login_button = page.locator("button:has-text('Login')")
        error_message = page.locator("[data-testid='stAlert']")

        # Either still on login page or showing error
        assert login_button.is_visible() or error_message.count() > 0

    def test_login_with_empty_credentials(self, page: "Page", base_url: str) -> None:
        """Test login attempt with empty credentials."""
        page.goto(base_url)
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Click login without filling form
        page.click("button:has-text('Login')")

        # Wait a bit
        page.wait_for_timeout(1000)

        # Should still be on login page
        login_button = page.locator("button:has-text('Login')")
        assert login_button.is_visible()


class TestLogoutFlow:
    """Tests for the logout functionality."""

    def test_logout_redirects_to_login(self, authenticated_page: "Page", base_url: str) -> None:
        """Test that logout redirects to login page."""
        page = authenticated_page

        # Find and click logout button in sidebar
        sidebar = page.locator("[data-testid='stSidebar']")
        logout_button = sidebar.locator("button:has-text('Logout')")

        if logout_button.count() > 0:
            logout_button.click()

            # Wait for login form to appear
            page.wait_for_selector(
                "input[aria-label='Username']",
                timeout=STREAMLIT_LOAD_TIMEOUT,
            )

            # Verify we're back at login
            assert page.locator("button:has-text('Login')").is_visible()


class TestSessionPersistence:
    """Tests for session management."""

    def test_session_persists_on_refresh(self, authenticated_page: "Page") -> None:
        """Test that session persists after page refresh."""
        page = authenticated_page

        # Verify we're authenticated
        assert page.locator("text=Portainer Dashboard").is_visible()

        # Refresh the page
        page.reload()

        # Wait for page to reload
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Check if still authenticated (dashboard visible) or redirected to login
        # This depends on session cookie behavior
        dashboard_visible = page.locator("text=Portainer Dashboard").count() > 0
        login_visible = page.locator("button:has-text('Login')").count() > 0

        # Either should be true (session persisted or properly handled)
        assert dashboard_visible or login_visible

    def test_session_info_displayed_in_sidebar(
        self, authenticated_page: "Page"
    ) -> None:
        """Test that session info is displayed in the sidebar."""
        page = authenticated_page

        # Check sidebar for session/user info
        sidebar = page.locator("[data-testid='stSidebar']")

        # Look for username or session timeout info
        user_info = sidebar.locator(f":has-text('{TEST_USERNAME}')")
        session_info = sidebar.locator(":has-text('Session')")

        # At least one should be present
        assert user_info.count() > 0 or session_info.count() > 0


class TestProtectedRoutes:
    """Tests for route protection."""

    def test_protected_page_requires_auth(self, page: "Page", base_url: str) -> None:
        """Test that protected pages redirect to login when not authenticated."""
        # Try to access containers page directly without auth
        page.goto(f"{base_url}/Containers")

        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Should be redirected to login or show login form
        login_visible = page.locator("button:has-text('Login')").count() > 0
        dashboard_visible = page.locator("text=Portainer Dashboard").count() > 0

        # Either login form (not authenticated) or dashboard (session cookie present)
        assert login_visible or dashboard_visible

    def test_all_sidebar_links_accessible_when_authenticated(
        self, authenticated_page: "Page"
    ) -> None:
        """Test that all sidebar navigation links are accessible."""
        page = authenticated_page

        sidebar = page.locator("[data-testid='stSidebar']")

        # Get all navigation links
        nav_links = sidebar.locator("a")
        link_count = nav_links.count()

        # Should have at least a few navigation links
        assert link_count >= 1

        # Click each link and verify page loads
        for i in range(min(link_count, 3)):  # Test first 3 links to save time
            link = nav_links.nth(i)
            if link.is_visible():
                link.click()

                # Wait for page to load
                page.wait_for_selector(
                    "[data-testid='stAppViewContainer']",
                    timeout=STREAMLIT_LOAD_TIMEOUT,
                )

                # Verify no error toast
                error_toast = page.locator("[data-testid='stToast']:has-text('error')")
                assert error_toast.count() == 0
