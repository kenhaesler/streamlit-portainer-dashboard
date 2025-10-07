from __future__ import annotations

import json

import pandas as pd

from app.services.llm_context import (
    build_context_summary,
    enforce_context_budget,
    estimate_token_count,
    serialise_records,
)


def test_estimate_token_count_uses_conservative_rounding() -> None:
    assert estimate_token_count("") == 0
    assert estimate_token_count("abcd") == 1
    assert estimate_token_count("abcde") == 2


def test_build_context_summary_returns_hotspot_information() -> None:
    containers = pd.DataFrame(
        {
            "state": ["running", "stopped", "running"],
            "status": ["healthy", "unhealthy", "healthy"],
            "environment_name": ["prod", "prod", "staging"],
        }
    )
    container_details = pd.DataFrame(
        {
            "environment_name": ["prod", "prod", "staging"],
            "endpoint_name": ["east", "west", "central"],
            "container_name": ["api", "worker", "db"],
            "cpu_percent": ["75%", "10%", "55%"],
            "memory_percent": ["40%", "5%", "60%"],
        }
    )
    stacks = pd.DataFrame({"stack_status": ["active", "deploying"]})
    hosts = pd.DataFrame({"total_cpus": [4, 8], "total_memory": [8_000_000_000, 16_000_000_000]})

    summary = build_context_summary(containers, container_details, stacks, hosts)

    assert summary["containers"]["total"] == 3
    assert summary["containers"]["unhealthy"] == 1
    assert "running" in summary["containers"]["by_state"]
    assert summary["stacks"]["total"] == 2
    assert summary["hosts"]["cpus"] == 12.0
    assert summary["hosts"]["memory_bytes"] == 24_000_000_000.0
    assert summary["top_cpu"][0]["container_name"] == "api"
    assert summary["top_memory"][0]["container_name"] == "db"


def test_enforce_context_budget_trims_low_priority_sections() -> None:
    containers = pd.DataFrame(
        {"container_name": [f"c{i}" for i in range(20)], "state": ["running"] * 20}
    )
    container_health = pd.DataFrame(
        {
            "container_name": [f"c{i}" for i in range(20)],
            "health_status": ["healthy"] * 20,
        }
    )
    volumes = pd.DataFrame({"volume_name": [f"v{i}" for i in range(5)]})

    frames = {
        "containers": containers,
        "container_health": container_health,
        "volumes": volumes,
    }

    payload = {key: serialise_records(df) for key, df in frames.items()}
    baseline_tokens = estimate_token_count(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )

    trimmed_payload, trimmed_frames, notices, final_tokens = enforce_context_budget(
        payload, frames, max_tokens=1
    )

    assert final_tokens <= baseline_tokens
    if "container_health" in trimmed_frames:
        assert len(trimmed_frames["container_health"]) < len(container_health)
    assert "volumes" not in trimmed_payload
    assert notices  # user is informed about the adjustments
    # Original frames remain untouched
    assert len(containers) == 20
    assert len(container_health) == 20
