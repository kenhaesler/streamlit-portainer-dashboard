# Performance Audit Plan

**Date:** 2026-01-26
**Status:** Proposed
**Priority:** High

---

## Executive Summary

This document outlines performance bottlenecks identified in the Streamlit-Portainer Dashboard application and provides a prioritized improvement plan. The audit covers the FastAPI backend, Streamlit frontend, caching layer, database operations, and infrastructure configuration.

### Key Findings

| Severity | Issue Count | Categories |
|----------|-------------|------------|
| Critical | 2 | HTTP connection pooling, SQLite connections |
| High | 2 | Sequential fetching, cache locking |
| Medium | 5 | In-memory caching, DataFrame ops, frontend calls |
| Low | 3 | Workers, Docker limits, logging |

---

## Critical Issues

### 1. HTTP Client Connection Pooling

**Severity:** Critical
**Files Affected:**
- `src/portainer_dashboard/services/portainer_client.py:130-139`
- `src/portainer_dashboard/services/llm_client.py:187-195`
- `streamlit_ui/api_client.py:168-179`

**Current Problem:**
A new `httpx.AsyncClient` is created for EVERY API request instead of reusing connections. This incurs:
- TCP handshake overhead per request
- TLS negotiation per request (for HTTPS)
- Connection setup latency multiplied across all Portainer environments

**Current Pattern:**
```python
# portainer_client.py
async def __aenter__(self):
    self._client = httpx.AsyncClient(...)  # New client every time
    return self

# Used in loops:
for env in environments:
    client = create_portainer_client(env)
    async with client:  # Creates new connection
        await client.list_all_endpoints()
```

**Proposed Solution:**
1. Create a shared `httpx.AsyncClient` per environment with connection pooling
2. Use application lifespan to manage client lifecycle
3. Implement a client pool/registry for multi-environment scenarios

```python
# Proposed: Client registry with connection pooling
class PortainerClientPool:
    def __init__(self):
        self._clients: dict[str, httpx.AsyncClient] = {}

    async def get_client(self, env_config: EnvironmentConfig) -> httpx.AsyncClient:
        key = env_config.api_url
        if key not in self._clients:
            self._clients[key] = httpx.AsyncClient(
                base_url=env_config.api_url,
                headers={"X-API-Key": env_config.api_key},
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._clients[key]

    async def close_all(self):
        for client in self._clients.values():
            await client.aclose()
```

**Estimated Impact:** 30-50% reduction in API call latency for sequential operations

---

### 2. SQLite Connection Management

**Severity:** Critical
**Files Affected:**
- `src/portainer_dashboard/core/session.py:144`
- `src/portainer_dashboard/services/metrics_store.py:32`
- `src/portainer_dashboard/services/actions_store.py`
- `src/portainer_dashboard/services/trace_store.py`

**Current Problem:**
New SQLite database connections are opened for EVERY database operation:

```python
# Current pattern in metrics_store.py
def _connect(self) -> sqlite3.Connection:
    return sqlite3.connect(self._db_path)  # New connection every call

def store_metrics_batch(self, metrics):
    with self._lock, self._connect() as connection:  # Opens new connection
        # ... store metrics
```

This causes:
- Connection initialization overhead per operation
- Lock contention between operations
- Thread serialization delays

**Proposed Solution:**
1. Implement connection pooling using `sqlite3` with WAL mode
2. Consider `aiosqlite` for async operations
3. Use a single connection per thread with thread-local storage

```python
# Proposed: Thread-local connection pool
import threading

class SQLiteConnectionPool:
    def __init__(self, db_path: str, max_connections: int = 5):
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _init_db(self):
        """Enable WAL mode for better concurrent reads."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.close()

    def get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
            )
        return self._local.connection
```

**Estimated Impact:** 40-60% reduction in database operation latency

---

## High Priority Issues

### 3. Sequential Data Fetching

**Severity:** High
**Files Affected:**
- `src/portainer_dashboard/services/cache_service.py:209-248`
- `src/portainer_dashboard/websocket/llm_chat.py:147-163`
- `src/portainer_dashboard/services/data_collector.py`
- `src/portainer_dashboard/services/metrics_collector.py`

**Current Problem:**
Multi-endpoint data fetching is done sequentially in loops:

```python
# Current: Sequential fetching
for env in environments:
    async with client:
        endpoints = await client.list_all_endpoints()
        for ep in endpoints:
            containers = await client.list_containers_for_endpoint(...)  # Waits each time
```

**Proposed Solution:**
Use `asyncio.gather()` for parallel fetching with optional concurrency limits:

```python
# Proposed: Parallel fetching with semaphore
async def fetch_all_containers(
    client: PortainerClient,
    endpoints: list[Endpoint],
    max_concurrent: int = 10
) -> list[Container]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_one(endpoint):
        async with semaphore:
            return await client.list_containers_for_endpoint(endpoint.id)

    results = await asyncio.gather(
        *[fetch_one(ep) for ep in endpoints],
        return_exceptions=True
    )
    return [c for r in results if not isinstance(r, Exception) for c in r]
```

**Estimated Impact:** 50-80% reduction in multi-endpoint fetch time (depends on endpoint count)

---

### 4. File-Based Cache with Blocking Locks

**Severity:** High
**Files Affected:**
- `src/portainer_dashboard/core/cache.py:73-91`

**Current Problem:**
- `FileLock` blocks with 5-second timeout on lock acquisition
- Full JSON serialization/deserialization for every cache operation
- No in-memory hot cache layer

```python
# Current: Blocking file lock
with _acquire_cache_lock(path):  # Blocks up to 5 seconds
    return _read_payload(path)   # JSON deserialization
```

**Proposed Solution:**
1. Add an in-memory LRU cache layer in front of file cache
2. Use async file I/O for non-blocking operations
3. Implement cache stampede protection

```python
# Proposed: Two-tier caching
from functools import lru_cache
from cachetools import TTLCache

class TieredCache:
    def __init__(self, max_memory_items: int = 100, memory_ttl: int = 60):
        self._memory_cache = TTLCache(maxsize=max_memory_items, ttl=memory_ttl)
        self._file_cache = FileCache()  # Existing implementation

    async def get(self, key: str) -> Any | None:
        # Check memory first (no I/O)
        if key in self._memory_cache:
            return self._memory_cache[key]

        # Fall back to file cache
        value = await self._file_cache.get(key)
        if value is not None:
            self._memory_cache[key] = value
        return value
```

**Estimated Impact:** 90% reduction in cache hit latency for hot data

---

## Medium Priority Issues

### 5. Cache Key PBKDF2 Computation

**Severity:** Medium
**File:** `src/portainer_dashboard/core/cache.py:115-143`

**Current Problem:**
PBKDF2 with 200,000 iterations runs for EVERY cache key computation:

```python
# Expensive operation per request
api_key_hash = hashlib.pbkdf2_hmac(
    "sha256",
    api_key.encode(),
    salt,
    iterations=200_000  # CPU-intensive
).hex()
```

**Proposed Solution:**
Cache the PBKDF2 result per API key (it's deterministic):

```python
@lru_cache(maxsize=32)
def _hash_api_key(api_key: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        api_key.encode(),
        b"portainer-cache-salt",
        iterations=200_000
    ).hex()
```

**Estimated Impact:** Eliminates ~50-100ms CPU time per cache operation

---

### 6. DataFrame Conversion Overhead

**Severity:** Medium
**Files Affected:**
- `src/portainer_dashboard/services/portainer_client.py:578-681`
- `src/portainer_dashboard/services/cache_service.py:206-207, 247-248`

**Current Problem:**
Large DataFrames are created even when data goes straight to cache:

```python
# Creates full DataFrame, then immediately converts to dict
df = normalise_endpoint_metadata(raw_data)
cached_data = df.to_dict("records")  # Wasteful conversion
```

**Proposed Solution:**
1. Use dict-based normalization when DataFrame features aren't needed
2. Lazy DataFrame conversion only when charting/filtering is required

```python
# Proposed: Direct dict normalization for caching
def normalise_endpoint_metadata_dict(raw_data: list[dict]) -> list[dict]:
    """Dict-based normalization - no pandas overhead."""
    return [
        {
            "id": ep.get("Id"),
            "name": ep.get("Name"),
            "status": ep.get("Status"),
            # ... other fields
        }
        for ep in raw_data
    ]
```

**Estimated Impact:** 20-40% reduction in memory usage and CPU for data normalization

---

### 7. Frontend Sequential API Calls

**Severity:** Medium
**Files Affected:**
- `streamlit_ui/api_client.py`
- `streamlit_ui/Home.py:110-113`

**Current Problem:**
Streamlit pages make sequential API calls:

```python
# Current: Sequential calls
endpoints = client.get_endpoints()     # Wait
containers = client.get_containers()   # Wait
stacks = client.get_stacks()           # Wait
```

**Proposed Solution:**
1. Create a batch endpoint on the backend
2. Or use `concurrent.futures` for parallel sync calls in Streamlit

```python
# Option A: Batch endpoint
# Backend: /api/v1/dashboard/overview
@router.get("/overview")
async def get_dashboard_overview():
    endpoints, containers, stacks = await asyncio.gather(
        cache_service.get_endpoints(),
        cache_service.get_containers(),
        cache_service.get_stacks(),
    )
    return {"endpoints": endpoints, "containers": containers, "stacks": stacks}

# Option B: Concurrent frontend calls
from concurrent.futures import ThreadPoolExecutor

def get_dashboard_data():
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            "endpoints": executor.submit(client.get_endpoints),
            "containers": executor.submit(client.get_containers),
            "stacks": executor.submit(client.get_stacks),
        }
        return {k: f.result() for k, f in futures.items()}
```

**Estimated Impact:** 40-60% reduction in page load time

---

### 8. Streamlit HTTP Client Pooling

**Severity:** Medium
**File:** `streamlit_ui/api_client.py:168-179`

**Current Problem:**
New `httpx.Client` created for each API call in Streamlit:

```python
def _get_client():
    with httpx.Client(base_url=BACKEND_URL, ...) as client:  # New each time
        yield client
```

**Proposed Solution:**
Use Streamlit session state for client reuse:

```python
def get_http_client() -> httpx.Client:
    """Get or create a reusable HTTP client."""
    if "http_client" not in st.session_state:
        st.session_state.http_client = httpx.Client(
            base_url=BACKEND_URL,
            timeout=API_TIMEOUT,
            limits=httpx.Limits(max_keepalive_connections=5),
        )
    return st.session_state.http_client
```

**Estimated Impact:** 15-25% reduction in frontend API latency

---

### 9. Cache TTL Synchronization

**Severity:** Medium
**Files Affected:**
- `streamlit_ui/api_client.py:25` (60s TTL)
- Backend cache (900s TTL)

**Current Problem:**
Frontend cache expires at 60s while backend cache is 900s, causing unnecessary API calls that still hit cached backend data.

**Proposed Solution:**
1. Align TTLs or make frontend TTL configurable
2. Consider cache headers from backend to drive frontend caching

```python
# api_client.py
STREAMLIT_CACHE_TTL = int(os.getenv("STREAMLIT_CACHE_TTL", "300"))  # Match or relate to backend
```

**Estimated Impact:** 30-50% reduction in redundant API calls

---

## Low Priority Issues

### 10. Single Worker Process

**Severity:** Low
**File:** `src/portainer_dashboard/config.py:506`

**Current:** `workers: int = 1`

**Proposed Solution:**
Scale workers based on CPU cores for production:

```python
workers: int = int(os.getenv("WORKERS", max(2, os.cpu_count() or 2)))
```

**Estimated Impact:** Linear scaling of concurrent request handling

---

### 11. Docker Resource Limits

**Severity:** Low
**File:** `docker-compose.yml`

**Proposed Addition:**
```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 1G
        reservations:
          memory: 512M

  streamlit:
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 512M
```

**Estimated Impact:** Prevents resource exhaustion, enables better orchestration

---

### 12. Tiered Timeouts

**Severity:** Low
**Files Affected:** `src/portainer_dashboard/config.py`

**Current:** All timeouts set to 60s

**Proposed:**
```python
# Tiered timeouts by operation type
ENDPOINT_LIST_TIMEOUT = 10  # Fast metadata operations
CONTAINER_STATS_TIMEOUT = 15  # Stats collection
LLM_STREAM_TIMEOUT = 120  # Long-running LLM operations
```

---

## Implementation Roadmap

### Phase 1: Critical Fixes (1-2 days effort) ✅ COMPLETED

1. [x] Implement HTTP connection pooling for `PortainerClient`
2. [x] Implement HTTP connection pooling for `LLMClient`
3. [x] Add SQLite connection pooling with WAL mode
4. [x] Cache PBKDF2 API key hashes

### Phase 2: High Impact Improvements (2-3 days effort) ✅ COMPLETED

5. [x] Add `asyncio.gather()` for parallel endpoint fetching in `cache_service.py`
6. [x] Add `asyncio.gather()` for LLM context building in `llm_chat.py`
7. [x] Implement in-memory LRU cache layer
8. [x] Create batch dashboard overview endpoint

### Phase 3: Medium Priority Optimizations (2-3 days effort) ✅ COMPLETED

9. [x] Implement dict-based normalization for caching path
10. [x] Add Streamlit HTTP client reuse via session state
11. [x] Synchronize frontend/backend cache TTLs
12. [x] Parallelize frontend API calls (via batch endpoint)

### Phase 4: Infrastructure & Configuration (1 day effort)

13. [ ] Configure worker count based on environment
14. [ ] Add Docker resource limits
15. [ ] Implement tiered timeouts
16. [ ] Add structured logging with performance metrics

---

## Metrics to Track

After implementing these changes, monitor:

1. **API Response Times:** P50, P95, P99 latencies
2. **Cache Hit Rates:** Memory cache vs file cache vs miss
3. **Connection Pool Utilization:** Active vs idle connections
4. **Database Lock Contention:** Wait time for SQLite locks
5. **Memory Usage:** Before/after comparison
6. **Page Load Times:** Streamlit page render times

---

## Testing Strategy

For each optimization:

1. **Baseline Measurement:** Record current performance metrics
2. **Unit Tests:** Ensure functionality preserved
3. **Load Tests:** Verify improvements under concurrent load
4. **Integration Tests:** Confirm end-to-end behavior
5. **Rollback Plan:** Feature flags for critical changes

---

## Conclusion

The most impactful improvements are:

1. **HTTP Connection Pooling** - Quick win with significant latency reduction
2. **Parallel Data Fetching** - Major improvement for multi-environment setups
3. **In-Memory Caching** - Eliminates I/O for hot data
4. **SQLite Connection Pooling** - Reduces contention and overhead

Implementing Phase 1 and Phase 2 changes should result in **40-70% overall performance improvement** for typical dashboard operations.
