from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.llm_client import LLMClient, LLMClientError


class _DummyResponse:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - nothing to do
        return

    def json(self) -> dict[str, object]:
        return self._payload


def test_chat_returns_first_message(monkeypatch):
    """The client should extract the first message text from the response."""

    captured: dict[str, object] = {}

    def fake_post(url, *, headers=None, json=None, timeout=None, verify=None):  # type: ignore[override]
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        captured["verify"] = verify
        payload = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello from the model."},
                }
            ]
        }
        return _DummyResponse(payload)

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(
        base_url="https://example.test/v1/chat/completions",
        token="api-token",
        model="gpt-oss",
        verify_ssl=False,
    )

    response = client.chat([{"role": "user", "content": "Ping"}], temperature=0.5, max_tokens=256)

    assert response == "Hello from the model."
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer api-token"
    assert captured["json"]["temperature"] == 0.5
    assert captured["json"]["max_tokens"] == 256
    assert captured["verify"] is False


def test_chat_supports_custom_ca_bundle(monkeypatch):
    """Custom CA bundle paths should be forwarded to requests."""

    captured: dict[str, object] = {}

    def fake_post(url, *, headers=None, json=None, timeout=None, verify=None):  # type: ignore[override]
        captured["verify"] = verify
        payload = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello."},
                }
            ]
        }
        return _DummyResponse(payload)

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(base_url="https://example.test/api", verify_ssl="/etc/ssl/certs/ca.pem")

    client.chat([{"role": "user", "content": "Ping"}])

    assert captured["verify"] == "/etc/ssl/certs/ca.pem"


def test_chat_supports_basic_auth(monkeypatch):
    """Username/password tokens should be sent as HTTP Basic credentials."""

    captured: dict[str, object] = {}

    def fake_post(url, *, headers=None, json=None, timeout=None, verify=None):  # type: ignore[override]
        captured["headers"] = headers
        return _DummyResponse({
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Response"},
                }
            ]
        })

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(base_url="https://example.test/api", token="user:secret")
    client.chat([{"role": "user", "content": "Ping"}])

    expected = "Basic " + base64.b64encode(b"user:secret").decode("ascii")
    assert captured["headers"]["Authorization"] == expected


def test_chat_raises_for_missing_choices(monkeypatch):
    """An invalid payload should raise an ``LLMClientError``."""

    def fake_post(*args, **kwargs):  # type: ignore[override]
        return _DummyResponse({"choices": []})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(base_url="https://example.test/api")

    with pytest.raises(LLMClientError):
        client.chat([{"role": "user", "content": "Ping"}])


def test_chat_supports_structured_content(monkeypatch):
    """LLM responses using message content blocks should be flattened."""

    def fake_post(*args, **kwargs):  # type: ignore[override]
        return _DummyResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "Hello"},
                                {"type": "text", "text": " world"},
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(base_url="https://example.test/api")
    response = client.chat([{"role": "user", "content": "Ping"}])

    assert response == "Hello world"


def test_chat_surfaces_truncation_errors(monkeypatch):
    """Truncated responses should raise a descriptive error."""

    def fake_post(*args, **kwargs):  # type: ignore[override]
        return _DummyResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "length",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(base_url="https://example.test/api")

    with pytest.raises(LLMClientError) as excinfo:
        client.chat([{"role": "user", "content": "Ping"}])

    message = str(excinfo.value)
    assert "truncated" in message
    assert "context window" in message


def test_chat_includes_usage_hint_when_available(monkeypatch):
    """Usage metadata should be surfaced in truncation errors if provided."""

    def fake_post(*args, **kwargs):  # type: ignore[override]
        return _DummyResponse(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "prompt_tokens": 46595,
                    "prompt_tokens_limit": 8192,
                },
            }
        )

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    client = LLMClient(base_url="https://example.test/api")

    with pytest.raises(LLMClientError) as excinfo:
        client.chat([{"role": "user", "content": "Ping"}])

    message = str(excinfo.value)
    assert "46595" in message
    assert "8192" in message
