"""Landing page for the Streamlit Portainer dashboard."""
from __future__ import annotations

import textwrap

import streamlit as st
from dotenv import load_dotenv

try:  # pragma: no cover - import shim for Streamlit runtime
    from app.auth import (  # type: ignore[import-not-found]
        render_logout_button,
        require_authentication,
        get_active_session_count,
    )
    from app.managers.background_job_runner import (  # type: ignore[import-not-found]
        BackgroundJobRunner,
    )
    from app.managers.environment_manager import (  # type: ignore[import-not-found]
        EnvironmentManager,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback when executed as a script
    from auth import (  # type: ignore[no-redef]
        render_logout_button,
        require_authentication,
        get_active_session_count,
    )
    from managers.background_job_runner import (  # type: ignore[no-redef]
        BackgroundJobRunner,
    )
    from managers.environment_manager import (  # type: ignore[no-redef]
        EnvironmentManager,
    )


load_dotenv()

st.set_page_config(page_title="Portainer Dashboard", page_icon="🛳️", layout="wide")

require_authentication()
render_logout_button()

environment_manager = EnvironmentManager(st.session_state)
environments = environment_manager.initialise()
BackgroundJobRunner().maybe_run_backups(environments)
environment_manager.apply_selected_environment()

st.markdown(
    """
    <style>
        .home-hero {
            padding: 3.5rem 3rem;
            border-radius: 1.5rem;
            background: linear-gradient(135deg, #143266 0%, #1f6db0 60%, #32b5c5 100%);
            color: white;
            box-shadow: 0 18px 45px rgba(20, 50, 102, 0.35);
        }
        .home-hero h1 {
            font-size: 2.6rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 1.2rem;
        }
        .home-hero p {
            font-size: 1.1rem;
            margin-bottom: 0.6rem;
        }
        .home-tag {
            display: inline-block;
            background: rgba(255, 255, 255, 0.2);
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            font-size: 0.85rem;
            letter-spacing: 0.08em;
            font-weight: 600;
            text-transform: uppercase;
        }
        .home-card {
            border-radius: 1rem;
            padding: 1.25rem 1.5rem;
            background: rgba(255, 255, 255, 0.65);
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
            height: 100%;
        }
        .home-card h3 {
            margin-bottom: 0.75rem;
        }
        .home-steps {
            display: flex;
            gap: 1.5rem;
            flex-wrap: wrap;
        }
        .home-step {
            flex: 1 1 220px;
            border-radius: 0.85rem;
            padding: 1.2rem 1.4rem;
            background: rgba(15, 23, 42, 0.03);
            border: 1px solid rgba(15, 23, 42, 0.08);
        }
        .home-step strong {
            display: block;
            font-size: 1.05rem;
            margin-bottom: 0.3rem;
        }
        @media (max-width: 600px) {
            .home-hero {
                padding: 2.5rem 2rem;
            }
            .home-hero h1 {
                font-size: 2.1rem;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)

saved_environments = environment_manager.get_saved_environments()
secured_environment_count = sum(
    1 for env in saved_environments if bool(env.get("verify_ssl", True))
)
api_keys_available = sum(1 for env in saved_environments if env.get("api_key"))
active_sessions = get_active_session_count()

hero_col1, hero_col2 = st.columns([3, 2], gap="large")
with hero_col1:
    st.markdown(
        """
        <div class="home-hero">
            <span class="home-tag">Portainer control centre</span>
            <h1>Command your Docker and edge fleet with confidence.</h1>
            <p>Monitor, explore, and optimise every environment you have connected to Portainer.\
               The dashboard brings real-time visibility to your stacks, containers, and edge agents.</p>
            <p>Use the sidebar navigation to jump into focused dashboards or configure new environments\
               without leaving this page.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hero_col2:
    st.markdown(
        """
        <div class="home-card">
            <h3>Quick insight</h3>
            <p style="margin-bottom: 0.75rem;">Here's a snapshot of your configuration.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    metric_cols = st.columns(3, gap="medium")
    metric_cols[0].metric(
        "Environments",
        len(saved_environments),
        help="Configured Portainer environments",
    )
    metric_cols[1].metric(
        "Secured connections",
        secured_environment_count,
        help="Environments with SSL verification enabled",
    )
    metric_cols[2].metric(
        "Active sessions",
        active_sessions,
        help="Authenticated users currently connected to the dashboard",
    )
    st.metric(
        "API keys stored",
        api_keys_available,
        help="Number of environments with an API key configured",
    )

st.divider()

st.subheader("Get started in three simple steps")
steps = [
    ("🧭", "Select a Portainer environment", "Use the selector in the sidebar to switch between the environments you have configured."),
    ("⚙️", "Configure credentials", "Open the Settings page to add API keys, choose verification options, and store default environments."),
    ("📊", "Explore the dashboards", "Drill into fleet health, workloads, containers, and image utilisation using the pages on the left."),
]

st.markdown('<div class="home-steps">', unsafe_allow_html=True)
for icon, title, description in steps:
    st.markdown(
        f"<div class='home-step'><strong>{icon} {title}</strong><span>{description}</span></div>",
        unsafe_allow_html=True,
    )
st.markdown('</div>', unsafe_allow_html=True)

st.divider()

st.subheader("Where to next?")
page_links = [
    (
        "🛰️ Fleet overview",
        "pages/1_Fleet_Overview.py",
        "Analyse stack coverage, container load, and image usage at a glance.",
    ),
    (
        "🛠️ Workload explorer",
        "pages/4_Workload_Explorer.py",
        "Filter containers, stacks, and endpoints in real time.",
    ),
    (
        "🩺 Container health",
        "pages/3_Container_Health.py",
        "Spot issues quickly with health and status checks.",
    ),
    (
        "🧱 Image footprint",
        "pages/5_Image_Footprint.py",
        "Track image usage and storage across environments.",
    ),
    (
        "⚙️ Settings",
        "pages/6_Settings.py",
        "Manage API connections and environment credentials.",
    ),
]

page_link = getattr(st, "page_link", None)
if page_link is not None:
    for label, path, description in page_links:
        page_link(path, label=label, help=description)
else:
    for label, _, description in page_links:
        st.markdown(f"- **{label}** — {description}")

if saved_environments:
    st.divider()
    st.subheader("Configured environments")
    for environment in saved_environments:
        name = str(environment.get("name", "Unnamed environment"))
        api_url = environment.get("api_url") or "Not set"
        verify_ssl = "Enabled" if bool(environment.get("verify_ssl", True)) else "Disabled"
        st.markdown(
            textwrap.dedent(
                f"""
                **{name}**  \
                • API URL: `{api_url}`  \
                • SSL verification: {verify_ssl}
                """
            ).strip()
        )
else:
    st.info(
        "No saved Portainer environments detected. Configure an environment from the Settings page or provide credentials using environment variables.",
    )

