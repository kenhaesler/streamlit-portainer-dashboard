from __future__ import annotations

from typing import Any

import pytest

from app.managers.environment_manager import EnvironmentManager


def test_initialise_loads_environments_and_sets_default_selection():
    state: dict[str, Any] = {}
    loader_called = False

    def fake_loader() -> list[dict[str, object]]:
        nonlocal loader_called
        loader_called = True
        return [
            {
                "name": "Prod",
                "api_url": "https://prod.example/api",
                "api_key": "token",
                "verify_ssl": True,
            }
        ]

    manager = EnvironmentManager(
        state,
        clear_cache=lambda **_: None,
        loader=fake_loader,
        saver=lambda environments: None,
        env_setter=lambda key, value: None,
    )

    environments = manager.initialise()

    assert loader_called is True
    assert environments[0]["name"] == "Prod"
    assert state[EnvironmentManager.ENVIRONMENTS_KEY][0]["name"] == "Prod"
    assert state[EnvironmentManager.SELECTED_ENV_KEY] == "Prod"


def test_initialise_preserves_existing_selection():
    state: dict[str, Any] = {
        EnvironmentManager.ENVIRONMENTS_KEY: [
            {"name": "Prod"},
            {"name": "Staging"},
        ],
        EnvironmentManager.SELECTED_ENV_KEY: "Staging",
    }

    manager = EnvironmentManager(
        state,
        clear_cache=lambda **_: None,
        loader=lambda: state[EnvironmentManager.ENVIRONMENTS_KEY],
        saver=lambda environments: None,
        env_setter=lambda key, value: None,
    )

    manager.initialise()

    assert state[EnvironmentManager.SELECTED_ENV_KEY] == "Staging"


def test_set_saved_environments_persists_to_state_and_disk():
    state: dict[str, Any] = {}
    saved_payload: list[list[dict[str, object]]] = []

    def fake_saver(environments: list[dict[str, object]]) -> None:
        saved_payload.append(list(environments))

    manager = EnvironmentManager(
        state,
        clear_cache=lambda **_: None,
        loader=lambda: [],
        saver=fake_saver,
        env_setter=lambda key, value: None,
    )

    payload = [
        {
            "name": "Prod",
            "api_url": "https://prod.example/api",
            "api_key": "token",
            "verify_ssl": False,
        }
    ]

    manager.set_saved_environments(payload)

    assert state[EnvironmentManager.ENVIRONMENTS_KEY] == payload
    assert saved_payload == [payload]


@pytest.mark.parametrize(
    "previous,expected_persistent",
    [("", False), ("   ", False), ("Prod", True)],
)
def test_set_active_environment_flags_cache_invalidation(previous: str, expected_persistent: bool):
    state: dict[str, Any] = {
        EnvironmentManager.ENVIRONMENTS_KEY: [
            {"name": "Prod"},
            {"name": "Staging"},
        ],
        EnvironmentManager.SELECTED_ENV_KEY: previous,
    }

    cache_flags: list[bool] = []

    def fake_clear_cache(*, persistent: bool) -> None:
        cache_flags.append(persistent)

    manager = EnvironmentManager(
        state,
        clear_cache=fake_clear_cache,
        loader=lambda: state[EnvironmentManager.ENVIRONMENTS_KEY],
        saver=lambda environments: None,
        env_setter=lambda key, value: None,
    )

    manager.set_active_environment("Staging")

    assert state[EnvironmentManager.SELECTED_ENV_KEY] == "Staging"
    assert state.get(EnvironmentManager.APPLIED_ENV_KEY) is None
    assert cache_flags == [expected_persistent]


def test_apply_selected_environment_sets_environment_variables():
    state: dict[str, Any] = {
        EnvironmentManager.ENVIRONMENTS_KEY: [
            {
                "name": "Prod",
                "api_url": "https://prod.example/api",
                "api_key": "token",
                "verify_ssl": False,
            }
        ],
        EnvironmentManager.SELECTED_ENV_KEY: "Prod",
    }

    assigned: dict[str, str] = {}
    call_count = 0

    def fake_env_setter(key: str, value: str) -> None:
        nonlocal call_count
        call_count += 1
        assigned[key] = value

    manager = EnvironmentManager(
        state,
        clear_cache=lambda **_: None,
        loader=lambda: state[EnvironmentManager.ENVIRONMENTS_KEY],
        saver=lambda environments: None,
        env_setter=fake_env_setter,
    )

    manager.apply_selected_environment()
    manager.apply_selected_environment()  # second call should be a no-op

    assert assigned == {
        "PORTAINER_API_URL": "https://prod.example/api",
        "PORTAINER_API_KEY": "token",
        "PORTAINER_VERIFY_SSL": "false",
        "PORTAINER_ENVIRONMENT_NAME": "Prod",
    }
    assert state[EnvironmentManager.APPLIED_ENV_KEY] == "Prod"
    assert call_count == 4  # second call should not reapply
