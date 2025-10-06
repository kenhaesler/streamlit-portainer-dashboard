"""Client helpers for interacting with OpenWebUI/Ollama compatible APIs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import requests

__all__ = ["LLMClient", "LLMClientError"]


class LLMClientError(RuntimeError):
    """Raised when an LLM request fails."""


def _normalise_messages(messages: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    normalised: list[dict[str, object]] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = message.get("content", "")
        normalised.append({"role": role, "content": content})
    return normalised


def _extract_response_text(payload: Mapping[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        raise LLMClientError("LLM API response did not include any choices")
    first_choice = choices[0]
    if isinstance(first_choice, Mapping):
        message = first_choice.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
        content = first_choice.get("text")
        if isinstance(content, str):
            return content.strip()
    if isinstance(first_choice, str):
        return first_choice.strip()
    raise LLMClientError("LLM API response did not contain text output")


@dataclass
class LLMClient:
    """Lightweight client for OpenAI-compatible LLM endpoints."""

    base_url: str
    token: str | None = None
    model: str = "gpt-oss"
    timeout: tuple[float, float] = (10.0, 60.0)
    verify_ssl: bool = True

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token.strip()}"
        return headers

    def _payload(
        self,
        messages: Iterable[Mapping[str, object]],
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
        extra_options: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _normalise_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if extra_options:
            payload.update(dict(extra_options))
        return payload

    def chat(
        self,
        messages: Iterable[Mapping[str, object]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
        stream: bool = False,
        extra_options: Mapping[str, object] | None = None,
    ) -> str:
        """Send a chat completion request and return the first response text."""

        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            extra_options=extra_options,
        )
        try:
            response = requests.post(
                self.base_url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise LLMClientError(f"Failed to query LLM API: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:  # pragma: no cover - unexpected payload
            raise LLMClientError("Invalid JSON response from LLM API") from exc
        if not isinstance(data, Mapping):
            raise LLMClientError("Unexpected LLM API response format")
        return _extract_response_text(data)

