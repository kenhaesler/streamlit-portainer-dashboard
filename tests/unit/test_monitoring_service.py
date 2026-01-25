"""Tests for the monitoring service module."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from portainer_dashboard.models.monitoring import (
    ContainerCapabilities,
    ImageStatus,
    InfrastructureSnapshot,
    InsightSeverity,
    MonitoringInsight,
    MonitoringReport,
)
from portainer_dashboard.services.monitoring_service import (
    _build_analysis_prompt,
    _generate_fallback_insights,
    _parse_llm_insights,
)


class TestBuildAnalysisPrompt:
    """Tests for building LLM analysis prompts."""

    def test_basic_prompt(self) -> None:
        """Test basic prompt generation."""
        snapshot = InfrastructureSnapshot(
            endpoints_online=5,
            endpoints_offline=1,
            containers_running=20,
            containers_stopped=5,
            containers_unhealthy=2,
        )

        prompt = _build_analysis_prompt(snapshot)

        assert "Infrastructure Summary" in prompt
        assert "5 online" in prompt
        assert "1 offline" in prompt
        assert "20 running" in prompt
        assert "5 stopped" in prompt
        assert "2 unhealthy" in prompt

    def test_prompt_with_security_issues(self) -> None:
        """Test prompt includes security issues."""
        snapshot = InfrastructureSnapshot(
            endpoints_online=1,
            containers_running=1,
            security_issues=[
                ContainerCapabilities(
                    endpoint_id=1,
                    endpoint_name="prod",
                    container_id="abc123",
                    container_name="privileged-app",
                    privileged=True,
                    cap_add=["NET_ADMIN"],
                    elevated_risks=["Container running in privileged mode"],
                )
            ],
        )

        prompt = _build_analysis_prompt(snapshot)

        assert "Security Issues Detected" in prompt
        assert "privileged-app" in prompt
        assert "NET_ADMIN" in prompt
        assert "privileged mode" in prompt

    def test_prompt_with_outdated_images(self) -> None:
        """Test prompt includes outdated images."""
        snapshot = InfrastructureSnapshot(
            endpoints_online=1,
            containers_running=1,
            outdated_images=[
                ImageStatus(
                    stack_id=1,
                    stack_name="my-stack",
                    endpoint_id=1,
                    endpoint_name="prod",
                    image_name="nginx:latest",
                    outdated=True,
                )
            ],
        )

        prompt = _build_analysis_prompt(snapshot)

        assert "Outdated Images" in prompt
        assert "my-stack" in prompt
        assert "nginx:latest" in prompt


class TestParseLLMInsights:
    """Tests for parsing LLM responses."""

    def test_parse_valid_json(self) -> None:
        """Test parsing valid JSON response."""
        response = '''[
            {
                "severity": "warning",
                "category": "security",
                "title": "Elevated privileges",
                "description": "Container has NET_ADMIN",
                "affected_resources": ["my-app"],
                "recommended_action": "Remove capability"
            }
        ]'''

        insights = _parse_llm_insights(response)

        assert len(insights) == 1
        assert insights[0].severity == InsightSeverity.WARNING
        assert insights[0].category == "security"
        assert insights[0].title == "Elevated privileges"

    def test_parse_json_with_code_fence(self) -> None:
        """Test parsing JSON with markdown code fence."""
        response = '''```json
[
    {
        "severity": "critical",
        "category": "availability",
        "title": "Endpoint offline",
        "description": "Production endpoint is down"
    }
]
```'''

        insights = _parse_llm_insights(response)

        assert len(insights) == 1
        assert insights[0].severity == InsightSeverity.CRITICAL

    def test_parse_empty_array(self) -> None:
        """Test parsing empty array."""
        response = "[]"
        insights = _parse_llm_insights(response)
        assert len(insights) == 0

    def test_parse_invalid_json(self) -> None:
        """Test parsing invalid JSON returns empty list."""
        response = "This is not JSON"
        insights = _parse_llm_insights(response)
        assert len(insights) == 0

    def test_parse_unknown_severity(self) -> None:
        """Test parsing unknown severity defaults to INFO."""
        response = '''[{"severity": "unknown", "category": "test", "title": "Test"}]'''
        insights = _parse_llm_insights(response)

        assert len(insights) == 1
        assert insights[0].severity == InsightSeverity.INFO


class TestGenerateFallbackInsights:
    """Tests for fallback insight generation."""

    def test_offline_endpoints(self) -> None:
        """Test insight generation for offline endpoints."""
        snapshot = InfrastructureSnapshot(
            endpoints_online=5,
            endpoints_offline=2,
            endpoint_details=[
                {"endpoint_name": "prod", "endpoint_status": 1},
                {"endpoint_name": "dev", "endpoint_status": 0},
                {"endpoint_name": "staging", "endpoint_status": 0},
            ],
        )

        insights = _generate_fallback_insights(snapshot)

        offline_insights = [
            i for i in insights
            if "offline" in i.title.lower()
        ]
        assert len(offline_insights) == 1
        assert offline_insights[0].severity == InsightSeverity.CRITICAL
        assert "dev" in offline_insights[0].affected_resources
        assert "staging" in offline_insights[0].affected_resources

    def test_unhealthy_containers(self) -> None:
        """Test insight generation for unhealthy containers."""
        snapshot = InfrastructureSnapshot(
            containers_running=10,
            containers_unhealthy=2,
            container_details=[
                {"container_name": "app1", "status": "Up 2 hours (unhealthy)"},
                {"container_name": "app2", "status": "Up 1 hour (healthy)"},
            ],
        )

        insights = _generate_fallback_insights(snapshot)

        unhealthy_insights = [
            i for i in insights
            if "unhealthy" in i.title.lower()
        ]
        assert len(unhealthy_insights) == 1
        assert unhealthy_insights[0].severity == InsightSeverity.WARNING

    def test_security_issues(self) -> None:
        """Test insight generation for security issues."""
        snapshot = InfrastructureSnapshot(
            containers_running=5,
            security_issues=[
                ContainerCapabilities(
                    endpoint_id=1,
                    container_id="abc",
                    container_name="privileged-app",
                    privileged=True,
                    elevated_risks=["Container running in privileged mode"],
                ),
                ContainerCapabilities(
                    endpoint_id=1,
                    container_id="def",
                    container_name="net-admin-app",
                    privileged=False,
                    cap_add=["NET_ADMIN"],
                    elevated_risks=["Elevated capability: NET_ADMIN"],
                ),
            ],
        )

        insights = _generate_fallback_insights(snapshot)

        security_insights = [
            i for i in insights
            if i.category == "security"
        ]
        assert len(security_insights) == 2

        privileged_insight = next(
            i for i in security_insights
            if "privileged-app" in i.affected_resources
        )
        assert privileged_insight.severity == InsightSeverity.CRITICAL

    def test_outdated_images(self) -> None:
        """Test insight generation for outdated images."""
        snapshot = InfrastructureSnapshot(
            containers_running=5,
            outdated_images=[
                ImageStatus(
                    stack_id=1,
                    stack_name="web-stack",
                    endpoint_id=1,
                    image_name="nginx:latest",
                    outdated=True,
                )
            ],
        )

        insights = _generate_fallback_insights(snapshot)

        image_insights = [
            i for i in insights
            if i.category == "image"
        ]
        assert len(image_insights) == 1
        assert image_insights[0].severity == InsightSeverity.INFO
        assert "web-stack" in image_insights[0].affected_resources

    def test_no_issues(self) -> None:
        """Test no insights when no issues found."""
        snapshot = InfrastructureSnapshot(
            endpoints_online=5,
            endpoints_offline=0,
            containers_running=20,
            containers_stopped=0,
            containers_unhealthy=0,
        )

        insights = _generate_fallback_insights(snapshot)
        assert len(insights) == 0


class TestMonitoringInsight:
    """Tests for MonitoringInsight model."""

    def test_default_id_generated(self) -> None:
        """Test that IDs are auto-generated."""
        insight = MonitoringInsight(
            severity=InsightSeverity.INFO,
            category="test",
            title="Test insight",
            description="Test description",
        )

        assert insight.id is not None
        assert len(insight.id) == 36  # UUID format

    def test_default_timestamp(self) -> None:
        """Test that timestamp is auto-generated."""
        insight = MonitoringInsight(
            severity=InsightSeverity.INFO,
            category="test",
            title="Test insight",
            description="Test description",
        )

        assert insight.timestamp is not None
        assert isinstance(insight.timestamp, datetime)


class TestMonitoringReport:
    """Tests for MonitoringReport model."""

    def test_default_values(self) -> None:
        """Test default values for report."""
        report = MonitoringReport()

        assert report.id is not None
        assert report.timestamp is not None
        assert report.insights == []
        assert report.summary == ""
        assert report.endpoints_analyzed == 0
        assert report.containers_analyzed == 0
        assert report.security_issues_found == 0
        assert report.outdated_images_found == 0
