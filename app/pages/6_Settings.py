"""Settings page for managing Portainer environments."""
from __future__ import annotations

from pathlib import Path

import logging

import streamlit as st

LOGGER = logging.getLogger(__name__)

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

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.services.backup import (  # type: ignore[import-not-found]
        backup_directory,
        create_environment_backup,
        default_backup_password,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from services.backup import (  # type: ignore[no-redef]
        backup_directory,
        create_environment_backup,
        default_backup_password,
    )

_BACKUP_SESSION_KEY = "portainer_backup_latest_path"
_BACKUP_PASSWORD_KEY = "portainer_backup_password"
_BACKUP_PASSWORD_RESET_KEY = "portainer_backup_password_reset"


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
        submitted = st.form_submit_button(
            "Save environment", width="stretch"
        )
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
            LOGGER.info("Created Portainer environment %s", name_value)
        else:
            updated_envs[edit_index] = updated_env
            LOGGER.info("Updated Portainer environment %s", name_value)
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
        LOGGER.info(
            "Testing Portainer connection for %s (%s)",
            name_value or "<unnamed>",
            api_url_value,
        )
        try:
            client = PortainerClient(
                base_url=api_url_value,
                api_key=api_key_value,
                verify_ssl=verify_ssl_value,
            )
            client.list_edge_endpoints()
        except ValueError as exc:
            st.error(f"Connection test failed: {exc}")
            LOGGER.warning(
                "Portainer connection test failed for %s: %s",
                name_value or "<unnamed>",
                exc,
            )
        except PortainerAPIError as exc:
            st.error(f"Connection test failed: {exc}")
            LOGGER.warning(
                "Portainer API connection test failed for %s: %s",
                name_value or "<unnamed>",
                exc,
            )
        else:
            st.success("Successfully connected to Portainer.")
            LOGGER.info(
                "Portainer connection test succeeded for %s", name_value or "<unnamed>"
            )

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

    st.subheader("Backups")
    backup_dir = str(backup_directory())
    st.caption(
        "Backups are stored in the dashboard volume under "
        f"`{backup_dir}`."
    )
    active_config = next(
        (env for env in environments_state if env.get("name") == active_env),
        None,
    )
    if active_config is None:
        st.info("Select an environment to create backups.")
    else:
        if st.session_state.pop(_BACKUP_PASSWORD_RESET_KEY, False):
            st.session_state[_BACKUP_PASSWORD_KEY] = default_backup_password() or ""

        st.session_state.setdefault(
            _BACKUP_PASSWORD_KEY, default_backup_password() or ""
        )

        st.text_input(
            "Backup password (optional)",
            key=_BACKUP_PASSWORD_KEY,
            type="password",
            help="Portainer encrypts the backup with this password when provided.",
        )
        create_backup_clicked = st.button(
            "Create backup",
            key="portainer_create_backup",
            use_container_width=True,
        )
        if create_backup_clicked:
            LOGGER.info(
                "Backup requested for environment %s", active_env or "<unnamed>"
            )
            with st.spinner("Requesting backup from Portainer..."):
                try:
                    password_input = st.session_state[_BACKUP_PASSWORD_KEY].strip()
                    backup_password = password_input or default_backup_password()
                    backup_path = create_environment_backup(
                        active_config,
                        password=backup_password or None,
                    )
                except ValueError as exc:
                    st.error(f"Unable to create backup: {exc}")
                    LOGGER.warning(
                        "Unable to create backup for %s: %s",
                        active_env or "<unnamed>",
                        exc,
                    )
                except PortainerAPIError as exc:
                    st.error(f"Backup failed: {exc}")
                    LOGGER.warning(
                        "Portainer backup failed for %s: %s",
                        active_env or "<unnamed>",
                        exc,
                    )
                except OSError as exc:
                    st.error(f"Failed to save backup: {exc}")
                    LOGGER.warning(
                        "Failed saving backup for %s: %s",
                        active_env or "<unnamed>",
                        exc,
                    )
                else:
                    st.session_state[_BACKUP_SESSION_KEY] = str(backup_path)
                    backup_display = str(backup_path)
                    st.success(
                        "Backup created successfully. Saved to "
                        f"`{backup_display}`."
                    )
                    LOGGER.info(
                        "Backup for %s saved to %s",
                        active_env or "<unnamed>",
                        backup_path,
                    )
                    st.session_state[_BACKUP_PASSWORD_RESET_KEY] = True

        latest_backup = st.session_state.get(_BACKUP_SESSION_KEY)
        if latest_backup:
            backup_path = Path(str(latest_backup))
            if backup_path.exists():
                with backup_path.open("rb") as handle:
                    st.download_button(
                        "Download latest backup",
                        data=handle.read(),
                        file_name=backup_path.name,
                        use_container_width=True,
                        key="portainer_download_backup",
                    )
                st.caption(f"Latest backup located at `{backup_path}`.")
            else:
                st.session_state.pop(_BACKUP_SESSION_KEY, None)
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
            LOGGER.info("Deleted Portainer environment %s", env_name or "<unnamed>")
            rerun_app()

