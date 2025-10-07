from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import backup_scheduler


def _fixed_time(year=2024, month=1, day=1, hour=12, minute=0, second=0):
    return _dt.datetime(
        year, month, day, hour, minute, second, tzinfo=_dt.timezone.utc
    )


def test_scheduler_initialises_state(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "2h")
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: _fixed_time())

    generated = backup_scheduler.maybe_run_scheduled_backups([])

    assert generated == []
    schedule_path = backup_scheduler.schedule_state_path()
    assert schedule_path.exists()
    payload = json.loads(schedule_path.read_text("utf-8"))
    assert payload["interval_seconds"] == 7200
    assert payload["next_run"] > 0
    assert payload["history"] == []


def test_scheduler_runs_when_due(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "10s")

    environment = {"name": "Production", "api_url": "https://api", "api_key": "token"}
    created: list[Path] = []

    def _fake_backup(env):
        destination = tmp_path / f"backup-{len(created)}.tar"
        destination.write_text(env["name"])
        created.append(destination)
        return destination

    monkeypatch.setattr(backup_scheduler, "create_environment_backup", _fake_backup)

    start = _fixed_time()
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: start)
    backup_scheduler.maybe_run_scheduled_backups([environment])

    later = start + _dt.timedelta(seconds=11)
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: later)
    generated = backup_scheduler.maybe_run_scheduled_backups([environment])

    assert generated == created
    assert generated[0].read_text("utf-8") == "Production"

    snapshot = backup_scheduler.get_schedule_snapshot()
    assert snapshot.history
    latest = snapshot.history[0]
    assert latest.generated_paths[0].read_text("utf-8") == "Production"
    assert latest.errors == ()
    assert latest.status == "completed"
    assert snapshot.managed_by_env is True
    assert snapshot.env_value == "10s"
    assert snapshot.env_parse_error is None

    after = later + _dt.timedelta(seconds=5)
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: after)
    assert backup_scheduler.maybe_run_scheduled_backups([environment]) == []


def test_scheduler_clears_state_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "30m")
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: _fixed_time())
    backup_scheduler.maybe_run_scheduled_backups([])

    schedule_path = backup_scheduler.schedule_state_path()
    assert schedule_path.exists()

    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "0")
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: _fixed_time(hour=15))
    assert backup_scheduler.maybe_run_scheduled_backups([]) == []
    snapshot = backup_scheduler.get_schedule_snapshot()
    assert snapshot.interval_seconds == 0
    assert snapshot.next_run is None


def test_update_schedule_interval_persists_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.delenv("PORTAINER_BACKUP_INTERVAL", raising=False)
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: _fixed_time())

    snapshot = backup_scheduler.update_schedule_interval(3600)
    assert snapshot.interval_seconds == 3600
    assert snapshot.next_run is not None
    assert snapshot.managed_by_env is False
    assert snapshot.env_value is None

    reloaded = backup_scheduler.get_schedule_snapshot()
    assert reloaded.interval_seconds == 3600
    assert reloaded.next_run is not None
    assert reloaded.managed_by_env is False
    assert reloaded.env_value is None

    backup_scheduler.update_schedule_interval(0)
    disabled = backup_scheduler.get_schedule_snapshot()
    assert disabled.interval_seconds == 0
    assert disabled.managed_by_env is False
    assert disabled.env_value is None


def test_snapshot_reports_environment_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "45m")
    monkeypatch.setattr(backup_scheduler, "_utcnow", lambda: _fixed_time())

    snapshot = backup_scheduler.get_schedule_snapshot()

    assert snapshot.managed_by_env is True
    assert snapshot.env_value == "45m"
    assert snapshot.env_parse_error is None
    assert snapshot.interval_seconds == 2700
    assert snapshot.next_run is not None


def test_snapshot_reports_invalid_environment_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "bogus")

    snapshot = backup_scheduler.get_schedule_snapshot()

    assert snapshot.managed_by_env is True
    assert snapshot.env_value == "bogus"
    assert snapshot.env_parse_error is not None
    assert snapshot.interval_seconds == 0
    assert snapshot.next_run is None


def test_update_schedule_rejected_when_env_variable_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("PORTAINER_BACKUP_INTERVAL", "30m")

    with pytest.raises(RuntimeError):
        backup_scheduler.update_schedule_interval(600)
