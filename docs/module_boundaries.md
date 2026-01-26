# Module Boundaries and Ownership

This document defines the module architecture, ownership responsibilities, and guidelines for extending the codebase.

## Architecture Overview

The Streamlit Portainer Dashboard follows a hybrid FastAPI + Streamlit architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streamlit Frontend                           │
│                    (streamlit_ui/)                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   Home.py   │  │   pages/    │  │      shared.py          │ │
│  │  (Entry)    │  │ (Multi-page)│  │  (Reusable components)  │ │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘ │
│         │                │                     │               │
│         └────────────────┼─────────────────────┘               │
│                          │                                     │
│                          ▼                                     │
│                   api_client.py                                │
│              (HTTP client for backend)                         │
└──────────────────────────┬─────────────────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                             │
│               (src/portainer_dashboard/)                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    main.py                               │  │
│  │              (App factory, lifespan)                     │  │
│  └──────────────────────────┬───────────────────────────────┘  │
│                             │                                   │
│     ┌───────────────────────┼───────────────────────┐          │
│     │                       │                       │          │
│     ▼                       ▼                       ▼          │
│  ┌────────┐          ┌───────────┐          ┌───────────────┐  │
│  │ api/v1/│          │ websocket/│          │   scheduler/  │  │
│  │(Routes)│          │(Streaming)│          │  (Background) │  │
│  └───┬────┘          └─────┬─────┘          └───────┬───────┘  │
│      │                     │                        │          │
│      └─────────────────────┼────────────────────────┘          │
│                            │                                   │
│                            ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                      services/                           │  │
│  │  ┌──────────────────┐  ┌──────────────────┐             │  │
│  │  │ portainer_client │  │    llm_client    │             │  │
│  │  └────────┬─────────┘  └────────┬─────────┘             │  │
│  │           │                     │                        │  │
│  │  ┌────────┴─────────┐  ┌───────┴────────┐               │  │
│  │  │  data_collector  │  │ monitoring_svc │               │  │
│  │  └──────────────────┘  └────────────────┘               │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────┬─────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      External APIs                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐│
│  │  Portainer   │  │  LLM (Ollama │  │ Kibana/Elasticsearch   ││
│  │     API      │  │  / OpenAI)   │  │       (Logs)           ││
│  └──────────────┘  └──────────────┘  └────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

## Module Ownership Matrix

| Module | Owner | Responsibility |
|--------|-------|----------------|
| `src/portainer_dashboard/api/v1/` | Backend | REST API endpoints for all resources |
| `src/portainer_dashboard/auth/` | Backend | Authentication (static + OIDC) |
| `src/portainer_dashboard/services/` | Backend | External integrations, business logic |
| `src/portainer_dashboard/websocket/` | Backend | Real-time streaming (LLM, monitoring) |
| `src/portainer_dashboard/scheduler/` | Backend | Background jobs (monitoring interval) |
| `src/portainer_dashboard/config.py` | Backend | Pydantic settings from env vars |
| `src/portainer_dashboard/core/session.py` | Backend | SQLite-backed session storage |
| `streamlit_ui/Home.py` | Frontend | Dashboard entry point, KPIs |
| `streamlit_ui/pages/` | Frontend | Multi-page views |
| `streamlit_ui/shared.py` | Frontend | Reusable UI components |
| `streamlit_ui/api_client.py` | Frontend | HTTP client for backend |

## Data Flow

### 1. User Authentication

```
User → Streamlit Login Form → api_client.py
     → FastAPI /auth/login → auth/ module
     → Session stored in SQLite
     → Session cookie returned to frontend
```

### 2. Infrastructure Data

```
Streamlit Page → api_client.py → FastAPI /api/v1/endpoints
              → services/portainer_client.py
              → Portainer API
              → normalise_*() functions → Pydantic models
              → JSON response → Plotly charts + tables
```

### 3. LLM Assistant

```
User Query → Streamlit WebSocket → FastAPI /ws/llm/chat
          → websocket/llm_chat.py
          → _build_context() [fetches infrastructure data]
          → _build_system_prompt() [adds few-shot examples]
          → services/llm_client.py → LLM API
          → stream_chat() → WebSocket chunks → UI
```

### 4. AI Monitoring

```
Scheduler tick → monitoring_service.run_analysis()
             → data_collector.collect_snapshot()
             → portainer_client [endpoints, containers, logs]
             → llm_client.chat() or fallback rules
             → insights_store.add_report()
             → WebSocket broadcast → AI Monitor page
```

## Guidelines for Adding New Features

### Adding a New Streamlit Page

1. Create `streamlit_ui/pages/X_Page_Name.py`
2. Import shared components from `streamlit_ui/shared.py`
3. Use `api_client.py` for all backend communication
4. Never call external APIs directly from the frontend

### Adding a New API Endpoint

1. Create route in `src/portainer_dashboard/api/v1/`
2. Add any business logic to `services/`
3. Register router in `main.py`
4. Update `api_client.py` with corresponding method

### Adding a New External Integration

1. Create service in `src/portainer_dashboard/services/`
2. Add configuration to `config.py`
3. Document env vars in `README.md` and `CLAUDE.md`
4. Expose via API endpoint, not directly to frontend

### Adding Background Jobs

1. Add job to `scheduler/` module
2. Configure interval via env var in `config.py`
3. Use `services/` for actual work
4. Broadcast results via WebSocket if real-time updates needed

## Prohibited Patterns

- **Frontend calling external APIs directly**: All external calls go through backend services
- **Services importing from api/**: Services are independent; API routes depend on services
- **Duplicating HTTP client logic**: Use `api_client.py` in frontend, `httpx` clients in backend
- **Hardcoding configuration**: All config via `config.py` and environment variables
- **Skipping normalization**: Portainer data must pass through `normalise_*()` functions
