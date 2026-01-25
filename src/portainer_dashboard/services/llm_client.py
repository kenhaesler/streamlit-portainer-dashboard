"""Async LLM client with streaming support."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from portainer_dashboard.config import LLMSettings, get_settings

LOGGER = logging.getLogger(__name__)


class LLMClientError(RuntimeError):
    """Raised when an LLM request fails."""


def _normalise_messages(
    messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = message.get("content", "")
        normalised.append({"role": role, "content": content})
    return normalised


def _coerce_content_to_text(content: object) -> str | None:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Sequence) and not isinstance(content, str):
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
        if finish_reason_normalised in {
            "length",
            "model_length",
            "context_length_exceeded",
        }:
            hint = _format_truncation_hint(payload)
            raise LLMClientError(
                "LLM API truncated the response before any text was generated. "
                "This typically means the combined prompt and expected completion exceeded the model's context window. "
                "Reduce the prompt size or request fewer tokens and try again."
                + (f" {hint}" if hint else "")
            )
        raise LLMClientError(
            f"LLM API reported finish reason '{finish_reason}' without returning any text"
        )
    raise LLMClientError("LLM API response did not contain text output")


@dataclass
class AsyncLLMClient:
    """Async client for OpenAI-compatible LLM endpoints with streaming support."""

    base_url: str
    token: str | None = None
    model: str = "gpt-oss"
    timeout: float = 60.0
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
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
        extra_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _normalise_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if extra_options:
            payload.update(extra_options)
        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
        extra_options: dict[str, Any] | None = None,
    ) -> str:
        """Send a chat completion request and return the response text."""
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_options=extra_options,
        )
        async with httpx.AsyncClient(
            timeout=self.timeout, verify=self.verify_ssl
        ) as client:
            try:
                response = await client.post(
                    self.base_url,
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise LLMClientError(f"Failed to query LLM API: {exc}") from exc
            try:
                data = response.json()
            except ValueError as exc:
                raise LLMClientError("Invalid JSON response from LLM API") from exc
            if not isinstance(data, Mapping):
                raise LLMClientError("Unexpected LLM API response format")
            return _extract_response_text(data)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 512,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion response chunks."""
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra_options=extra_options,
        )
        async with httpx.AsyncClient(
            timeout=self.timeout, verify=self.verify_ssl
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    self.base_url,
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            choices = data.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield content
            except httpx.HTTPError as exc:
                raise LLMClientError(f"Failed to stream from LLM API: {exc}") from exc


def create_llm_client(settings: LLMSettings | None = None) -> AsyncLLMClient | None:
    """Create an async LLM client from settings."""
    if settings is None:
        settings = get_settings().llm
    if not settings.api_endpoint:
        return None
    return AsyncLLMClient(
        base_url=settings.api_endpoint,
        token=settings.bearer_token,
        model=settings.model,
        timeout=float(settings.timeout),
        verify_ssl=settings.ca_bundle is None,
    )


__all__ = [
    "AsyncLLMClient",
    "LLMClientError",
    "create_llm_client",
]
