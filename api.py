"""Thin async REST client for the local Home-Assistant-style server."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import async_timeout

from .const import (
    API_PATH_CONFIG,
    API_PATH_MEDIA_PLAYER,
    API_PATH_MEDIA_PLAYER_COMMAND,
)

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 10


class LocalMediaPlayerApiError(Exception):
    """Raised when a call to the local server fails."""


class LocalMediaPlayerClient:
    """Wraps GET/POST calls to the local server's media-player endpoints."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int) -> None:
        self._session = session
        self._base_url = f"http://{host}:{port}"

    async def async_get_config(self) -> dict[str, Any]:
        """GET /api/home-assistant/config."""
        return await self._get(API_PATH_CONFIG)

    async def async_get_media_player_state(self) -> dict[str, Any]:
        """GET /api/home-assistant/media-player."""
        return await self._get(API_PATH_MEDIA_PLAYER)

    async def async_send_command(self, payload: dict[str, Any]) -> None:
        """POST /api/home-assistant/media-player/command."""
        url = f"{self._base_url}{API_PATH_MEDIA_PLAYER_COMMAND}"
        try:
            async with async_timeout.timeout(TIMEOUT):
                async with self._session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise LocalMediaPlayerApiError(
                            f"Command failed ({resp.status}): {text}"
                        )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LocalMediaPlayerApiError(f"Error sending command: {err}") from err

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with async_timeout.timeout(TIMEOUT):
                async with self._session.get(url) as resp:
                    if resp.status >= 400:
                        text = await resp.text()
                        raise LocalMediaPlayerApiError(
                            f"GET {path} failed ({resp.status}): {text}"
                        )
                    return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LocalMediaPlayerApiError(f"Error fetching {path}: {err}") from err
