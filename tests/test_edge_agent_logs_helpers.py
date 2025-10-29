from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.edge_agent_logs import build_agent_dataframe


def test_build_agent_dataframe_prefers_hostname_entries():
    container_data = pd.DataFrame(
        {
            "endpoint_id": [101, 202],
            "endpoint_name": ["edge-alpha", "edge-gamma"],
        }
    )
    endpoint_data = pd.DataFrame(
        {
            "endpoint_id": [101, 202],
            "endpoint_name": ["edge-alpha", "edge-gamma"],
            "agent_hostname": ["alpha-host", ""],
        }
    )

    result = build_agent_dataframe(container_data, endpoint_data)

    assert list(result["endpoint_id"]) == [101, 202]
    assert result.loc[0, "agent_hostname"] == "alpha-host"
    assert result.loc[0, "endpoint_name"] == "edge-alpha"
    assert result.loc[1, "agent_hostname"] == ""
    assert result.loc[1, "endpoint_name"] == "edge-gamma"
