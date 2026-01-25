"""API v1 router aggregating all endpoint modules."""

from fastapi import APIRouter

from portainer_dashboard.api.v1.endpoints import router as endpoints_router
from portainer_dashboard.api.v1.containers import router as containers_router
from portainer_dashboard.api.v1.stacks import router as stacks_router
from portainer_dashboard.api.v1.backup import router as backup_router
from portainer_dashboard.api.v1.logs import router as logs_router

router = APIRouter(tags=["API v1"])

router.include_router(endpoints_router, prefix="/endpoints")
router.include_router(containers_router, prefix="/containers")
router.include_router(stacks_router, prefix="/stacks")
router.include_router(backup_router, prefix="/backup")
router.include_router(logs_router, prefix="/logs")

__all__ = ["router"]
