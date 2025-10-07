"""Client helpers for interacting with OpenWebUI/Ollama compatible APIs."""
from __future__ import annotations

import base64
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


def _coerce_content_to_text(content: object) -> str | None:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Sequence):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
        if parts:
            return "".join(parts).strip()
    return None


def _format_truncation_hint(payload: Mapping[str, object]) -> str | None:
    """Extract any usage metadata that can explain truncation."""

    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        prompt_tokens = usage.get("prompt_tokens") or usage.get("prompt_token_count")
        limit_tokens = (
            usage.get("prompt_tokens_limit")
            or usage.get("prompt_limit")
            or usage.get("context_window")
        )
        if isinstance(prompt_tokens, int) and prompt_tokens > 0:
            if isinstance(limit_tokens, int) and limit_tokens > 0:
                return (
                    "The request used approximately "
                    f"{prompt_tokens} prompt tokens against a {limit_tokens}-token context window."
                )
            return f"The request used approximately {prompt_tokens} prompt tokens."

    detail = payload.get("detail") or payload.get("error")
    if isinstance(detail, Mapping):
        detail_message = detail.get("message") or detail.get("detail")
        if isinstance(detail_message, str) and detail_message.strip():
            return detail_message.strip()
    if isinstance(detail, str) and detail.strip():
        return detail.strip()

    return None


def _extract_response_text(payload: Mapping[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        raise LLMClientError("LLM API response did not include any choices")
    first_choice = choices[0]
    finish_reason: str | None = None
    if isinstance(first_choice, Mapping):
        finish_reason_value = first_choice.get("finish_reason")
        if isinstance(finish_reason_value, str):
            finish_reason = finish_reason_value.strip()
        message = first_choice.get("message")
        if isinstance(message, Mapping):
            content_text = _coerce_content_to_text(message.get("content"))
            if content_text:
                return content_text
        content_text = _coerce_content_to_text(first_choice.get("text"))
        if content_text:
            return content_text
    if isinstance(first_choice, str) and first_choice.strip():
        return first_choice.strip()
    if finish_reason:
        finish_reason_normalised = finish_reason.lower()
        if finish_reason_normalised in {"length", "model_length", "context_length_exceeded"}:
            hint = _format_truncation_hint(payload)
            raise LLMClientError(
                "LLM API truncated the response before any text was generated. "
                "This typically means the combined prompt and expected completion exceeded the model's context window. "
                "Reduce the prompt size or request fewer tokens and try again."
                + (f" {hint}" if hint else "")
            )
        raise LLMClientError(
            "LLM API reported finish reason '%s' without returning any text" % finish_reason
        )
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
        if not self.token:
            return headers

        token_clean = self.token.strip()
        if not token_clean:
            return headers

        prefix = token_clean.split(" ", 1)[0].lower()
        if prefix in {"bearer", "basic"}:
            headers["Authorization"] = token_clean
            return headers

        if ":" in token_clean:
            basic_token = base64.b64encode(token_clean.encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {basic_token}"
        else:
            headers["Authorization"] = f"Bearer {token_clean}"
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

