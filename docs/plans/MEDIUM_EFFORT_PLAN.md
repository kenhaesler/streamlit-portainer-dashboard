# Medium Effort Features Plan

This document outlines implementation plans for medium-effort features identified during the codebase review.

## 1. Dedicated Metrics Dashboard Page

### Overview
Create a new Streamlit page (`7_Metrics.py`) that visualizes time-series CPU and memory metrics. The backend API already exists (`/api/v1/metrics/`), but there's no dedicated frontend visualization.

### Implementation Steps

1. **Create new page** `streamlit_ui/pages/7_Metrics.py`
   - Add to navigation after AI Operations

2. **API Client Methods** in `streamlit_ui/api_client.py`
   ```python
   def get_metrics_status() -> dict
   def get_metrics_dashboard() -> dict
   def get_container_metrics(container_id: str, hours: int = 24) -> list
   def get_container_metrics_summary(container_id: str) -> dict
   def get_anomalies(hours: int = 24) -> list
   ```

3. **Page Layout**
   - **Header**: Metrics collection status, last update time
   - **KPI Row**: Total containers monitored, anomalies detected, avg CPU, avg memory
   - **Container Selector**: Dropdown to pick container for detailed view
   - **Time Range Selector**: 1h, 6h, 24h, 7d options
   - **Charts**:
     - Line chart: CPU % over time (Plotly)
     - Line chart: Memory % over time (Plotly)
     - Anomaly markers overlaid on charts
   - **Anomaly Table**: List of detected anomalies with severity

4. **Data Flow**
   ```
   User selects container + time range
       → API call to /api/v1/metrics/containers/{id}
       → Transform to DataFrame
       → Render Plotly line charts
       → Overlay anomaly points from /api/v1/metrics/containers/{id}/anomalies
   ```

### Files to Create/Modify
- `streamlit_ui/pages/7_Metrics.py` (new)
- `streamlit_ui/api_client.py` (add methods)

### Estimated Complexity
- Frontend: ~200 lines
- Backend: Already exists

---

## 2. Global Search

### Overview
Add a search bar in the sidebar or header that searches across containers, stacks, and endpoints. Results link to the relevant detail pages.

### Implementation Steps

1. **Backend Search Endpoint** `src/portainer_dashboard/api/v1/search.py`
   ```python
   @router.get("/")
   async def search(
       q: str,
       types: list[str] = Query(default=["containers", "stacks", "endpoints"])
   ) -> SearchResults
   ```
   - Query cached data (containers, stacks, endpoints)
   - Return unified results with type, name, id, endpoint_id

2. **Search Results Model** `src/portainer_dashboard/models/search.py`
   ```python
   class SearchResult(BaseModel):
       type: Literal["container", "stack", "endpoint"]
       name: str
       id: str
       endpoint_id: int | None
       endpoint_name: str | None
       status: str | None

   class SearchResults(BaseModel):
       query: str
       results: list[SearchResult]
       total: int
   ```

3. **Frontend Search Component** in `streamlit_ui/shared.py`
   - Add search input to sidebar
   - Debounced search (300ms delay)
   - Display results in expandable section
   - Click result to navigate to detail page

4. **Navigation Logic**
   - Container → `/Containers` page with pre-filter
   - Stack → `/Fleet_Stacks` page with pre-filter
   - Endpoint → `/Fleet_Stacks` endpoint tab with pre-filter

### Files to Create/Modify
- `src/portainer_dashboard/api/v1/search.py` (new)
- `src/portainer_dashboard/models/search.py` (new)
- `src/portainer_dashboard/api/v1/__init__.py` (register router)
- `streamlit_ui/shared.py` (add search UI)
- `streamlit_ui/api_client.py` (add search method)

### Estimated Complexity
- Backend: ~100 lines
- Frontend: ~80 lines

---

## 3. SQLite Connection Pooling

### Overview
Currently, SQLite connections are created per-request. Add connection pooling for metrics, traces, sessions, and actions databases to improve performance under load.

### Implementation Steps

1. **Create Connection Pool Manager** `src/portainer_dashboard/core/db_pool.py`
   ```python
   import aiosqlite
   from contextlib import asynccontextmanager

   class SQLitePool:
       def __init__(self, db_path: str, pool_size: int = 5):
           self.db_path = db_path
           self.pool_size = pool_size
           self._pool: asyncio.Queue[aiosqlite.Connection] = asyncio.Queue()

       async def initialize(self):
           for _ in range(self.pool_size):
               conn = await aiosqlite.connect(self.db_path)
               await self._pool.put(conn)

       @asynccontextmanager
       async def acquire(self):
           conn = await self._pool.get()
           try:
               yield conn
           finally:
               await self._pool.put(conn)

       async def close(self):
           while not self._pool.empty():
               conn = await self._pool.get()
               await conn.close()
   ```

2. **Global Pool Registry** in `src/portainer_dashboard/core/db_pool.py`
   ```python
   class DatabasePools:
       sessions: SQLitePool | None = None
       metrics: SQLitePool | None = None
       traces: SQLitePool | None = None
       actions: SQLitePool | None = None

       @classmethod
       async def initialize(cls, data_dir: Path):
           cls.sessions = SQLitePool(data_dir / "sessions.db")
           cls.metrics = SQLitePool(data_dir / "metrics.db")
           # ... etc
           await asyncio.gather(
               cls.sessions.initialize(),
               cls.metrics.initialize(),
               # ...
           )
   ```

3. **Integrate with Lifespan** in `main.py`
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       await DatabasePools.initialize(settings.data_dir)
       yield
       await DatabasePools.close()
   ```

4. **Update Services** to use pooled connections
   - `core/session.py` → use `DatabasePools.sessions`
   - `services/metrics_collector.py` → use `DatabasePools.metrics`
   - `core/telemetry.py` → use `DatabasePools.traces`
   - `services/remediation_service.py` → use `DatabasePools.actions`

### Files to Create/Modify
- `src/portainer_dashboard/core/db_pool.py` (new)
- `src/portainer_dashboard/main.py` (lifespan integration)
- `src/portainer_dashboard/core/session.py` (use pool)
- `src/portainer_dashboard/services/metrics_collector.py` (use pool)
- `src/portainer_dashboard/core/telemetry.py` (use pool)
- `src/portainer_dashboard/services/remediation_service.py` (use pool)

### Estimated Complexity
- New pool manager: ~100 lines
- Service updates: ~50 lines each

---

## 4. Audit Logging

### Overview
Log all user actions (login, logout, remediation approvals, backups, container actions) to a persistent store for compliance and debugging.

### Implementation Steps

1. **Audit Log Model** `src/portainer_dashboard/models/audit.py`
   ```python
   class AuditLogEntry(BaseModel):
       id: str
       timestamp: datetime
       user: str
       action: str  # login, logout, approve_action, execute_action, create_backup
       resource_type: str | None  # container, stack, endpoint
       resource_id: str | None
       details: dict | None
       ip_address: str | None
       user_agent: str | None
   ```

2. **Audit Service** `src/portainer_dashboard/services/audit_service.py`
   - SQLite storage in `.data/audit.db`
   - Async write methods
   - Query methods with filtering (user, action, date range)
   - Retention policy (auto-delete after X days)

3. **Middleware Integration** `src/portainer_dashboard/core/audit_middleware.py`
   - Capture request metadata (IP, user agent)
   - Hook into auth events
   - Decorator for audited endpoints

4. **Audit API Endpoints** `src/portainer_dashboard/api/v1/audit.py`
   ```python
   @router.get("/")
   async def get_audit_logs(
       user: str | None,
       action: str | None,
       start_date: datetime | None,
       end_date: datetime | None,
       limit: int = 100
   ) -> list[AuditLogEntry]
   ```

5. **Frontend Audit Log Viewer** in Settings page
   - Table with filtering
   - Export to CSV

### Files to Create/Modify
- `src/portainer_dashboard/models/audit.py` (new)
- `src/portainer_dashboard/services/audit_service.py` (new)
- `src/portainer_dashboard/core/audit_middleware.py` (new)
- `src/portainer_dashboard/api/v1/audit.py` (new)
- `src/portainer_dashboard/api/v1/remediation.py` (add audit calls)
- `src/portainer_dashboard/api/v1/backup.py` (add audit calls)
- `src/portainer_dashboard/auth/routes.py` (add audit calls)
- `streamlit_ui/pages/6_Settings.py` (add audit viewer)

### Estimated Complexity
- Backend: ~300 lines
- Frontend: ~100 lines

---

## Implementation Priority

1. **Metrics Dashboard** - High value, backend exists, straightforward UI work
2. **Global Search** - High usability impact, moderate complexity
3. **SQLite Connection Pooling** - Performance improvement, foundational
4. **Audit Logging** - Compliance/security, can be done incrementally

## Dependencies

- Metrics Dashboard: None
- Global Search: None
- SQLite Connection Pooling: None (but should be done before audit logging)
- Audit Logging: Benefits from SQLite connection pooling
