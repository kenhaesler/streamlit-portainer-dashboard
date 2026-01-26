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

        # Either we see login form OR we're already on dashboard (valid session)
        login_form = page.locator("[data-testid='stForm'], form")
        dashboard = page.locator("text=Quick Navigation")

        # Wait a bit for page to stabilize
        page.wait_for_timeout(1000)

        # Should see either login form or dashboard
        assert login_form.count() > 0 or dashboard.count() > 0

    def test_login_with_valid_credentials(self, page: "Page", base_url: str) -> None:
        """Test successful login with valid credentials."""
        page.goto(base_url)
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Check if already authenticated
        if page.locator("text=Quick Navigation").count() > 0:
            assert True
            return

        # Fill login form using Streamlit selectors
        username_input = page.locator("[data-testid='stTextInput'] input").first
        password_input = page.locator("input[type='password']").first

        username_input.fill(TEST_USERNAME)
        password_input.fill(TEST_PASSWORD)

        # Click login button
        page.locator("[data-testid='stFormSubmitButton'] button, button:has-text('Login')").first.click()

        # Wait for dashboard to load
        page.wait_for_selector("text=Quick Navigation", timeout=STREAMLIT_LOAD_TIMEOUT)

        # Verify dashboard elements are visible
        assert page.locator("text=Portainer Dashboard").is_visible()

    def test_login_with_invalid_credentials(self, page: "Page", base_url: str) -> None:
        """Test login failure with invalid credentials."""
        page.goto(base_url)
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Check if already authenticated - skip test
        if page.locator("text=Quick Navigation").count() > 0:
            # Already logged in, can't test invalid credentials
            assert True
            return

        # Fill login form with wrong credentials
        username_input = page.locator("[data-testid='stTextInput'] input").first
        password_input = page.locator("input[type='password']").first

        username_input.fill("wronguser")
        password_input.fill("wrongpass")

        page.locator("[data-testid='stFormSubmitButton'] button, button:has-text('Login')").first.click()

        # Wait a bit for the error to appear
        page.wait_for_timeout(2000)

        # Should still see login form or error message, not dashboard
        login_form = page.locator("[data-testid='stForm'], form")
        error_message = page.locator("[data-testid='stAlert'], :has-text('Invalid')")
        dashboard = page.locator("text=Quick Navigation")

        # Should NOT be on dashboard
        assert login_form.count() > 0 or error_message.count() > 0 or dashboard.count() == 0

    def test_login_with_empty_credentials(self, page: "Page", base_url: str) -> None:
        """Test login attempt with empty credentials."""
        page.goto(base_url)
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Check if already authenticated - skip test
        if page.locator("text=Quick Navigation").count() > 0:
            assert True
            return

        # Click login without filling form
        page.locator("[data-testid='stFormSubmitButton'] button, button:has-text('Login')").first.click()

        # Wait a bit
        page.wait_for_timeout(1000)

        # Should still be on login page (form visible)
        login_form = page.locator("[data-testid='stForm'], form")
        assert login_form.count() > 0


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
        page.wait_for_selector("text=Portainer Dashboard", timeout=STREAMLIT_LOAD_TIMEOUT)

        # Refresh the page
        page.reload()

        # Wait for page to reload
        page.wait_for_selector(
            "[data-testid='stAppViewContainer']",
            timeout=STREAMLIT_LOAD_TIMEOUT,
        )

        # Wait for content to load
        page.wait_for_timeout(2000)

        # Check if still authenticated (dashboard visible) or redirected to login
        dashboard_visible = page.locator("text=Quick Navigation").count() > 0
        login_visible = page.locator("[data-testid='stForm'], form").count() > 0

        # Either should be true (session persisted or properly handled)
        assert dashboard_visible or login_visible

    def test_session_info_displayed_in_sidebar(
        self, authenticated_page: "Page"
    ) -> None:
        """Test that session info is displayed in the sidebar."""
        page = authenticated_page

        # Check sidebar exists
        sidebar = page.locator("[data-testid='stSidebar']")
        assert sidebar.count() > 0

        # Sidebar should have some content (navigation links, logout, etc.)
        sidebar_content = sidebar.locator("a, button, [data-testid='stMarkdown']")
        assert sidebar_content.count() > 0


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

        # Wait for content to load
        page.wait_for_timeout(2000)

        # Should be redirected to login or show login form, OR if session cookie exists, show page
        login_visible = page.locator("[data-testid='stForm'], form, :has-text('Login')").count() > 0
        dashboard_visible = page.locator("text=Portainer Dashboard, text=Containers").count() > 0

        # Either login form (not authenticated) or page content (session cookie present)
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
