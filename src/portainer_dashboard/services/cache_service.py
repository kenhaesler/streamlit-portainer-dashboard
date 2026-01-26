"""Caching service for Portainer data.

Provides centralized caching for all Portainer API data with:
- Startup cache warming
- Background refresh
- TTL-based expiration
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from portainer_dashboard.config import get_settings
from portainer_dashboard.core.cache import (
    CacheEntry,
    is_cache_enabled,
    load_cache_entry,
    store_cache_entry,
)
from portainer_dashboard.services.portainer_client import (
    AsyncPortainerClient,
    PortainerAPIError,
    create_portainer_client,
    normalise_endpoint_containers_dict,
    normalise_endpoint_metadata_dict,
    normalise_endpoint_stacks_dict,
)

LOGGER = logging.getLogger(__name__)

# Cache keys for different data types
CACHE_KEY_ENDPOINTS = "portainer_endpoints"
CACHE_KEY_CONTAINERS = "portainer_containers"
CACHE_KEY_CONTAINERS_STOPPED = "portainer_containers_stopped"
CACHE_KEY_STACKS = "portainer_stacks"


@dataclass
class CachedData:
    """Container for cached Portainer data with metadata."""

    data: list[dict[str, Any]]
    refreshed_at: float | None = None
    from_cache: bool = False


class PortainerCacheService:
    """Service for caching Portainer API data."""

    def __init__(self) -> None:
        self._refresh_lock = asyncio.Lock()
        self._last_refresh: float | None = None

    async def get_endpoints(self, *, force_refresh: bool = False) -> CachedData:
        """Get endpoints with caching."""
        if not force_refresh and is_cache_enabled():
            entry = load_cache_entry(CACHE_KEY_ENDPOINTS)
            if entry and not entry.is_expired:
                endpoints = entry.payload.get("endpoints", [])
                return CachedData(
                    data=endpoints,
                    refreshed_at=entry.refreshed_at,
                    from_cache=True,
                )

        # Fetch fresh data
        endpoints = await self._fetch_endpoints()
        if is_cache_enabled() and endpoints:
            store_cache_entry(CACHE_KEY_ENDPOINTS, {"endpoints": endpoints})

        return CachedData(data=endpoints, refreshed_at=time.time(), from_cache=False)

    async def get_containers(
        self, *, include_stopped: bool = False, force_refresh: bool = False
    ) -> CachedData:
        """Get containers with caching."""
        cache_key = CACHE_KEY_CONTAINERS_STOPPED if include_stopped else CACHE_KEY_CONTAINERS

        if not force_refresh and is_cache_enabled():
            entry = load_cache_entry(cache_key)
            if entry and not entry.is_expired:
                containers = entry.payload.get("containers", [])
                return CachedData(
                    data=containers,
                    refreshed_at=entry.refreshed_at,
                    from_cache=True,
                )

        # Fetch fresh data
        containers = await self._fetch_containers(include_stopped=include_stopped)
        if is_cache_enabled() and containers:
            store_cache_entry(cache_key, {"containers": containers})

        return CachedData(data=containers, refreshed_at=time.time(), from_cache=False)

    async def get_stacks(self, *, force_refresh: bool = False) -> CachedData:
        """Get stacks with caching."""
        if not force_refresh and is_cache_enabled():
            entry = load_cache_entry(CACHE_KEY_STACKS)
            if entry and not entry.is_expired:
                stacks = entry.payload.get("stacks", [])
                return CachedData(
                    data=stacks,
                    refreshed_at=entry.refreshed_at,
                    from_cache=True,
                )

        # Fetch fresh data
        stacks = await self._fetch_stacks()
        if is_cache_enabled() and stacks:
            store_cache_entry(CACHE_KEY_STACKS, {"stacks": stacks})

        return CachedData(data=stacks, refreshed_at=time.time(), from_cache=False)

    async def warm_cache(self) -> dict[str, bool]:
        """Pre-fetch all data and warm the cache.

        Returns a dict indicating which caches were warmed successfully.
        """
        results = {
            "endpoints": False,
            "containers": False,
            "containers_stopped": False,
            "stacks": False,
        }

        async with self._refresh_lock:
            LOGGER.info("Warming Portainer cache...")
            start_time = time.time()

            try:
                endpoints_data = await self.get_endpoints(force_refresh=True)
                results["endpoints"] = len(endpoints_data.data) > 0
                LOGGER.info("Cached %d endpoints", len(endpoints_data.data))
            except Exception as exc:
                LOGGER.warning("Failed to warm endpoints cache: %s", exc)

            try:
                containers_data = await self.get_containers(
                    include_stopped=False, force_refresh=True
                )
                results["containers"] = len(containers_data.data) >= 0
                LOGGER.info("Cached %d running containers", len(containers_data.data))
            except Exception as exc:
                LOGGER.warning("Failed to warm containers cache: %s", exc)

            try:
                containers_stopped_data = await self.get_containers(
                    include_stopped=True, force_refresh=True
                )
                results["containers_stopped"] = len(containers_stopped_data.data) >= 0
                LOGGER.info(
                    "Cached %d containers (including stopped)",
                    len(containers_stopped_data.data),
                )
            except Exception as exc:
                LOGGER.warning("Failed to warm containers (stopped) cache: %s", exc)

            try:
                stacks_data = await self.get_stacks(force_refresh=True)
                results["stacks"] = len(stacks_data.data) >= 0
                LOGGER.info("Cached %d stacks", len(stacks_data.data))
            except Exception as exc:
                LOGGER.warning("Failed to warm stacks cache: %s", exc)

            self._last_refresh = time.time()
            elapsed = time.time() - start_time
            LOGGER.info("Cache warming completed in %.2f seconds", elapsed)

        return results

    async def refresh_cache(self) -> dict[str, bool]:
        """Refresh the cache in the background.

        This is identical to warm_cache but named for clarity when called
        from the scheduler.
        """
        return await self.warm_cache()

    async def _fetch_endpoints(self) -> list[dict[str, Any]]:
        """Fetch all endpoints from Portainer."""
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()

        if not environments:
            LOGGER.warning("No Portainer environments configured")
            return []

        all_endpoints: list[dict] = []

        for env in environments:
            client = create_portainer_client(env)
            try:
                async with client:
                    raw_endpoints = await client.list_all_endpoints()
                    all_endpoints.extend(raw_endpoints)
            except PortainerAPIError as exc:
                LOGGER.error("Failed to fetch endpoints from %s: %s", env.name, exc)
                continue

        # Use dict-based normalization (avoids pandas overhead)
        return normalise_endpoint_metadata_dict(all_endpoints)

    async def _fetch_containers(
        self, *, include_stopped: bool = False
    ) -> list[dict[str, Any]]:
        """Fetch all containers from Portainer with parallel endpoint fetching."""
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()

        if not environments:
            return []

        all_endpoints: list[dict] = []
        containers_by_endpoint: dict[int, list[dict]] = {}

        for env in environments:
            client = create_portainer_client(env)
            try:
                async with client:
                    endpoints = await client.list_all_endpoints()
                    all_endpoints.extend(endpoints)

                    # Parallel fetch containers for all endpoints
                    async def fetch_containers_for_endpoint(ep: dict) -> tuple[int, list[dict]]:
                        ep_id = int(ep.get("Id") or ep.get("id") or 0)
                        try:
                            containers = await client.list_containers_for_endpoint(
                                ep_id, include_stopped=include_stopped
                            )
                            return ep_id, containers
                        except PortainerAPIError as exc:
                            LOGGER.debug(
                                "Failed to fetch containers for endpoint %d: %s",
                                ep_id,
                                exc,
                            )
                            return ep_id, []

                    # Fetch containers in parallel using asyncio.gather
                    results = await asyncio.gather(
                        *[fetch_containers_for_endpoint(ep) for ep in endpoints],
                        return_exceptions=True
                    )

                    for result in results:
                        if isinstance(result, Exception):
                            LOGGER.debug("Container fetch error: %s", result)
                            continue
                        ep_id, containers = result
                        containers_by_endpoint[ep_id] = containers

            except PortainerAPIError as exc:
                LOGGER.error("Failed to fetch from %s: %s", env.name, exc)
                continue

        # Use dict-based normalization (avoids pandas overhead)
        return normalise_endpoint_containers_dict(all_endpoints, containers_by_endpoint)

    async def _fetch_stacks(self) -> list[dict[str, Any]]:
        """Fetch all stacks from Portainer with parallel endpoint fetching."""
        settings = get_settings()
        environments = settings.portainer.get_configured_environments()

        if not environments:
            return []

        all_endpoints: list[dict] = []
        stacks_by_endpoint: dict[int, list[dict]] = {}

        for env in environments:
            client = create_portainer_client(env)
            try:
                async with client:
                    endpoints = await client.list_all_endpoints()
                    all_endpoints.extend(endpoints)

                    # Parallel fetch stacks for all endpoints
                    async def fetch_stacks_for_endpoint(ep: dict) -> tuple[int, list[dict]]:
                        ep_id = int(ep.get("Id") or ep.get("id") or 0)
                        try:
                            stacks = await client.list_stacks_for_endpoint(ep_id)
                            return ep_id, stacks
                        except PortainerAPIError as exc:
                            LOGGER.debug(
                                "Failed to fetch stacks for endpoint %d: %s",
                                ep_id,
                                exc,
                            )
                            return ep_id, []

                    # Fetch stacks in parallel using asyncio.gather
                    results = await asyncio.gather(
                        *[fetch_stacks_for_endpoint(ep) for ep in endpoints],
                        return_exceptions=True
                    )

                    for result in results:
                        if isinstance(result, Exception):
                            LOGGER.debug("Stack fetch error: %s", result)
                            continue
                        ep_id, stacks = result
                        stacks_by_endpoint[ep_id] = stacks

            except PortainerAPIError as exc:
                LOGGER.error("Failed to fetch from %s: %s", env.name, exc)
                continue

        # Use dict-based normalization (avoids pandas overhead)
        return normalise_endpoint_stacks_dict(all_endpoints, stacks_by_endpoint)


# Singleton instance
_cache_service: PortainerCacheService | None = None


def get_cache_service() -> PortainerCacheService:
    """Get the singleton cache service instance."""
    global _cache_service
    if _cache_service is None:
        _cache_service = PortainerCacheService()
    return _cache_service


__all__ = [
    "CachedData",
    "PortainerCacheService",
    "get_cache_service",
]
