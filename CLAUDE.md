# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Run tests
pytest -q

# Smoke test (validates Streamlit boot + login flow)
scripts/check_app_starts.sh

# Local development (requires Python 3.12 and dependencies from requirements.txt)
streamlit run app/Home.py

# Docker build
docker build -t streamlit-portainer-dashboard .

# Docker Compose (production)
docker compose up -d
```

## Architecture Overview

This is a Streamlit dashboard for Portainer infrastructure management. It visualizes Docker containers, images, stacks, and edge agents across distributed environments, with LLM assistant and Kibana log integration.

### Layer Structure

```
UI Layer (app/Home.py, app/pages/)
    │
    ▼
Shared Helpers (dashboard_state.py, environment_cache.py, config/, auth.py)
    │
    ▼
Services (app/services/: portainer_client.py, llm_client.py, kibana_client.py, backup.py)
    │
    ▼
External APIs (Portainer, LLM endpoints, Kibana/Elasticsearch)
```

### Key Modules

- **`app/Home.py`** - Entry point; environment selection and metrics dashboard
- **`app/pages/`** - Multi-page views (Fleet Overview, Container Health, Workload Explorer, Settings, LLM Assistant, Edge Agent Logs)
- **`app/dashboard_state.py`** - Session state coordination and Portainer data fetching
- **`app/services/portainer_client.py`** - HTTP wrapper for Portainer API
- **`app/services/llm_client.py`** + **`llm_context.py`** - LLM integration with two-stage workflow (research plan → answer)
- **`app/config/__init__.py`** - Configuration parsing from environment variables
- **`app/auth.py`** - Static + OIDC authentication with session management
- **`app/session_storage.py`** - Pluggable session backend (memory or SQLite)

### Data Flow

1. User loads page → `fetch_portainer_data()` checks persistent cache (TTL-based)
2. Serve stale data immediately, refresh in background
3. Query Portainer API → normalize to pandas DataFrames
4. Apply session filters → render Plotly charts + Streamlit tables

### LLM Assistant Workflow

The assistant uses a two-stage approach:
1. **Planning**: Build data hub + operational overview → ask LLM for research plan (JSON)
2. **Execution**: Execute `QueryRequest`s against the data hub
3. **Answer**: Supply results to LLM for final response

Context trimming via `LLM_MAX_TOKENS` and `max_context_tokens` prevents oversized prompts.

## Development Guidelines

- **Python 3.12** with type hints; use `from __future__ import annotations`
- Keep UI code in `app/pages/` or `app/components/`; use `dashboard_state.py` for state
- Place external integrations in `app/services/` (no reimplemented HTTP calls)
- Mock HTTP requests in tests (see existing patterns in `tests/`)
- Run `scripts/check_app_starts.sh` after UI changes
- Avoid truncating data; design for full datasets
- Import order: standard library → third-party → local

## Testing

- Run `pytest -q` before submitting changes
- Do not commit while tests are failing
- Mock credentials via `monkeypatch`; tests should not depend on real Portainer/LLM connections

## Key Environment Variables

Authentication: `DASHBOARD_USERNAME`, `DASHBOARD_KEY`, `DASHBOARD_AUTH_PROVIDER` (static|oidc)

Portainer: `PORTAINER_API_URL`, `PORTAINER_API_KEY`, `PORTAINER_VERIFY_SSL`

Caching: `PORTAINER_CACHE_ENABLED`, `PORTAINER_CACHE_TTL_SECONDS`, `PORTAINER_CACHE_DIR`

Session: `DASHBOARD_SESSION_BACKEND` (memory|sqlite), `DASHBOARD_SESSION_TIMEOUT_MINUTES`

LLM: `LLM_API_ENDPOINT`, `LLM_BEARER_TOKEN`, `LLM_MAX_TOKENS`, `LLM_CA_BUNDLE`

Kibana: `KIBANA_LOGS_ENDPOINT`, `KIBANA_API_KEY`

## Container Details

- Docker Hardened Images (DHI) base: `dhi.io/python:3.12.12-debian12` runtime, `dhi.io/python:3.12.12-debian12-dev` build stage
- Non-root user (UID 65532)
- Volume mount at `/app/.streamlit` for persistence
- Health check on `http://127.0.0.1:8501/_stcore/health`
