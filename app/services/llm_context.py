from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

__all__ = [
    "DataTable",
    "LLMDataHub",
    "QueryMetric",
    "QueryPlan",
    "QueryRequest",
    "QueryResult",
    "parse_query_plan",
    "serialise_records",
]


def serialise_records(df: pd.DataFrame) -> list[dict[str, object]]:
    """Return JSON-serialisable records from *df*.

    Objects unsupported by the JSON encoder are coerced to strings so large Portainer
    tables can be safely shared with the LLM without exploding the payload.
    """

    if df.empty:
        return []

    records: list[dict[str, object]] = []
    for row in df.to_dict(orient="records"):
        cleaned: dict[str, object] = {}
        for key, value in row.items():
            if value in (None, ""):
                cleaned[key] = value
            elif isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        records.append(cleaned)
    return records


@dataclass(slots=True, frozen=True)
class QueryMetric:
    """Aggregation instruction included in a :class:`QueryRequest`."""

    name: str
    operation: str
    column: str | None = None

    def normalised_operation(self) -> str:
        op = self.operation.strip().lower()
        if op == "avg":
            return "mean"
        return op


@dataclass(slots=True, frozen=True)
class QueryRequest:
    """Structured request for a dataframe slice or aggregation."""

    table: str
    columns: tuple[str, ...] | None = None
    filters: Mapping[str, Any] | None = None
    limit: int | None = None
    order_by: tuple[tuple[str, str], ...] = ()
    group_by: tuple[str, ...] = ()
    metrics: tuple[QueryMetric, ...] = ()
    description: str | None = None


@dataclass(slots=True, frozen=True)
class QueryPlan:
    """Query plan returned by the LLM before data retrieval."""

    plan: str
    requests: tuple[QueryRequest, ...]
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class QueryResult:
    """Result of executing a :class:`QueryRequest`."""

    table: str
    label: str
    type: str
    dataframe: pd.DataFrame
    metadata: Mapping[str, Any] = field(default_factory=dict)
    description: str | None = None
    metrics: tuple[QueryMetric, ...] = ()

    def to_prompt_payload(self) -> Mapping[str, Any]:
        return {
            "table": self.table,
            "label": self.label,
            "type": self.type,
            "metadata": dict(self.metadata),
            "records": serialise_records(self.dataframe),
            "description": self.description,
        }


@dataclass(slots=True, frozen=True)
class DataTable:
    """Represents a dataframe exposed to the assistant."""

    name: str
    display_name: str
    dataframe: pd.DataFrame
    description: str
    default_columns: tuple[str, ...] | None = None
    searchable_columns: tuple[str, ...] = ()

    def row_count(self) -> int:
        return int(len(self.dataframe))

    def column_names(self) -> list[str]:
        return [str(column) for column in self.dataframe.columns]


class LLMDataHub:
    """Registry exposing Portainer tables to the LLM via structured queries."""

    def __init__(
        self,
        tables: Sequence[DataTable],
        *,
        max_rows_per_request: int = 500,
    ) -> None:
        self._tables: dict[str, DataTable] = {table.name: table for table in tables}
        self.max_rows_per_request = max(max_rows_per_request, 1)

    def describe_for_llm(self) -> Mapping[str, Any]:
        """Return catalog metadata used in the research prompt."""

        catalog: dict[str, Any] = {}
        for table in self._tables.values():
            catalog[table.name] = {
                "display_name": table.display_name,
                "rows": table.row_count(),
                "columns": table.column_names(),
                "description": table.description,
                "searchable_columns": list(table.searchable_columns),
                "default_columns": list(table.default_columns or []),
            }
        return catalog

    def _table(self, name: str) -> DataTable | None:
        return self._tables.get(name)

    def iter_tables(self) -> Sequence[DataTable]:
        return tuple(self._tables.values())

    def get_table(self, name: str) -> DataTable | None:
        return self._table(name)

    def build_overview(self) -> Mapping[str, Any]:
        """Compute high level insights for UI and prompts."""

        overview: dict[str, Any] = {
            "tables": {name: table.row_count() for name, table in self._tables.items()},
            "issues": {},
        }
        containers = self._table("containers")
        container_health = self._table("container_health")
        stacks = self._table("stacks")
        hosts = self._table("hosts")

        if containers:
            df = containers.dataframe
            overview["containers"] = {
                "total": int(len(df)),
                "states": (
                    df.get("state", pd.Series(dtype=str))
                    .astype(str)
                    .str.lower()
                    .value_counts(dropna=True)
                    .to_dict()
                ),
            }
            unhealthy = (
                df.get("status", pd.Series(dtype=str))
                .astype(str)
                .str.contains("unhealthy", case=False, na=False)
                .sum()
            )
            restarting = (
                df.get("state", pd.Series(dtype=str))
                .astype(str)
                .str.contains("restarting", case=False, na=False)
                .sum()
            )
            overview["issues"]["unhealthy_containers"] = int(unhealthy)
            overview["issues"]["restarting_containers"] = int(restarting)
            overview["issues"]["environments"] = int(
                df.get("environment_name", pd.Series(dtype=str))
                .dropna()
                .nunique()
            )
        if container_health:
            details = container_health.dataframe
            cpu = (
                pd.to_numeric(
                    details.get("cpu_percent", pd.Series(dtype=float))
                    .astype(str)
                    .str.rstrip("%"),
                    errors="coerce",
                )
                .fillna(0)
            )
            mem = (
                pd.to_numeric(
                    details.get("memory_percent", pd.Series(dtype=float))
                    .astype(str)
                    .str.rstrip("%"),
                    errors="coerce",
                )
                .fillna(0)
            )
            if not cpu.empty:
                overview["hotspots_cpu"] = (
                    details.assign(cpu_percent=cpu)
                    .sort_values("cpu_percent", ascending=False)
                    .head(5)
                )
            if not mem.empty:
                overview["hotspots_memory"] = (
                    details.assign(memory_percent=mem)
                    .sort_values("memory_percent", ascending=False)
                    .head(5)
                )
        if stacks:
            overview["stacks"] = {
                "total": int(len(stacks.dataframe)),
                "status_counts": (
                    stacks.dataframe.get("stack_status", pd.Series(dtype=str))
                    .astype(str)
                    .str.lower()
                    .value_counts(dropna=True)
                    .head(10)
                    .to_dict()
                ),
            }
        if hosts:
            total_cpu = (
                hosts.dataframe.get("total_cpus", pd.Series(dtype=float)).fillna(0).sum()
            )
            total_memory = (
                hosts.dataframe.get("total_memory", pd.Series(dtype=float)).fillna(0).sum()
            )
            overview["hosts"] = {
                "total": int(len(hosts.dataframe)),
                "total_cpus": float(total_cpu),
                "total_memory": float(total_memory),
            }
        return overview

    def execute_requests(self, requests: Sequence[QueryRequest]) -> list[QueryResult]:
        results: list[QueryResult] = []
        for request in requests:
            table = self._table(request.table)
            if not table:
                continue
            df = table.dataframe
            filtered = self._apply_filters(df, request.filters)
            filtered_count = int(len(filtered))
            if request.group_by:
                ordered = self._apply_order(filtered, request.order_by)
                aggregated = self._aggregate(
                    ordered,
                    request.group_by,
                    request.metrics,
                )
                result_df = self._apply_limit(aggregated, request.limit)
                result_type = "aggregation"
            else:
                ordered = self._apply_order(filtered, request.order_by)
                limited = self._apply_limit(ordered, request.limit)
                result_df = self._select_columns(limited, request.columns, table.default_columns)
                result_type = "rows"
            result_df = result_df.fillna("")
            results.append(
                QueryResult(
                    table=request.table,
                    label=table.display_name,
                    type=result_type,
                    dataframe=result_df,
                    metadata={
                        "total_rows": table.row_count(),
                        "filtered_rows": filtered_count,
                        "returned_rows": int(len(result_df)),
                        "limit": self._normalise_limit(request.limit),
                        "order_by": [list(order) for order in request.order_by],
                        "group_by": list(request.group_by),
                    },
                    description=request.description,
                    metrics=request.metrics,
                )
            )
        return results

    def serialise_results(self, results: Sequence[QueryResult]) -> Mapping[str, Any]:
        return {
            "results": [result.to_prompt_payload() for result in results],
        }

    # Internal helpers -------------------------------------------------

    def _normalise_limit(self, limit: int | None) -> int:
        if limit is None or limit <= 0:
            return self.max_rows_per_request
        return min(limit, self.max_rows_per_request)

    def _apply_limit(self, df: pd.DataFrame, limit: int | None) -> pd.DataFrame:
        final_limit = self._normalise_limit(limit)
        return df.head(final_limit)

    def _apply_order(
        self, df: pd.DataFrame, order_by: Sequence[tuple[str, str]]
    ) -> pd.DataFrame:
        if not order_by:
            return df
        columns: list[str] = []
        ascending: list[bool] = []
        for column, direction in order_by:
            if column not in df.columns:
                continue
            columns.append(column)
            ascending.append(direction.lower() != "desc")
        if not columns:
            return df
        return df.sort_values(by=columns, ascending=ascending)

    def _select_columns(
        self,
        df: pd.DataFrame,
        requested: Sequence[str] | None,
        default_columns: Sequence[str] | None,
    ) -> pd.DataFrame:
        columns = list(requested or default_columns or df.columns)
        valid_columns = [column for column in columns if column in df.columns]
        if not valid_columns:
            return df
        return df.loc[:, valid_columns]

    def _aggregate(
        self,
        df: pd.DataFrame,
        group_by: Sequence[str],
        metrics: Sequence[QueryMetric],
    ) -> pd.DataFrame:
        if not group_by:
            return df
        available_group = [column for column in group_by if column in df.columns]
        if not available_group:
            return df
        grouped = df.groupby(available_group, dropna=False, sort=False)
        series_to_concat: list[pd.Series] = []
        for metric in metrics:
            operation = metric.normalised_operation()
            if operation == "count":
                series = grouped.size().rename(metric.name or "count")
                series_to_concat.append(series)
            else:
                column = metric.column
                if not column or column not in df.columns:
                    continue
                try:
                    series = grouped[column].agg(operation).rename(metric.name)
                except (TypeError, ValueError):
                    continue
                series_to_concat.append(series)
        if not series_to_concat:
            series_to_concat.append(grouped.size().rename("count"))
        aggregated = pd.concat(series_to_concat, axis=1).reset_index()
        return aggregated

    def _apply_filters(
        self,
        df: pd.DataFrame,
        filters: Mapping[str, Any] | None,
    ) -> pd.DataFrame:
        if not filters:
            return df
        filtered = df
        for column, raw_criteria in filters.items():
            if column not in filtered.columns:
                continue
            filtered = self._apply_single_filter(filtered, column, raw_criteria)
            if filtered.empty:
                break
        return filtered

    def _apply_single_filter(
        self,
        df: pd.DataFrame,
        column: str,
        criteria: Any,
    ) -> pd.DataFrame:
        if isinstance(criteria, Mapping):
            return self._apply_mapping_filter(df, column, criteria)
        if isinstance(criteria, Sequence) and not isinstance(criteria, (str, bytes)):
            values = [str(value).strip() for value in criteria if str(value).strip()]
            if not values:
                return df
            return df[df[column].astype(str).isin(values)]
        value = str(criteria).strip()
        if not value:
            return df
        return df[df[column].astype(str) == value]

    def _apply_mapping_filter(
        self,
        df: pd.DataFrame,
        column: str,
        criteria: Mapping[str, Any],
    ) -> pd.DataFrame:
        series = df[column]
        mask = pd.Series(True, index=series.index)
        for key, value in criteria.items():
            key_normalised = str(key).lower()
            if key_normalised in {"equals", "eq"}:
                mask &= series.astype(str) == str(value)
            elif key_normalised in {"in", "one_of"} and isinstance(value, Sequence):
                choices = [str(item).strip() for item in value if str(item).strip()]
                if choices:
                    mask &= series.astype(str).isin(choices)
            elif key_normalised in {"not_in", "not"} and isinstance(value, Sequence):
                choices = [str(item).strip() for item in value if str(item).strip()]
                if choices:
                    mask &= ~series.astype(str).isin(choices)
            elif key_normalised in {"contains", "substring"}:
                mask &= series.astype(str).str.contains(str(value), case=False, na=False)
            elif key_normalised in {"gt", "gte", "lt", "lte"}:
                numeric = pd.to_numeric(series, errors="coerce")
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                if key_normalised == "gt":
                    mask &= numeric > numeric_value
                elif key_normalised == "gte":
                    mask &= numeric >= numeric_value
                elif key_normalised == "lt":
                    mask &= numeric < numeric_value
                elif key_normalised == "lte":
                    mask &= numeric <= numeric_value
        return df[mask]


def _extract_first_json_object(text: str) -> Mapping[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, Mapping):
        return parsed
    return None


def parse_query_plan(raw_text: str) -> QueryPlan | None:
    """Parse a JSON query plan returned by the LLM."""

    payload = _extract_first_json_object(raw_text)
    if not payload:
        return None

    plan_text = str(payload.get("plan") or payload.get("summary") or "").strip()
    notes = tuple(
        str(note).strip()
        for note in payload.get("notes", [])
        if isinstance(note, str) and note.strip()
    )
    warnings: list[str] = []
    requests_payload = payload.get("requests") or payload.get("queries")
    if not isinstance(requests_payload, Sequence):
        return QueryPlan(plan=plan_text, requests=(), notes=notes, warnings=tuple(warnings))

    requests: list[QueryRequest] = []
    for raw_request in requests_payload:
        if not isinstance(raw_request, Mapping):
            continue
        table_raw = raw_request.get("table") or raw_request.get("name")
        if not isinstance(table_raw, str) or not table_raw.strip():
            warnings.append("Skipped plan entry without a table name.")
            continue
        table = table_raw.strip()
        columns_payload = raw_request.get("columns")
        columns: tuple[str, ...] | None = None
        if isinstance(columns_payload, Sequence) and not isinstance(columns_payload, (str, bytes)):
            column_values = [
                str(column).strip() for column in columns_payload if str(column).strip()
            ]
            columns = tuple(column_values) if column_values else None
        filters_payload = raw_request.get("filters")
        if isinstance(filters_payload, Mapping):
            filters = dict(filters_payload)
        else:
            filters = None
        limit_raw = raw_request.get("limit")
        limit: int | None = None
        if isinstance(limit_raw, (int, float)):
            limit_candidate = int(limit_raw)
            if limit_candidate > 0:
                limit = limit_candidate
        order_payload = raw_request.get("order_by") or raw_request.get("sort")
        order_by: list[tuple[str, str]] = []
        if isinstance(order_payload, Mapping):
            column = order_payload.get("column")
            direction = order_payload.get("direction", "asc")
            if isinstance(column, str):
                order_by.append((column.strip(), str(direction)))
        elif isinstance(order_payload, Sequence):
            for entry in order_payload:
                if not isinstance(entry, Mapping):
                    continue
                column = entry.get("column")
                if not isinstance(column, str) or not column.strip():
                    continue
                direction = entry.get("direction", "asc")
                order_by.append((column.strip(), str(direction)))
        group_payload = raw_request.get("group_by") or raw_request.get("groups")
        group_by: tuple[str, ...] = ()
        if isinstance(group_payload, Sequence) and not isinstance(group_payload, (str, bytes)):
            group_values = [
                str(column).strip() for column in group_payload if str(column).strip()
            ]
            group_by = tuple(group_values)
        metrics_payload = raw_request.get("metrics") or raw_request.get("aggregations")
        metrics: list[QueryMetric] = []
        if isinstance(metrics_payload, Sequence):
            for entry in metrics_payload:
                if not isinstance(entry, Mapping):
                    continue
                name = str(entry.get("name") or entry.get("label") or "").strip() or "metric"
                operation_raw = entry.get("operation") or entry.get("agg") or entry.get("type")
                if not isinstance(operation_raw, str):
                    continue
                operation = operation_raw.strip()
                column_raw = entry.get("column") or entry.get("field")
                column = str(column_raw).strip() if isinstance(column_raw, str) else None
                metrics.append(QueryMetric(name=name, operation=operation, column=column))
        description = raw_request.get("reason") or raw_request.get("why")
        if isinstance(description, str):
            description = description.strip() or None
        requests.append(
            QueryRequest(
                table=table,
                columns=columns,
                filters=filters,
                limit=limit,
                order_by=tuple(order_by),
                group_by=group_by,
                metrics=tuple(metrics),
                description=description,
            )
        )
    return QueryPlan(
        plan=plan_text,
        requests=tuple(requests),
        notes=notes,
        warnings=tuple(warnings),
    )
