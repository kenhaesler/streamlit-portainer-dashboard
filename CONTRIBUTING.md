# Contributing

Thanks for investing time in improving the Streamlit Portainer dashboard! This project already ships with operator-focused documentation; the resources below help you extend the codebase safely.

## Before you start

1. Review the [module boundaries guide](docs/module_boundaries.md) to understand how pages, services, and shared helpers interact.
2. Skim the existing documentation in `docs/` to see whether your change touches related operational guidance.
3. Set up a Python 3.14 environment and install the dependencies: `pip install -e ".[dev,streamlit,e2e]"`
4. For E2E testing, install Playwright browsers: `playwright install chromium`

## Architecture

This is a hybrid FastAPI + Streamlit dashboard:
- **Backend:** `src/portainer_dashboard/` - FastAPI application
- **Frontend:** `streamlit_ui/` - Streamlit UI pages

## Development tips

- Keep new Streamlit UI in `streamlit_ui/pages/` and use `streamlit_ui/shared.py` for reusable components.
- Place external integrations and background jobs in `src/portainer_dashboard/services/`, ensuring callers interact with the service instead of reimplementing HTTP requests.
- Extend `src/portainer_dashboard/config.py` when introducing new configuration sources so tests and documentation stay consistent.
- Add or update tests under `tests/` when you change behaviour, especially when touching Portainer, Kibana, or LLM integrations.

## Pull request checklist

Include this lightweight checklist in your pull request description or verify each item before requesting review:

- [ ] Changes respect the [documented module boundaries](docs/module_boundaries.md) (UI → shared helpers → services).
- [ ] New or modified pages reuse shared components/state instead of duplicating helpers.
- [ ] Services remain the only layer that calls external APIs or long-running jobs.
- [ ] Documentation updates accompany new configuration flags, background jobs, or navigation entries.
- [ ] Unit/integration tests cover new logic or existing suites remain green (`pytest tests/unit tests/integration -q`).
- [ ] For UI changes, E2E tests pass (`pytest tests/e2e/ -v`) or new E2E tests are added.

Following these steps keeps the module boundaries clear and helps reviewers focus on the substance of your contribution.

## Running tests

```bash
# Unit & integration tests
pytest tests/unit tests/integration -q

# E2E tests (requires playwright)
pip install -e ".[e2e]"
playwright install chromium
pytest tests/e2e/ -v

# E2E with Docker Compose mock environment
docker compose -f docker-compose.e2e.yml up -d --wait
pytest tests/e2e/ -v
docker compose -f docker-compose.e2e.yml down -v
```
