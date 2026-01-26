"""E2E test fixtures for Playwright-based testing."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Test environment configuration - can be overridden via environment variables
TEST_FRONTEND_URL = os.environ.get("E2E_FRONTEND_URL", "http://localhost:8503")
TEST_USERNAME = os.environ.get("E2E_USERNAME", "testuser")
TEST_PASSWORD = os.environ.get("E2E_PASSWORD", "testpass")

# Timeout settings (in milliseconds)
DEFAULT_TIMEOUT = 15000
STREAMLIT_LOAD_TIMEOUT = 30000


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Configure browser context for E2E tests."""
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


@pytest.fixture
def page(page: "Page") -> "Page":
    """Configure page with default timeouts."""
    page.set_default_timeout(DEFAULT_TIMEOUT)
    page.set_default_navigation_timeout(STREAMLIT_LOAD_TIMEOUT)
    return page


@pytest.fixture
def authenticated_page(page: "Page") -> "Page":
    """Login and return authenticated page.

    Navigates to the frontend, logs in with test credentials,
    and waits for the dashboard to fully load.
    """
    # Navigate to login page
    page.goto(TEST_FRONTEND_URL)

    # Wait for Streamlit to load
    page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=STREAMLIT_LOAD_TIMEOUT)

    # Fill login form - Streamlit uses aria-label for input identification
    username_input = page.locator("input[aria-label='Username']")
    password_input = page.locator("input[aria-label='Password']")

    # Wait for login form to be visible
    username_input.wait_for(state="visible", timeout=DEFAULT_TIMEOUT)

    username_input.fill(TEST_USERNAME)
    password_input.fill(TEST_PASSWORD)

    # Click login button
    page.click("button:has-text('Login')")

    # Wait for dashboard to load (look for main dashboard elements)
    page.wait_for_selector("text=Portainer Dashboard", timeout=STREAMLIT_LOAD_TIMEOUT)

    # Wait for any initial spinners to disappear
    page.wait_for_selector(".stSpinner", state="hidden", timeout=STREAMLIT_LOAD_TIMEOUT)

    return page


@pytest.fixture
def base_url() -> str:
    """Return the frontend base URL."""
    return TEST_FRONTEND_URL


def wait_for_streamlit_ready(page: "Page", timeout: int = STREAMLIT_LOAD_TIMEOUT) -> None:
    """Wait for Streamlit app to be fully loaded and interactive.

    Args:
        page: Playwright page object
        timeout: Maximum time to wait in milliseconds
    """
    # Wait for main container
    page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=timeout)

    # Wait for any spinners to disappear
    page.wait_for_selector(".stSpinner", state="hidden", timeout=timeout)

    # Wait for skeleton loaders to disappear
    page.wait_for_selector("[data-testid='stSkeleton']", state="hidden", timeout=timeout)


def wait_for_toast_message(page: "Page", timeout: int = DEFAULT_TIMEOUT) -> str | None:
    """Wait for and return a toast message.

    Args:
        page: Playwright page object
        timeout: Maximum time to wait in milliseconds

    Returns:
        Toast message text or None if no toast appears
    """
    try:
        toast = page.wait_for_selector("[data-testid='stToast']", timeout=timeout)
        return toast.text_content() if toast else None
    except Exception:
        return None
