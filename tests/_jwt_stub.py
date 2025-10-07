"""Minimal PyJWT stub used for local testing when the dependency is absent."""
"""Minimal JWT test stub used when PyJWT is unavailable.

This module mirrors the subset of the :mod:`PyJWT` API that our unit tests
exercise. It intentionally keeps the implementation lightweight and is only
loaded from :mod:`tests.conftest` when the real dependency cannot be imported.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import sys
import time
from types import SimpleNamespace
from typing import Any, Iterable, Sequence

__all__ = [
    "InvalidTokenError",
    "InvalidSignatureError",
    "ExpiredSignatureError",
    "InvalidAudienceError",
    "InvalidIssuerError",
    "DecodeError",
    "encode",
    "decode",
    "get_unverified_header",
    "algorithms",
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "InvalidTokenError",
    "DecodeError",
    "ExpiredSignatureError",
    "InvalidSignatureError",
    "InvalidAudienceError",
    "InvalidIssuerError",
    "MissingRequiredClaimError",
    "algorithms",
    "encode",
    "decode",
    "get_unverified_header",
]


class InvalidTokenError(Exception):
    """Base class for token validation errors."""
    """Base exception raised when a JWT cannot be processed."""


class DecodeError(InvalidTokenError):
    """Raised when a token cannot be decoded."""


class InvalidSignatureError(InvalidTokenError):
    """Raised when the signature check fails."""


class ExpiredSignatureError(InvalidTokenError):
    """Raised when the token's ``exp`` claim is in the past."""


class InvalidAudienceError(InvalidTokenError):
    """Raised when the ``aud`` claim does not match the expected audience."""


class InvalidIssuerError(InvalidTokenError):
    """Raised when the ``iss`` claim does not match the expected issuer."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(data + padding)
    except (ValueError, binascii.Error) as exc:
        raise DecodeError("Invalid base64url encoding") from exc


class _HS256Algorithm:
    name = "HS256"

    def prepare_key(self, key: str | bytes) -> bytes:
        if isinstance(key, bytes):
            return key
        if isinstance(key, str):
            return key.encode("utf-8")
        raise TypeError("Keys must be str or bytes")

    def sign(self, msg: bytes, key: str | bytes) -> bytes:
        prepared = self.prepare_key(key)
        return hmac.new(prepared, msg, hashlib.sha256).digest()

    def verify(self, msg: bytes, key: str | bytes, signature: bytes) -> bool:
        expected = self.sign(msg, key)
        return hmac.compare_digest(expected, signature)

    def from_jwk(self, jwk_json: str) -> bytes:
        try:
            payload = json.loads(jwk_json)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            raise InvalidTokenError("JWK payload was not valid JSON") from exc
        if payload.get("kty") != "oct":
            raise InvalidTokenError("Only symmetric octet JWKs are supported")
        key_material = payload.get("k")
        if not isinstance(key_material, str):
            raise InvalidTokenError("JWK payload missing key material")
        return _b64url_decode(key_material)


_HS256 = _HS256Algorithm()


class _AlgorithmsNamespace(SimpleNamespace):
    def get_default_algorithms(self) -> dict[str, _HS256Algorithm]:
        return {"HS256": _HS256}


algorithms = _AlgorithmsNamespace()


def _normalise_algorithms(raw: Iterable[str] | None) -> set[str]:
    if raw is None:
        return {"HS256"}
    if isinstance(raw, str):
        return {raw}
    return {str(value) for value in raw}


def _require_required_claims(payload: dict[str, Any], required: Sequence[str]) -> None:
    for claim in required:
        if claim not in payload:
            raise InvalidTokenError(f"Token missing required claim: {claim}")


def get_unverified_header(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise DecodeError("Not enough segments")
    header_segment = parts[0]
    try:
        header_payload = _b64url_decode(header_segment)
        return json.loads(header_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecodeError("Invalid token header") from exc


def encode(
    payload: dict[str, Any],
    key: str | bytes,
    algorithm: str = "HS256",
    headers: dict[str, Any] | None = None,
) -> str:
    if algorithm != "HS256":
        raise InvalidTokenError(f"Unsupported algorithm: {algorithm}")
    header = {"alg": algorithm, "typ": "JWT"}
    if headers:
        header.update(headers)
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_segment = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = _HS256.sign(signing_input, key)
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"
class ExpiredSignatureError(InvalidTokenError):
    """Raised when the token has expired."""


class InvalidSignatureError(InvalidTokenError):
    """Raised when the signature is invalid."""


class InvalidAudienceError(InvalidTokenError):
    """Raised when the audience claim does not match expectations."""


class InvalidIssuerError(InvalidTokenError):
    """Raised when the issuer claim does not match expectations."""


class MissingRequiredClaimError(InvalidTokenError):
    """Raised when required claims are missing from the token."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padded = data + "=" * ((4 - len(data) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (ValueError, binascii.Error) as exc:  # pragma: no cover - defensive
        raise DecodeError("Token segment was not valid base64url") from exc


def _json_load(data: str) -> Any:
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise DecodeError("Token segment did not contain valid JSON") from exc


def _to_bytes(value: bytes | str) -> bytes:
    return value if isinstance(value, bytes) else value.encode("utf-8")


def _sign(message: bytes, key: bytes, algorithm: str) -> bytes:
    if algorithm != "HS256":
        raise InvalidTokenError(f"Unsupported algorithm: {algorithm}")
    return hmac.new(key, message, hashlib.sha256).digest()


def _build_segments(payload: Mapping[str, Any], *, headers: Mapping[str, Any]) -> tuple[str, str, bytes]:
    header = {"typ": "JWT", "alg": headers.get("alg", "HS256")}
    header.update(headers)
    header_segment = _b64encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_segment = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    return header_segment, payload_segment, signing_input


def encode(
    payload: Mapping[str, Any],
    key: str | bytes,
    algorithm: str = "HS256",
    *,
    headers: Mapping[str, Any] | None = None,
) -> str:
    """Return a signed JWT token."""

    headers = dict(headers or {})
    headers.setdefault("alg", algorithm)
    header_segment, payload_segment, signing_input = _build_segments(payload, headers=headers)
    signature = _sign(signing_input, _to_bytes(key), headers["alg"])
    return f"{header_segment}.{payload_segment}.{_b64encode(signature)}"


def get_unverified_header(token: str) -> Mapping[str, Any]:
    """Return the decoded JWT header without verifying the signature."""

    parts = token.split(".")
    if len(parts) != 3:
        raise DecodeError("Token structure is invalid")
    return _json_load(_b64decode(parts[0]).decode("utf-8"))


def _ensure_required_claims(payload: Mapping[str, Any], required: Iterable[str]) -> None:
    missing = [claim for claim in required if claim not in payload]
    if missing:
        raise MissingRequiredClaimError(f"Missing required claims: {', '.join(sorted(missing))}")


def _validate_audience(payload: Mapping[str, Any], audience: str | Sequence[str] | None) -> None:
    if audience is None:
        return
    claim = payload.get("aud")
    expected = {audience} if isinstance(audience, str) else set(audience)
    if isinstance(claim, str):
        claims = {claim}
    elif isinstance(claim, Sequence):
        claims = set(claim)
    else:
        raise InvalidAudienceError("Audience claim is not a string or sequence")
    if not expected.intersection(claims):
        raise InvalidAudienceError("Audience claim did not match expected value")


def _validate_issuer(payload: Mapping[str, Any], issuer: str | None) -> None:
    if issuer is None:
        return
    claim = payload.get("iss")
    if claim != issuer:
        raise InvalidIssuerError("Issuer claim did not match expected value")


def _validate_expiration(payload: Mapping[str, Any]) -> None:
    exp = payload.get("exp")
    if exp is None:
        return
    try:
        expiry = float(exp)
    except (TypeError, ValueError) as exc:
        raise DecodeError("Expiration claim was not a number") from exc
    if expiry <= time.time():
        raise ExpiredSignatureError("Token has expired")


def decode(
    token: str,
    key: str | bytes,
    *,
    algorithms: Iterable[str] | None = None,
    audience: str | None = None,
    issuer: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise DecodeError("Not enough segments")
    header_segment, payload_segment, signature_segment = parts

    header = get_unverified_header(token)
    allowed = _normalise_algorithms(algorithms)
    algorithm_name = header.get("alg")
    if not isinstance(algorithm_name, str) or algorithm_name not in allowed:
        raise InvalidTokenError("Algorithm not allowed")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = _b64url_decode(signature_segment)
    if not _HS256.verify(signing_input, key, signature):
        raise InvalidSignatureError("Signature verification failed")

    try:
        payload_bytes = _b64url_decode(payload_segment)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecodeError("Invalid token payload") from exc

    required = options.get("require", []) if options else []
    _require_required_claims(payload, required)

    exp = payload.get("exp")
    if exp is not None:
        try:
            expires_at = float(exp)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
            raise InvalidTokenError("Invalid exp claim") from exc
        if time.time() > expires_at:
            raise ExpiredSignatureError("Token has expired")

    if audience is not None:
        audience_claim = payload.get("aud")
        if isinstance(audience_claim, (list, tuple, set)):
            audiences = {str(item) for item in audience_claim}
            is_valid = str(audience) in audiences
        else:
            is_valid = audience_claim == audience
        if not is_valid:
            raise InvalidAudienceError("Audience validation failed")

    if issuer is not None and payload.get("iss") != issuer:
        raise InvalidIssuerError("Issuer validation failed")

    return payload


# Register the stub as ``jwt`` when imported via ``importlib``.
if __name__ == "jwt":
    sys.modules.setdefault("jwt", sys.modules[__name__])
    algorithms: Sequence[str] | None = None,
    *,
    audience: str | Sequence[str] | None = None,
    issuer: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Verify a token signature and return the decoded payload."""

    options = options or {}
    parts = token.split(".")
    if len(parts) != 3:
        raise DecodeError("Token structure is invalid")

    header_segment, payload_segment, signature_segment = parts
    header = _json_load(_b64decode(header_segment).decode("utf-8"))
    payload = _json_load(_b64decode(payload_segment).decode("utf-8"))

    algorithm = header.get("alg")
    if not isinstance(algorithm, str):
        raise DecodeError("Token did not specify an algorithm")
    if algorithms is not None and algorithm not in algorithms:
        raise InvalidTokenError("Token algorithm is not allowed")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = _b64decode(signature_segment)
    expected = _sign(signing_input, _to_bytes(key), algorithm)
    if not hmac.compare_digest(signature, expected):
        raise InvalidSignatureError("Token signature mismatch")

    _ensure_required_claims(payload, options.get("require", []))
    _validate_audience(payload, audience)
    _validate_issuer(payload, issuer)
    _validate_expiration(payload)

    return payload


@dataclass
class _HS256Algorithm:
    """Minimal representation of the HS256 algorithm for compatibility."""

    name: str = "HS256"

    def from_jwk(self, jwk_json: str) -> bytes:
        data = json.loads(jwk_json)
        key = data.get("k")
        if not isinstance(key, str):
            raise DecodeError("JWK did not provide a symmetric key")
        return _b64decode(key)


class _AlgorithmRegistry:
    def __init__(self) -> None:
        self._algorithms = {"HS256": _HS256Algorithm()}

    def get_default_algorithms(self) -> dict[str, _HS256Algorithm]:
        return dict(self._algorithms)


algorithms = _AlgorithmRegistry()
