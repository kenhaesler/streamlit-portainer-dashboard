"""Entry point for the Streamlit Portainer dashboard."""
from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.dashboard_state import (  # type: ignore[import-not-found]
        apply_selected_environment,
        get_saved_environments,
        initialise_session_state,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from dashboard_state import (  # type: ignore[no-redef]
        apply_selected_environment,
        get_saved_environments,
        initialise_session_state,
    )


try:  # pragma: no cover - import shim for Streamlit runtime
    from app.ui_helpers import apply_global_theme  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from ui_helpers import apply_global_theme  # type: ignore[no-redef]


load_dotenv()

st.set_page_config(page_title="Portainer Dashboard", layout="wide")
apply_global_theme()

initialise_session_state()
apply_selected_environment()

st.title("🚀 Streamlit Portainer Dashboard")
st.write(
    "Navigate using the sidebar to explore the different dashboards. "
    "Use the **Settings** page to configure Portainer environments."
)

if not get_saved_environments():
    st.info(
        "No saved Portainer environments detected. Configure an environment from the "
        "Settings page or provide credentials using environment variables."
    )

