"""Shared UI helpers for Streamlit pages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from plotly.graph_objects import Figure
import streamlit as st


THEME_SESSION_KEY = "_streamlit_portainer_global_theme_applied"

# A cohesive palette that matches the custom glassmorphic theme and works
# across categorical Plotly charts.
GLASSMORPHIC_COLOR_SEQUENCE: Sequence[str] = (
    "#7C5CFF",
    "#4ADEDE",
    "#38BDF8",
    "#F472B6",
    "#FACC15",
    "#A855F7",
    "#22D3EE",
    "#2DD4BF",
    "#94A3B8",
)


def apply_global_theme() -> None:
    """Inject global CSS overrides that complement the configured theme."""

    if st.session_state.get(THEME_SESSION_KEY):
        return

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600&family=Source+Code+Pro:wght@400;600&display=swap');
        :root {
            --app-primary: #7c5cff;
            --app-surface: rgba(15, 23, 42, 0.52);
            --app-surface-strong: rgba(15, 23, 42, 0.72);
            --app-border: rgba(148, 163, 184, 0.35);
            --app-shadow: 0 18px 45px rgba(12, 21, 38, 0.45);
            --app-blur: blur(18px);
            --app-text: #e2e8f0;
            --app-muted: #94a3b8;
        }
        html, body, [data-testid="stAppViewContainer"] {
            font-family: 'Poppins', 'Inter', sans-serif;
            color: var(--app-text);
            background: radial-gradient(circle at top left, rgba(124, 92, 255, 0.22), rgba(15, 23, 42, 0.85) 55%), #0f172a;
        }
        div[data-testid="stAppViewContainer"] > div:first-child {
            padding-bottom: 2rem;
        }
        section.main {
            background: transparent;
        }
        section.main > div {
            background: var(--app-surface);
            border-radius: 18px;
            border: 1px solid var(--app-border);
            box-shadow: var(--app-shadow);
            backdrop-filter: var(--app-blur);
            -webkit-backdrop-filter: var(--app-blur);
            padding: 2rem 2.25rem;
            margin: 1.5rem auto;
        }
        section[data-testid="stSidebar"] > div {
            background: var(--app-surface-strong);
            border-right: 1px solid var(--app-border);
            backdrop-filter: var(--app-blur);
            -webkit-backdrop-filter: var(--app-blur);
        }
        section[data-testid="stSidebar"] .sidebar-content {
            padding: 1.5rem 1rem;
        }
        h1, h2, h3, h4 {
            color: var(--app-text);
            letter-spacing: 0.02em;
        }
        p, span, label, .stMarkdown, .stMarkdown p {
            color: var(--app-muted);
        }
        div[data-testid="stMetricValue"] {
            color: var(--app-text);
        }
        div[data-testid="metric-container"] {
            background: rgba(15, 23, 42, 0.55);
            border-radius: 16px;
            border: 1px solid var(--app-border);
            padding: 1rem;
        }
        .stButton button, .stDownloadButton button, .stFormSubmitButton button {
            background: linear-gradient(135deg, rgba(124, 92, 255, 0.9), rgba(76, 150, 255, 0.9));
            border: none;
            color: white;
            border-radius: 999px;
            padding: 0.6rem 1.6rem;
            box-shadow: 0 10px 25px rgba(124, 92, 255, 0.35);
            transition: all 0.25s ease-in-out;
        }
        .stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {
            background: linear-gradient(135deg, rgba(124, 92, 255, 1), rgba(56, 189, 248, 0.95));
            box-shadow: 0 14px 30px rgba(56, 189, 248, 0.35);
        }
        .stDataFrame, .stTable {
            background: rgba(15, 23, 42, 0.4);
            border-radius: 16px;
            border: 1px solid var(--app-border);
            overflow: hidden;
        }
        .stDataFrame table {
            color: var(--app-text);
        }
        .stTabs [data-baseweb="tab-list"] {
            background-color: rgba(15, 23, 42, 0.35);
            border-radius: 999px;
            padding: 0.4rem;
            border: 1px solid rgba(124, 92, 255, 0.35);
        }
        .stTabs [data-baseweb="tab"] {
            color: var(--app-muted);
        }
        .stTabs [aria-selected="true"] {
            background-color: rgba(124, 92, 255, 0.25);
            color: var(--app-text);
        }
        .stAlert {
            background: rgba(15, 23, 42, 0.55);
            border-radius: 16px;
            border-left: 4px solid var(--app-primary);
            color: var(--app-text);
        }
        .stMarkdown code, code {
            font-family: 'Source Code Pro', monospace;
            background: rgba(148, 163, 184, 0.15);
            color: var(--app-text);
            border-radius: 6px;
            padding: 0.2rem 0.45rem;
        }
        footer, header[data-testid="stHeader"] {
            background: transparent;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state[THEME_SESSION_KEY] = True


def style_plotly_figure(fig: Figure, *, show_legend: bool = True) -> Figure:
    """Apply a consistent visual style to Plotly figures."""

    fig.update_layout(
        template="plotly_dark",
        colorway=list(GLASSMORPHIC_COLOR_SEQUENCE),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            title="" if show_legend else None,
            bgcolor="rgba(15, 23, 42, 0.6)",
            bordercolor="rgba(148, 163, 184, 0.3)",
            borderwidth=1,
        ),
        margin=dict(l=40, r=20, t=70, b=40),
        hoverlabel=dict(
            bgcolor="rgba(15, 23, 42, 0.85)",
            font=dict(color="#F8FAFC", family="Poppins, 'Inter', sans-serif"),
        ),
        paper_bgcolor="rgba(15, 23, 42, 0)",
        plot_bgcolor="rgba(15, 23, 42, 0.45)",
        font=dict(family="Poppins, 'Inter', sans-serif", color="#E2E8F0"),
        title_font=dict(family="Poppins, 'Inter', sans-serif", color="#F8FAFC"),
    )
    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(148, 163, 184, 0.2)",
        zerolinecolor="rgba(148, 163, 184, 0.25)",
        linecolor="rgba(148, 163, 184, 0.4)",
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(148, 163, 184, 0.2)",
        zerolinecolor="rgba(148, 163, 184, 0.25)",
        linecolor="rgba(148, 163, 184, 0.4)",
    )
    if not show_legend:
        fig.update_layout(showlegend=False)
    return fig


def render_page_header(
    title: str,
    *,
    description: str | None = None,
    icon: str | None = None,
) -> None:
    """Render a consistent page heading with an optional description."""

    icon_prefix = f"{icon} " if icon else ""
    st.title(f"{icon_prefix}{title}")
    if description:
        st.caption(description)


def render_kpi_row(metrics: Iterable[tuple[str, int | float, str | None]]) -> None:
    """Display a row of metric cards with optional help text."""

    metrics = list(metrics)
    if not metrics:
        return
    columns = st.columns(len(metrics))
    for column, (label, value, help_text) in zip(columns, metrics):
        with column:
            st.metric(label, value)
            if help_text:
                st.caption(help_text)


def render_empty_state(message: str, *, icon: str = "ℹ️") -> bool:
    """Render an informational empty state and return ``True`` when shown."""

    st.info(message, icon=icon)
    return True


@dataclass
class ExportableDataFrame:
    """Helper holding dataframe metadata for download buttons."""

    label: str
    data: "pd.DataFrame"
    filename: str

    def render_download_button(self) -> None:
        """Render a download button for the wrapped dataframe."""

        import pandas as pd  # Local import to avoid circular dependency

        if self.data.empty:
            return
        csv_bytes = self.data.to_csv(index=False).encode("utf-8")
        st.download_button(
            self.label,
            data=csv_bytes,
            file_name=self.filename,
            mime="text/csv",
            width="stretch",
        )
