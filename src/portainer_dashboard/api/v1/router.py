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

router = APIRouter(tags=["API v1"])

router.include_router(dashboard_router)  # Dashboard overview (batch fetching)
router.include_router(endpoints_router, prefix="/endpoints")
router.include_router(containers_router, prefix="/containers")
router.include_router(stacks_router, prefix="/stacks")
router.include_router(backup_router, prefix="/backup")
router.include_router(logs_router, prefix="/logs")
router.include_router(monitoring_router)
router.include_router(metrics_router)
router.include_router(remediation_router)
router.include_router(traces_router)

__all__ = ["router"]
