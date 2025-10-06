# streamlit-portainer-dashboard

A streamlit application that pulls information from the Portainer API and visualizes everything.

## Configuration

The application is configured via environment variables:

- `PORTAINER_API_URL` – Base URL of your Portainer instance (e.g. `https://portainer.example.com/api`).
- `PORTAINER_API_KEY` – API key used for authentication.
- `PORTAINER_VERIFY_SSL` – Optional. Set to `false` to disable TLS certificate verification when using self-signed certificates.
- `DASHBOARD_USERNAME` – Username required to sign in to the dashboard UI.
- `DASHBOARD_KEY` – Access key (password) required to sign in to the dashboard UI.
- `DASHBOARD_SESSION_TIMEOUT_MINUTES` – Optional. Expire authenticated sessions after the specified number of minutes of inactivity. Omit or set to a non-positive value to disable the timeout.
- `PORTAINER_CACHE_ENABLED` – Optional. Defaults to `true`. Set to `false` to disable persistent caching of Portainer API responses between sessions.
- `PORTAINER_CACHE_TTL_SECONDS` – Optional. Number of seconds before cached Portainer API responses are refreshed. Defaults to 900 seconds (15 minutes). Set to `0` or a negative value to keep cached data until it is manually invalidated.
- `PORTAINER_CACHE_DIR` – Optional. Directory used to persist cached Portainer data. Defaults to `.streamlit/cache` inside the application directory.
- `PORTAINER_BACKUP_INTERVAL` – Optional. Interval used for automatic Portainer backups (for example `24h` or `30m`). Set to `0`, `off`, or leave unset to disable recurring backups. The dashboard persists the next scheduled run on disk so restarts continue the cadence without creating duplicate backups.

Both `DASHBOARD_USERNAME` and `DASHBOARD_KEY` must be set. When they are missing, the app blocks access and displays an error so
operators can fix the configuration before exposing the dashboard.

After signing in, operators can use the persistent **Log out** button in the sidebar to clear their authentication session when
they step away from the dashboard. When a session timeout is configured, the remaining time is shown in the sidebar so
operators can always see how much longer the session will stay active. The dashboard automatically refreshes idle sessions every
second to keep the countdown up to date. During the final 30 seconds a warning banner appears with a **Keep me logged in**
button; clicking it immediately refreshes the activity timestamp and prevents the session from expiring.

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

### Persistent API caching

The dashboard now caches Portainer API responses to reduce latency for returning users. The first fetch after
start-up populates the cache on disk (by default inside `.streamlit/cache`, which is persisted automatically when
using the provided Docker volume). Subsequent logins reuse the cached data until either the configured TTL expires
or the cache is invalidated. The cache is automatically cleared when operators switch the active Portainer
environment, press the **Refresh data** button in the sidebar, or modify the saved environment configuration. You
can adjust or disable the behaviour through the new environment variables documented above.

### LLM assistant

The **LLM assistant** page lets you connect an OpenWebUI/Ollama deployment to the dashboard. Provide the chat
completion endpoint (for example `https://llm.example.com/v1/chat/completions`), your API token and
model name (such as `gpt-oss`). The page summarises the containers and stacks returned by Portainer—including any
warnings—and sends that context along with your natural language question. This makes it possible to ask questions
like “are there any containers that have issues and why?” directly from the dashboard. Responses are displayed in
the UI and you can download the exact context shared with the model for auditing.

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
