# LLM Context Management

This document explains how the LLM assistant constructs prompts, manages context size, and streams responses.

## Overview

The LLM integration consists of three main components:

| Component | File | Responsibility |
|-----------|------|----------------|
| LLM Client | `services/llm_client.py` | HTTP client pool, streaming, retry logic |
| Chat WebSocket | `websocket/llm_chat.py` | Context building, prompt construction |
| Monitoring Service | `services/monitoring_service.py` | Automated analysis prompts |

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     WebSocket Handler                            │
│                   (llm_chat.py:llm_chat_websocket)               │
│                                                                  │
│  1. Receive user messages                                        │
│  2. Build infrastructure context                                 │
│  3. Construct system prompt with few-shot examples               │
│  4. Stream response chunks back to client                        │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Context Builder                             │
│                  (_build_context_uncached)                       │
│                                                                  │
│  - Fetch all endpoints (limit: 10 per environment)               │
│  - Fetch containers and stacks per endpoint (parallel)           │
│  - Fetch CPU/memory stats for running containers                 │
│  - Fetch logs for stopped/unhealthy/restarting containers        │
│  - Sanitize logs to remove secrets                               │
│  - Format as Markdown for LLM consumption                        │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                       LLM Client Pool                            │
│                      (llm_client.py)                             │
│                                                                  │
│  - Connection pooling (10 max, 5 keepalive)                      │
│  - Exponential backoff retry (3 attempts)                        │
│  - SSE streaming for chunk delivery                              │
│  - Bearer/Basic auth support                                     │
└──────────────────────────────────────────────────────────────────┘
```

## Context Building Process

### 1. Infrastructure Context (`_build_context_uncached`)

The context is built by fetching data from Portainer:

```python
# llm_chat.py:149-356
async def _build_context_uncached() -> str:
    # For each configured environment:
    #   1. Get ALL endpoints (not just edge)
    #   2. Limit to first 10 endpoints for context
    #   3. Fetch containers and stacks in parallel
    #   4. Fetch CPU/memory stats for running containers
    #   5. Fetch logs for problematic containers
```

**Context Structure:**
```markdown
## Environment 'production'
Total endpoints: 5 (4 online, 1 offline)
Total containers: 42 (38 running, 4 stopped)
Total stacks: 12

### Endpoints:
- **web-server-1**: online
- **web-server-2**: online
- **db-server**: online

### Containers:
- **nginx** (endpoint: web-server-1)
  - Image: nginx:1.25
  - State: running (Up 3 days)
  - CPU: 2.5%
  - Memory: 128MB / 512MB (25%)

- **failed-app** (endpoint: web-server-2)
  - Image: myapp:latest
  - State: exited (Exited (1) 5 minutes ago)
  - **Recent Logs:**
```
2024-01-15T10:30:45Z Error: Connection refused to database:5432
2024-01-15T10:30:45Z Fatal: Could not connect to PostgreSQL
```

### Stacks:
- **web-stack**: 1
- **monitoring**: 1
```

### 2. Context Caching

To reduce API load, context is cached for 30 seconds:

```python
# llm_chat.py:33-60
_CONTEXT_CACHE_TTL_SECONDS = 30.0

@dataclass
class _ContextCache:
    context: str = ""
    timestamp: float = 0.0
    lock: asyncio.Lock | None = None

    def is_valid(self) -> bool:
        return (
            self.context
            and (time.monotonic() - self.timestamp) < _CONTEXT_CACHE_TTL_SECONDS
        )
```

### 3. System Prompt Construction

The system prompt includes:

1. **Role definition**: Infrastructure management assistant
2. **Context injection**: Current infrastructure state
3. **Behavioral guidelines**: Concise, use markdown, analyze logs
4. **Few-shot examples**: Sample Q&A pairs for consistent responses

```python
# llm_chat.py:390-442
def _build_system_prompt(context: str) -> str:
    return f"""You are a helpful assistant for managing Portainer infrastructure...

{context}

When answering questions:
1. Be concise and direct
2. Use the provided infrastructure context
3. Check "Recent Logs" for stopped/unhealthy containers
...

## Example Interactions
**User:** How many containers are running?
**Assistant:** Based on the current infrastructure data...
"""
```

## Log Collection and Sanitization

### Problematic Container Detection

Logs are collected for containers in these states:
- `exited` (with non-zero exit code)
- `dead`
- `restarting`
- `unhealthy` (in status string)

```python
# llm_chat.py:264-278
for _, row in df_containers.iterrows():
    state = row.get("state", "")
    status = row.get("status", "")

    if state in ("exited", "dead", "created", "restarting"):
        stopped_container_ids.append(...)
    elif "unhealthy" in status.lower():
        stopped_container_ids.append(...)
```

### Log Sanitization

Logs are sanitized before sending to the LLM to remove potential secrets:

```python
# llm_chat.py:328-334
from portainer_dashboard.services.log_sanitizer import sanitize_logs

logs = sanitize_logs(logs)
# Truncate to last 20 lines
log_lines = logs.strip().split("\n")[-20:]
```

## Monitoring Service Prompts

The monitoring service uses a different prompt structure optimized for JSON output:

```python
# monitoring_service.py:35-83
MONITORING_SYSTEM_PROMPT = """You are an infrastructure monitoring AI...

Focus on:
1. Resource Issues: High CPU/memory usage
2. Availability: Unhealthy containers, offline endpoints
3. Security: Elevated privileges, dangerous capabilities
4. Images: Outdated images with available updates
5. Logs: Error patterns in container logs
6. Optimization: Unused resources

Respond ONLY with a valid JSON array of insight objects...
"""
```

### Analysis Prompt Construction

```python
# monitoring_service.py:86-160
def _build_analysis_prompt(snapshot: InfrastructureSnapshot) -> str:
    parts = []
    parts.append("## Infrastructure Summary")
    parts.append(f"Timestamp: {snapshot.timestamp.isoformat()}")
    parts.append(f"Endpoints: {snapshot.endpoints_online} online...")

    if snapshot.security_issues:
        parts.append("\n## Security Issues Detected")
        for issue in snapshot.security_issues:
            parts.append(f"\n### Container: {issue.container_name}")
            ...

    if snapshot.container_logs:
        parts.append("\n## Container Logs for Analysis")
        # Sanitize and limit to 3000 chars per container
        ...
```

## Streaming Implementation

### Client-Side Streaming

```python
# llm_client.py:398-496
async def stream_chat(self, messages, ...) -> AsyncIterator[str]:
    async with client.stream("POST", self.base_url, ...) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                data = json.loads(data_str)
                content = data["choices"][0]["delta"].get("content")
                if content:
                    yield content
```

### WebSocket Delivery

```python
# llm_chat.py:494-510
async for chunk in llm_client.stream_chat(full_messages, ...):
    await websocket.send_json({
        "type": "chunk",
        "content": chunk,
    })

# Signal completion
await websocket.send_json({
    "type": "done",
    "content": "",
})
```

## Retry and Error Handling

### Exponential Backoff

```python
# llm_client.py:39-100
async def _retry_with_backoff(operation, func, max_retries=3, ...):
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as exc:
            if not _is_retryable_error(exc):
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            jitter = delay * 0.1 * random.random()
            await asyncio.sleep(delay + jitter)
```

### Retryable Errors

- `httpx.TimeoutException`
- `httpx.ConnectError`
- HTTP 5xx server errors
- HTTP 429 rate limits

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_ENDPOINT` | - | Chat completions URL |
| `LLM_MODEL` | `gpt-oss` | Model identifier |
| `LLM_BEARER_TOKEN` | - | Auth token (Bearer or user:pass for Basic) |
| `LLM_MAX_TOKENS` | 200000 | Max answer length |
| `LLM_TIMEOUT` | 60 | Request timeout (seconds) |

## Limitations

1. **Context window**: Large infrastructures may exceed model limits; currently limited to 10 endpoints
2. **Log truncation**: Only last 20 lines per container in chat, 3000 chars in monitoring
3. **Cache staleness**: 30-second cache means data may be slightly outdated
4. **No conversation memory**: Each request rebuilds full context (no session persistence)
