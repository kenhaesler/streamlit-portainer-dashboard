"""Settings page for managing Portainer environments."""
from __future__ import annotations

import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.auth import (  # type: ignore[import-not-found]
        render_logout_button,
        require_authentication,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from auth import (  # type: ignore[no-redef]
        render_logout_button,
        require_authentication,
    )

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.dashboard_state import (  # type: ignore[import-not-found]
        apply_selected_environment,
        clear_cached_data,
        get_saved_environments,
        get_selected_environment_name,
        initialise_session_state,
        set_active_environment,
        set_saved_environments,
        trigger_rerun,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from dashboard_state import (  # type: ignore[no-redef]
        apply_selected_environment,
        clear_cached_data,
        get_saved_environments,
        get_selected_environment_name,
        initialise_session_state,
        set_active_environment,
        set_saved_environments,
        trigger_rerun,
    )

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.portainer_client import (  # type: ignore[import-not-found]
        PortainerAPIError,
        PortainerClient,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from portainer_client import (  # type: ignore[no-redef]
        PortainerAPIError,
        PortainerClient,
    )



def rerun_app() -> None:
    """Trigger a Streamlit rerun across supported API versions."""

    trigger_rerun()


require_authentication()
render_logout_button()

st.title("Settings")

initialise_session_state()

pending_active_env_key = "portainer_env_pending_active"
if pending_active := st.session_state.pop(pending_active_env_key, None):
    set_active_environment(pending_active)

apply_selected_environment()

st.header("Portainer environments")

environments_state = get_saved_environments()
env_names = [env.get("name", "") for env in environments_state if env.get("name")]

form_selection_key = "portainer_env_form_selection"
prev_selection_key = "portainer_env_form_prev_selection"
pending_selection_key = "portainer_env_form_pending_selection"
options = ["New environment", *env_names]

if pending_selection := st.session_state.pop(pending_selection_key, None):
    st.session_state[form_selection_key] = pending_selection

if st.session_state.get(form_selection_key) not in options:
    default_env = get_selected_environment_name() or "New environment"
    st.session_state[form_selection_key] = (
        default_env if default_env in env_names else "New environment"
    )

selection = st.selectbox("Manage environment", options, key=form_selection_key)
selected_env = next(
    (env for env in environments_state if env.get("name") == selection),
    None,
)

if st.session_state.get(prev_selection_key) != selection:
    st.session_state[prev_selection_key] = selection
    st.session_state["portainer_env_form_name"] = (
        selected_env.get("name", "") if selected_env else ""
    )
    st.session_state["portainer_env_form_api_url"] = (
        selected_env.get("api_url", "") if selected_env else ""
    )
    st.session_state["portainer_env_form_api_key"] = (
        selected_env.get("api_key", "") if selected_env else ""
    )
    st.session_state["portainer_env_form_verify_ssl"] = (
        bool(selected_env.get("verify_ssl", True)) if selected_env else True
    )

st.session_state.setdefault("portainer_env_form_name", "")
st.session_state.setdefault("portainer_env_form_api_url", "")
st.session_state.setdefault("portainer_env_form_api_key", "")
st.session_state.setdefault("portainer_env_form_verify_ssl", True)

form_error: str | None = None
test_connection_clicked = False
with st.form("portainer_env_form"):
    st.text_input("Name", key="portainer_env_form_name")
    st.text_input("API URL", key="portainer_env_form_api_url")
    st.text_input(
        "API key",
        key="portainer_env_form_api_key",
        type="password",
    )
    st.checkbox(
        "Verify SSL certificates",
        key="portainer_env_form_verify_ssl",
    )
    save_col, test_col = st.columns(2)
    with save_col:
        submitted = st.form_submit_button("Save environment", width="stretch")
    with test_col:
        test_connection_clicked = st.form_submit_button(
            "Test connection",
            width="stretch",
        )

name_value = st.session_state["portainer_env_form_name"].strip()
api_url_value = st.session_state["portainer_env_form_api_url"].strip()
api_key_value = st.session_state["portainer_env_form_api_key"].strip()
verify_ssl_value = bool(st.session_state["portainer_env_form_verify_ssl"])

if submitted:
    missing_fields = [
        label
        for label, value in (
            ("Name", name_value),
            ("API URL", api_url_value),
            ("API key", api_key_value),
        )
        if not value
    ]
    if missing_fields:
        form_error = f"Please provide values for: {', '.join(missing_fields)}."
    else:
        updated_env = {
            "name": name_value,
            "api_url": api_url_value,
            "api_key": api_key_value,
            "verify_ssl": verify_ssl_value,
        }
        updated_envs = list(environments_state)
        edit_index = None
        if selected_env is not None:
            edit_index = environments_state.index(selected_env)
        else:
            for idx, env in enumerate(environments_state):
                if env.get("name") == name_value:
                    edit_index = idx
                    break
        if edit_index is None:
            updated_envs.append(updated_env)
        else:
            updated_envs[edit_index] = updated_env
        set_saved_environments(updated_envs)
        set_active_environment(name_value)
        st.session_state[pending_selection_key] = name_value
        st.session_state[prev_selection_key] = name_value
        clear_cached_data()
        rerun_app()

if form_error:
    st.error(form_error)

if test_connection_clicked and not submitted:
    if not api_url_value or not api_key_value:
        st.error("Please provide values for: API URL, API key.")
    else:
        try:
            client = PortainerClient(
                base_url=api_url_value,
                api_key=api_key_value,
                verify_ssl=verify_ssl_value,
            )
            client.list_edge_endpoints()
        except ValueError as exc:
            st.error(f"Connection test failed: {exc}")
        except PortainerAPIError as exc:
            st.error(f"Connection test failed: {exc}")
        else:
            st.success("Successfully connected to Portainer.")

if env_names:
    st.subheader("Active environment")
    active_env = get_selected_environment_name()
    choice = st.radio(
        "Choose which environment to use for dashboards",
        env_names,
        index=env_names.index(active_env) if active_env in env_names else 0,
        key="portainer_selected_env",
    )
    if choice != active_env:
        set_active_environment(choice)
        rerun_app()
else:
    st.info("No environments saved yet. Add one using the form above.")

for env in environments_state:
    env_name = env.get("name", "")
    cols = st.columns([3, 1])
    with cols[0]:
        st.markdown(f"**{env_name}**  \n{env.get('api_url', '')}")
    with cols[1]:
        if st.button("Delete", key=f"delete_env_{env_name}"):
            updated_envs = [
                existing for existing in environments_state if existing.get("name") != env_name
            ]
            set_saved_environments(updated_envs)
            if get_selected_environment_name() == env_name:
                next_name = updated_envs[0]["name"] if updated_envs else ""
                st.session_state[pending_active_env_key] = next_name
            clear_cached_data()
            rerun_app()

