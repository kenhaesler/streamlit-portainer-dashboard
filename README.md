# streamlit-portainer-dashboard

<img width="1860" height="1049" alt="image" src="https://github.com/user-attachments/assets/b2200e6e-0d41-423f-b8ee-e67d882b571b" />


A hybrid FastAPI + Streamlit application that pulls information from the Portainer API and visualizes everything. Designed for IT administrators managing Docker infrastructure across distributed environments.

## Features

### Dashboard Pages

- **Home** – KPI overview with endpoint status and container state charts
- **Workload Explorer** – Container distribution across endpoints with interactive filtering
- **Fleet Overview** – Edge agent monitoring, stack management, and visual analytics
- **Container Health** – Health status monitoring, alerts, and detailed container inspection
- **Image Footprint** – Image distribution analysis with treemap and sunburst visualizations
- **Settings** – Connection management, backup creation, and restore instructions
- **LLM Assistant** – AI-powered infrastructure analysis with natural language queries
- **Edge Agent Logs** – Container log exploration via Kibana/Elasticsearch integration
- **AI Monitor** – Real-time AI-powered monitoring insights with automated analysis
- **Container Logs** *(New in v3.0)* – Direct Docker log access via Portainer API
- **Network Topology** *(New in v3.0)* – Interactive visualization of container network connections

### Quality-of-Life Features (v3.0)

- **Container Environment Variables** – View env vars, networks, mounts, and labels in Container Health
- **CSV Export** – Download buttons on all data tables for easy reporting
- **Refresh Buttons** – Manual data refresh available on every page
- **LLM Log Integration** – Assistant automatically fetches logs for stopped/unhealthy containers to diagnose issues
- **Backup Restore Documentation** – Clear step-by-step restore instructions in Settings

## Architecture & contributor docs

- [Module boundaries and ownership](docs/module_boundaries.md) – high-level architecture, module responsibilities, and guidance on where to place new functionality.
- [LLM context management](docs/llm_context_management.md) – explains how prompt construction and trimming works inside the assistant.
- [Portainer data audit](docs/portainer_data_audit.md) – details the telemetry surfaced for compliance reviews.

## Supply Chain Security

### Software Bill of Materials (SBOM)

This project automatically generates a Software Bill of Materials (SBOM) for all Docker images built through the CI/CD pipeline. The SBOM provides a comprehensive inventory of all software components, libraries, and dependencies included in the container image, helping you:

- **Identify vulnerabilities** – Cross-reference dependencies against known security databases
- **Track licenses** – Ensure compliance with open source licensing requirements
- **Audit supply chain** – Understand the complete software composition of deployed images
- **Facilitate incident response** – Quickly determine if a newly-disclosed vulnerability affects your deployment

#### How SBOMs are Generated

The GitHub Actions workflow automatically generates SBOM attestations using Docker BuildKit during the build process. Each pushed image includes:

- **SBOM attestation** – A complete inventory of software packages and their versions
- **Provenance attestation** – Metadata about how the image was built, including source repository, build arguments, and build environment

These attestations are stored alongside the image in the container registry and can be inspected using Docker's attestation tools.

#### Accessing the SBOM

To inspect the SBOM for a specific image, use the Docker CLI:

```bash
# View the SBOM for the latest image
docker buildx imagetools inspect kenhaesler/streamlit-portainer-dashboard:latest --format "{{ json .SBOM }}"

# View the provenance attestation
docker buildx imagetools inspect kenhaesler/streamlit-portainer-dashboard:latest --format "{{ json .Provenance }}"
```

For a more user-friendly format, you can use the `docker scout` command:

```bash
docker scout sbom kenhaesler/streamlit-portainer-dashboard:latest
```

#### Continuous Security Monitoring

The SBOM is regenerated with every build, ensuring that it always reflects the current state of dependencies. This enables:

- Automated vulnerability scanning in CI/CD
- Integration with security monitoring tools
- Compliance reporting for audits and certifications

For more information about Docker attestations and SBOM generation, see the [Docker documentation on attestations](https://docs.docker.com/build/ci/github-actions/attestations/).

## Configuration

The application is configured via environment variables:

- `PORTAINER_API_URL` – Base URL of your Portainer instance (e.g. `https://portainer.example.com/api`).
- `PORTAINER_API_KEY` – API key used for authentication.
- `PORTAINER_VERIFY_SSL` – Optional. Set to `false` to disable TLS certificate verification when using self-signed certificates.
- `DASHBOARD_USERNAME` – Username required to sign in to the dashboard UI.
- `DASHBOARD_KEY` – Access key (password) required to sign in to the dashboard UI.
- `DASHBOARD_AUTH_PROVIDER` – Optional. Set to `oidc` to enable OpenID Connect single sign-on. Defaults to `static`, which uses the username/key form above.
- `DASHBOARD_SESSION_TIMEOUT_MINUTES` – Optional. Expire authenticated sessions after the specified number of minutes of inactivity. Omit or set to a non-positive value to disable the timeout.
- `DASHBOARD_SESSION_BACKEND` – Optional. Selects where authenticated session metadata is stored. Defaults to `memory`, which keeps sessions in-process. Set to `sqlite` to persist sessions in a shared SQLite database (recommended for multi-container deployments).
- `DASHBOARD_SESSION_SQLITE_PATH` – Optional. When using the SQLite session backend, override the database path. Defaults to `.streamlit/sessions.db` inside the application directory.
- `DASHBOARD_LOG_LEVEL` – Optional. Overrides the log verbosity for the dashboard. Accepts standard Python levels (e.g. `INFO`, `DEBUG`, `ERROR`) plus `TRACE`/`VERBOSE`. Defaults to `INFO` when unset or invalid.
- `DASHBOARD_OIDC_ISSUER` – Required when `DASHBOARD_AUTH_PROVIDER=oidc`. Base issuer URL advertised by your identity provider.
- `DASHBOARD_OIDC_CLIENT_ID` – Required when `DASHBOARD_AUTH_PROVIDER=oidc`. OAuth client identifier registered with the provider.
- `DASHBOARD_OIDC_CLIENT_SECRET` – Optional. Client secret issued by the provider. Omit for public clients using PKCE only.
- `DASHBOARD_OIDC_REDIRECT_URI` – Required when `DASHBOARD_AUTH_PROVIDER=oidc`. Callback URL configured for the dashboard client (for example `https://dashboard.example.com/`).
- `DASHBOARD_OIDC_SCOPES` – Optional. Space-separated list of scopes to request during login. Defaults to `openid profile email` and always ensures the mandatory `openid` scope is requested.
- `DASHBOARD_OIDC_DISCOVERY_URL` – Optional. Overrides the OIDC discovery document URL. When unset the dashboard fetches `{issuer}/.well-known/openid-configuration` automatically.
- `DASHBOARD_OIDC_AUDIENCE` – Optional. Audience value to enforce when validating ID tokens. Defaults to the configured client ID.
- `PORTAINER_CACHE_ENABLED` – Optional. Defaults to `true`. Set to `false` to disable persistent caching of Portainer API responses between sessions.
- `PORTAINER_CACHE_TTL_SECONDS` – Optional. Number of seconds before cached Portainer API responses are refreshed. Defaults to 900 seconds (15 minutes). Set to `0` or a negative value to keep cached data until it is manually invalidated.
- `PORTAINER_CACHE_DIR` – Optional. Directory used to persist cached Portainer data. Defaults to `.streamlit/cache` inside the application directory.
- `PORTAINER_BACKUP_INTERVAL` – Optional. Interval used for automatic Portainer backups (for example `24h` or `30m`). Set to `0`, `off`, or leave unset to disable recurring backups. Operators can also configure the cadence from **Settings → Scheduled backups**, which persists the value on disk. When this environment variable is set (for example in Docker Compose), the dashboard surfaces the configured value but the UI controls become read-only so the container configuration remains authoritative.
- `LLM_API_ENDPOINT` – Optional. When set, the LLM assistant page defaults to this chat completion endpoint.
- `LLM_BEARER_TOKEN` – Optional. When set, the LLM assistant page pre-populates the bearer token field so every authenticated user can reuse the shared credentials. When both `LLM_API_ENDPOINT` and `LLM_BEARER_TOKEN` are provided the endpoint and credential inputs become read-only, signalling that the deployment manages the LLM configuration.
- `LLM_MAX_TOKENS` – Optional. Caps the maximum answer length slider in the LLM assistant. Defaults to `200000` and must be an integer.
- `DASHBOARD_CA_BUNDLE` – Optional. Path to a PEM-encoded CA bundle that should be trusted for all HTTPS integrations (Portainer, LLM, Kibana).
- `KIBANA_LOGS_ENDPOINT` – Optional. Full URL of the Kibana/Elasticsearch search endpoint (for example `https://elastic.example.com/_search`) used to retrieve container logs.
- `KIBANA_API_KEY` – Optional. API key sent via the `Authorization: ApiKey <token>` header when querying Kibana. Required when `KIBANA_LOGS_ENDPOINT` is set.
- `KIBANA_VERIFY_SSL` – Optional. Defaults to `true`. Set to `false` to skip TLS verification when connecting to Kibana with self-signed certificates.
- `KIBANA_TIMEOUT_SECONDS` – Optional. Request timeout (in seconds) for Kibana log queries. Defaults to 30 seconds when unset or invalid.
- `MONITORING_ENABLED` – Optional. Defaults to `true`. Set to `false` to disable the AI-powered infrastructure monitoring feature.
- `MONITORING_INTERVAL_MINUTES` – Optional. How often the monitoring service analyzes infrastructure. Defaults to 5 minutes.
- `MONITORING_MAX_INSIGHTS_STORED` – Optional. Maximum number of insights to keep in memory. Defaults to 100.
- `MONITORING_INCLUDE_SECURITY_SCAN` – Optional. Defaults to `true`. Enables scanning for elevated container capabilities.
- `MONITORING_INCLUDE_IMAGE_CHECK` – Optional. Defaults to `true`. Enables checking for outdated container images.

When `DASHBOARD_AUTH_PROVIDER` is unset or set to `static`, both `DASHBOARD_USERNAME` and `DASHBOARD_KEY` must be provided. The app blocks access and displays an error until those credentials are configured. When `DASHBOARD_AUTH_PROVIDER=oidc`, configure the matching `DASHBOARD_OIDC_*` variables instead—the dashboard redirects users through the standard authorization-code flow, discovers the provider endpoints via the well-known document, and validates ID tokens against the advertised JWKS before establishing a session.

After signing in, operators can use the persistent **Log out** button in the sidebar to clear their authentication session when
they step away from the dashboard. When a session timeout is configured, the remaining time is shown in the sidebar so
operators can always see how much longer the session will stay active. The dashboard automatically refreshes idle sessions every
second to keep the countdown up to date. During the final 30 seconds a warning banner appears with a **Keep me logged in**
button; clicking it immediately refreshes the activity timestamp and prevents the session from expiring.

When OpenID Connect is enabled the dashboard still issues an application session so Streamlit components can operate without
re-running the full OIDC flow on every page load. The backing store for those sessions is controlled through the environment
variables above, ensuring both static and OIDC deployments benefit from the shared persistence layer.

### Theme

The default Streamlit theme is configured through `.streamlit/config.toml`. The dashboard ships with a
dark-first theme that uses Portainer's signature blue (`#009fe3`) as the accent colour:

```toml
[theme]
base = "dark"
primaryColor = "#009fe3"
```

Users can still toggle between Streamlit's light and dark modes from the app settings. Only the primary
accent colour is overridden, so the interface remains readable in either mode.

### Logging

The dashboard configures Python's logging system on startup so messages from both the app and its
dependencies are emitted to the console. Diagnostic output up to `WARNING` is routed to standard
output, while anything `ERROR` and above is sent to standard error. Set the `DASHBOARD_LOG_LEVEL`
environment variable (for example `DEBUG` or `INFO`) to adjust verbosity when troubleshooting.
No additional switches are required—logs become visible as soon as the app starts.

### Trusting internal certificate authorities

Many enterprises issue TLS certificates from a private certificate authority (CA). To keep
`PORTAINER_VERIFY_SSL=true` (the default) and avoid suppressing verification inside the dashboard,
mount the host's CA bundle into the container so Python reuses the same trust store:

1. Export your internal root/intermediate certificates on the host and install them in the operating
   system trust store (for example by placing `*.crt` files under `/usr/local/share/ca-certificates`
   and running `update-ca-certificates` on Debian/Ubuntu).
2. Mount the populated trust store into the container. With Docker Compose you can extend the service
   definition as follows so the distroless image sees the updated bundle:

   ```yaml
   services:
     streamlit-portainer-dashboard:
       volumes:
         - streamlit_portainer_envs:/app/.streamlit
         - /etc/ssl/certs/ca-certificates.crt:/etc/ssl/certs/ca-certificates.crt:ro
         - /usr/local/share/ca-certificates:/usr/local/share/ca-certificates:ro
   ```

   The first bind mount exposes the consolidated CA bundle that Debian maintains at
   `/etc/ssl/certs/ca-certificates.crt`, while the second covers individual certificates in case
   client libraries consult `SSL_CERT_DIR`.
   For RHEL/Fedora hosts, the consolidated bundle typically lives at
   `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`, so make sure `/etc/pki/ca-trust` is mounted
   and point `DASHBOARD_CA_BUNDLE` at that path so the dashboard uses it for TLS verification.
3. Restart the container so the updated certificates are loaded. Python's TLS stack now trusts the
   same issuers as the host and continues to validate Portainer, Kibana, or any other HTTPS
   integrations without disabling verification.

### Persistent API caching

The dashboard now caches Portainer API responses to reduce latency for returning users. The first fetch after
start-up populates the cache on disk (by default inside `.streamlit/cache`, which is persisted automatically when
using the provided Docker volume). Subsequent logins reuse the cached data until either the configured TTL expires
or the cache is invalidated. When cached data becomes stale the dashboard serves the previous snapshot immediately
and refreshes it in the background, clearly indicating when the repull is in progress. The cache is automatically
cleared when operators switch the active Portainer environment, press the **Refresh data** button in the sidebar,
or modify the saved environment configuration. You
can adjust or disable the behaviour through the new environment variables documented above.

### LLM assistant

The **LLM assistant** page lets you connect an OpenWebUI/Ollama deployment to the dashboard. Provide the chat
completion endpoint (for example `https://llm.example.com/v1/chat/completions`), your API token and
model name (such as `gpt-oss`). When the `LLM_BEARER_TOKEN` environment variable is present, the bearer-token
field is pre-filled automatically so operators can start querying immediately. Setting both `LLM_API_ENDPOINT`
and `LLM_BEARER_TOKEN` locks the connection details, making it clear which managed LLM instance the dashboard uses.
The token field accepts either a
traditional bearer token or a `username:password`
pair, which is automatically sent using HTTP Basic authentication when detected. The page now builds an
operational summary (container counts, unhealthy services, top CPU/memory consumers) before serialising the
underlying Portainer tables. You can steer how much detail reaches the LLM by adjusting both the maximum number
of container rows and a dedicated “Max context tokens” control that accepts custom budgets for extended-context
models; the assistant automatically trims low-priority tables or reduces their size when the payload would exceed
that budget. This keeps prompts efficient even when
large environments are selected. The UI surfaces the exact context size, any trade-offs that were applied, and
still allows you to download the data that was shared for auditing. With the context in place you can ask natural
language questions—such as “are there any containers that have issues and why?”—and review the LLM response
directly inside the dashboard.
When your LLM API uses a private certificate authority, set `DASHBOARD_CA_BUNDLE` to point at the
PEM file that should be trusted for TLS verification.

#### How the LLM workflow is orchestrated

At a high level the assistant prepares the data hub and operational overview, asks the model for a research plan,
executes the requested queries, and finally supplies the results for the answer stage. The following diagram
captures the flow:

```mermaid
flowchart TD
    A[User enters question + config] --> B[Build data hub & overview]
    B --> C[_build_research_prompt()]
    C --> D[LLMClient.chat (planning)]
    D -->|plan JSON| E[parse_query_plan()]
    E --> F{Any requests?}
    F -- Yes --> G[Execute QueryRequests via LLMDataHub]
    G --> H[serialise_results()]
    F -- No --> H
    H --> I[_build_answer_prompt()]
    I --> J[LLMClient.chat (answer)]
    J --> K[Display answer & plan\nStore in conversation]
    K --> L[Expose datasets & payload for auditing]
```

**Planning stage** – `_build_research_prompt()` primes the LLM to return a JSON plan describing which tables or
metrics it wants to inspect. `parse_query_plan()` extracts the structured instructions, skips malformed entries,
and warns when the model requests more datasets than allowed.

**Execution stage** – For each valid request the hub filters and serialises the relevant Portainer dataframes and
captures a compact summary of what was shared with the model.

**Answer stage** – `_build_answer_prompt()` restates the question, embeds the executed plan and results, and asks
the LLM to provide a final answer that reuses the supplied JSON context. The response is displayed alongside the
plan and downloadable datasets so operators can audit exactly what was sent.

### Container Logs (Direct Docker Access)

The **Container Logs** page provides direct access to Docker container logs via the Portainer API, without requiring
Kibana/Elasticsearch. This is useful for quick debugging when you need to check why a container stopped or is
misbehaving:

- Select an endpoint and container from dropdown menus
- Configure tail lines (100-5000) and time range (15 minutes to 24 hours)
- Toggle timestamp display
- Download logs as a text file for offline analysis

The LLM assistant also uses this capability to automatically fetch logs for stopped or unhealthy containers, enabling
it to diagnose issues when you ask questions like "Why did container X stop?"

### Edge agent log explorer

The **Edge agent logs** page surfaces container logs collected in Kibana/Elasticsearch. Configure the
`KIBANA_LOGS_ENDPOINT` and `KIBANA_API_KEY` environment variables to enable the integration. The page reuses your
current Portainer filters so you can drill into a specific subset of environments or endpoints before issuing a log
query. Specify a time window (15 minutes to 24 hours), optional container name or message search term and download the
results as CSV for further analysis.

### AI Infrastructure Monitor

The **AI Monitor** page provides real-time AI-powered insights about your infrastructure. The monitoring service runs
in the background every 5 minutes (configurable via `MONITORING_INTERVAL_MINUTES`) and analyzes:

- **Resource usage** – High CPU/memory consumption across containers
- **Availability** – Unhealthy containers, offline endpoints
- **Security** – Containers with elevated privileges (NET_ADMIN, SYS_ADMIN, SYS_PTRACE, etc.)
- **Images** – Outdated container images with available updates
- **Optimization** – Unused resources and efficiency recommendations

When an LLM endpoint is configured (`LLM_API_ENDPOINT`), the monitoring service uses AI to generate human-readable
insights with recommended actions. Without an LLM, the service falls back to rule-based analysis.

Insights are delivered in real-time via WebSocket and displayed in the AI Monitor dashboard. Historical insights
are stored in memory (up to `MONITORING_MAX_INSIGHTS_STORED`) and can be filtered by severity level.

### Network Topology

The **Network Topology** page visualizes container network connections across your infrastructure:

- **Interactive Graph** – Containers displayed as nodes, networks as diamond hubs, with edges showing connections
- **Color Coding** – Running containers in green, stopped in gray, networks in blue
- **Filtering** – Filter by endpoint or network name to focus on specific segments
- **Hover Details** – View container name, endpoint, state, image, and IP addresses
- **Connections Table** – Tabular view of all network connections with CSV export

This visualization helps identify network isolation issues, understand container communication patterns, and
document infrastructure topology.

## Usage

### Run with Docker Compose
1. Create a `.env` file (for example by copying `.env.example` if you have one) and populate it with the variables described above,
   including the mandatory `DASHBOARD_USERNAME` and `DASHBOARD_KEY` credentials.
2. Start the application:
   ```bash
   docker compose up -d
   ```
3. Visit http://localhost:8501 to access the dashboard. Any Portainer environments you add inside the app will be stored in the named `streamlit_portainer_envs` volume and remain available for future runs.
4. Use the sidebar controls to manage Portainer environments and filtering. The **Auto-refresh interval** slider can automatically reload data at 15–300 second intervals (set it to `Off`/`0` to disable auto-refresh).

### Run with Docker
1. Build the image (or pull it from your own registry):
   ```bash
   docker build -t streamlit-portainer-dashboard .
   ```
2. Create a `.env` file that contains the variables described above.
3. Create a named volume so the app can persist the saved Portainer environments between runs. Fresh volumes receive the
   pre-populated `.streamlit` directory owned by the distroless `nonroot` user (UID/GID `65532`), so the container can write
   the `portainer_environments.json` file without any manual permission changes:
   ```bash
   docker volume create streamlit_portainer_envs
   ```
4. Start the container, mounting the volume at `/app/.streamlit`:
   ```bash
   docker run -p 8501:8501 --env-file .env \
     -v streamlit_portainer_envs:/app/.streamlit \
     streamlit-portainer-dashboard
   ```
5. Visit http://localhost:8501 to access the dashboard. Any Portainer environments you add inside the app will be stored in the mounted volume and remain available for future container runs.
6. Use the sidebar controls to manage Portainer environments and filtering. The **Auto-refresh interval** slider can automatically reload data at 15–300 second intervals (set it to `Off`/`0` to disable auto-refresh).

#### Repairing existing volumes

If you created the `streamlit_portainer_envs` volume before this ownership fix, update its permissions so the runtime user can persist changes:

```bash
docker run --rm -v streamlit_portainer_envs:/app/.streamlit busybox \
  chown -R 65532:65532 /app/.streamlit
```

### Customising the storage location

By default the dashboard stores the saved environments in a `.streamlit/portainer_environments.json` file inside the application directory. When that location is not writable (for example on some managed hosting platforms) the app will fall back to other writable directories automatically. You can explicitly control the storage path via environment variables:

- Set `PORTAINER_ENVIRONMENTS_PATH` to the full path of the JSON file to use.
- Alternatively, set `PORTAINER_ENVIRONMENTS_DIR` to point to a writable directory and the default file name (`portainer_environments.json`) will be created inside it.
