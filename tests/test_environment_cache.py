import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import CacheConfig
from app import environment_cache


def test_store_cache_entry_is_atomic_under_concurrency(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_CACHE_ENABLED", "1")
    monkeypatch.setenv("PORTAINER_CACHE_DIR", str(tmp_path))

    key = "concurrent-key"
    config = CacheConfig(enabled=True, ttl_seconds=900, directory=tmp_path)
    writers = 5
    barrier = threading.Barrier(writers)

    def _write_payload(index: int) -> None:
        barrier.wait()
        environment_cache.store_cache_entry(config, key, {"value": index})

    with ThreadPoolExecutor(max_workers=writers) as executor:
        futures = [executor.submit(_write_payload, i) for i in range(writers)]
        for future in futures:
            future.result(timeout=2)

    entry = environment_cache.load_cache_entry(config, key)
    assert entry is not None
    assert entry.payload["value"] in set(range(writers))

    payload = json.loads((tmp_path / f"{key}.json").read_text("utf-8"))
    assert isinstance(payload.get("payload"), dict)


def test_cache_read_waits_until_write_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAINER_CACHE_ENABLED", "1")
    monkeypatch.setenv("PORTAINER_CACHE_DIR", str(tmp_path))

    key = "slow-key"
    config = CacheConfig(enabled=True, ttl_seconds=900, directory=tmp_path)
    partial_written = threading.Event()
    allow_completion = threading.Event()

    original_write_text = Path.write_text

    def _slow_write(self: Path, text: str, encoding: str | None = None, errors: str | None = None):
        if self.parent == tmp_path and self.suffix == ".json":
            midpoint = max(1, len(text) // 2)
            original_write_text(self, text[:midpoint], encoding=encoding, errors=errors)
            partial_written.set()
            allow_completion.wait(timeout=1)
            return original_write_text(self, text, encoding=encoding, errors=errors)
        return original_write_text(self, text, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "write_text", _slow_write)

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer = executor.submit(
            environment_cache.store_cache_entry, config, key, {"value": "payload"}
        )
        assert partial_written.wait(timeout=1)
        reader = executor.submit(environment_cache.load_cache_entry, config, key)
        time.sleep(0.1)
        assert not reader.done()
        allow_completion.set()
        result = reader.result(timeout=1)
        writer.result(timeout=1)

    assert result is not None
    assert result.payload["value"] == "payload"
