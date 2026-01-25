"""Tests for configuration module."""

from __future__ import annotations

from datetime import timedelta

import pytest

from portainer_dashboard.config import (
    AuthSettings,
    CacheSettings,
    ConfigurationError,
    OIDCSettings,
    PortainerSettings,
    Settings,
    StaticAuthSettings,
    reload_settings,
)


class TestStaticAuthSettings:
    """Tests for static authentication settings."""

    def test_defaults(self) -> None:
        """Test default values."""
        settings = StaticAuthSettings()
        assert settings.username is None
        assert settings.key is None

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test loading from environment variables."""
        monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
        monkeypatch.setenv("DASHBOARD_KEY", "secret123")

        settings = StaticAuthSettings()
        assert settings.username == "admin"
        assert settings.key == "secret123"


class TestOIDCSettings:
    """Tests for OIDC settings."""

    def test_scope_list_default(self) -> None:
        """Test default scopes."""
        settings = OIDCSettings()
        assert settings.scope_list == ["openid", "profile", "email"]

    def test_scope_list_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test custom scopes."""
        monkeypatch.setenv("DASHBOARD_OIDC_SCOPES", "openid profile groups")
        settings = OIDCSettings()
        assert settings.scope_list == ["openid", "profile", "groups"]

    def test_scope_list_adds_openid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that openid is added if missing."""
        monkeypatch.setenv("DASHBOARD_OIDC_SCOPES", "profile email")
        settings = OIDCSettings()
        assert settings.scope_list[0] == "openid"

    def test_well_known_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test well-known URL generation."""
        monkeypatch.setenv("DASHBOARD_OIDC_ISSUER", "https://auth.example.com")
        settings = OIDCSettings()
        assert (
            settings.well_known_url
            == "https://auth.example.com/.well-known/openid-configuration"
        )

    def test_well_known_url_with_trailing_slash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test well-known URL with trailing slash."""
        monkeypatch.setenv("DASHBOARD_OIDC_ISSUER", "https://auth.example.com/")
        settings = OIDCSettings()
        assert (
            settings.well_known_url
            == "https://auth.example.com/.well-known/openid-configuration"
        )


class TestAuthSettings:
    """Tests for authentication settings."""

    def test_defaults(self) -> None:
        """Test default values."""
        settings = AuthSettings()
        assert settings.provider == "static"
        assert settings.session_timeout == timedelta(minutes=60)  # Default 60 min

    def test_session_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test session timeout parsing."""
        monkeypatch.setenv("DASHBOARD_SESSION_TIMEOUT_MINUTES", "30")
        settings = AuthSettings()
        assert settings.session_timeout == timedelta(minutes=30)

    def test_session_timeout_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test zero session timeout falls back to default."""
        monkeypatch.setenv("DASHBOARD_SESSION_TIMEOUT_MINUTES", "0")
        settings = AuthSettings()
        assert settings.session_timeout == timedelta(minutes=60)  # Falls back to 60 min


class TestCacheSettings:
    """Tests for cache settings."""

    def test_defaults(self) -> None:
        """Test default values."""
        settings = CacheSettings()
        assert settings.enabled is True
        assert settings.ttl_seconds == 900
        assert settings.directory is not None

    def test_custom_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test custom TTL."""
        monkeypatch.setenv("PORTAINER_CACHE_TTL_SECONDS", "600")
        settings = CacheSettings()
        assert settings.ttl_seconds == 600


class TestPortainerSettings:
    """Tests for Portainer settings."""

    def test_defaults(self) -> None:
        """Test default values."""
        settings = PortainerSettings()
        assert settings.api_url is None
        assert settings.api_key is None
        assert settings.verify_ssl is True
        assert settings.environment_name == "Default"

    def test_get_configured_environments_single(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test single environment configuration."""
        monkeypatch.setenv("PORTAINER_API_URL", "http://localhost:9000")
        monkeypatch.setenv("PORTAINER_API_KEY", "test-key")

        settings = PortainerSettings(
            api_url="http://localhost:9000",
            api_key="test-key",
        )
        envs = settings.get_configured_environments()

        assert len(envs) == 1
        assert envs[0].name == "Default"
        assert envs[0].api_url == "http://localhost:9000"


class TestSettings:
    """Tests for aggregate settings."""

    def test_oidc_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test OIDC validation when enabled."""
        monkeypatch.setenv("DASHBOARD_AUTH_PROVIDER", "oidc")

        with pytest.raises(ConfigurationError, match="issuer URL is missing"):
            Settings()

    def test_oidc_validation_with_issuer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test OIDC validation with issuer but missing client_id."""
        monkeypatch.setenv("DASHBOARD_AUTH_PROVIDER", "oidc")
        monkeypatch.setenv("DASHBOARD_OIDC_ISSUER", "https://auth.example.com")

        with pytest.raises(ConfigurationError, match="client ID is missing"):
            Settings()
