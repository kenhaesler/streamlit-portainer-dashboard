"""Helpers for shaping Portainer context payloads sent to the LLM."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping

import pandas as pd

__all__ = [
    "build_context_summary",
    "enforce_context_budget",
    "estimate_token_count",
    "serialise_records",
]


def serialise_records(df: pd.DataFrame) -> list[dict[str, object]]:
    """Return JSON-serialisable records from *df*.

    Streamlit dataframes often include rich objects (e.g. lists, timestamps) that the
    JSON encoder cannot handle out-of-the-box. This helper coerces unsupported values
    to strings while preserving scalars and ``None``/empty strings so that prompts
    remain faithful to the original data.
    """

    if df.empty:
        return []
    serialised: list[dict[str, object]] = []
    for record in df.to_dict(orient="records"):
        cleaned: dict[str, object] = {}
        for key, value in record.items():
            if value in ("", None):
                cleaned[key] = value
            elif isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        serialised.append(cleaned)
    return serialised


def estimate_token_count(text: str) -> int:
    """Return a rough token estimate for *text*.

    We approximate the token count using the common heuristic of four characters per
    token. This keeps the calculation fast while remaining conservative enough to
    detect payloads that are likely to breach the model's context window.
    """

    if not text:
        return 0
    # ``math.ceil`` avoids underestimating payload size.
    return math.ceil(len(text) / 4)


def _to_numeric_percentage(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    cleaned = series.astype(str).str.rstrip("%")
    return pd.to_numeric(cleaned, errors="coerce")


def build_context_summary(
    containers: pd.DataFrame,
    container_details: pd.DataFrame,
    stacks: pd.DataFrame,
    hosts: pd.DataFrame,
    *,
    top_n: int = 5,
) -> dict[str, object]:
    """Create a compact summary of key Portainer metrics.

    The summary provides high-level counts and hotspot indicators so the LLM can
    orient itself quickly even when detailed tables need to be trimmed.
    """

    summary: dict[str, object] = {}

    if not containers.empty:
        state_counts = (
            containers.get("state", pd.Series(dtype=str))
            .astype(str)
            .str.lower()
            .value_counts(dropna=True)
            .to_dict()
        )
        status_series = containers.get("status", pd.Series(dtype=str)).astype(str)
        unhealthy_count = int(
            status_series.str.contains("unhealthy", case=False, na=False).sum()
        )
        summary["containers"] = {
            "total": int(len(containers)),
            "by_state": {key: int(value) for key, value in state_counts.items()},
            "unhealthy": unhealthy_count,
            "environments": sorted(
                {
                    str(value)
                    for value in containers.get("environment_name", pd.Series(dtype=str))
                    .dropna()
                    .unique()
                }
            ),
        }

    if not stacks.empty:
        summary["stacks"] = {
            "total": int(len(stacks)),
            "statuses": {
                key: int(value)
                for key, value in stacks.get("stack_status", pd.Series(dtype=str))
                .astype(str)
                .str.lower()
                .value_counts(dropna=True)
                .head(5)
                .items()
            },
        }

    if not hosts.empty:
        summary["hosts"] = {
            "total": int(len(hosts)),
            "cpus": float(hosts.get("total_cpus", pd.Series(dtype=float)).fillna(0).sum()),
            "memory_bytes": float(
                hosts.get("total_memory", pd.Series(dtype=float)).fillna(0).sum()
            ),
        }

    if not container_details.empty:
        cpu_series = _to_numeric_percentage(container_details.get("cpu_percent"))
        mem_series = _to_numeric_percentage(container_details.get("memory_percent"))
        details_with_metrics = container_details.assign(
            cpu_percent=cpu_series,
            memory_percent=mem_series,
        )

        top_cpu = (
            details_with_metrics.dropna(subset=["cpu_percent"])
            .sort_values("cpu_percent", ascending=False)
            .head(top_n)
        )
        if not top_cpu.empty:
            summary["top_cpu"] = [
                {
                    "environment_name": row.get("environment_name", ""),
                    "endpoint_name": row.get("endpoint_name", ""),
                    "container_name": row.get("container_name", ""),
                    "cpu_percent": round(float(row.get("cpu_percent", 0.0)), 2),
                }
                for row in top_cpu.to_dict(orient="records")
            ]

        top_memory = (
            details_with_metrics.dropna(subset=["memory_percent"])
            .sort_values("memory_percent", ascending=False)
            .head(top_n)
        )
        if not top_memory.empty:
            summary["top_memory"] = [
                {
                    "environment_name": row.get("environment_name", ""),
                    "endpoint_name": row.get("endpoint_name", ""),
                    "container_name": row.get("container_name", ""),
                    "memory_percent": round(float(row.get("memory_percent", 0.0)), 2),
                }
                for row in top_memory.to_dict(orient="records")
            ]

    return summary


def _estimate_payload_tokens(payload: Mapping[str, object]) -> int:
    compact_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return estimate_token_count(compact_json)


def enforce_context_budget(
    payload: dict[str, object],
    frames: dict[str, pd.DataFrame],
    max_tokens: int,
) -> tuple[dict[str, object], dict[str, pd.DataFrame], list[str], int]:
    """Ensure *payload* stays within *max_tokens* by trimming lower-priority tables.

    The function returns a ``(payload, frames, notices, token_count)`` tuple where
    ``payload`` mirrors the final JSON sent to the LLM, ``frames`` exposes the
    truncated DataFrames for UI rendering, and ``notices`` summarises any
    adjustments applied.
    """

    payload_copy: dict[str, object] = dict(payload)
    frames_copy: dict[str, pd.DataFrame] = {
        key: df.copy() for key, df in frames.items()
    }
    if max_tokens <= 0:
        token_count = _estimate_payload_tokens(payload_copy)
        return payload_copy, frames_copy, [], token_count

    notices: list[str] = []
    token_count = _estimate_payload_tokens(payload_copy)

    def _update_section(key: str, df: pd.DataFrame) -> None:
        frames_copy[key] = df
        payload_copy[key] = serialise_records(df)

    while token_count > max_tokens:
        adjusted = False

        for key, minimum, message_template in (
            (
                "container_health",
                5,
                "Trimmed container health metrics to the first %s rows to respect the context budget.",
            ),
            (
                "containers",
                5,
                "Trimmed container inventory to the first %s rows to respect the context budget.",
            ),
        ):
            df = frames_copy.get(key)
            if df is not None and len(df) > minimum:
                new_length = max(minimum, len(df) // 2)
                truncated = df.head(new_length)
                _update_section(key, truncated)
                token_count = _estimate_payload_tokens(payload_copy)
                notices.append(message_template % new_length)
                adjusted = True
                break
        if adjusted:
            continue

        for key, message in (
            ("images", "Omitted image inventory to satisfy the context budget."),
            ("volumes", "Omitted volume inventory to satisfy the context budget."),
            ("hosts", "Omitted host capacity details to satisfy the context budget."),
            ("stacks", "Omitted stack inventory to satisfy the context budget."),
            ("endpoints", "Omitted endpoint metadata to satisfy the context budget."),
            ("warnings", "Omitted Portainer warnings to satisfy the context budget."),
        ):
            if key in payload_copy:
                payload_copy.pop(key, None)
                frames_copy.pop(key, None)
                token_count = _estimate_payload_tokens(payload_copy)
                notices.append(message)
                adjusted = True
                break
        if adjusted:
            continue

        df = frames_copy.get("containers")
        if df is not None and len(df) > 5:
            truncated = df.head(5)
            _update_section("containers", truncated)
            token_count = _estimate_payload_tokens(payload_copy)
            notices.append(
                "Reduced container inventory to the first 5 rows due to persistent context pressure."
            )
            continue

        if "container_health" in payload_copy:
            payload_copy.pop("container_health", None)
            frames_copy.pop("container_health", None)
            token_count = _estimate_payload_tokens(payload_copy)
            notices.append(
                "Removed detailed container health metrics due to persistent context pressure."
            )
            continue

        # No further reductions possible – break to avoid an infinite loop.
        break

    return payload_copy, frames_copy, notices, token_count
