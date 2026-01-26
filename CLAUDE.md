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

## Local End-to-End Testing

Before committing changes, test the full stack locally with Ollama and Docker Engine.

### Prerequisites

1. **Docker Engine** running locally (Docker Desktop or native Docker)
2. **Ollama** running locally at `http://localhost:11434`
3. **Python 3.14** with dependencies installed: `pip install -e ".[dev]"`

### 1. Start Ollama

```bash
# Ensure Ollama is running
ollama serve

# Pull a model (if not already available)
ollama pull llama3.2
```

### 2. Create Local Environment File

Create a `.env.local` file (do not commit):

```bash
# Authentication
DASHBOARD_USERNAME=admin
DASHBOARD_KEY=localtest
DASHBOARD_AUTH_PROVIDER=static

# Portainer (use local Docker socket or a test Portainer instance)
PORTAINER_API_URL=http://localhost:9000/api
PORTAINER_API_KEY=your_local_portainer_key
PORTAINER_VERIFY_SSL=false

# LLM - Ollama local
LLM_API_ENDPOINT=http://localhost:11434/v1/chat/completions
LLM_MODEL=llama3.2
LLM_BEARER_TOKEN=

# Disable monitoring for local testing (optional)
MONITORING_ENABLED=false

# Caching
PORTAINER_CACHE_ENABLED=true
PORTAINER_CACHE_TTL_SECONDS=30
```

### 3. Run Backend Locally

```bash
# Load environment and start FastAPI
set -a && source .env.local && set +a
uvicorn src.portainer_dashboard.main:app --reload --host 0.0.0.0 --port 8000
```

Or on Windows PowerShell:
```powershell
Get-Content .env.local | ForEach-Object { if ($_ -match '^([^#][^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2]) } }
uvicorn src.portainer_dashboard.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Run Frontend Locally

In a separate terminal:

```bash
set -a && source .env.local && set +a
export BACKEND_URL=http://localhost:8000
streamlit run streamlit_ui/Home.py --server.port 8502
```

Or on Windows PowerShell:
```powershell
$env:BACKEND_URL = "http://localhost:8000"
streamlit run streamlit_ui/Home.py --server.port 8502
```

### 5. Verify Local Stack

1. **Backend health**: `curl http://localhost:8000/health`
2. **Frontend**: Open `http://localhost:8502` in browser
3. **Login** with `admin` / `localtest`
4. **Test LLM**: Navigate to Assistant page and send a test message
5. **Test Portainer**: Check that endpoints/containers load (requires valid Portainer connection)

### 6. Run Unit Tests

```bash
pytest tests/unit tests/integration -q
```

### Local Portainer for Testing (Optional)

If you need a local Portainer instance:

```bash
docker run -d -p 9000:9000 --name portainer \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

Then create an API key in Portainer UI: Settings → Users → your user → API Keys.

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
