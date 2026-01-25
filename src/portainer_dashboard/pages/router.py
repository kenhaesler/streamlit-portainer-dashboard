"""HTML page routes for the dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from portainer_dashboard.auth.dependencies import OptionalUserDep
from portainer_dashboard.config import get_settings
from portainer_dashboard.dependencies import JinjaEnvDep

if TYPE_CHECKING:
    from jinja2 import Environment

router = APIRouter()


def _require_auth(user: OptionalUserDep, next_url: str = "/") -> RedirectResponse | None:
    """Return a redirect to login if user is not authenticated."""
    if user is None:
        return RedirectResponse(url=f"/auth/login?next={next_url}", status_code=303)
    return None


@router.get("/", response_class=HTMLResponse, response_model=None)
async def home_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the home page."""
    redirect = _require_auth(user, "/")
    if redirect:
        return redirect

    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    template = jinja.get_template("pages/home.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/",
        environments=environments,
        selected_environment=environments[0].name if environments else None,
    )
    return HTMLResponse(content=content)


@router.get("/fleet", response_class=HTMLResponse, response_model=None)
async def fleet_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the fleet overview page."""
    redirect = _require_auth(user, "/fleet")
    if redirect:
        return redirect

    template = jinja.get_template("pages/fleet.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/fleet",
    )
    return HTMLResponse(content=content)


@router.get("/health", response_class=HTMLResponse, response_model=None)
async def health_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the container health page."""
    redirect = _require_auth(user, "/health")
    if redirect:
        return redirect

    template = jinja.get_template("pages/health.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/health",
    )
    return HTMLResponse(content=content)


@router.get("/workloads", response_class=HTMLResponse, response_model=None)
async def workloads_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the workload explorer page."""
    redirect = _require_auth(user, "/workloads")
    if redirect:
        return redirect

    template = jinja.get_template("pages/workloads.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/workloads",
    )
    return HTMLResponse(content=content)


@router.get("/images", response_class=HTMLResponse, response_model=None)
async def images_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the image footprint page."""
    redirect = _require_auth(user, "/images")
    if redirect:
        return redirect

    template = jinja.get_template("pages/images.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/images",
    )
    return HTMLResponse(content=content)


@router.get("/assistant", response_class=HTMLResponse, response_model=None)
async def assistant_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the LLM assistant page."""
    redirect = _require_auth(user, "/assistant")
    if redirect:
        return redirect

    settings = get_settings()
    llm_configured = bool(settings.llm.api_endpoint)

    template = jinja.get_template("pages/assistant.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/assistant",
        llm_configured=llm_configured,
    )
    return HTMLResponse(content=content)


@router.get("/logs", response_class=HTMLResponse, response_model=None)
async def logs_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the edge agent logs page."""
    redirect = _require_auth(user, "/logs")
    if redirect:
        return redirect

    settings = get_settings()
    kibana_configured = settings.kibana.is_configured

    template = jinja.get_template("pages/logs.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/logs",
        kibana_configured=kibana_configured,
    )
    return HTMLResponse(content=content)


@router.get("/settings", response_class=HTMLResponse, response_model=None)
async def settings_page(
    request: Request,
    jinja: JinjaEnvDep,
    user: OptionalUserDep,
) -> Response:
    """Render the settings page."""
    redirect = _require_auth(user, "/settings")
    if redirect:
        return redirect

    settings = get_settings()
    environments = settings.portainer.get_configured_environments()

    template = jinja.get_template("pages/settings.html")
    content = await template.render_async(
        request=request,
        user=user,
        current_path="/settings",
        environments=environments,
        settings=settings,
    )
    return HTMLResponse(content=content)


__all__ = ["router"]
