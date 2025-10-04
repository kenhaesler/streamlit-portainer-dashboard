# streamlit-portainer-dashboard

A streamlit application that pulls information from the Portainer API and visualizes everything.

## Configuration

The application is configured via environment variables:

- `PORTAINER_API_URL` – Base URL of your Portainer instance (e.g. `https://portainer.example.com/api`).
- `PORTAINER_API_KEY` – API key used for authentication.
- `PORTAINER_VERIFY_SSL` – Optional. Set to `false` to disable TLS certificate verification when using self-signed certificates.
