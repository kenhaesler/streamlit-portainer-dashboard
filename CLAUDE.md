# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Sync Reminder

When making significant changes to the codebase (new features, architectural changes, new environment variables), also update:
- **README.md** - User-facing documentation, configuration options
- **CONTRIBUTING.md** - Developer guidelines, module paths
- **AGENTS.md** - AI agent guidelines, project layout

## Build & Run Commands

```bash
# Run tests
pytest tests/unit tests/integration -q

# Docker Compose (hybrid architecture)
docker compose up -d

# Build images locally
docker build -t portainer-dashboard-backend -f Dockerfile .
docker build -t portainer-dashboard-frontend -f Dockerfile.streamlit .

# Access points
# - Streamlit UI: http://localhost:8502
# - FastAPI Backend: http://localhost:8000
```

## Architecture Overview

This is a hybrid FastAPI + Streamlit dashboard for Portainer infrastructure management. It visualizes Docker containers, images, stacks, and edge agents across distributed environments, with LLM assistant and Kibana log integration.

### Layer Structure

```
Streamlit Frontend (streamlit_ui/)
    │
    ▼ HTTP/WebSocket
FastAPI Backend (src/portainer_dashboard/)
    ├── API Routes (api/v1/)
    ├── Auth (auth/)
    ├── Services (services/)
    └── WebSocket (websocket/)
    │
    ▼
External APIs (Portainer, LLM endpoints, Kibana/Elasticsearch)
```

### Key Modules

**Backend (src/portainer_dashboard/):**
- **`main.py`** - FastAPI app factory with lifespan management
- **`api/v1/`** - REST API endpoints (endpoints, containers, stacks, backup, logs, monitoring)
- **`auth/`** - Static + OIDC authentication with session management
- **`services/`** - Portainer client, LLM client, Kibana client, backup service, monitoring service
- **`websocket/llm_chat.py`** - WebSocket streaming for LLM responses
- **`websocket/monitoring_insights.py`** - WebSocket for real-time monitoring insights
- **`scheduler/`** - APScheduler for background monitoring tasks
- **`config.py`** - Pydantic settings from environment variables
- **`core/session.py`** - SQLite-backed session storage

**Frontend (streamlit_ui/):**
- **`Home.py`** - Dashboard entry point with KPIs and charts
- **`pages/`** - Multi-page views (Fleet Overview, Container Health, Workload Explorer, etc.)
- **`api_client.py`** - HTTP client for backend communication
- **`shared.py`** - Shared UI components (sidebar with session timeout)

### Data Flow

1. User authenticates via FastAPI backend → session stored in SQLite
2. Streamlit frontend calls backend API with session cookie
3. Backend queries Portainer API → normalizes to Pydantic models
4. Frontend renders Plotly charts + Streamlit tables

### LLM Assistant

- WebSocket streaming from backend to frontend
- Supports Ollama and OpenAI-compatible endpoints
- Context-aware queries about infrastructure state

## Development Guidelines

- **Python 3.14** with type hints; use built-in generics (`list`, `dict`)
- Backend code in `src/portainer_dashboard/`
- Frontend code in `streamlit_ui/`
- Templates in `templates/` (HTMX alternative UI)
- Mock HTTP requests in tests
- Import order: standard library → third-party → local

## Testing

- Run `pytest tests/unit tests/integration -q` before submitting changes
- Do not commit while tests are failing
- Mock credentials via `monkeypatch`

## Key Environment Variables

**Authentication:**
- `DASHBOARD_USERNAME`, `DASHBOARD_KEY` - Static credentials
- `DASHBOARD_AUTH_PROVIDER` - `static` or `oidc`
- `DASHBOARD_SESSION_TIMEOUT_MINUTES` - Session timeout (default: 60)

**Portainer:**
- `PORTAINER_API_URL`, `PORTAINER_API_KEY`, `PORTAINER_VERIFY_SSL`

**Caching:**
- `PORTAINER_CACHE_ENABLED`, `PORTAINER_CACHE_TTL_SECONDS`

**LLM:**
- `LLM_API_ENDPOINT`, `LLM_MODEL`, `LLM_BEARER_TOKEN`

**Kibana:**
- `KIBANA_LOGS_ENDPOINT`, `KIBANA_API_KEY`

**AI Monitoring:**
- `MONITORING_ENABLED` - Enable/disable AI monitoring (default: true)
- `MONITORING_INTERVAL_MINUTES` - Analysis interval (default: 5)
- `MONITORING_MAX_INSIGHTS_STORED` - Max insights in memory (default: 100)
- `MONITORING_EXCLUDED_CONTAINERS` - Comma-separated container names to exclude from monitoring (default: portainer,sysdig-host-shield,traefik,portainer_edge_agent)

## Container Details

**Backend:**
- Base: `dhi.io/python:3.14.2-debian13`
- Non-root user (UID 65532)
- Health check: `http://localhost:8000/health`

**Frontend:**
- Base: `python:3.12-slim`
- Non-root user (UID 1000)
- Health check: `http://localhost:8502/_stcore/health`
