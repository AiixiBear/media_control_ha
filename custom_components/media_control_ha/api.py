"""Thin async REST client for the local Home-Assistant-style server.

Authentication (media_control app 1.1.0+): when a password is set in the
app, every request must present it as ``Authorization: Bearer <password>``
(preferred — the token never appears in a URL) or ``X-Api-Key``. A
missing/wrong password gets HTTP 401. When no password is set the server
is open and no auth header is sent, which is also how older app versions
behave.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout

from .const import (
    API_PATH_AUTH_CHECK,
    API_PATH_CONFIG,
    API_PATH_MEDIA_PLAYER,
    API_PATH_MEDIA_PLAYER_COMMAND,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 10


class LocalMediaPlayerApiError(Exception):
    """Raised when a call to the local server fails."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class LocalMediaPlayerAuthError(LocalMediaPlayerApiError):
    """Raised when the server rejects the request with HTTP 401.

    This means either the configured password is wrong, or the app has
    a password set and the integration was configured without one.
    """


class LocalMediaPlayerClient:
    """Wraps GET/POST calls to the local server's media-player endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        password: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = f"http://{host}:{port}"
        self._password = (password or "").strip() or None

    @property
    def password_configured(self) -> bool:
        """True when this client will send an auth header."""
        return self._password is not None

    def _headers(self) -> dict[str, str]:
        if self._password is None:
            return {}
        return {"Authorization": f"Bearer {self._password}"}

    async def async_check_auth(self) -> dict[str, Any]:
        """GET /api/auth/check.

        Returns ``{"authenticated": true, "auth_required": bool}`` when
        the request is authorised. Raises :class:`LocalMediaPlayerAuthError`
        (401) when the server requires a password and the configured one
        is missing or wrong.
        """
        return await self._get(API_PATH_AUTH_CHECK)

    async def async_get_config(self) -> dict[str, Any]:
        """GET /api/home-assistant/config.

        The payload includes ``requires_auth`` and the auth scheme, but
        never the token itself.
        """
        return await self._get(API_PATH_CONFIG)

    async def async_get_media_player_state(self) -> dict[str, Any]:
        """GET /api/home-assistant/media-player."""
        return await self._get(API_PATH_MEDIA_PLAYER)

    async def async_send_command(self, payload: dict[str, Any]) -> None:
        """POST /api/home-assistant/media-player/command."""
        url = f"{self._base_url}{API_PATH_MEDIA_PLAYER_COMMAND}"
        try:
            async with async_timeout.timeout(TIMEOUT):
                async with self._session.post(
                    url, json=payload, headers=self._headers()
                ) as resp:
                    if resp.status == 401:
                        raise LocalMediaPlayerAuthError(
                            "Command rejected (401): authentication failed — "
                            "check the password set in the app",
                            status=401,
                        )
                    if resp.status >= 400:
                        text = await resp.text()
                        raise LocalMediaPlayerApiError(
                            f"Command failed ({resp.status}): {text}",
                            status=resp.status,
                        )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LocalMediaPlayerApiError(f"Error sending command: {err}") from err

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with async_timeout.timeout(TIMEOUT):
                async with self._session.get(url, headers=self._headers()) as resp:
                    if resp.status == 401:
                        raise LocalMediaPlayerAuthError(
                            f"GET {path} rejected (401): authentication failed — "
                            "check the password set in the app",
                            status=401,
                        )
                    if resp.status >= 400:
                        text = await resp.text()
                        raise LocalMediaPlayerApiError(
                            f"GET {path} failed ({resp.status}): {text}",
                            status=resp.status,
                        )
                    return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LocalMediaPlayerApiError(f"Error fetching {path}: {err}") from err
