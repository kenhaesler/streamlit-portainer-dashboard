"""API v1 router aggregating all endpoint modules."""

from fastapi import APIRouter

from portainer_dashboard.api.v1.dashboard import router as dashboard_router
from portainer_dashboard.api.v1.endpoints import router as endpoints_router
from portainer_dashboard.api.v1.containers import router as containers_router
from portainer_dashboard.api.v1.stacks import router as stacks_router
from portainer_dashboard.api.v1.backup import router as backup_router
from portainer_dashboard.api.v1.logs import router as logs_router
from portainer_dashboard.api.v1.monitoring import router as monitoring_router
from portainer_dashboard.api.v1.metrics import router as metrics_router
from portainer_dashboard.api.v1.remediation import router as remediation_router
from portainer_dashboard.api.v1.traces import router as traces_router

router = APIRouter()

# Dashboard overview - batch fetching for frontend optimization
router.include_router(
    dashboard_router,
    tags=["Dashboard"],
)

# Portainer endpoints (edge agents)
router.include_router(
    endpoints_router,
    prefix="/endpoints",
    tags=["Endpoints"],
)

# Docker containers management
router.include_router(
    containers_router,
    prefix="/containers",
    tags=["Containers"],
)

# Portainer stacks management
router.include_router(
    stacks_router,
    prefix="/stacks",
    tags=["Stacks"],
)

# Portainer backup operations
router.include_router(
    backup_router,
    prefix="/backup",
    tags=["Backup"],
)

# Kibana/Elasticsearch log integration
router.include_router(
    logs_router,
    prefix="/logs",
    tags=["Logs"],
)

# AI-powered monitoring and insights
router.include_router(
    monitoring_router,
    tags=["Monitoring"],
)

# Time-series metrics and anomaly detection
router.include_router(
    metrics_router,
    tags=["Metrics"],
)

# Self-healing remediation actions
router.include_router(
    remediation_router,
    tags=["Remediation"],
)

# Distributed tracing
router.include_router(
    traces_router,
    tags=["Traces"],
)

__all__ = ["router"]
