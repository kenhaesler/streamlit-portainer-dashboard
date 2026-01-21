from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.kibana_client import KibanaClient
from app.tls import CA_BUNDLE_ENV_VAR


def test_kibana_client_uses_dashboard_ca_bundle(monkeypatch, tmp_path: Path) -> None:
    bundle = tmp_path / "ca.pem"
    bundle.write_text("cert-data")
    monkeypatch.setenv(CA_BUNDLE_ENV_VAR, str(bundle))

    client = KibanaClient(
        endpoint="https://kibana.example/_search",
        api_key="token",
        verify_ssl=True,
    )

    assert client._verify_ssl == str(bundle.resolve())
