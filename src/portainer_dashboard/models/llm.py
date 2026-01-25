"""LLM assistant models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Chat message representation."""

    role: Literal["user", "assistant", "system"]
    content: str


class QueryRequest(BaseModel):
    """A request to query the Portainer data hub."""

    query_type: Literal[
        "endpoints",
        "stacks",
        "containers",
        "container_details",
        "host_metrics",
        "volumes",
        "images",
    ]
    filters: dict[str, Any] = Field(default_factory=dict)
    columns: list[str] | None = None
    limit: int | None = None


class QueryResult(BaseModel):
    """Result of a query against the data hub."""

    query_type: str
    record_count: int
    data: list[dict[str, Any]]
    truncated: bool = False


class QueryPlan(BaseModel):
    """Plan for executing queries against the data hub."""

    queries: list[QueryRequest] = Field(default_factory=list)
    reasoning: str = ""


class ChatRequest(BaseModel):
    """Chat request payload."""

    messages: list[Message]
    max_tokens: int = 1024
    temperature: float = 0.2


class ChatResponse(BaseModel):
    """Chat response payload."""

    content: str
    finish_reason: str | None = None


class StreamChunk(BaseModel):
    """Streaming response chunk."""

    type: Literal["chunk", "done", "error"]
    content: str = ""


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "Message",
    "QueryPlan",
    "QueryRequest",
    "QueryResult",
    "StreamChunk",
]
