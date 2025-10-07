# Portainer data coverage audit

This note summarises the Portainer information currently collected by the dashboard and highlights additional data that could be valuable—especially when preparing context for the LLM assistant.

## Current API coverage

The client now collects a richer slice of the Portainer API:

- Edge endpoint listings via `/endpoints` (with status metadata) to discover managed environments and capture agent versions, platform information, tags, and last check-in timestamps.【F:app/portainer_client.py†L181-L278】【F:app/pages/7_LLM_Assistant.py†L300-L334】
- Stack listings per endpoint through `/stacks` and `/edge/stacks` to map workloads to locations.【F:app/portainer_client.py†L188-L208】
- Container summaries from `/endpoints/{id}/docker/containers/json`, optionally including stopped containers, augmented with inspect and stats snapshots for health status, mounts, networks, and resource usage.【F:app/portainer_client.py†L210-L374】【F:app/portainer_client.py†L376-L515】
- Docker host metadata and usage reports via `/docker/info` and `/docker/system/df` to expose capacity indicators (CPU, memory, image counts, layer sizes).【F:app/portainer_client.py†L517-L602】
- Volume inventories from `/docker/volumes` and image inventories from `/docker/images/json` for persistence and footprint analysis.【F:app/portainer_client.py†L604-L681】
- Optional stack image status checks for drift detection.【F:app/portainer_client.py†L227-L233】

The normalisation helpers preserve these additional fields so the dashboard and LLM assistant can surface metadata, telemetry, and inventories in their respective tables and prompts.【F:app/pages/7_LLM_Assistant.py†L288-L406】

## Opportunities to enrich the dataset

### Remaining opportunities

The latest update closes several of the gaps originally identified, but there is still scope to enrich the dataset further:

- **Historical trends** – Persisting multiple samples of container stats and host utilisation would enable time-series analysis instead of single snapshots.
- **Event streams** – Surfacing container logs or recent events (with redaction) could help the LLM correlate failures with telemetry.
- **LLM payload shaping** – Providing summarised rollups (e.g., "top 5 containers by CPU") in addition to raw tables would keep prompts concise for very large fleets.

These incremental refinements would deepen the operational insights available in the UI while giving the LLM enough structured data to answer higher-value questions about capacity planning, health diagnostics, and configuration drift.
