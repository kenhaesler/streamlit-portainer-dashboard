# Agent Guidelines

> Stick to Python best practices whenever possible. For additional guidance, refer to [this best practices guide](https://gist.github.com/ruimaranhao/4e18cbe3dad6f68040c32ed6709090a3).

Welcome! This repository powers the Streamlit Portainer dashboard with a hybrid FastAPI + Streamlit architecture. Follow these tips when working inside this project:

## Project layout

**Backend (FastAPI):**
- Entry point is `src/portainer_dashboard/main.py`
- API routes in `src/portainer_dashboard/api/v1/`
- Services in `src/portainer_dashboard/services/`
- WebSocket handlers in `src/portainer_dashboard/websocket/`
- Background scheduler in `src/portainer_dashboard/scheduler/`
- Configuration in `src/portainer_dashboard/config.py`

**Frontend (Streamlit):**
- Entry point is `streamlit_ui/Home.py`
- Additional pages in `streamlit_ui/pages/`
- Shared helpers in `streamlit_ui/shared.py`
- API client in `streamlit_ui/api_client.py`

**Tests:**
- Unit/integration tests reside in `tests/unit/` and `tests/integration/`
- E2E tests using Playwright are in `tests/e2e/`
  - Page Object Model classes in `tests/e2e/pages/`
  - MockServer configs in `tests/e2e/mocks/`
- Tests cover Portainer client, backup helpers, LLM integration, monitoring services, and full UI flows

**Scripts:**
- Shell utilities live in `scripts/`; the `check_app_starts.sh` script bootstraps the Streamlit server for smoke testing.

## Development workflow
- Prefer Python 3.14 (matching the Dockerfile) and keep code type-hinted. Use built-in generics (`list`, `dict`, `tuple`) instead of `typing.List`, `typing.Dict`, `typing.Tuple`. Use `X | None` instead of `Optional[X]`. Import `Callable`, `Iterable`, `Mapping`, `Sequence` from `collections.abc` instead of `typing`.
- Run formatting/linters that ship with the repository (currently none). Stay consistent with the existing style—standard library first, third-party next, local imports last.
- Write tests with `pytest`. Use `pytest -q` for the unit suite. When you add new behaviour that touches Portainer interactions, make sure to mock HTTP requests just like the existing tests do.
- Use `scripts/check_app_starts.sh` for a quick smoke test after substantial UI changes. It expects the Streamlit dependencies to be installed in the current environment.
- Keep the dashboard user-friendly and responsive. Optimise for performance where practical and ensure new features preserve the app's security posture.
- Avoid capping or truncating data whenever possible; instead, design solutions that can gracefully handle the full data set.

## Testing expectations
- Always run the available automated checks when modifying code. At a minimum execute `pytest tests/unit tests/integration -q` before submitting a change, and run any targeted tests that cover the modules you touched.
- Do not commit changes while any required automated tests are failing.
- When you adjust UI flows or authentication, pair the unit tests with a manual smoke test via `scripts/check_app_starts.sh` to confirm the app still boots and the login flow works as expected.
- For UI changes, consider running E2E tests: `pytest tests/e2e/ -v` (requires `pip install -e ".[e2e]"` and `playwright install chromium`).
- E2E tests can run against the Docker Compose mock environment: `docker compose -f docker-compose.e2e.yml up -d --wait`

## Environment & configuration
- Streamlit configuration lives under `.streamlit/`. Data directories are configured via environment variables.
- Authentication relies on the `DASHBOARD_USERNAME` and `DASHBOARD_KEY` environment variables (or OIDC). Tests should not depend on real credentials—mock them via `monkeypatch` if necessary.
- AI Monitoring is configured via `MONITORING_*` environment variables (enabled, interval, max insights).

## Pull request expectations
- Update the documentation when you add new environment variables, UI pages, or background jobs.
- Highlight any operational impacts (new ports, scheduled tasks, or migrations) in the PR description so maintainers can plan deployments accordingly.

Happy hacking!
