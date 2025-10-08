"""Helper utilities for the edge agent logs page."""
from __future__ import annotations

import pandas as pd


_AGENT_COLUMNS = ["endpoint_id", "endpoint_name", "agent_hostname"]


def build_agent_dataframe(
    container_data: pd.DataFrame, endpoint_data: pd.DataFrame
) -> pd.DataFrame:
    """Merge container and endpoint metadata into a de-duplicated frame."""

    frames: list[pd.DataFrame] = []

    if not container_data.empty:
        container_columns = [
            column for column in ("endpoint_id", "endpoint_name") if column in container_data.columns
        ]
        if container_columns:
            frames.append(container_data[container_columns].copy())

    if not endpoint_data.empty:
        endpoint_columns = [
            column for column in _AGENT_COLUMNS if column in endpoint_data.columns
        ]
        if endpoint_columns:
            frames.append(endpoint_data[endpoint_columns].copy())

    if not frames:
        return pd.DataFrame(columns=_AGENT_COLUMNS)

    merged = pd.concat(frames, ignore_index=True, sort=False)

    for column in _AGENT_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA

    merged = merged.dropna(subset=["endpoint_id"], how="any")

    merged["agent_hostname"] = merged["agent_hostname"].astype("string")
    merged["endpoint_name"] = merged["endpoint_name"].astype("string")

    merged = merged.assign(
        _has_hostname=lambda df: df["agent_hostname"].str.strip().fillna("").ne("")
    )

    sort_columns = ["endpoint_id", "_has_hostname", "agent_hostname", "endpoint_name"]
    sort_order = [True, False, True, True]
    merged = (
        merged.sort_values(by=sort_columns, ascending=sort_order, kind="stable")
        .drop_duplicates(subset=["endpoint_id"], keep="first")
        .reset_index(drop=True)
    )

    merged = merged.drop(columns="_has_hostname")

    return merged[_AGENT_COLUMNS]
