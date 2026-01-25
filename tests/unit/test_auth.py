"""Tests for authentication module."""

from __future__ import annotations

import pytest

from portainer_dashboard.auth.static_auth import verify_credentials


class TestStaticAuth:
    """Tests for static authentication."""

    def test_verify_valid_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test verifying valid credentials."""
        monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
        monkeypatch.setenv("DASHBOARD_KEY", "secret123")

        from portainer_dashboard.config import reload_settings
        reload_settings()

        assert verify_credentials("admin", "secret123") is True

    def test_verify_invalid_username(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test verifying invalid username."""
        monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
        monkeypatch.setenv("DASHBOARD_KEY", "secret123")

        from portainer_dashboard.config import reload_settings
        reload_settings()

        assert verify_credentials("wrong", "secret123") is False

    def test_verify_invalid_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test verifying invalid password."""
        monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
        monkeypatch.setenv("DASHBOARD_KEY", "secret123")

        from portainer_dashboard.config import reload_settings
        reload_settings()

        assert verify_credentials("admin", "wrong") is False

    def test_verify_no_credentials_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test verifying when no credentials are configured."""
        monkeypatch.delenv("DASHBOARD_USERNAME", raising=False)
        monkeypatch.delenv("DASHBOARD_KEY", raising=False)

        from portainer_dashboard.config import reload_settings
        reload_settings()

        assert verify_credentials("admin", "secret123") is False
