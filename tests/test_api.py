"""Tests for the REST client: auth headers, 401 handling, payloads.

These tests use a fake aiohttp session, so they run without a Home
Assistant install.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest

from custom_components.media_control_ha.api import (
    LocalMediaPlayerApiError,
    LocalMediaPlayerAuthError,
    LocalMediaPlayerClient,
)

AUTH_CHECK = {"authenticated": True, "auth_required": True}
CONFIG = {
    "entity_id": "media_player.media_control_hub_test",
    "requires_auth": True,
    "auth": {"type": "bearer", "header": "Authorization", "scheme": "Bearer"},
}
STATE = {
    "entity_id": "media_player.media_control_hub_test",
    "state": "playing",
    "attributes": {
        "friendly_name": "大便媒體控制 - Test",
        "media_title": "Test Track",
        "media_artist": "Test Artist",
        "media_album_name": "Test Album",
        "media_duration": 240000,
        "media_position": 42000,
        "media_position_updated_at": "2026-11-10T00:00:00+00:00",
        "app_name": "Sample Music",
        "package_name": "com.example.music",
        "artwork_url": None,
    },
}


class FakeResponse:
    """Minimal stand-in for aiohttp.ClientResponse."""

    def __init__(
        self, status: int, payload: dict[str, Any] | None = None, text: str = ""
    ) -> None:
        self.status = status
        self._payload = payload or {}
        self._text = text

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._payload

    async def text(self) -> str:
        return self._text


class FakeSession:
    """Records every request and returns canned responses by path."""

    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def _record(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        path = url.split("http://127.0.0.1:8080", 1)[-1]
        return self._responses[path]

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._record("POST", url, **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_bearer_header_sent_on_every_request() -> None:
    session = FakeSession(
        {
            "/api/auth/check": FakeResponse(200, AUTH_CHECK),
            "/api/home-assistant/config": FakeResponse(200, CONFIG),
            "/api/home-assistant/media-player": FakeResponse(200, STATE),
            "/api/home-assistant/media-player/command": FakeResponse(200, {"ok": True}),
        }
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080, password="secret123")
    assert client.password_configured is True
    run(client.async_check_auth())
    run(client.async_get_config())
    run(client.async_get_media_player_state())
    run(client.async_send_command({"action": "media_play_pause", "packageName": "com.example.music"}))

    assert len(session.calls) == 4
    for call in session.calls:
        assert call["headers"] == {"Authorization": "Bearer secret123"}, call


def test_no_auth_header_without_password() -> None:
    session = FakeSession(
        {
            "/api/auth/check": FakeResponse(
                200, {"authenticated": True, "auth_required": False}
            ),
            "/api/home-assistant/media-player": FakeResponse(200, STATE),
        }
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080)
    assert client.password_configured is False
    assert run(client.async_check_auth()) == {
        "authenticated": True,
        "auth_required": False,
    }
    run(client.async_get_media_player_state())
    for call in session.calls:
        assert call["headers"] == {}, call


def test_empty_or_blank_password_means_no_auth() -> None:
    session = FakeSession(
        {"/api/home-assistant/media-player": FakeResponse(200, STATE)}
    )
    for password in ("", "   ", None):
        client = LocalMediaPlayerClient(
            session, "127.0.0.1", 8080, password=password
        )
        assert client.password_configured is False
        run(client.async_get_media_player_state())
    assert all(call["headers"] == {} for call in session.calls)


def test_401_on_get_raises_auth_error() -> None:
    session = FakeSession(
        {"/api/auth/check": FakeResponse(401, None, "need auth")}
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080, password="wrongpass")
    with pytest.raises(LocalMediaPlayerAuthError) as excinfo:
        run(client.async_check_auth())
    assert excinfo.value.status == 401


def test_401_on_command_raises_auth_error() -> None:
    session = FakeSession(
        {
            "/api/home-assistant/media-player/command": FakeResponse(
                401, None, "need auth"
            )
        }
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080, password="wrongpass")
    with pytest.raises(LocalMediaPlayerAuthError):
        run(
            client.async_send_command(
                {"action": "media_pause", "packageName": "com.example.music"}
            )
        )


def test_500_raises_api_error_with_status() -> None:
    session = FakeSession(
        {"/api/home-assistant/media-player": FakeResponse(500, None, "boom")}
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080)
    with pytest.raises(LocalMediaPlayerApiError) as excinfo:
        run(client.async_get_media_player_state())
    assert excinfo.value.status == 500
    assert not isinstance(excinfo.value, LocalMediaPlayerAuthError)


def test_connection_error_raises_api_error() -> None:
    class FailingSession:
        def get(self, url: str, **kwargs: Any):
            raise aiohttp.ClientError("unreachable")

    client = LocalMediaPlayerClient(FailingSession(), "127.0.0.1", 8080)
    with pytest.raises(LocalMediaPlayerApiError):
        run(client.async_get_media_player_state())


def test_command_posts_payload_and_bearer_header() -> None:
    session = FakeSession(
        {
            "/api/home-assistant/media-player/command": FakeResponse(200, {"ok": True}),
        }
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080, password="secret123")
    payload = {
        "action": "media_seek",
        "packageName": "com.example.music",
        "positionMs": 42000,
        "seekPosition": 42000,
    }
    run(client.async_send_command(payload))
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == (
        "http://127.0.0.1:8080/api/home-assistant/media-player/command"
    )
    assert call["json"] == payload
    assert call["headers"] == {"Authorization": "Bearer secret123"}


def test_config_reports_requires_auth() -> None:
    session = FakeSession(
        {"/api/home-assistant/config": FakeResponse(200, CONFIG)}
    )
    client = LocalMediaPlayerClient(session, "127.0.0.1", 8080, password="secret123")
    config = run(client.async_get_config())
    assert config["requires_auth"] is True
    assert config["auth"]["scheme"] == "Bearer"
    assert "secret123" not in str(config)
