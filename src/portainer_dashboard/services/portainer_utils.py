"""Internal utility functions for Portainer data processing."""

from __future__ import annotations


def _coerce_int(value: object) -> int | None:
    """Return value as an integer when possible."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


def _first_present(mapping: dict[str, object], *keys: str) -> object:
    """Return the first value present for keys in mapping."""
    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _stack_targets_endpoint(stack: dict[str, object], endpoint_id: int) -> bool:
    """Return True when a stack is assigned to the provided endpoint."""
    endpoint_keys = ("EndpointId", "EndpointID", "endpointId", "endpointID")
    for key in endpoint_keys:
        if key not in stack:
            continue
        coerced = _coerce_int(stack.get(key))
        if coerced is None:
            continue
        if coerced == endpoint_id:
            return True

    deployment_info = stack.get("DeploymentInfo") or stack.get("deploymentInfo")
    if isinstance(deployment_info, dict):
        str_endpoint_id = str(endpoint_id)
        if str_endpoint_id in {str(key) for key in deployment_info.keys()}:
            return True
        for info in deployment_info.values():
            if not isinstance(info, dict):
                continue
            for key in endpoint_keys:
                if key not in info:
                    continue
                coerced = _coerce_int(info.get(key))
                if coerced is None:
                    continue
                if coerced == endpoint_id:
                    return True

    return False


def _stack_has_endpoint_metadata(stack: dict[str, object]) -> bool:
    """Return True when the stack embeds any endpoint assignment metadata."""
    endpoint_keys = ("EndpointId", "EndpointID", "endpointId", "endpointID")
    for key in endpoint_keys:
        if key not in stack:
            continue
        coerced = _coerce_int(stack.get(key))
        if coerced is None:
            continue
        return True

    deployment_info = stack.get("DeploymentInfo") or stack.get("deploymentInfo")
    if isinstance(deployment_info, dict):
        if any(_coerce_int(key) is not None for key in deployment_info.keys()):
            return True
        for info in deployment_info.values():
            if not isinstance(info, dict):
                continue
            for key in endpoint_keys:
                if key not in info:
                    continue
                coerced = _coerce_int(info.get(key))
                if coerced is None:
                    continue
                return True

    return False


__all__ = [
    "_coerce_int",
    "_first_present",
    "_stack_targets_endpoint",
    "_stack_has_endpoint_metadata",
]
