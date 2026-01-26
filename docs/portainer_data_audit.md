# Portainer Data Audit

This document details what data is collected from Portainer, how it is processed, and what telemetry is exposed for compliance reviews.

## Data Collection Overview

The dashboard collects data from Portainer via its REST API. All data flows through the backend services before reaching the frontend or LLM.

```
Portainer API → portainer_client.py → data_collector.py → monitoring_service.py
                       ↓                     ↓                      ↓
              Normalization           InfrastructureSnapshot    MonitoringReport
                       ↓                     ↓                      ↓
                JSON Response          insights_store.py      WebSocket broadcast
```

## Data Categories

### 1. Endpoint Metadata

**Source**: `GET /api/endpoints`

| Field | Description | Retention |
|-------|-------------|-----------|
| `endpoint_id` | Unique Portainer identifier | Session |
| `endpoint_name` | Human-readable name | Session |
| `endpoint_status` | Online (1) or Offline (2) | Session |
| `agent_version` | Edge agent version | Session |
| `platform` | OS platform (linux/windows) | Session |
| `operating_system` | Full OS name | Session |
| `group_id` | Endpoint group assignment | Session |
| `tags` | User-defined tags | Session |
| `last_check_in` | Last heartbeat timestamp | Session |
| `url` | Docker socket/TCP URL | Session |
| `agent_hostname` | Extracted hostname | Session |

**Normalization**: `normalise_endpoint_metadata()` in `portainer_client.py:686-791`

### 2. Container Data

**Source**: `GET /api/endpoints/{id}/docker/containers/json`

| Field | Description | Retention |
|-------|-------------|-----------|
| `container_id` | Docker container ID | Session |
| `container_name` | Container name (without `/` prefix) | Session |
| `image` | Image reference | Session |
| `state` | running/exited/dead/etc. | Session |
| `status` | Human-readable status | Session |
| `restart_count` | Number of restarts | Session |
| `created_at` | Creation timestamp | Session |
| `ports` | Port mappings summary | Session |

**Normalization**: `normalise_endpoint_containers()` in `portainer_client.py:858-947`

### 3. Container Logs

**Source**: `GET /api/endpoints/{id}/docker/containers/{cid}/logs`

| Field | Description | Retention |
|-------|-------------|-----------|
| `logs` | Raw log output | Sanitized, not persisted |
| `log_lines` | Number of lines | Session |
| `exit_code` | Container exit code | Session |
| `truncated` | Whether logs were truncated | Session |

**Important**: Logs are sanitized before LLM processing to remove potential secrets.

**Collection Criteria** (from `data_collector.py:34-78`):
- Containers in states: `exited`, `dead`, `restarting`
- Containers with `unhealthy` in status
- Non-zero exit codes

### 4. Container Stats

**Source**: `GET /api/endpoints/{id}/docker/containers/{cid}/stats?stream=false`

| Field | Description | Retention |
|-------|-------------|-----------|
| `cpu_usage` | CPU utilization percentage | Session |
| `memory_usage` | Memory used (MB) | Session |
| `memory_limit` | Memory limit (MB) | Session |
| `memory_percent` | Memory utilization percentage | Session |

**Calculation**: `_calculate_cpu_percent()` and `_calculate_memory_usage()` in `llm_chat.py:63-112`

### 5. Stack Data

**Source**: `GET /api/stacks` and `GET /api/edge/stacks`

| Field | Description | Retention |
|-------|-------------|-----------|
| `stack_id` | Unique stack identifier | Session |
| `stack_name` | Stack name | Session |
| `stack_status` | Deployment status | Session |
| `stack_type` | Compose/Swarm/Kubernetes | Session |

**Normalization**: `normalise_endpoint_stacks()` in `portainer_client.py:794-855`

### 6. Image Data

**Source**: `GET /api/endpoints/{id}/docker/images/json`

| Field | Description | Retention |
|-------|-------------|-----------|
| `image_id` | Docker image ID | Session |
| `reference` | Image tag or digest | Session |
| `size` | Image size in bytes | Session |
| `created_at` | Image creation time | Session |
| `dangling` | Whether image is dangling | Session |

**Normalization**: `normalise_endpoint_images()` in `portainer_client.py:950-1013`

### 7. Security Scan Data

**Source**: Container inspection via `GET /api/endpoints/{id}/docker/containers/{cid}/json`

| Field | Description | Retention |
|-------|-------------|-----------|
| `privileged` | Container runs in privileged mode | Session |
| `cap_add` | Added Linux capabilities | Session |
| `security_opt` | Security options | Session |
| `elevated_risks` | Detected security risks | Session |

**Processing**: `security_scanner.py` (via `data_collector.py:130-134`)

## InfrastructureSnapshot Model

The `InfrastructureSnapshot` (`models/monitoring.py`) aggregates all collected data:

```python
@dataclass
class InfrastructureSnapshot:
    timestamp: datetime
    endpoints_online: int = 0
    endpoints_offline: int = 0
    containers_running: int = 0
    containers_stopped: int = 0
    containers_unhealthy: int = 0
    security_issues: list[ContainerCapabilities] = field(default_factory=list)
    outdated_images: list[ImageStatus] = field(default_factory=list)
    container_logs: list[ContainerLogs] = field(default_factory=list)
    endpoint_details: list[dict] = field(default_factory=list)
    container_details: list[dict] = field(default_factory=list)
```

## Data Sent to LLM

When the LLM assistant or monitoring service is used, the following data may be sent to the configured LLM endpoint:

### Chat Context (llm_chat.py)

| Data | Included | Sanitized |
|------|----------|-----------|
| Endpoint names | Yes | No |
| Endpoint status | Yes | No |
| Container names | Yes | No |
| Container images | Yes | No |
| Container states | Yes | No |
| CPU/memory stats | Yes | No |
| Container logs | Yes (last 20 lines) | **Yes** |
| Stack names | Yes | No |

### Monitoring Analysis (monitoring_service.py)

| Data | Included | Sanitized |
|------|----------|-----------|
| Summary counts | Yes | No |
| Security issues | Yes | No |
| Outdated images | Yes | No |
| Container logs | Yes (last 3000 chars) | **Yes** |

## Log Sanitization

The `log_sanitizer.py` service removes sensitive patterns before sending to LLM:

- API keys and tokens
- Passwords and secrets
- Connection strings with credentials
- Environment variable values that may contain secrets

## Data Storage

### Session Storage

| Store | Location | Data | TTL |
|-------|----------|------|-----|
| Portainer cache | `.streamlit/cache/` | API responses | Configurable (default 15min) |
| Session DB | `.streamlit/sessions.db` | Auth sessions | Configurable timeout |
| Insights store | In-memory | MonitoringReports | 100 entries max |

### No Persistent Storage

The following data is **not** persisted:
- Container logs (processed in-memory only)
- LLM conversations (no history storage)
- Container stats (fetched on-demand)

## Compliance Considerations

### Data Minimization

1. **Endpoint limit**: Only first 10 endpoints per environment for LLM context
2. **Log truncation**: Maximum 20 lines (chat) or 3000 chars (monitoring) per container
3. **Cache TTL**: Configurable expiration prevents stale data accumulation

### Access Control

1. **Authentication required**: All API endpoints require valid session
2. **Portainer API key**: Scoped to specific Portainer permissions
3. **LLM token**: Separate credential for LLM API access

### Audit Trail

1. **Logging**: All API calls logged with `LOGGER.info/debug`
2. **Timestamps**: All snapshots include UTC timestamp
3. **Report history**: Monitoring reports stored with timestamps

## Configuration for Compliance

### Disable Data Collection

```bash
# Disable AI monitoring entirely
MONITORING_ENABLED=false

# Disable security scans
MONITORING_INCLUDE_SECURITY_SCAN=false

# Disable image update checks
MONITORING_INCLUDE_IMAGE_CHECK=false

# Disable log analysis
MONITORING_INCLUDE_LOG_ANALYSIS=false

# Exclude specific containers from monitoring
MONITORING_EXCLUDED_CONTAINERS=sensitive-app,secrets-manager
```

### Reduce Data Exposure

```bash
# Shorter cache TTL
PORTAINER_CACHE_TTL_SECONDS=60

# Shorter session timeout
DASHBOARD_SESSION_TIMEOUT_MINUTES=15

# Limit monitoring insight storage
MONITORING_MAX_INSIGHTS_STORED=25
```

## API Endpoints and Data Returned

| Endpoint | Data Returned |
|----------|---------------|
| `GET /api/v1/endpoints` | Endpoint metadata |
| `GET /api/v1/endpoints/{id}/containers` | Container list |
| `GET /api/v1/endpoints/{id}/containers/{cid}/logs` | Container logs |
| `GET /api/v1/monitoring/insights` | Monitoring reports |
| `WS /ws/llm/chat` | LLM streaming responses |
| `WS /ws/monitoring/insights` | Real-time monitoring updates |
