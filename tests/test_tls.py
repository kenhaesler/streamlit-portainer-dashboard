from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tls import CA_BUNDLE_ENV_VAR, get_ca_bundle_path, resolve_ca_bundle_path


def test_get_ca_bundle_path_reads_env(monkeypatch, tmp_path: Path) -> None:
    bundle = tmp_path / "ca-bundle.pem"
    bundle.write_text("cert-data")
    monkeypatch.setenv(CA_BUNDLE_ENV_VAR, str(bundle))

    assert get_ca_bundle_path() == str(bundle.resolve())


def test_get_ca_bundle_path_ignores_missing_file(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.pem"
    monkeypatch.setenv(CA_BUNDLE_ENV_VAR, str(missing))

    assert get_ca_bundle_path() is None


def test_resolve_ca_bundle_path_rejects_empty() -> None:
    assert resolve_ca_bundle_path("") is None
