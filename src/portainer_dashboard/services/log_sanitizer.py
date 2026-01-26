"""Log sanitization utilities to remove secrets before sending to LLM."""

from __future__ import annotations

import re

# Secret patterns to sanitize from logs before sending to LLM
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # API keys (generic patterns)
    (re.compile(r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(x-api-key|authorization)\s*[=:]\s*["\']?([a-zA-Z0-9_\-\.]+)["\']?'), r'\1=***REDACTED***'),

    # Bearer tokens
    (re.compile(r'(?i)(bearer)\s+([a-zA-Z0-9_\-\.]+)'), r'\1 ***REDACTED***'),

    # Passwords in various formats
    (re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\']+)["\']?'), r'\1=***REDACTED***'),
    (re.compile(r'(?i)(secret|token)\s*[=:]\s*["\']?([^\s"\']+)["\']?'), r'\1=***REDACTED***'),

    # Connection strings (PostgreSQL, MySQL, MongoDB, Redis)
    (re.compile(r'(?i)(postgres|postgresql|mysql|mongodb|redis)://[^:]+:([^@]+)@'), r'\1://***:***REDACTED***@'),

    # AWS credentials
    (re.compile(r'(?i)(aws_access_key_id|aws_secret_access_key)\s*[=:]\s*["\']?([a-zA-Z0-9/+=]+)["\']?'), r'\1=***REDACTED***'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '***AWS_KEY_REDACTED***'),

    # Private keys
    (re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(RSA\s+)?PRIVATE\s+KEY-----'), '***PRIVATE_KEY_REDACTED***'),

    # JWT tokens (header.payload.signature format)
    (re.compile(r'eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*'), '***JWT_REDACTED***'),

    # Generic secrets in environment variable format
    (re.compile(r'(?i)(DB_PASSWORD|DATABASE_PASSWORD|MYSQL_PASSWORD|POSTGRES_PASSWORD|REDIS_PASSWORD)\s*[=:]\s*["\']?([^\s"\']+)["\']?'), r'\1=***REDACTED***'),

    # SSH keys
    (re.compile(r'ssh-rsa\s+[A-Za-z0-9+/=]+'), 'ssh-rsa ***REDACTED***'),
    (re.compile(r'ssh-ed25519\s+[A-Za-z0-9+/=]+'), 'ssh-ed25519 ***REDACTED***'),
]


def sanitize_logs(logs: str) -> str:
    """Sanitize logs by removing potential secrets and sensitive data.

    This function applies regex patterns to detect and redact common secret
    patterns like API keys, passwords, tokens, and connection strings.

    Args:
        logs: The raw log string to sanitize

    Returns:
        The sanitized log string with secrets redacted
    """
    if not logs:
        return logs

    sanitized = logs
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized


__all__ = ["sanitize_logs"]
