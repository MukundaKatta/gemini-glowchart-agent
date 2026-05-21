"""Perfect Corp YouCam S2S auth.

Two credential modes are supported:

1. Long-lived bearer token (most paygo / hackathon redemptions). The
   value of PERFECT_CORP_API_KEY is sent directly as
   `Authorization: Bearer ${key}`. No RSA handshake needed. Detected
   by calling `/s2s/v1.0/client/credit` once on first use.

2. Client-id + RSA-PKCS1v15 handshake (legacy / enterprise tenants).
   The api key is used as `client_id` and a short-lived access token
   is fetched from `/s2s/v1.0/client/auth` by RSA-encrypting
   `f"{api_key}_{timestamp_ms}"` with the tenant public key. Cached
   in-process until 5 minutes before server-side expiry.

The first call probes mode 1; if that returns 200 the key is used as a
bearer token from then on. Otherwise we fall through to mode 2.

Credentials come from env vars only; the public key (mode 2) is
base64-DER and loaded via `serialization.load_der_public_key`.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


DEFAULT_API_HOST = "https://yce-api-01.makeupar.com"
_AUTH_PATH = "/s2s/v1.0/client/auth"
_CREDIT_PATH = "/s2s/v1.0/client/credit"
# Re-auth a bit before the server-side expiry so tokens never expire mid-request.
_EXPIRY_GUARD_SECS = 5 * 60


@dataclass
class _CachedToken:
    access_token: str
    # Epoch seconds (monotonic) after which the token must be refreshed.
    # For mode 1 (long-lived bearer) this is +inf so we never re-auth.
    refresh_after: float


_lock = threading.Lock()
_cached: _CachedToken | None = None
# Whether we've decided this key is a long-lived bearer. None means unknown.
_is_bearer_key: bool | None = None


def _api_host() -> str:
    return os.environ.get("GLOWCHART_API_HOST", DEFAULT_API_HOST)


def _encrypt_id_token(api_key: str, public_key_b64: str, timestamp_ms: int) -> str:
    """Return the base64-encoded RSA-PKCS1v15 ciphertext of the payload.

    Kept in its own function so tests can supply a known timestamp and
    public key without going through the env-var dance.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    der_bytes = base64.b64decode(public_key_b64)
    public_key = serialization.load_der_public_key(der_bytes)
    payload = f"{api_key}_{timestamp_ms}".encode("ascii")
    ciphertext = public_key.encrypt(payload, padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode("ascii")


def _parse_expires_at(raw: Any) -> float:
    """Best-effort parse of the API's expires_at into a monotonic deadline.

    The API has shipped this as either an ISO-8601 string or epoch ms in
    different versions. Whichever we get, return a monotonic deadline
    minus the safety guard.
    """
    now_mono = time.monotonic()
    if isinstance(raw, (int, float)):
        # Epoch seconds vs epoch ms heuristic: anything > 10^12 is ms.
        epoch = float(raw) / 1000.0 if raw > 1e12 else float(raw)
        delta = max(0.0, epoch - time.time())
        return now_mono + delta - _EXPIRY_GUARD_SECS
    if isinstance(raw, str) and raw:
        try:
            # Tolerate trailing Z.
            iso = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = max(0.0, dt.timestamp() - time.time())
            return now_mono + delta - _EXPIRY_GUARD_SECS
        except ValueError:
            pass
    # Default to a conservative 30-min cache if the response shape is unknown.
    return now_mono + (30 * 60) - _EXPIRY_GUARD_SECS


def reset_token_cache() -> None:
    """Drop the cached token + mode detection. Used by tests and after a 401."""
    global _cached, _is_bearer_key
    with _lock:
        _cached = None
        _is_bearer_key = None


def _probe_bearer_mode(api_key: str) -> bool:
    """Return True if the api_key works as a direct bearer token.

    Cheapest signal we have: a GET on /s2s/v1.0/client/credit that
    returns 200 means the server accepts the key as-is.
    """
    import requests  # noqa: E402

    try:
        r = requests.get(
            f"{_api_host()}{_CREDIT_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _rsa_handshake(api_key: str) -> _CachedToken:
    """Run the client_id + RSA-PKCS1v15 auth handshake. Returns the
    minted access token with parsed expiry."""
    public_key_b64 = os.environ.get("PERFECT_CORP_PUBLIC_KEY_B64", "")
    if not public_key_b64:
        raise RuntimeError(
            "PERFECT_CORP_PUBLIC_KEY_B64 not set and key is not a bearer token. "
            "Provide the tenant public key for the RSA handshake."
        )

    import requests  # noqa: E402

    timestamp_ms = int(time.time() * 1000)
    id_token = _encrypt_id_token(api_key, public_key_b64, timestamp_ms)
    url = f"{_api_host()}{_AUTH_PATH}"
    r = requests.post(
        url,
        json={"client_id": api_key, "id_token": id_token},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    body = r.json()
    result = body.get("result") or {}
    access_token = result.get("access_token") or ""
    if not access_token:
        raise RuntimeError(f"auth response missing access_token: {body}")
    refresh_after = _parse_expires_at(result.get("expires_at"))
    return _CachedToken(access_token=access_token, refresh_after=refresh_after)


def get_access_token(force_refresh: bool = False) -> str:
    """Return a Bearer token for the YouCam API, re-authing as needed.

    Reads PERFECT_CORP_API_KEY (required) and, for the RSA handshake
    mode, PERFECT_CORP_PUBLIC_KEY_B64. Raises RuntimeError if the api
    key is missing.
    """
    global _cached, _is_bearer_key
    with _lock:
        if (
            not force_refresh
            and _cached is not None
            and time.monotonic() < _cached.refresh_after
        ):
            return _cached.access_token

    api_key = os.environ.get("PERFECT_CORP_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "PERFECT_CORP_API_KEY must be set for real-mode (GLOWCHART_STUB=0) calls."
        )

    # Mode detection (first call only). If the key passes a credit-check
    # as a direct bearer, treat it as long-lived; otherwise fall back to
    # the RSA handshake.
    with _lock:
        bearer = _is_bearer_key
    if bearer is None:
        bearer = _probe_bearer_mode(api_key)
        with _lock:
            _is_bearer_key = bearer

    if bearer:
        # Long-lived. Cache effectively forever; the credit-check on next
        # use will catch a revocation.
        token_obj = _CachedToken(access_token=api_key, refresh_after=float("inf"))
    else:
        token_obj = _rsa_handshake(api_key)

    with _lock:
        _cached = token_obj
    return token_obj.access_token
