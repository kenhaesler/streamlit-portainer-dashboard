import pandas as pd

from app.services.llm_context import (
    DataTable,
    LLMDataHub,
    QueryMetric,
    QueryRequest,
    parse_query_plan,
    serialise_records,
)


def test_serialise_records_handles_mixed_types() -> None:
    frame = pd.DataFrame(
        {
            "name": ["api", "worker"],
            "labels": [["a", "b"], {"key": "value"}],
            "state": ["running", "stopped"],
        }
    )
    records = serialise_records(frame)

    assert records[0]["labels"] == "['a', 'b']"
    assert records[1]["labels"] == "{'key': 'value'}"


def test_data_hub_filters_and_limits_rows() -> None:
    frame = pd.DataFrame(
        {
            "container_name": ["api", "worker", "db"],
            "status": ["healthy", "unhealthy", "unhealthy"],
            "environment_name": ["prod", "prod", "staging"],
        }
    )
    hub = LLMDataHub(
        [
            DataTable(
                name="containers",
                display_name="Containers",
                dataframe=frame,
                description="Containers",
                default_columns=("container_name", "status"),
            )
        ],
        max_rows_per_request=2,
    )

    request = QueryRequest(
        table="containers",
        columns=("container_name", "status"),
        filters={"status": {"in": ["unhealthy"]}},
    )
    result = hub.execute_requests([request])[0]

    assert result.type == "rows"
    assert list(result.dataframe["container_name"]) == ["worker", "db"]
    assert result.metadata["filtered_rows"] == 2
    assert result.metadata["returned_rows"] == 2


def test_data_hub_supports_grouped_metrics() -> None:
    frame = pd.DataFrame(
        {
            "environment_name": ["prod", "prod", "staging"],
            "cpu_percent": [70, 10, 55],
            "memory_percent": [40, 15, 60],
        }
    )
    hub = LLMDataHub(
        [
            DataTable(
                name="container_health",
                display_name="Container health",
                dataframe=frame,
                description="Health checks",
            )
        ]
    )

    request = QueryRequest(
        table="container_health",
        group_by=("environment_name",),
        metrics=(
            QueryMetric(name="count", operation="count"),
            QueryMetric(name="avg_cpu", operation="mean", column="cpu_percent"),
        ),
    )
    result = hub.execute_requests([request])[0]

    assert result.type == "aggregation"
    assert set(result.dataframe.columns) == {"environment_name", "count", "avg_cpu"}
    prod_row = result.dataframe[result.dataframe["environment_name"] == "prod"].iloc[0]
    assert prod_row["count"] == 2
    assert prod_row["avg_cpu"] == 40


def test_parse_query_plan_extracts_requests() -> None:
    plan_text = """
    The following plan should be executed:
    {
        "plan": "Check unhealthy containers and summarise by environment",
        "requests": [
            {
                "table": "containers",
                "filters": {"status": {"in": ["unhealthy"]}},
                "columns": ["container_name", "status"],
                "limit": 10
            },
            {
                "table": "container_health",
                "group_by": ["environment_name"],
                "metrics": [
                    {"name": "count", "operation": "count"},
                    {"name": "avg_cpu", "operation": "avg", "column": "cpu_percent"}
                ]
            }
        ]
    }
    """

    plan = parse_query_plan(plan_text)

    assert plan is not None
    assert plan.plan.startswith("Check unhealthy containers")
    assert len(plan.requests) == 2
    assert plan.requests[0].table == "containers"
    assert plan.requests[1].group_by == ("environment_name",)
    assert plan.requests[1].metrics[1].normalised_operation() == "mean"
