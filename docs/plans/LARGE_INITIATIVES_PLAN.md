# Large Initiatives Plan

This document outlines implementation plans for larger features that require significant development effort.

## 1. Real-Time Container Updates via WebSocket

### Overview
Currently, container state is fetched on-demand via manual refresh. This initiative adds WebSocket subscriptions so the UI updates automatically when container states change.

### Architecture

```
┌─────────────────┐     WebSocket      ┌─────────────────┐
│  Streamlit UI   │◄──────────────────►│  FastAPI WS     │
│  (subscriber)   │                    │  (broadcaster)  │
└─────────────────┘                    └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │  Background     │
                                       │  Poller Task    │
                                       └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │  Portainer API  │
                                       └─────────────────┘
```

### Implementation Steps

#### Phase 1: Backend WebSocket Infrastructure

1. **Create State Change Detector** `src/portainer_dashboard/services/state_monitor.py`
   ```python
   class ContainerStateMonitor:
       def __init__(self):
           self._previous_states: dict[str, str] = {}
           self._subscribers: set[WebSocket] = set()

       async def poll_and_detect_changes(self) -> list[StateChange]:
           current = await self._fetch_all_container_states()
           changes = self._diff_states(self._previous_states, current)
           self._previous_states = current
           return changes

       async def broadcast_changes(self, changes: list[StateChange]):
           for ws in self._subscribers:
               await ws.send_json([c.model_dump() for c in changes])
   ```

2. **State Change Model** `src/portainer_dashboard/models/realtime.py`
   ```python
   class StateChange(BaseModel):
       container_id: str
       container_name: str
       endpoint_id: int
       endpoint_name: str
       previous_state: str | None
       current_state: str
       timestamp: datetime
       change_type: Literal["created", "started", "stopped", "removed", "health_changed"]
   ```

3. **WebSocket Endpoint** `src/portainer_dashboard/websocket/container_state.py`
   ```python
   @router.websocket("/ws/containers/state")
   async def container_state_stream(websocket: WebSocket):
       await websocket.accept()
       state_monitor.subscribe(websocket)
       try:
           while True:
               # Keep connection alive, changes broadcast by monitor
               await websocket.receive_text()
       except WebSocketDisconnect:
           state_monitor.unsubscribe(websocket)
   ```

4. **Background Polling Task** in scheduler
   ```python
   async def poll_container_states():
       changes = await state_monitor.poll_and_detect_changes()
       if changes:
           await state_monitor.broadcast_changes(changes)

   # Run every 5 seconds
   scheduler.add_job(poll_container_states, 'interval', seconds=5)
   ```

#### Phase 2: Frontend WebSocket Integration

5. **Streamlit WebSocket Client** `streamlit_ui/ws_client.py`
   ```python
   import streamlit as st
   from websockets.sync.client import connect

   def subscribe_to_container_state(on_change: Callable):
       """Subscribe to real-time container state changes."""
       ws_url = st.session_state.get("ws_url", "ws://localhost:8000")

       with connect(f"{ws_url}/ws/containers/state") as ws:
           while True:
               message = ws.recv()
               changes = json.loads(message)
               on_change(changes)
   ```

6. **Update Containers Page** `streamlit_ui/pages/2_Containers.py`
   - Add "Live Updates" toggle
   - When enabled, establish WebSocket connection
   - Update container table in-place when changes received
   - Show toast notifications for state changes

7. **Update Home Page** `streamlit_ui/Home.py`
   - Subscribe to state changes for KPI updates
   - Animate KPI cards when values change

#### Phase 3: Enhanced Features

8. **Notification System**
   - Toast notifications for critical changes (container stopped, unhealthy)
   - Sound alerts (optional)
   - Desktop notifications via browser API

9. **Change History Panel**
   - Rolling log of recent state changes
   - Filterable by endpoint, container, change type

### Configuration

```python
# New environment variables
REALTIME_ENABLED: bool = True
REALTIME_POLL_INTERVAL_SECONDS: int = 5
REALTIME_MAX_SUBSCRIBERS: int = 100
```

### Files to Create/Modify

**New Files:**
- `src/portainer_dashboard/services/state_monitor.py`
- `src/portainer_dashboard/models/realtime.py`
- `src/portainer_dashboard/websocket/container_state.py`
- `streamlit_ui/ws_client.py`

**Modified Files:**
- `src/portainer_dashboard/main.py` (register WS route)
- `src/portainer_dashboard/scheduler/jobs.py` (add polling job)
- `src/portainer_dashboard/config.py` (add settings)
- `streamlit_ui/pages/2_Containers.py` (live updates)
- `streamlit_ui/Home.py` (live KPIs)

### Estimated Effort
- Backend: 2-3 days
- Frontend: 2-3 days
- Testing: 1-2 days
- **Total: 5-8 days**

---

## 2. Role-Based Access Control (RBAC)

### Overview
Add user roles (admin, operator, viewer) with permission-based access to features. Admins can do everything, operators can execute actions, viewers are read-only.

### Role Definitions

| Permission | Viewer | Operator | Admin |
|------------|--------|----------|-------|
| View dashboards | ✓ | ✓ | ✓ |
| View containers/stacks | ✓ | ✓ | ✓ |
| View logs | ✓ | ✓ | ✓ |
| Use LLM assistant | ✓ | ✓ | ✓ |
| Approve remediation | ✗ | ✓ | ✓ |
| Execute remediation | ✗ | ✓ | ✓ |
| Create backups | ✗ | ✓ | ✓ |
| Manage users | ✗ | ✗ | ✓ |
| View audit logs | ✗ | ✗ | ✓ |
| Configure settings | ✗ | ✗ | ✓ |

### Implementation Steps

#### Phase 1: User & Role Models

1. **User Model** `src/portainer_dashboard/models/user.py`
   ```python
   class Role(str, Enum):
       VIEWER = "viewer"
       OPERATOR = "operator"
       ADMIN = "admin"

   class User(BaseModel):
       id: str
       username: str
       role: Role
       created_at: datetime
       last_login: datetime | None

   class Permission(str, Enum):
       VIEW_DASHBOARD = "view_dashboard"
       VIEW_CONTAINERS = "view_containers"
       VIEW_LOGS = "view_logs"
       USE_LLM = "use_llm"
       APPROVE_REMEDIATION = "approve_remediation"
       EXECUTE_REMEDIATION = "execute_remediation"
       CREATE_BACKUP = "create_backup"
       MANAGE_USERS = "manage_users"
       VIEW_AUDIT = "view_audit"
       CONFIGURE_SETTINGS = "configure_settings"

   ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
       Role.VIEWER: {
           Permission.VIEW_DASHBOARD,
           Permission.VIEW_CONTAINERS,
           Permission.VIEW_LOGS,
           Permission.USE_LLM,
       },
       Role.OPERATOR: {
           # All viewer permissions plus...
           Permission.APPROVE_REMEDIATION,
           Permission.EXECUTE_REMEDIATION,
           Permission.CREATE_BACKUP,
       },
       Role.ADMIN: {
           # All permissions
       },
   }
   ```

2. **User Storage** `src/portainer_dashboard/services/user_service.py`
   - SQLite storage for users
   - CRUD operations
   - Password hashing (for static auth)
   - Role assignment

#### Phase 2: Authentication Integration

3. **Update Session Model** `src/portainer_dashboard/core/session.py`
   ```python
   class SessionData(BaseModel):
       user_id: str
       username: str
       role: Role
       permissions: set[Permission]
       created_at: datetime
       expires_at: datetime
   ```

4. **Permission Dependency** `src/portainer_dashboard/api/deps.py`
   ```python
   def require_permission(permission: Permission):
       async def check_permission(
           session: SessionData = Depends(get_current_session)
       ):
           if permission not in session.permissions:
               raise HTTPException(403, "Insufficient permissions")
           return session
       return check_permission

   # Usage in routes:
   @router.post("/actions/{id}/execute")
   async def execute_action(
       id: str,
       session: SessionData = Depends(require_permission(Permission.EXECUTE_REMEDIATION))
   ):
       ...
   ```

5. **Update Static Auth** `src/portainer_dashboard/auth/static.py`
   - Support multiple users in config
   - Assign roles to users
   ```python
   # Environment config example:
   DASHBOARD_USERS='[{"username":"admin","password_hash":"...","role":"admin"},{"username":"viewer","password_hash":"...","role":"viewer"}]'
   ```

6. **Update OIDC Auth** `src/portainer_dashboard/auth/oidc.py`
   - Map OIDC claims/groups to roles
   - Configure role claim name
   ```python
   OIDC_ROLE_CLAIM = "roles"  # or "groups"
   OIDC_ADMIN_GROUPS = ["dashboard-admins"]
   OIDC_OPERATOR_GROUPS = ["dashboard-operators"]
   ```

#### Phase 3: Frontend Permission Enforcement

7. **Permission Context** in `streamlit_ui/shared.py`
   ```python
   def get_user_permissions() -> set[str]:
       """Get current user's permissions from session."""
       return st.session_state.get("permissions", set())

   def has_permission(permission: str) -> bool:
       return permission in get_user_permissions()

   def require_permission(permission: str):
       """Decorator to require permission for a page."""
       if not has_permission(permission):
           st.error("You don't have permission to access this page.")
           st.stop()
   ```

8. **Update Pages** to check permissions
   - Hide/disable buttons for unauthorized actions
   - Show permission-denied message for restricted pages
   - Filter navigation based on role

#### Phase 4: User Management UI (Admin Only)

9. **User Management Page** `streamlit_ui/pages/8_Users.py`
   - List all users
   - Create new user (static auth only)
   - Edit user role
   - Delete user
   - View user's last login

### Configuration

```python
# New environment variables
RBAC_ENABLED: bool = True
RBAC_DEFAULT_ROLE: Role = Role.VIEWER

# For static auth with multiple users
DASHBOARD_USERS: str = '[...]'  # JSON array

# For OIDC role mapping
OIDC_ROLE_CLAIM: str = "roles"
OIDC_ADMIN_GROUPS: list[str] = ["dashboard-admins"]
OIDC_OPERATOR_GROUPS: list[str] = ["dashboard-operators"]
```

### Migration Path

1. Existing single-user static auth continues to work (user gets admin role)
2. RBAC can be enabled incrementally
3. OIDC users without role claim default to viewer

### Files to Create/Modify

**New Files:**
- `src/portainer_dashboard/models/user.py`
- `src/portainer_dashboard/services/user_service.py`
- `src/portainer_dashboard/api/v1/users.py`
- `streamlit_ui/pages/8_Users.py`

**Modified Files:**
- `src/portainer_dashboard/core/session.py`
- `src/portainer_dashboard/api/deps.py`
- `src/portainer_dashboard/auth/static.py`
- `src/portainer_dashboard/auth/oidc.py`
- `src/portainer_dashboard/config.py`
- `streamlit_ui/shared.py`
- `streamlit_ui/api_client.py`
- All pages (permission checks)

### Estimated Effort
- Backend models & services: 2 days
- Auth integration: 2 days
- API permission enforcement: 1 day
- Frontend enforcement: 2 days
- User management UI: 1 day
- Testing: 2 days
- **Total: 10-12 days**

---

## 3. End-to-End Test Suite

### Overview
Add comprehensive E2E tests using Playwright to verify critical user flows work correctly across the full stack.

### Test Framework Setup

1. **Install Dependencies**
   ```bash
   pip install playwright pytest-playwright
   playwright install chromium
   ```

2. **Test Configuration** `tests/e2e/conftest.py`
   ```python
   import pytest
   from playwright.sync_api import Page, Browser

   @pytest.fixture(scope="session")
   def backend_server():
       """Start FastAPI backend for tests."""
       # Start uvicorn in subprocess
       yield server_url
       # Cleanup

   @pytest.fixture(scope="session")
   def frontend_server(backend_server):
       """Start Streamlit frontend for tests."""
       # Start streamlit in subprocess
       yield frontend_url
       # Cleanup

   @pytest.fixture
   def authenticated_page(page: Page, frontend_server) -> Page:
       """Login and return authenticated page."""
       page.goto(frontend_server)
       page.fill('[data-testid="username"]', "admin")
       page.fill('[data-testid="password"]', "test")
       page.click('[data-testid="login-button"]')
       page.wait_for_url("**/Home")
       return page
   ```

### Test Scenarios

#### Authentication Tests `tests/e2e/test_auth.py`
```python
def test_login_success(page, frontend_server):
    """Test successful login with valid credentials."""

def test_login_failure(page, frontend_server):
    """Test login rejection with invalid credentials."""

def test_logout(authenticated_page):
    """Test logout clears session."""

def test_session_timeout(authenticated_page):
    """Test session expires after timeout."""
```

#### Navigation Tests `tests/e2e/test_navigation.py`
```python
def test_home_page_loads(authenticated_page):
    """Test home page displays KPIs."""

def test_navigate_to_containers(authenticated_page):
    """Test navigation to containers page."""

def test_navigate_to_all_pages(authenticated_page):
    """Test all navigation links work."""
```

#### Container Management Tests `tests/e2e/test_containers.py`
```python
def test_container_list_displays(authenticated_page):
    """Test container list loads and shows data."""

def test_container_filtering(authenticated_page):
    """Test container state filter works."""

def test_container_details_expand(authenticated_page):
    """Test container details expansion."""
```

#### LLM Assistant Tests `tests/e2e/test_llm_assistant.py`
```python
def test_send_message(authenticated_page):
    """Test sending a message to LLM."""

def test_streaming_response(authenticated_page):
    """Test response streams correctly."""

def test_quick_questions(authenticated_page):
    """Test quick question buttons work."""
```

#### Remediation Tests `tests/e2e/test_remediation.py`
```python
def test_view_pending_actions(authenticated_page):
    """Test viewing pending remediation actions."""

def test_approve_action(authenticated_page):
    """Test approving a remediation action."""

def test_reject_action(authenticated_page):
    """Test rejecting a remediation action."""
```

### CI/CD Integration

```yaml
# .github/workflows/e2e.yml
name: E2E Tests
on: [push, pull_request]
jobs:
  e2e:
    runs-on: ubuntu-latest
    services:
      portainer:
        image: portainer/portainer-ce:latest
        ports:
          - 9000:9000
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v6
        with:
          python-version: '3.14'
      - run: pip install -e ".[dev]"
      - run: playwright install chromium
      - run: pytest tests/e2e -v --screenshot=on --video=on
      - uses: actions/upload-artifact@v6
        if: failure()
        with:
          name: test-results
          path: test-results/
```

### Files to Create

- `tests/e2e/conftest.py`
- `tests/e2e/test_auth.py`
- `tests/e2e/test_navigation.py`
- `tests/e2e/test_containers.py`
- `tests/e2e/test_llm_assistant.py`
- `tests/e2e/test_remediation.py`
- `tests/e2e/test_settings.py`
- `.github/workflows/e2e.yml`

### Estimated Effort
- Test infrastructure setup: 1 day
- Auth & navigation tests: 1 day
- Feature tests: 2-3 days
- CI/CD integration: 0.5 day
- **Total: 5-6 days**

---

## Implementation Roadmap

### Quarter 1
1. **Real-Time Container Updates** - Highest user value
2. **E2E Test Suite** - Foundation for safe feature development

### Quarter 2
3. **RBAC** - Required for enterprise adoption

### Dependencies
- E2E tests should be in place before major RBAC changes
- Real-time updates are independent and can proceed in parallel
