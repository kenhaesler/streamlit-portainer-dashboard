# streamlit-portainer-dashboard

A streamlit application that pulls information from the Portainer API and visualizes everything.

## Configuration

The application is configured via environment variables:

- `PORTAINER_API_URL` – Base URL of your Portainer instance (e.g. `https://portainer.example.com/api`).
- `PORTAINER_API_KEY` – API key used for authentication.
- `PORTAINER_VERIFY_SSL` – Optional. Set to `false` to disable TLS certificate verification when using self-signed certificates.

## Usage

### Run with Docker
1. Build the image (or pull it from your own registry):
   ```bash
   docker build -t streamlit-portainer-dashboard .
   ```
2. Create a `.env` file that contains the variables described above.
3. Create a named volume so the app can persist the saved Portainer environments between runs:
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

## Development

### Run tests

Compile the Streamlit app to ensure there are no syntax errors:

```bash
python -m compileall app
```

### Build and run locally

Build the Docker image, create the volume used for persisted Streamlit data, and start the container:

```bash
docker build -t streamlit-portainer-dashboard .
docker volume create streamlit_portainer_envs
docker run -p 8501:8501 --env-file .env -v streamlit_portainer_envs:/app/.streamlit streamlit-portainer-dashboard
```
