"""Portainer data models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Endpoint(BaseModel):
    """Portainer endpoint (edge agent) representation."""

    endpoint_id: int
    endpoint_name: str | None = None
    endpoint_status: int | None = None
    agent_version: str | None = None
    platform: str | None = None
    operating_system: str | None = None
    group_id: int | None = None
    tags: str | None = None
    last_check_in: str | None = None
    url: str | None = None
    agent_hostname: str | None = None


class Stack(BaseModel):
    """Portainer stack representation."""

    endpoint_id: int
    endpoint_name: str | None = None
    endpoint_status: int | None = None
    stack_id: int | None = None
    stack_name: str | None = None
    stack_status: int | None = None
    stack_type: int | None = None


class Container(BaseModel):
    """Docker container representation."""

    endpoint_id: int
    endpoint_name: str | None = None
    container_id: str | None = None
    container_name: str | None = None
    image: str | None = None
    state: str | None = None
    status: str | None = None
    restart_count: int | None = None
    created_at: str | None = None
    ports: str | None = None


class ContainerDetails(BaseModel):
    """Extended container details with metrics."""

    endpoint_id: int
    endpoint_name: str | None = None
    container_id: str | None = None
    container_name: str | None = None
    health_status: str | None = None
    last_exit_code: int | None = None
    last_finished_at: str | None = None
    cpu_percent: float | None = None
    memory_usage: int | None = None
    memory_limit: int | None = None
    memory_percent: float | None = None
    environment: list[str] | None = None  # ["KEY=value", ...]
    networks: dict[str, Any] | None = None  # Network settings
    mounts: list[dict[str, Any]] | None = None  # Volume mounts
    labels: dict[str, str] | None = None  # Container labels
    restart_policy: str | None = None
    privileged: bool | None = None
    image: str | None = None
    state: str | None = None
    status: str | None = None


class HostMetrics(BaseModel):
    """Docker host capacity information."""

    endpoint_id: int
    endpoint_name: str | None = None
    docker_version: str | None = None
    architecture: str | None = None
    operating_system: str | None = None
    total_cpus: int | None = None
    total_memory: int | None = None
    swarm_node: bool | None = None
    containers_total: int | None = None
    containers_running: int | None = None
    containers_stopped: int | None = None
    volumes_total: int | None = None
    images_total: int | None = None
    layers_size: int | None = None


class Volume(BaseModel):
    """Docker volume representation."""

    endpoint_id: int
    endpoint_name: str | None = None
    volume_name: str | None = None
    driver: str | None = None
    scope: str | None = None
    mountpoint: str | None = None
    labels: str | None = None


class Image(BaseModel):
    """Docker image representation."""

    endpoint_id: int
    endpoint_name: str | None = None
    image_id: str | None = None
    reference: str | None = None
    size: int | None = None
    created_at: str | None = None
    dangling: bool | None = None


class PortainerDataResponse(BaseModel):
    """Complete Portainer data response."""

    endpoints: list[Endpoint] = Field(default_factory=list)
    stacks: list[Stack] = Field(default_factory=list)
    containers: list[Container] = Field(default_factory=list)
    container_details: list[ContainerDetails] = Field(default_factory=list)
    host_metrics: list[HostMetrics] = Field(default_factory=list)
    volumes: list[Volume] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    refreshed_at: float | None = None
    is_stale: bool = False


class ContainerLogsResponse(BaseModel):
    """Container logs response."""

    endpoint_id: int
    container_id: str
    container_name: str | None = None
    logs: str
    tail: int
    timestamps: bool


class BackupRequest(BaseModel):
    """Backup creation request."""

    password: str | None = None


class BackupResponse(BaseModel):
    """Backup creation response."""

    success: bool
    filename: str | None = None
    size: int | None = None
    message: str = ""


__all__ = [
    "BackupRequest",
    "BackupResponse",
    "Container",
    "ContainerDetails",
    "ContainerLogsResponse",
    "Endpoint",
    "HostMetrics",
    "Image",
    "PortainerDataResponse",
    "Stack",
    "Volume",
]
