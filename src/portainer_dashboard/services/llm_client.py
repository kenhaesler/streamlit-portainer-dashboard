"""Async LLM client with streaming support and connection pooling."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from portainer_dashboard.config import LLMSettings, get_settings

LOGGER = logging.getLogger(__name__)

# Retry configuration
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds
_DEFAULT_RETRY_MAX_DELAY = 10.0  # seconds
_DEFAULT_RETRY_JITTER = 0.1  # 10% jitter


def _is_retryable_error(exc: Exception) -> bool:
    """Check if an error is retryable (transient)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        # Retry on 5xx server errors and 429 rate limits
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return False


async def _retry_with_backoff[T](
    operation: str,
    func,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    base_delay: float = _DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = _DEFAULT_RETRY_MAX_DELAY,
) -> T:
    """Execute a function with exponential backoff retry.

    Args:
        operation: Description of the operation for logging
        func: Async function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)

    Returns:
        The result of the function

    Raises:
        The last exception if all retries fail
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as exc:
            last_exception = exc

            if not _is_retryable_error(exc):
                # Non-retryable error, raise immediately
                raise

            if attempt >= max_retries:
                # All retries exhausted
                LOGGER.warning(
                    "%s failed after %d attempts: %s",
                    operation,
                    attempt + 1,
                    exc,
                )
                raise

            # Calculate delay with exponential backoff and jitter
            delay = min(base_delay * (2**attempt), max_delay)
            jitter = delay * _DEFAULT_RETRY_JITTER * random.random()
            delay += jitter

            LOGGER.info(
                "%s attempt %d failed (%s), retrying in %.2fs...",
                operation,
                attempt + 1,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")

# Connection pool for LLM API clients
_DEFAULT_MAX_CONNECTIONS = 10
_DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 5
_DEFAULT_KEEPALIVE_EXPIRY = 60.0  # LLM connections can be long-lived


class LLMClientPool:
    """Connection pool manager for LLM API clients.

    Maintains pooled connections for better performance on repeated LLM API calls.
    """

    def __init__(self) -> None:
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        verify_ssl: bool = True,
    ) -> httpx.AsyncClient:
        """Get or create a pooled client for the given base URL."""
        key = base_url

        async with self._lock:
            if key not in self._clients:
                limits = httpx.Limits(
                    max_connections=_DEFAULT_MAX_CONNECTIONS,
                    max_keepalive_connections=_DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
                    keepalive_expiry=_DEFAULT_KEEPALIVE_EXPIRY,
                )
                self._clients[key] = httpx.AsyncClient(
                    timeout=timeout,
                    verify=verify_ssl,
                    limits=limits,
                )
                LOGGER.debug("Created pooled LLM client for %s", base_url)

            return self._clients[key]

    async def close_all(self) -> None:
        """Close all pooled clients."""
        async with self._lock:
            for url, client in self._clients.items():
                try:
                    await client.aclose()
                    LOGGER.debug("Closed pooled LLM client for %s", url)
                except Exception as exc:
                    LOGGER.warning("Error closing LLM client for %s: %s", url, exc)
            self._clients.clear()


# Global LLM client pool singleton
_llm_client_pool: LLMClientPool | None = None


def get_llm_client_pool() -> LLMClientPool:
    """Get or create the global LLM client pool."""
    global _llm_client_pool
    if _llm_client_pool is None:
        _llm_client_pool = LLMClientPool()
    return _llm_client_pool


async def shutdown_llm_client_pool() -> None:
    """Shutdown the global LLM client pool. Call during application shutdown."""
    global _llm_client_pool
    if _llm_client_pool is not None:
        await _llm_client_pool.close_all()
        _llm_client_pool = None


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
    """Async client for OpenAI-compatible LLM endpoints with streaming support.

    Uses connection pooling by default for better performance on repeated calls.
    """

    base_url: str
    token: str | None = None
    model: str = "gpt-oss"
    timeout: float = 60.0
    verify_ssl: bool = True
    use_pool: bool = True  # Use connection pooling by default
    _pooled_client: httpx.AsyncClient | None = field(init=False, repr=False, default=None)

    async def _get_pooled_client(self) -> httpx.AsyncClient:
        """Get a pooled client for this LLM endpoint."""
        if self._pooled_client is None:
            pool = get_llm_client_pool()
            self._pooled_client = await pool.get_client(
                self.base_url,
                timeout=self.timeout,
                verify_ssl=self.verify_ssl,
            )
        return self._pooled_client

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
        """Send a chat completion request and return the response text.

        Includes automatic retry with exponential backoff for transient errors
        (timeouts, connection errors, 5xx server errors, rate limits).
        """
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_options=extra_options,
        )

        async def _do_request() -> httpx.Response:
            if self.use_pool:
                client = await self._get_pooled_client()
                response = await client.post(
                    self.base_url,
                    headers=self._headers(),
                    json=payload,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout, verify=self.verify_ssl
                ) as client:
                    response = await client.post(
                        self.base_url,
                        headers=self._headers(),
                        json=payload,
                    )
            response.raise_for_status()
            return response

        try:
            response = await _retry_with_backoff("LLM chat request", _do_request)
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
        """Stream chat completion response chunks.

        Includes automatic retry with exponential backoff for connection errors.
        Note: Retry only applies to initial connection; mid-stream errors are not retried.
        """
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra_options=extra_options,
        )

        async def _process_stream(response) -> AsyncIterator[str]:
            """Process SSE stream and yield content chunks."""
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

        # Retry logic for initial connection with exponential backoff
        last_exception: Exception | None = None
        for attempt in range(_DEFAULT_MAX_RETRIES + 1):
            try:
                if self.use_pool:
                    client = await self._get_pooled_client()
                    async with client.stream(
                        "POST",
                        self.base_url,
                        headers=self._headers(),
                        json=payload,
                    ) as response:
                        response.raise_for_status()
                        async for chunk in _process_stream(response):
                            yield chunk
                        return  # Success, exit retry loop
                else:
                    async with httpx.AsyncClient(
                        timeout=self.timeout, verify=self.verify_ssl
                    ) as client:
                        async with client.stream(
                            "POST",
                            self.base_url,
                            headers=self._headers(),
                            json=payload,
                        ) as response:
                            response.raise_for_status()
                            async for chunk in _process_stream(response):
                                yield chunk
                            return  # Success, exit retry loop

            except httpx.HTTPError as exc:
                last_exception = exc

                if not _is_retryable_error(exc):
                    raise LLMClientError(f"Failed to stream from LLM API: {exc}") from exc

                if attempt >= _DEFAULT_MAX_RETRIES:
                    raise LLMClientError(
                        f"Failed to stream from LLM API after {attempt + 1} attempts: {exc}"
                    ) from exc

                delay = min(_DEFAULT_RETRY_BASE_DELAY * (2**attempt), _DEFAULT_RETRY_MAX_DELAY)
                jitter = delay * _DEFAULT_RETRY_JITTER * random.random()
                delay += jitter

                LOGGER.info(
                    "LLM stream attempt %d failed (%s), retrying in %.2fs...",
                    attempt + 1,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)

        # Should not reach here
        if last_exception:
            raise LLMClientError(f"Failed to stream from LLM API: {last_exception}") from last_exception


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
    "LLMClientPool",
    "create_llm_client",
    "get_llm_client_pool",
    "shutdown_llm_client_pool",
]
