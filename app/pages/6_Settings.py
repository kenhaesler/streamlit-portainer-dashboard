"""Settings page for managing Portainer environments."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import streamlit as st

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.config import (  # type: ignore[import-not-found]
        ConfigurationError as ConfigError,
        get_config,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from config import (  # type: ignore[no-redef]
        ConfigurationError as ConfigError,
        get_config,
    )

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
        clear_cached_data,
        trigger_rerun,
    )
    from app.managers.background_job_runner import (  # type: ignore[import-not-found]
        BackgroundJobRunner,
    )
    from app.managers.environment_manager import (  # type: ignore[import-not-found]
        EnvironmentManager,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from dashboard_state import (  # type: ignore[no-redef]
        clear_cached_data,
        trigger_rerun,
    )
    from managers.background_job_runner import (  # type: ignore[no-redef]
        BackgroundJobRunner,
    )
    from managers.environment_manager import (  # type: ignore[no-redef]
        EnvironmentManager,
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
    from app.services.backup_scheduler import (  # type: ignore[import-not-found]
        ScheduleSnapshot,
        get_schedule_snapshot,
        update_schedule_interval,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from services.backup import (  # type: ignore[no-redef]
        backup_directory,
        create_environment_backup,
        default_backup_password,
    )
    from services.backup_scheduler import (  # type: ignore[no-redef]
        ScheduleSnapshot,
        get_schedule_snapshot,
        update_schedule_interval,
    )

_BACKUP_SESSION_KEY = "portainer_backup_latest_path"
_BACKUP_PASSWORD_KEY = "portainer_backup_password"
_BACKUP_PASSWORD_RESET_KEY = "portainer_backup_password_reset"

_SCHEDULE_FORM_KEY = "portainer_backup_schedule_form"
_SCHEDULE_ENABLE_KEY = "portainer_backup_schedule_enable"
_SCHEDULE_VALUE_KEY = "portainer_backup_schedule_value"
_SCHEDULE_UNIT_KEY = "portainer_backup_schedule_unit"
_SCHEDULE_ENV_VAR = "PORTAINER_BACKUP_INTERVAL"

_INTERVAL_OPTIONS = [
    ("Seconds", 1),
    ("Minutes", 60),
    ("Hours", 3600),
    ("Days", 86_400),
]


def _format_timestamp(value: _dt.datetime | None) -> str:
    if value is None:
        return "—"
    try:
        localised = value.astimezone()
    except ValueError:
        localised = value
    return localised.strftime("%Y-%m-%d %H:%M:%S %Z")


def _seconds_to_parts(seconds: int) -> tuple[int, str]:
    seconds = max(int(seconds), 0)
    if seconds <= 0:
        return 24, "Hours"
    for label, multiplier in reversed(_INTERVAL_OPTIONS):
        if multiplier == 0:
            continue
        if seconds % multiplier == 0:
            return seconds // multiplier, label
    return seconds, "Seconds"


def _parts_to_seconds(value: int, unit_label: str) -> int:
    lookup = {label: multiplier for label, multiplier in _INTERVAL_OPTIONS}
    multiplier = lookup.get(unit_label, 1)
    return max(int(value), 0) * multiplier


def rerun_app() -> None:
    """Trigger a Streamlit rerun across supported API versions."""

    trigger_rerun()

try:
    CONFIG = get_config()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

require_authentication(CONFIG)
render_logout_button()

st.title("Settings")

initialise_session_state(CONFIG)

pending_active_env_key = "portainer_env_pending_active"
if pending_active := st.session_state.pop(pending_active_env_key, None):
    set_active_environment(CONFIG, pending_active)

apply_selected_environment(CONFIG)
environment_manager = EnvironmentManager(
    st.session_state, clear_cache=clear_cached_data
)
environments = environment_manager.initialise()
BackgroundJobRunner().maybe_run_backups(environments)

pending_active_env_key = "portainer_env_pending_active"
if pending_active := st.session_state.pop(pending_active_env_key, None):
    environment_manager.set_active_environment(pending_active)

environment_manager.apply_selected_environment()

st.header("Portainer environments")

environments_state = environment_manager.get_saved_environments()
env_names = [env.get("name", "") for env in environments_state if env.get("name")]

form_selection_key = "portainer_env_form_selection"
prev_selection_key = "portainer_env_form_prev_selection"
pending_selection_key = "portainer_env_form_pending_selection"
options = ["New environment", *env_names]

if pending_selection := st.session_state.pop(pending_selection_key, None):
    st.session_state[form_selection_key] = pending_selection

if st.session_state.get(form_selection_key) not in options:
    default_env = environment_manager.get_selected_environment_name() or "New environment"
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
    st.session_state["portainer_env_form_show_api_key"] = False

st.session_state.setdefault("portainer_env_form_name", "")
st.session_state.setdefault("portainer_env_form_api_url", "")
st.session_state.setdefault("portainer_env_form_api_key", "")
st.session_state.setdefault("portainer_env_form_verify_ssl", True)
st.session_state.setdefault("portainer_env_form_show_api_key", False)

form_error: str | None = None
test_connection_clicked = False
with st.form("portainer_env_form"):
    st.text_input("Name", key="portainer_env_form_name")
    st.text_input("API URL", key="portainer_env_form_api_url")
    st.checkbox(
        "Show API key",
        key="portainer_env_form_show_api_key",
        help="Temporarily reveal the API key in this session.",
    )
    st.text_input(
        "API key",
        key="portainer_env_form_api_key",
        type=(
            "default"
            if st.session_state.get("portainer_env_form_show_api_key")
            else "password"
        ),
    )
    st.checkbox(
        "Verify SSL certificates",
        key="portainer_env_form_verify_ssl",
    )
    if not st.session_state.get("portainer_env_form_verify_ssl", True):
        st.warning(
            "SSL certificate verification is disabled. Only use this for trusted "
            "internal installations.",
            icon="⚠️",
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
        else:
            updated_envs[edit_index] = updated_env
        set_saved_environments(updated_envs)
        set_active_environment(CONFIG, name_value)
        environment_manager.set_saved_environments(updated_envs)
        environment_manager.set_active_environment(name_value)
        st.session_state[pending_selection_key] = name_value
        st.session_state[prev_selection_key] = name_value
        clear_cached_data(CONFIG)
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
    active_env = environment_manager.get_selected_environment_name()
    choice = st.radio(
        "Choose which environment to use for dashboards",
        env_names,
        index=env_names.index(active_env) if active_env in env_names else 0,
        key="portainer_selected_env",
    )
    if choice != active_env:
        set_active_environment(CONFIG, choice)
        environment_manager.set_active_environment(choice)
        rerun_app()

else:
    st.info("No environments saved yet. Add one using the form above.")

st.subheader("Backups")
backup_dir = str(backup_directory())
st.caption(
    "Backups are stored in the dashboard volume under "
    f"`{backup_dir}`."
)

schedule_snapshot: ScheduleSnapshot = get_schedule_snapshot()

active_config = next(
    (env for env in environments_state if env.get("name") == active_env),
    None,
)

if not env_names:
    st.caption("Add an environment above to create backups.")
elif active_config is None:
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
            except PortainerAPIError as exc:
                st.error(f"Backup failed: {exc}")
            except OSError as exc:
                st.error(f"Failed to save backup: {exc}")
            else:
                st.session_state[_BACKUP_SESSION_KEY] = str(backup_path)
                backup_display = str(backup_path)
                st.success(
                    "Backup created successfully. Saved to "
                    f"`{backup_display}`."
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

st.markdown("### Scheduled backups")

submitted_schedule = False
if schedule_snapshot.managed_by_env:
    env_value = schedule_snapshot.env_value or ""
    if env_value:
        st.info(
            "Recurring backups are managed by the "
            f"`{_SCHEDULE_ENV_VAR}` environment variable (value: `{env_value}`)."
        )
    else:
        st.info(
            "Recurring backups are managed by the "
            f"`{_SCHEDULE_ENV_VAR}` environment variable."
        )
    if schedule_snapshot.env_parse_error:
        st.warning(schedule_snapshot.env_parse_error)
else:
    unit_labels = [label for label, _ in _INTERVAL_OPTIONS]
    default_value, default_unit = _seconds_to_parts(schedule_snapshot.interval_seconds)
    try:
        default_index = unit_labels.index(default_unit)
    except ValueError:
        default_index = unit_labels.index("Seconds")

    with st.form(_SCHEDULE_FORM_KEY):
        enable_default = schedule_snapshot.interval_seconds > 0
        enabled = st.checkbox(
            "Enable recurring backups",
            value=enable_default,
            key=_SCHEDULE_ENABLE_KEY,
        )
        interval_value = st.number_input(
            "Run every",
            min_value=1,
            value=default_value,
            step=1,
            format="%d",
            key=_SCHEDULE_VALUE_KEY,
            disabled=not enabled,
        )
        unit_choice = st.selectbox(
            "Interval unit",
            unit_labels,
            index=default_index,
            key=_SCHEDULE_UNIT_KEY,
            disabled=not enabled,
        )
        submitted_schedule = st.form_submit_button(
            "Save schedule",
            use_container_width=True,
        )

    if submitted_schedule:
        try:
            if enabled:
                seconds = _parts_to_seconds(int(interval_value), unit_choice)
                if seconds <= 0:
                    st.warning(
                        "Please choose a schedule interval greater than zero seconds."
                    )
                else:
                    schedule_snapshot = update_schedule_interval(seconds)
                    st.success("Scheduled backups updated.")
            else:
                schedule_snapshot = update_schedule_interval(0)
                st.info("Scheduled backups disabled.")
        except RuntimeError as exc:
            st.warning(str(exc))
            schedule_snapshot = get_schedule_snapshot()

if schedule_snapshot.interval_seconds > 0:
    next_run_text = _format_timestamp(schedule_snapshot.next_run)
    st.caption(f"Next run scheduled for {next_run_text}.")
else:
    if schedule_snapshot.managed_by_env and schedule_snapshot.env_value:
        st.caption("Scheduled backups are disabled by the environment configuration.")
    else:
        st.caption("Scheduled backups are currently disabled.")

if schedule_snapshot.history:
    st.markdown("**Recent jobs**")
    history_rows = []
    for entry in schedule_snapshot.history:
        history_rows.append(
            {
                "Completed": _format_timestamp(entry.completed_at),
                "Status": entry.status.title(),
                "Archives": ", ".join(path.name for path in entry.generated_paths) or "—",
                "Errors": "\n".join(entry.errors) or "—",
            }
        )
    st.table(history_rows)
else:
    st.caption("No scheduled backups have run yet.")

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
            environment_manager.set_saved_environments(updated_envs)
            if environment_manager.get_selected_environment_name() == env_name:
                next_name = updated_envs[0]["name"] if updated_envs else ""
                st.session_state[pending_active_env_key] = next_name
            clear_cached_data(CONFIG)
            rerun_app()

