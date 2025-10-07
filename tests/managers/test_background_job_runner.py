from __future__ import annotations

from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.managers.background_job_runner import BackgroundJobRunner


def test_maybe_run_backups_invokes_runner():
    calls: list[list[dict[str, Any]]] = []

    def fake_runner(environments):
        calls.append(list(environments))

    runner = BackgroundJobRunner(backup_runner=fake_runner)
    payload = [{"name": "Prod"}]

    runner.maybe_run_backups(payload)

    assert calls == [payload]


def test_maybe_run_backups_logs_exception(caplog):
    def failing_runner(environments):  # pragma: no cover - exercised via logging assertion
        raise RuntimeError("boom")

    runner = BackgroundJobRunner(backup_runner=failing_runner)

    with caplog.at_level("WARNING"):
        runner.maybe_run_backups([{"name": "Prod"}])

    assert any("Scheduled backup execution failed" in record.message for record in caplog.records)
