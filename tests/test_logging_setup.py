"""Tests for the logging configuration helpers."""
from __future__ import annotations

import logging

from app import logging_setup


def test_configure_logging_routes_levels(capfd) -> None:
    logging_setup.configure_logging(level="trace", force=True)
    logger = logging.getLogger("tests.logging")

    logger.trace("trace message")  # type: ignore[attr-defined]
    logger.debug("debug message")
    logger.info("info message")
    logger.warning("warning message")
    logger.error("error message")

    captured = capfd.readouterr()
    stdout = captured.out
    stderr = captured.err

    assert "trace message" in stdout
    assert "debug message" in stdout
    assert "info message" in stdout
    assert "warning message" in stdout
    assert "error message" in stderr
    assert "error message" not in stdout


def test_configure_logging_level_aliases(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_LOG_LEVEL", "verbose")
    logging_setup.configure_logging(force=True)

    assert logging.getLogger().level == logging.DEBUG

