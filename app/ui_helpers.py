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
