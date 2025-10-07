"""Minimal JWT implementation used when PyJWT is unavailable."""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import sys
import time
from types import ModuleType
from typing import Any, Iterable, Mapping, MutableMapping

__all__ = ["install_jwt_stub"]


def install_jwt_stub() -> ModuleType:
    """Install a lightweight JWT module into :data:`sys.modules`."""

    module = ModuleType("jwt")
    module.__spec__ = importlib.util.spec_from_loader("jwt", loader=None)
    module.__package__ = "jwt"

    class InvalidTokenError(Exception):
        """Base exception raised for JWT validation errors."""

    class ExpiredSignatureError(InvalidTokenError):
        """Raised when a token expiration has passed."""

    class DecodeError(InvalidTokenError):
        """Raised when the token structure or payload is invalid."""

    class InvalidAlgorithmError(InvalidTokenError):
        """Raised when attempting to use an unsupported signing algorithm."""

    class MissingRequiredClaimError(InvalidTokenError):
        """Raised when required claims are absent during validation."""

    def _b64_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64_decode(segment: str) -> bytes:
        padding = "=" * (-len(segment) % 4)
        return base64.urlsafe_b64decode(segment + padding)

    def _to_bytes(value: str | bytes) -> bytes:
        return value if isinstance(value, bytes) else value.encode("utf-8")

    def _sign(message: bytes, key: str | bytes, algorithm: str) -> bytes:
        if algorithm != "HS256":
            raise InvalidAlgorithmError(f"Unsupported signing algorithm: {algorithm}")
        return hmac.new(_to_bytes(key), message, hashlib.sha256).digest()

    def get_unverified_header(token: str) -> Mapping[str, Any]:
        try:
            header_segment, _, _ = token.split(".")
        except ValueError as exc:
            raise DecodeError("JWT must contain header.payload.signature segments") from exc
        try:
            return json.loads(_b64_decode(header_segment))
        except (json.JSONDecodeError, ValueError) as exc:
            raise DecodeError("JWT header was not valid JSON") from exc

    def encode(
        payload: Mapping[str, Any],
        key: str | bytes,
        algorithm: str = "HS256",
        headers: MutableMapping[str, Any] | None = None,
    ) -> str:
        header: dict[str, Any] = {"alg": algorithm, "typ": "JWT"}
        if headers:
            header.update(headers)
        header_segment = _b64_encode(
            json.dumps(header, separators=(",", ":")).encode("utf-8")
        )
        payload_segment = _b64_encode(
            json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
        signature = _b64_encode(_sign(signing_input, key, algorithm))
        return f"{header_segment}.{payload_segment}.{signature}"

    def decode(
        token: str,
        key: str | bytes,
        algorithms: Iterable[str] | None = None,
        *,
        audience: str | Iterable[str] | None = None,
        issuer: str | None = None,
        options: Mapping[str, Iterable[str]] | None = None,
    ) -> dict[str, Any]:
        try:
            header_segment, payload_segment, signature_segment = token.split(".")
        except ValueError as exc:
            raise DecodeError("JWT must have exactly three segments") from exc

        header = json.loads(_b64_decode(header_segment))
        payload = json.loads(_b64_decode(payload_segment))
        algorithm = header.get("alg")
        if not isinstance(algorithm, str):
            raise InvalidAlgorithmError("JWT header did not declare an algorithm")
        if algorithms is not None and algorithm not in set(algorithms):
            raise InvalidAlgorithmError(f"Unsupported signing algorithm: {algorithm}")

        expected_signature = _b64_encode(
            _sign(f"{header_segment}.{payload_segment}".encode("ascii"), key, algorithm)
        )
        if not hmac.compare_digest(signature_segment, expected_signature):
            raise InvalidTokenError("JWT signature verification failed")

        required_claims = set(options.get("require", [])) if options else set()
        missing_claims = [claim for claim in required_claims if claim not in payload]
        if missing_claims:
            raise MissingRequiredClaimError(
                f"JWT is missing required claims: {', '.join(missing_claims)}"
            )

        now = int(time.time())
        exp = payload.get("exp")
        if exp is not None and now > int(exp):
            raise ExpiredSignatureError("JWT has expired")

        if issuer is not None and payload.get("iss") != issuer:
            raise InvalidTokenError("JWT issuer did not match expected value")

        if audience is not None:
            audiences: tuple[str, ...]
            if isinstance(audience, str):
                audiences = (audience,)
            else:
                audiences = tuple(audience)
            if payload.get("aud") not in audiences:
                raise InvalidTokenError("JWT audience did not match expected value")

        return payload

    class _HS256Algorithm:
        name = "HS256"

        def from_jwk(self, jwk_json: str) -> bytes:
            try:
                jwk = json.loads(jwk_json)
            except json.JSONDecodeError as exc:
                raise DecodeError("JWK payload was not valid JSON") from exc
            if jwk.get("kty") != "oct":
                raise InvalidAlgorithmError("Only symmetric JWK keys are supported in tests")
            key_b64 = jwk.get("k")
            if not isinstance(key_b64, str):
                raise DecodeError("JWK did not include a symmetric key")
            return _b64_decode(key_b64)

    class _AlgorithmRegistry:
        def __init__(self) -> None:
            self._algorithms = {"HS256": _HS256Algorithm()}

        def get_default_algorithms(self) -> dict[str, _HS256Algorithm]:
            return dict(self._algorithms)

    module.InvalidTokenError = InvalidTokenError
    module.ExpiredSignatureError = ExpiredSignatureError
    module.DecodeError = DecodeError
    module.InvalidAlgorithmError = InvalidAlgorithmError
    module.MissingRequiredClaimError = MissingRequiredClaimError
    module.encode = encode
    module.decode = decode
    module.get_unverified_header = get_unverified_header
    module.algorithms = _AlgorithmRegistry()
    module.__all__ = [
        "InvalidTokenError",
        "ExpiredSignatureError",
        "DecodeError",
        "InvalidAlgorithmError",
        "MissingRequiredClaimError",
        "encode",
        "decode",
        "get_unverified_header",
        "algorithms",
    ]

    sys.modules[module.__name__] = module
    return module

