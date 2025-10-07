# Contributing

Thanks for investing time in improving the Streamlit Portainer dashboard! This project already ships with operator-focused documentation; the resources below help you extend the codebase safely.

## Before you start

1. Review the [module boundaries guide](docs/module_boundaries.md) to understand how pages, services, and shared helpers interact.
2. Skim the existing documentation in `docs/` to see whether your change touches related operational guidance.
3. Set up a Python 3.12 environment and install the dependencies listed in `requirements.txt`.

## Development tips

- Keep new Streamlit UI in `app/pages/` (or `app/components/` for reusable fragments) and use `app/dashboard_state.py` to coordinate shared state.
- Place external integrations and background jobs in `app/services/`, ensuring callers interact with the service instead of reimplementing HTTP requests.
- Extend `app/config/` or `app/settings.py` when introducing new configuration sources so tests and documentation stay consistent.
- Add or update tests under `tests/` when you change behaviour, especially when touching Portainer, Kibana, or LLM integrations.

## Pull request checklist

Include this lightweight checklist in your pull request description or verify each item before requesting review:

- [ ] Changes respect the [documented module boundaries](docs/module_boundaries.md) (UI → shared helpers → services).
- [ ] New or modified pages reuse shared components/state instead of duplicating helpers.
- [ ] Services remain the only layer that calls external APIs or long-running jobs.
- [ ] Documentation updates accompany new configuration flags, background jobs, or navigation entries.
- [ ] Tests cover new logic or existing suites remain green (`pytest -q`).

Following these steps keeps the module boundaries clear and helps reviewers focus on the substance of your contribution.
