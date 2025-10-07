# Agent Guidelines

Welcome! This repository powers the Streamlit Portainer dashboard. Follow these tips when working inside this project:

## Project layout
- The Streamlit entry point is `app/Home.py`. Additional pages live under `app/pages/` and shared helpers inside `app/`.
- Tests reside in the `tests/` package and cover the Portainer client, backup helpers, and LLM integration.
- Shell utilities live in `scripts/`; the `check_app_starts.sh` script bootstraps the Streamlit server for smoke testing.

## Development workflow
- Prefer Python 3.12 (matching the Dockerfile) and keep code type-hinted. The codebase already imports `from __future__ import annotations` in most modules—follow suit for new files.
- Run formatting/linters that ship with the repository (currently none). Stay consistent with the existing style—standard library first, third-party next, local imports last.
- Write tests with `pytest`. Use `pytest -q` for the unit suite. When you add new behaviour that touches Portainer interactions, make sure to mock HTTP requests just like the existing tests do.
- Use `scripts/check_app_starts.sh` for a quick smoke test after substantial UI changes. It expects the Streamlit dependencies to be installed in the current environment.
- Keep the dashboard user-friendly and responsive. Optimise for performance where practical and ensure new features preserve the app's security posture.

## Environment & configuration
- Streamlit configuration and cached Portainer data live under `.streamlit/`. When your changes touch persistence or caching, verify they respect the `PORTAINER_CACHE_*` variables described in `README.md`.
- Authentication relies on the `DASHBOARD_USERNAME` and `DASHBOARD_KEY` environment variables. Tests should not depend on real credentials—mock them via `monkeypatch` if necessary.

## Pull request expectations
- Update the documentation when you add new environment variables, UI pages, or background jobs.
- Highlight any operational impacts (new ports, scheduled tasks, or migrations) in the PR description so maintainers can plan deployments accordingly.

Happy hacking!
