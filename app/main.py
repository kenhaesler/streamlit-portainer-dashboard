"""Entry point for the Streamlit Portainer dashboard."""
from __future__ import annotations

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.dashboard_state import (  # type: ignore[import-not-found]
        apply_selected_environment,
        get_saved_environments,
        initialise_session_state,
    )
    from app.ui_helpers import apply_lucerne_theme  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from dashboard_state import (  # type: ignore[no-redef]
        apply_selected_environment,
        get_saved_environments,
        initialise_session_state,
    )
    from ui_helpers import apply_lucerne_theme  # type: ignore[no-redef]


load_dotenv()

logo_path = Path(__file__).resolve().parent / "assets" / "ktlu-logo.svg"
st.set_page_config(
    page_title="Portainer Dashboard",
    layout="wide",
    page_icon=str(logo_path) if logo_path.exists() else "🔷",
)

if logo_path.exists():
    try:
        st.logo(str(logo_path))
    except Exception:  # pragma: no cover - optional enhancement
        pass

initialise_session_state()
apply_lucerne_theme()
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

