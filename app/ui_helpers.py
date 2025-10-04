"""Shared UI helpers for Streamlit pages."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from plotly.graph_objects import Figure
import streamlit as st


# Corporate colour palette derived from the Canton of Lucerne guidelines.
DEFAULT_COLOR_SEQUENCE: Sequence[str] = (
    "#009FE3",  # Hellblau – primary brand accent
    "#09202C",  # Mitternachtsblau – deep contrast tone
    "#94BED4",  # Puderblau – supporting tone
    "#DEF0FA",  # Hellblau light – neutral background tone
    "#999999",  # Warm grey – secondary text
    "#000000",  # Black – high contrast fallback
)


def apply_lucerne_theme() -> None:
    """Inject the Canton of Lucerne visual styling into the Streamlit app."""

    theme_key = "_lucerne_theme_applied"
    # Track the number of times the theme has been injected mainly for debugging
    # purposes, but always reapply the stylesheet. Streamlit rebuilds the page
    # with every navigation or rerun which clears previously injected CSS, so
    # skipping subsequent injections would cause the app to fall back to the
    # default styling on secondary pages.
    st.session_state[theme_key] = st.session_state.get(theme_key, 0) + 1
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;500;600;700&display=swap');

        :root {
            --lucerne-font-family: 'Source Sans 3', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            --lucerne-blue-primary: #009FE3;
            --lucerne-midnight: #09202C;
            --lucerne-powder: #94BED4;
            --lucerne-ice: #DEF0FA;
            --lucerne-grey: #8395A7;
            --lucerne-black: #000000;
            --lucerne-radius: 12px;
            --lucerne-shadow: 0 12px 32px rgba(9, 32, 44, 0.12);
            --lucerne-app-background: linear-gradient(180deg, rgba(222, 240, 250, 0.95) 0%, #f6fbff 45%);
            --lucerne-surface-background: rgba(255, 255, 255, 0.88);
            --lucerne-surface-border: rgba(0, 0, 0, 0.06);
            --lucerne-text-color: var(--lucerne-midnight);
            --lucerne-secondary-text: var(--lucerne-grey);
            --lucerne-sidebar-background: rgba(9, 32, 44, 0.95);
            --lucerne-sidebar-text: #ffffff;
            --lucerne-button-text: #ffffff;
            --lucerne-button-gradient-start: var(--lucerne-blue-primary);
            --lucerne-button-gradient-end: #34bdf4;
            --lucerne-table-header-bg: rgba(148, 190, 212, 0.45);
            --lucerne-table-row-alt: rgba(222, 240, 250, 0.65);
            --lucerne-table-row-hover: rgba(0, 159, 227, 0.12);
            --lucerne-alert-bg: rgba(222, 240, 250, 0.85);
            --lucerne-header-backdrop: rgba(255, 255, 255, 0.85);
            --lucerne-download-bg: rgba(9, 32, 44, 0.92);
        }

        body[data-theme="dark"] {
            --lucerne-app-background: radial-gradient(circle at 20% 20%, rgba(0, 159, 227, 0.12) 0%, rgba(7, 20, 29, 0.95) 55%, #030a11 100%);
            --lucerne-surface-background: rgba(9, 26, 38, 0.9);
            --lucerne-surface-border: rgba(255, 255, 255, 0.06);
            --lucerne-text-color: #e6f1f8;
            --lucerne-secondary-text: rgba(212, 224, 234, 0.75);
            --lucerne-sidebar-background: rgba(4, 18, 27, 0.95);
            --lucerne-sidebar-text: rgba(230, 241, 248, 0.95);
            --lucerne-button-text: #0b1d2a;
            --lucerne-button-gradient-start: #56c9f7;
            --lucerne-button-gradient-end: #009fe3;
            --lucerne-table-header-bg: rgba(0, 159, 227, 0.2);
            --lucerne-table-row-alt: rgba(7, 20, 29, 0.65);
            --lucerne-table-row-hover: rgba(86, 201, 247, 0.2);
            --lucerne-alert-bg: rgba(0, 159, 227, 0.18);
            --lucerne-header-backdrop: rgba(4, 18, 27, 0.85);
            --lucerne-download-bg: linear-gradient(135deg, #56c9f7, rgba(0, 159, 227, 0.9));
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            font-family: var(--lucerne-font-family);
            background: var(--lucerne-app-background);
            color: var(--lucerne-text-color);
            -webkit-font-smoothing: antialiased;
            text-rendering: optimizeLegibility;
        }

        .stApp header, [data-testid="stHeader"] {
            background: var(--lucerne-header-backdrop);
            backdrop-filter: blur(10px);
            border-bottom: 2px solid var(--lucerne-blue-primary);
        }

        .stApp [data-testid="stSidebar"] > div {
            background: var(--lucerne-sidebar-background);
            color: var(--lucerne-sidebar-text);
            backdrop-filter: blur(6px);
        }

        [data-testid="stSidebar"] a, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
            color: var(--lucerne-sidebar-text) !important;
        }

        [data-testid="stSidebar"] .stButton > button {
            background-color: rgba(148, 190, 212, 0.18);
            color: var(--lucerne-sidebar-text);
            border: 1px solid rgba(255, 255, 255, 0.25);
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background-color: rgba(0, 159, 227, 0.28);
        }

        .block-container {
            padding-top: 1.5rem;
        }

        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4,
        .stMarkdown h5, .stMarkdown h6, h1, h2, h3, h4, h5, h6 {
            color: var(--lucerne-text-color);
            letter-spacing: 0.015em;
            font-weight: 600;
        }

        .stButton > button {
            background: linear-gradient(135deg, var(--lucerne-button-gradient-start), var(--lucerne-button-gradient-end));
            color: var(--lucerne-button-text);
            border: none;
            border-radius: var(--lucerne-radius);
            padding: 0.65rem 1.75rem;
            font-weight: 600;
            box-shadow: var(--lucerne-shadow);
            transition: transform 0.18s ease, box-shadow 0.18s ease;
        }

        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 16px 40px rgba(0, 159, 227, 0.22);
        }

        .stTabs [data-baseweb="tab"] {
            color: var(--lucerne-secondary-text);
            font-weight: 600;
        }

        .stTabs [aria-selected="true"] {
            color: var(--lucerne-text-color) !important;
            border-bottom: 3px solid var(--lucerne-blue-primary);
        }

        .stMetric {
            background: var(--lucerne-surface-background);
            border-radius: var(--lucerne-radius);
            padding: 1.25rem;
            border: 1px solid var(--lucerne-surface-border);
            border-left: 6px solid var(--lucerne-blue-primary);
            box-shadow: var(--lucerne-shadow);
        }

        .stAlert {
            border-radius: var(--lucerne-radius);
            border-left: 6px solid var(--lucerne-blue-primary);
            background-color: var(--lucerne-alert-bg);
            color: var(--lucerne-text-color);
        }

        .stDataFrame, .stTable {
            border-radius: var(--lucerne-radius);
            overflow: hidden;
            box-shadow: var(--lucerne-shadow);
            background: var(--lucerne-surface-background);
            border: 1px solid var(--lucerne-surface-border);
        }

        .stDataFrame table {
            border-collapse: collapse;
        }

        .stDataFrame table thead tr {
            background: var(--lucerne-table-header-bg);
            color: var(--lucerne-text-color);
            font-weight: 600;
        }

        .stDataFrame table tbody tr:nth-child(even) {
            background-color: var(--lucerne-table-row-alt);
        }

        .stDataFrame table tbody tr:hover {
            background-color: var(--lucerne-table-row-hover);
        }

        .stDownloadButton > button {
            background: var(--lucerne-download-bg);
            color: #ffffff;
            border-radius: var(--lucerne-radius);
            border: none;
        }

        .stDownloadButton > button:hover {
            filter: brightness(1.05);
        }

        .stMarkdown a {
            color: var(--lucerne-blue-primary);
            font-weight: 600;
        }

        .stCaption, .stMarkdown small {
            color: var(--lucerne-secondary-text) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def style_plotly_figure(fig: Figure, *, show_legend: bool = True) -> Figure:
    """Apply a consistent visual style to Plotly figures."""

    fig.update_layout(
        template="plotly_white",
        colorway=list(DEFAULT_COLOR_SEQUENCE),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            title="" if show_legend else None,
        ),
        margin=dict(l=40, r=20, t=70, b=40),
        hoverlabel=dict(bgcolor="white", font=dict(color="#2f2f2f")),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(0, 0, 0, 0.08)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(0, 0, 0, 0.08)")
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

    apply_lucerne_theme()
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


def get_plotly_color_sequence() -> Sequence[str]:
    """Expose the default colour sequence for external callers."""

    return DEFAULT_COLOR_SEQUENCE


__all__ = [
    "DEFAULT_COLOR_SEQUENCE",
    "ExportableDataFrame",
    "get_plotly_color_sequence",
    "render_empty_state",
    "render_kpi_row",
    "render_page_header",
    "style_plotly_figure",
]
