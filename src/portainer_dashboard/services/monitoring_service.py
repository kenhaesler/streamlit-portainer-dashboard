"""AI-powered infrastructure monitoring service."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from portainer_dashboard.config import get_settings
from portainer_dashboard.models.monitoring import (
    InfrastructureSnapshot,
    InsightSeverity,
    MonitoringInsight,
    MonitoringReport,
)
from portainer_dashboard.services.data_collector import (
    DataCollector,
    create_data_collector,
)
from portainer_dashboard.services.insights_store import InsightsStore, get_insights_store
from portainer_dashboard.services.llm_client import (
    AsyncLLMClient,
    LLMClientError,
    create_llm_client,
)
from portainer_dashboard.services.log_sanitizer import sanitize_logs
from portainer_dashboard.services.metrics_collector import MetricsCollector, create_metrics_collector
from portainer_dashboard.services.anomaly_detector import AnomalyDetector, create_anomaly_detector
from portainer_dashboard.services.remediation_service import RemediationService, get_remediation_service

LOGGER = logging.getLogger(__name__)

MONITORING_SYSTEM_PROMPT = """You are an infrastructure monitoring AI analyzing a Portainer-managed Docker environment.

Analyze the following infrastructure data and generate actionable insights for sysadmins.

Focus on:
1. Resource Issues: High CPU/memory usage, resource exhaustion
2. Availability: Unhealthy containers, offline endpoints, degraded services
3. Security: Elevated privileges, dangerous capabilities, privileged containers
4. Images: Outdated images with available updates
5. Logs: Error patterns in container logs (exceptions, connection failures, OOM, crashes)
6. Optimization: Unused resources, potential improvements

When analyzing container logs, look for:
- Exception stack traces and error messages
- Connection failures (connection refused, timeout, reset)
- Out of memory (OOM) errors or memory pressure
- Repeated restart loops or crash patterns
- Authentication/authorization failures
- Database connection issues

For each issue found, provide:
- severity: "critical", "warning", "info", or "optimization"
- category: "resource", "security", "availability", "image", "logs", or "optimization"
- title: Brief descriptive title
- description: Detailed explanation of the issue
- affected_resources: List of affected container/endpoint names
- recommended_action: Specific action to resolve the issue

Respond ONLY with a valid JSON array of insight objects. If no issues are found, return an empty array [].

Example response format:
[
  {
    "severity": "warning",
    "category": "security",
    "title": "Container with elevated privileges",
    "description": "Container 'my-app' is running with NET_ADMIN capability which allows network configuration changes",
    "affected_resources": ["my-app"],
    "recommended_action": "Remove NET_ADMIN capability unless required for network debugging"
  },
  {
    "severity": "critical",
    "category": "logs",
    "title": "Out of memory errors detected",
    "description": "Container 'worker' shows OOM killer activity in logs, indicating memory exhaustion",
    "affected_resources": ["worker"],
    "recommended_action": "Increase memory limits or investigate memory leaks in the application"
  }
]"""


def _build_analysis_prompt(snapshot: InfrastructureSnapshot) -> str:
    """Build the analysis prompt with infrastructure data."""
    parts: list[str] = []

    parts.append("## Infrastructure Summary")
    parts.append(f"Timestamp: {snapshot.timestamp.isoformat()}")
    parts.append(f"Endpoints: {snapshot.endpoints_online} online, {snapshot.endpoints_offline} offline")
    parts.append(
        f"Containers: {snapshot.containers_running} running, "
        f"{snapshot.containers_stopped} stopped, "
        f"{snapshot.containers_unhealthy} unhealthy"
    )

    if snapshot.security_issues:
        parts.append("\n## Security Issues Detected")
        for issue in snapshot.security_issues:
            parts.append(f"\n### Container: {issue.container_name}")
            parts.append(f"Endpoint: {issue.endpoint_name}")
            parts.append(f"Privileged: {issue.privileged}")
            if issue.cap_add:
                parts.append(f"Added Capabilities: {', '.join(issue.cap_add)}")
            if issue.security_opt:
                parts.append(f"Security Options: {', '.join(issue.security_opt)}")
            if issue.elevated_risks:
                parts.append("Risks:")
                for risk in issue.elevated_risks:
                    parts.append(f"  - {risk}")

    if snapshot.outdated_images:
        parts.append("\n## Outdated Images")
        for img in snapshot.outdated_images:
            parts.append(f"- Stack: {img.stack_name}, Image: {img.image_name}")
            if img.current_digest and img.latest_digest:
                parts.append(f"  Current: {img.current_digest[:16]}...")
                parts.append(f"  Latest: {img.latest_digest[:16]}...")

    if snapshot.endpoint_details:
        parts.append("\n## Endpoints")
        for ep in snapshot.endpoint_details:
            status = "online" if ep.get("endpoint_status") == 1 else "offline"
            parts.append(f"- {ep.get('endpoint_name')}: {status}")

    if snapshot.containers_unhealthy > 0:
        parts.append("\n## Unhealthy Containers")
        for c in snapshot.container_details:
            status = c.get("status") or ""
            if "unhealthy" in status.lower():
                parts.append(f"- {c.get('container_name')}: {status}")

    if snapshot.container_logs:
        parts.append("\n## Container Logs for Analysis")
        parts.append(
            f"Logs collected from {len(snapshot.container_logs)} problematic container(s):"
        )
        for log_entry in snapshot.container_logs:
            parts.append(f"\n### Container: {log_entry.container_name}")
            parts.append(f"Endpoint: {log_entry.endpoint_name}")
            parts.append(f"State: {log_entry.state}")
            if log_entry.exit_code is not None:
                parts.append(f"Exit Code: {log_entry.exit_code}")
            parts.append(f"Log lines: {log_entry.log_lines}")
            if log_entry.truncated:
                parts.append("(logs truncated)")
            # Sanitize and limit log content to avoid overwhelming the LLM
            log_content = sanitize_logs(log_entry.logs)
            if len(log_content) > 3000:
                log_content = log_content[-3000:]
                parts.append("Recent log output (truncated to last 3000 chars):")
            else:
                parts.append("Recent log output:")
            parts.append("```")
            parts.append(log_content)
            parts.append("```")

    return "\n".join(parts)


def _parse_llm_insights(response: str) -> list[MonitoringInsight]:
    """Parse LLM response into MonitoringInsight objects."""
    response = response.strip()

    if response.startswith("```json"):
        response = response[7:]
    if response.startswith("```"):
        response = response[3:]
    if response.endswith("```"):
        response = response[:-3]
    response = response.strip()

    try:
        data = json.loads(response)
    except json.JSONDecodeError as exc:
        LOGGER.warning("Failed to parse LLM response as JSON: %s", exc)
        return []

    if not isinstance(data, list):
        LOGGER.warning("LLM response is not a list: %s", type(data))
        return []

    insights: list[MonitoringInsight] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        try:
            severity_str = item.get("severity", "info").lower()
            try:
                severity = InsightSeverity(severity_str)
            except ValueError:
                severity = InsightSeverity.INFO

            insight = MonitoringInsight(
                severity=severity,
                category=item.get("category", "optimization"),
                title=item.get("title", "Unknown Issue"),
                description=item.get("description", ""),
                affected_resources=item.get("affected_resources", []),
                recommended_action=item.get("recommended_action"),
            )
            insights.append(insight)
        except Exception as exc:
            LOGGER.debug("Failed to parse insight: %s", exc)
            continue

    return insights


def _deduplicate_insights(insights: list[MonitoringInsight]) -> list[MonitoringInsight]:
    """Remove duplicate insights based on title and affected resources.

    Two insights are considered duplicates if they have the same title
    and the same set of affected resources. When duplicates are found,
    the one with higher severity is kept.
    """
    if not insights:
        return insights

    # Build deduplication key: (normalized_title, frozenset of resources)
    seen: dict[tuple[str, frozenset[str]], MonitoringInsight] = {}
    severity_order = {
        InsightSeverity.CRITICAL: 4,
        InsightSeverity.WARNING: 3,
        InsightSeverity.INFO: 2,
        InsightSeverity.OPTIMIZATION: 1,
    }

    for insight in insights:
        # Normalize title for comparison (lowercase, strip whitespace)
        normalized_title = insight.title.lower().strip()
        resources_key = frozenset(r.lower().strip() for r in insight.affected_resources)
        key = (normalized_title, resources_key)

        if key in seen:
            existing = seen[key]
            # Keep the one with higher severity
            if severity_order.get(insight.severity, 0) > severity_order.get(existing.severity, 0):
                LOGGER.debug(
                    "Replacing duplicate insight '%s' (severity %s -> %s)",
                    insight.title,
                    existing.severity.value,
                    insight.severity.value,
                )
                seen[key] = insight
            else:
                LOGGER.debug(
                    "Skipping duplicate insight '%s' (keeping severity %s)",
                    insight.title,
                    existing.severity.value,
                )
        else:
            seen[key] = insight

    deduplicated = list(seen.values())

    if len(deduplicated) < len(insights):
        LOGGER.info(
            "Deduplicated insights: %d -> %d (removed %d duplicates)",
            len(insights),
            len(deduplicated),
            len(insights) - len(deduplicated),
        )

    return deduplicated


def _generate_fallback_insights(snapshot: InfrastructureSnapshot) -> list[MonitoringInsight]:
    """Generate insights without LLM based on collected data."""
    insights: list[MonitoringInsight] = []

    if snapshot.endpoints_offline > 0:
        offline_eps = [
            ep.get("endpoint_name")
            for ep in snapshot.endpoint_details
            if ep.get("endpoint_status") != 1
        ]
        insights.append(
            MonitoringInsight(
                severity=InsightSeverity.CRITICAL,
                category="availability",
                title=f"{snapshot.endpoints_offline} endpoint(s) offline",
                description=f"The following endpoints are currently offline: {', '.join(offline_eps)}",
                affected_resources=offline_eps,
                recommended_action="Check network connectivity and agent status on affected endpoints",
            )
        )

    if snapshot.containers_unhealthy > 0:
        unhealthy = [
            c.get("container_name")
            for c in snapshot.container_details
            if "unhealthy" in (c.get("status") or "").lower()
        ]
        insights.append(
            MonitoringInsight(
                severity=InsightSeverity.WARNING,
                category="availability",
                title=f"{snapshot.containers_unhealthy} container(s) unhealthy",
                description="Containers failing health checks detected",
                affected_resources=unhealthy,
                recommended_action="Check container logs and health check configuration",
            )
        )

    for issue in snapshot.security_issues:
        insights.append(
            MonitoringInsight(
                severity=InsightSeverity.WARNING if not issue.privileged else InsightSeverity.CRITICAL,
                category="security",
                title=f"Elevated privileges on {issue.container_name}",
                description="; ".join(issue.elevated_risks),
                affected_resources=[issue.container_name],
                recommended_action="Review and restrict container capabilities where possible",
            )
        )

    for img in snapshot.outdated_images:
        insights.append(
            MonitoringInsight(
                severity=InsightSeverity.INFO,
                category="image",
                title=f"Outdated image in stack {img.stack_name}",
                description=f"Image {img.image_name} has updates available",
                affected_resources=[img.stack_name or "unknown"],
                recommended_action="Update the stack to use the latest image version",
            )
        )

    # Analyze container logs for common error patterns
    for log_entry in snapshot.container_logs:
        logs_lower = log_entry.logs.lower()

        # Check for OOM errors
        if "out of memory" in logs_lower or "oom" in logs_lower or "killed" in logs_lower:
            insights.append(
                MonitoringInsight(
                    severity=InsightSeverity.CRITICAL,
                    category="logs",
                    title=f"Memory issues detected in {log_entry.container_name}",
                    description=(
                        f"Container {log_entry.container_name} on endpoint {log_entry.endpoint_name} "
                        f"shows signs of memory exhaustion (OOM) in logs."
                    ),
                    affected_resources=[log_entry.container_name],
                    recommended_action="Increase container memory limits or investigate memory leaks",
                )
            )
            continue  # Skip other checks for this container

        # Check for connection errors
        if any(
            pattern in logs_lower
            for pattern in ["connection refused", "connection reset", "connection timed out", "econnrefused"]
        ):
            insights.append(
                MonitoringInsight(
                    severity=InsightSeverity.WARNING,
                    category="logs",
                    title=f"Connection errors in {log_entry.container_name}",
                    description=(
                        f"Container {log_entry.container_name} on endpoint {log_entry.endpoint_name} "
                        f"shows connection failures in logs. State: {log_entry.state}"
                    ),
                    affected_resources=[log_entry.container_name],
                    recommended_action="Check network connectivity and dependent service availability",
                )
            )
            continue

        # Check for restarting containers
        if log_entry.state == "restarting":
            insights.append(
                MonitoringInsight(
                    severity=InsightSeverity.WARNING,
                    category="logs",
                    title=f"Container {log_entry.container_name} is restarting",
                    description=(
                        f"Container {log_entry.container_name} on endpoint {log_entry.endpoint_name} "
                        f"is in a restart loop. Check logs for crash reasons."
                    ),
                    affected_resources=[log_entry.container_name],
                    recommended_action="Investigate crash cause in logs and fix underlying issue",
                )
            )
            continue

        # Check for non-zero exit codes
        if log_entry.state == "exited_error" and log_entry.exit_code is not None:
            insights.append(
                MonitoringInsight(
                    severity=InsightSeverity.WARNING,
                    category="logs",
                    title=f"Container {log_entry.container_name} exited with error",
                    description=(
                        f"Container {log_entry.container_name} on endpoint {log_entry.endpoint_name} "
                        f"exited with code {log_entry.exit_code}."
                    ),
                    affected_resources=[log_entry.container_name],
                    recommended_action="Review logs to identify the cause of the error exit",
                )
            )

    return insights


@dataclass
class MonitoringService:
    """Orchestrates infrastructure monitoring and analysis."""

    data_collector: DataCollector
    insights_store: InsightsStore
    llm_client: AsyncLLMClient | None = None
    broadcast_callback: Callable[[MonitoringReport], Any] | None = None
    metrics_collector: MetricsCollector | None = None
    anomaly_detector: AnomalyDetector | None = None
    remediation_service: RemediationService | None = None

    async def run_analysis(self) -> MonitoringReport:
        """Run a complete monitoring analysis cycle."""
        LOGGER.info("Starting monitoring analysis")
        start_time = datetime.now(timezone.utc)

        # Collect metrics if enabled
        metrics_collected = 0
        if self.metrics_collector:
            try:
                metrics_collected = await self.metrics_collector.collect_all_metrics()
                LOGGER.info("Collected %d metrics", metrics_collected)
            except Exception as exc:
                LOGGER.warning("Metrics collection failed: %s", exc)

        try:
            snapshot = await self.data_collector.collect_snapshot()
        except Exception as exc:
            LOGGER.error("Failed to collect infrastructure snapshot: %s", exc)
            report = MonitoringReport(
                summary=f"Data collection failed: {exc}",
            )
            await self.insights_store.add_report(report)
            return report

        insights: list[MonitoringInsight] = []

        if self.llm_client:
            try:
                prompt = _build_analysis_prompt(snapshot)
                messages = [
                    {"role": "system", "content": MONITORING_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]

                response = await self.llm_client.chat(
                    messages,
                    temperature=0.1,
                    max_tokens=2048,
                )

                insights = _parse_llm_insights(response)
                LOGGER.info("LLM generated %d insights", len(insights))

            except LLMClientError as exc:
                LOGGER.warning("LLM analysis failed, using fallback: %s", exc)
                insights = _generate_fallback_insights(snapshot)
        else:
            LOGGER.info("No LLM configured, using fallback analysis")
            insights = _generate_fallback_insights(snapshot)

        # Deduplicate insights to avoid redundant alerts
        insights = _deduplicate_insights(insights)

        # Suggest remediation actions from insights (if enabled)
        actions_suggested = 0
        if self.remediation_service and self.remediation_service.is_enabled:
            actions_suggested = await self._suggest_remediation_actions(insights, snapshot)
            LOGGER.info("Suggested %d remediation actions", actions_suggested)

        critical_count = sum(1 for i in insights if i.severity == InsightSeverity.CRITICAL)
        warning_count = sum(1 for i in insights if i.severity == InsightSeverity.WARNING)

        summary_parts = []
        summary_parts.append(
            f"Analyzed {snapshot.endpoints_online + snapshot.endpoints_offline} endpoints "
            f"and {snapshot.containers_running + snapshot.containers_stopped} containers."
        )
        if insights:
            summary_parts.append(
                f"Found {len(insights)} issue(s): {critical_count} critical, {warning_count} warning."
            )
        else:
            summary_parts.append("No issues detected.")

        if metrics_collected > 0:
            summary_parts.append(f"Collected {metrics_collected} metrics.")

        if actions_suggested > 0:
            summary_parts.append(f"Suggested {actions_suggested} remediation action(s).")

        report = MonitoringReport(
            timestamp=start_time,
            insights=insights,
            summary=" ".join(summary_parts),
            endpoints_analyzed=snapshot.endpoints_online + snapshot.endpoints_offline,
            containers_analyzed=snapshot.containers_running + snapshot.containers_stopped,
            security_issues_found=len(snapshot.security_issues),
            outdated_images_found=len(snapshot.outdated_images),
            containers_with_logs_analyzed=len(snapshot.container_logs),
        )

        await self.insights_store.add_report(report)

        if self.broadcast_callback:
            try:
                await self.broadcast_callback(report)
            except Exception as exc:
                LOGGER.warning("Failed to broadcast report: %s", exc)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        LOGGER.info(
            "Monitoring analysis completed in %.2fs with %d insights",
            elapsed,
            len(insights),
        )

        return report

    async def _suggest_remediation_actions(
        self,
        insights: list[MonitoringInsight],
        snapshot: InfrastructureSnapshot,
    ) -> int:
        """Suggest remediation actions from insights.

        Returns the number of actions suggested.
        """
        if not self.remediation_service:
            return 0

        actions_created = 0

        # Build container lookup from snapshot
        container_lookup: dict[str, dict] = {}
        for container in snapshot.container_details:
            name = container.get("container_name")
            if name:
                container_lookup[name] = container

        # Also include log entries (these have endpoint info)
        for log_entry in snapshot.container_logs:
            # Log entries override container_details since they have complete info
            container_lookup[log_entry.container_name] = {
                "container_name": log_entry.container_name,
                "container_id": log_entry.container_id,
                "endpoint_id": log_entry.endpoint_id,
                "endpoint_name": log_entry.endpoint_name,
            }

        LOGGER.debug(
            "Container lookup built with %d entries: %s",
            len(container_lookup),
            list(container_lookup.keys()),
        )

        for insight in insights:
            # Only process actionable categories
            if insight.category.lower() not in {"availability", "logs", "resource"}:
                continue

            # Try to find affected container
            for resource_name in insight.affected_resources:
                container_info = container_lookup.get(resource_name)
                if not container_info:
                    LOGGER.debug(
                        "Resource '%s' from insight '%s' not found in container lookup",
                        resource_name,
                        insight.title,
                    )
                    continue

                container_id = container_info.get("container_id")
                endpoint_id = container_info.get("endpoint_id")

                if not container_id or not endpoint_id:
                    LOGGER.debug(
                        "Resource '%s' missing container_id=%s or endpoint_id=%s",
                        resource_name,
                        container_id,
                        endpoint_id,
                    )
                    continue

                action = self.remediation_service.suggest_action_from_insight(
                    insight=insight,
                    endpoint_id=endpoint_id,
                    endpoint_name=container_info.get("endpoint_name"),
                    container_id=container_id,
                    container_name=resource_name,
                )

                if action:
                    actions_created += 1

        return actions_created


async def create_monitoring_service(
    broadcast_callback: Callable[[MonitoringReport], Any] | None = None,
) -> MonitoringService:
    """Create a monitoring service with settings from configuration."""
    settings = get_settings()
    data_collector = create_data_collector()
    insights_store = await get_insights_store()
    llm_client = create_llm_client(settings.llm)

    # Create optional services based on configuration
    metrics_collector = None
    anomaly_detector = None
    remediation_service = None

    if settings.metrics.enabled:
        metrics_collector = await create_metrics_collector()
        if settings.metrics.anomaly_detection_enabled:
            anomaly_detector = await create_anomaly_detector()

    if settings.remediation.enabled:
        remediation_service = await get_remediation_service()

    return MonitoringService(
        data_collector=data_collector,
        insights_store=insights_store,
        llm_client=llm_client,
        broadcast_callback=broadcast_callback,
        metrics_collector=metrics_collector,
        anomaly_detector=anomaly_detector,
        remediation_service=remediation_service,
    )


__all__ = [
    "MonitoringService",
    "create_monitoring_service",
]
