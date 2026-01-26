"""Tests for log sanitizer utility."""

import pytest

from portainer_dashboard.services.log_sanitizer import sanitize_logs


class TestSanitizeLogs:
    """Tests for the sanitize_logs function."""

    def test_empty_logs(self):
        """Empty logs should return empty string."""
        assert sanitize_logs("") == ""
        assert sanitize_logs(None) is None

    def test_logs_without_secrets(self):
        """Logs without secrets should remain unchanged."""
        logs = "INFO: Application started successfully\nDEBUG: Processing request"
        assert sanitize_logs(logs) == logs

    def test_redacts_api_keys(self):
        """API keys should be redacted."""
        logs = "api_key=abc123def456ghi789jkl012mno345"
        result = sanitize_logs(logs)
        assert "abc123" not in result
        assert "***REDACTED***" in result

    def test_redacts_bearer_tokens(self):
        """Bearer tokens should be redacted."""
        logs = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = sanitize_logs(logs)
        assert "eyJhbGciOiJIUzI1NiI" not in result
        assert "***REDACTED***" in result or "***JWT_REDACTED***" in result

    def test_redacts_passwords(self):
        """Passwords should be redacted."""
        logs = "Connecting with password=mysecretpassword123\nDB_PASSWORD=anotherpassword"
        result = sanitize_logs(logs)
        assert "mysecretpassword123" not in result
        assert "anotherpassword" not in result
        assert "***REDACTED***" in result

    def test_redacts_connection_strings(self):
        """Database connection strings should have passwords redacted."""
        logs = "postgres://user:secretpass@localhost:5432/db"
        result = sanitize_logs(logs)
        assert "secretpass" not in result
        assert "***REDACTED***" in result

    def test_redacts_aws_keys(self):
        """AWS access keys should be redacted."""
        logs = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        result = sanitize_logs(logs)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "***REDACTED***" in result or "***AWS_KEY_REDACTED***" in result

    def test_redacts_jwt_tokens(self):
        """JWT tokens should be redacted."""
        # Test a standalone JWT (not preceded by token=)
        logs = "Auth header contains eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature123 value"
        result = sanitize_logs(logs)
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "***JWT_REDACTED***" in result

    def test_redacts_private_keys(self):
        """Private keys should be redacted."""
        logs = """Loading key:
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC
-----END PRIVATE KEY-----
Done"""
        result = sanitize_logs(logs)
        assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC" not in result
        assert "***PRIVATE_KEY_REDACTED***" in result

    def test_redacts_ssh_keys(self):
        """SSH keys should be redacted."""
        logs = "Loaded key: ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDn user@host"
        result = sanitize_logs(logs)
        assert "AAAAB3NzaC1yc2EAAAADAQABAAABAQDn" not in result
        assert "***REDACTED***" in result

    def test_preserves_error_messages(self):
        """Error messages and stack traces should be preserved."""
        logs = """ERROR: Connection refused to database
Traceback (most recent call last):
  File "app.py", line 42, in connect
    raise ConnectionError("Failed to connect")
ConnectionError: Failed to connect"""
        result = sanitize_logs(logs)
        assert "Connection refused" in result
        assert "Traceback" in result
        assert "ConnectionError" in result

    def test_multiple_secrets_in_same_log(self):
        """Multiple secrets in the same log should all be redacted."""
        logs = "password=secret1 api_key=abcdefghijklmnopqrstuvwxyz token=xyz123"
        result = sanitize_logs(logs)
        assert "secret1" not in result
        assert "abcdefghijklmnopqrstuvwxyz" not in result
        assert "xyz123" not in result
        assert result.count("***REDACTED***") >= 2
