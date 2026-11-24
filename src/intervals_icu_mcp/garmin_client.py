"""Async client for the Garmin Connect Personal API.

Garmin's Personal API gives one person read-only access to their own Garmin
Connect data with a self-issued key. The key is never sent to the data
endpoints: it is exchanged for a short-lived bearer token (a JWT valid for 24
hours or until the key expires, with no refresh tokens), and the token is what
authorizes each request.

The flow mirrors Garmin's own reference client, garmin/connect-personal-api-python
(Apache-2.0): ``POST`` the token path with ``Authorization: ApiKey <key>``; the
response body is the raw JWT; read its ``exp`` claim; refresh an hour early.
This module differs in two ways that suit a long-running server: it is async
(httpx, like the Intervals.icu client) and it caches the token in memory only,
never on disk.

Docs: https://developer.garmin.com/gc-developer-program/personal/personal-api/
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .auth import ICUConfig

TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"

# Refresh a cached token when it has less than this long left, as Garmin's
# reference client does, so a request never races an expiring token.
TOKEN_REFRESH_WINDOW_SECONDS = 60 * 60

# If a token's expiry cannot be read, assume a little under the documented
# 24-hour lifetime rather than failing.
FALLBACK_TOKEN_LIFETIME_SECONDS = 23 * 60 * 60

REQUEST_TIMEOUT_SECONDS = 30.0


class GarminAPIError(Exception):
    """An error from the Garmin Personal API, or from using it."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True)
class _Token:
    access_token: str = field(repr=False)
    expires_at: float


# In-memory token cache shared by every request in this process, keyed by a
# fingerprint of the base URL and key so a rotated key never reuses an old token.
_token_cache: dict[str, _Token] = {}
_token_locks: dict[int, asyncio.Lock] = {}


def _token_lock() -> asyncio.Lock:
    """One lock per event loop, so concurrent tool calls share one token exchange."""
    loop_id = id(asyncio.get_running_loop())
    lock = _token_locks.get(loop_id)
    if lock is None:
        lock = _token_locks[loop_id] = asyncio.Lock()
    return lock


def clear_token_cache() -> None:
    """Forget every cached token (used by tests and after a 401)."""
    _token_cache.clear()


def _fingerprint(base_url: str, api_key: str) -> str:
    return hashlib.sha256(f"{base_url}\0{api_key}".encode()).hexdigest()


def _jwt_expiration(access_token: str) -> float | None:
    """Return the JWT ``exp`` claim without verifying the signature, or None."""
    try:
        payload = access_token.split(".")[1]
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(decoded["exp"])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def _error_message(status_code: int, during: str) -> str:
    if status_code == 401:
        return (
            f"Garmin rejected the credentials during {during} (HTTP 401). The Personal API "
            "key may be revoked, expired, or mistyped; create a new key in Garmin Connect "
            "and update GARMIN_PERSONAL_API_KEY."
        )
    if status_code == 403:
        return f"Garmin refused access during {during} (HTTP 403)."
    if status_code == 404:
        return f"Garmin has no data for this request ({during}, HTTP 404)."
    if status_code == 429:
        return f"Garmin rate limit reached during {during} (HTTP 429). Try again shortly."
    if status_code >= 500:
        return f"Garmin server error during {during} (HTTP {status_code}). Try again later."
    return f"Garmin returned HTTP {status_code} during {during}."


class GarminClient:
    """Read-only async client for the Garmin Connect Personal API."""

    def __init__(self, config: ICUConfig):
        if not config.garmin_personal_api_key:
            raise GarminAPIError(
                "Garmin is not configured: set GARMIN_PERSONAL_API_KEY to a Garmin Connect "
                "Personal API key."
            )
        self._api_key = config.garmin_personal_api_key.strip()
        self.base_url = config.garmin_personal_api_base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GarminClient:
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=REQUEST_TIMEOUT_SECONDS)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GarminClient must be used as an async context manager")
        return self._client

    async def _token(self, *, force_refresh: bool = False) -> str:
        key = _fingerprint(self.base_url, self._api_key)
        async with _token_lock():
            cached = _token_cache.get(key)
            if (
                cached
                and not force_refresh
                and cached.expires_at - time.time() > TOKEN_REFRESH_WINDOW_SECONDS
            ):
                return cached.access_token
            try:
                response = await self._http.post(
                    TOKEN_PATH,
                    headers={"Accept": "*/*", "Authorization": f"ApiKey {self._api_key}"},
                )
            except httpx.HTTPError as e:
                raise GarminAPIError(f"Could not reach Garmin for a token: {e}") from e
            if not response.is_success:
                raise GarminAPIError(
                    _error_message(response.status_code, "the token exchange"),
                    response.status_code,
                )
            access_token = response.text.strip()
            if not access_token:
                raise GarminAPIError("Garmin's token endpoint returned an empty response.")
            expires_at = _jwt_expiration(access_token) or (
                time.time() + FALLBACK_TOKEN_LIFETIME_SECONDS
            )
            _token_cache[key] = _Token(access_token, expires_at)
            return access_token

    async def _get_response(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        for attempt in (1, 2):
            token = await self._token(force_refresh=attempt == 2)
            try:
                response = await self._http.get(
                    path,
                    params=clean,
                    headers={"Accept": accept, "Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as e:
                raise GarminAPIError(f"Could not reach Garmin: {e}") from e
            # A 401 on a data call usually means the cached token went stale
            # early (for example, the key was rotated); retry once with a new one.
            if response.status_code == 401 and attempt == 1:
                continue
            if not response.is_success:
                raise GarminAPIError(
                    _error_message(response.status_code, f"GET {path}"), response.status_code
                )
            return response
        raise AssertionError("unreachable")  # pragma: no cover

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a Personal API path; return decoded JSON, or None for an empty body."""
        response = await self._get_response(path, params)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as e:
            raise GarminAPIError(f"Garmin returned a non-JSON response for {path}.") from e

    async def get_bytes(self, path: str) -> bytes:
        """GET a binary resource, such as an original activity file."""
        response = await self._get_response(
            path,
            accept="application/zip, application/x-zip-compressed, application/octet-stream",
        )
        if not response.content:
            raise GarminAPIError(f"Garmin returned an empty file for {path}.")
        return response.content
