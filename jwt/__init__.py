"""Lightweight fallback implementation for the :mod:`jwt` API.

This module provides just enough functionality for the test suite and the
application to operate in environments where the optional PyJWT dependency is
not installed.  It supports HS256 signed tokens – the only algorithm exercised
in the tests – along with the minimal helpers used by :mod:`app.auth`.

If PyJWT is available in the execution environment it should be installed and
will take precedence over this compatibility shim.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "InvalidTokenError",
    "algorithms",
    "decode",
    "encode",
    "get_unverified_header",
]


class InvalidTokenError(Exception):
    """Raised when a token fails validation."""


def _base64url_encode(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(data).decode("ascii")
    return encoded.rstrip("=")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _to_bytes(value: str | bytes) -> bytes:
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


def encode(
    payload: Mapping[str, Any],
    key: str | bytes,
    *,
    algorithm: str = "HS256",
    headers: Mapping[str, Any] | None = None,
) -> str:
    """Return a signed JWT for ``payload`` using the provided ``key``."""

    if algorithm != "HS256":
        raise InvalidTokenError(f"Unsupported signing algorithm: {algorithm}.")

    header = {"alg": algorithm, "typ": "JWT"}
    if headers:
        header.update(headers)

    header_segment = _base64url_encode(_json_dumps(header))
    payload_segment = _base64url_encode(_json_dumps(payload))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")

    signature = hmac.new(_to_bytes(key), signing_input, hashlib.sha256).digest()
    signature_segment = _base64url_encode(signature)
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def get_unverified_header(token: str) -> dict[str, Any]:
    """Return the JWT header without validating the signature."""

    try:
        header_segment = token.split(".", 1)[0]
    except ValueError as exc:  # pragma: no cover - defensive
        raise InvalidTokenError("Token structure is invalid.") from exc

    try:
        header_bytes = _base64url_decode(header_segment)
        return json.loads(header_bytes.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("Token header is not valid JSON.") from exc


def _validate_required_claims(payload: Mapping[str, Any], required: Iterable[str]) -> None:
    for claim in required:
        if claim not in payload:
            raise InvalidTokenError(f"Missing required claim: {claim}.")


def _validate_audience(payload: Mapping[str, Any], audience: str | None) -> None:
    if audience is None:
        return
    aud = payload.get("aud")
    if aud is None:
        raise InvalidTokenError("Token is missing the required audience claim.")
    if isinstance(aud, Sequence) and not isinstance(aud, (str, bytes)):
        if audience not in aud:
            raise InvalidTokenError("Token audience does not match the expected value.")
        return
    if aud != audience:
        raise InvalidTokenError("Token audience does not match the expected value.")


def _validate_issuer(payload: Mapping[str, Any], issuer: str | None) -> None:
    if issuer is None:
        return
    if payload.get("iss") != issuer:
        raise InvalidTokenError("Token issuer does not match the expected value.")


def _validate_timestamp_claim(payload: Mapping[str, Any], claim: str, *, now: float) -> None:
    value = payload.get(claim)
    if value is None:
        return
    try:
        timestamp = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError(f"Token claim '{claim}' is not a valid timestamp.") from exc
    if claim == "exp" and timestamp < now:
        raise InvalidTokenError("Token has expired.")
    if claim == "nbf" and timestamp > now:
        raise InvalidTokenError("Token is not yet valid.")


def decode(
    token: str,
    key: str | bytes,
    *,
    algorithms: Sequence[str] | None = None,
    audience: str | None = None,
    issuer: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate ``token`` and return the decoded payload."""

    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise InvalidTokenError("Token structure is invalid.") from exc

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")

    try:
        header_bytes = _base64url_decode(header_segment)
        payload_bytes = _base64url_decode(payload_segment)
        signature = _base64url_decode(signature_segment)
    except ValueError as exc:
        raise InvalidTokenError("Token segments are not valid base64.") from exc

    try:
        header = json.loads(header_bytes.decode("utf-8"))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidTokenError("Token segments are not valid JSON.") from exc

    algorithm = header.get("alg")
    if not isinstance(algorithm, str):
        raise InvalidTokenError("Token header does not specify an algorithm.")

    allowed_algorithms = list(algorithms or [])
    if allowed_algorithms and algorithm not in allowed_algorithms:
        raise InvalidTokenError("Token was signed with an unexpected algorithm.")

    if algorithm != "HS256":
        raise InvalidTokenError(f"Unsupported signing algorithm: {algorithm}.")

    expected_signature = hmac.new(_to_bytes(key), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_signature, signature):
        raise InvalidTokenError("Signature verification failed.")

    now = time.time()
    _validate_timestamp_claim(payload, "exp", now=now)
    _validate_timestamp_claim(payload, "nbf", now=now)

    if options:
        required = options.get("require")
        if required:
            _validate_required_claims(payload, required)

    _validate_audience(payload, audience)
    _validate_issuer(payload, issuer)

    return payload


@dataclass(frozen=True)
class _HMACAlgorithm:
    name: str = "HS256"

    def from_jwk(self, jwk_json: str) -> bytes:
        try:
            data = json.loads(jwk_json)
        except json.JSONDecodeError as exc:
            raise InvalidTokenError("JWK is not valid JSON.") from exc

        if data.get("kty") != "oct":
            raise InvalidTokenError("Unsupported JWK key type.")

        key_value = data.get("k")
        if not isinstance(key_value, str) or not key_value:
            raise InvalidTokenError("JWK is missing the symmetric key value.")

        try:
            return _base64url_decode(key_value)
        except ValueError as exc:
            raise InvalidTokenError("JWK contained an invalid key value.") from exc


class _AlgorithmsModule:
    _default_algorithms: dict[str, _HMACAlgorithm]

    def __init__(self) -> None:
        self._default_algorithms = {"HS256": _HMACAlgorithm()}

    def get_default_algorithms(self) -> dict[str, _HMACAlgorithm]:
        return dict(self._default_algorithms)


algorithms = _AlgorithmsModule()
