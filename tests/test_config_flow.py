"""Tests for the config flow, re-auth and options (Home Assistant).

Skipped entirely when pytest-homeassistant-custom-component is not
installed (e.g. a plain local checkout) — the pure client tests in
test_api.py still run there.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.media_control_ha.const import (
    CONF_HOST,
    CONF_PACKAGE_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

HOST = "192.168.1.10"
PORT = 8080
BASE = f"http://{HOST}:{PORT}"

AUTH_CHECK_AUTH = {"authenticated": True, "auth_required": True}
AUTH_CHECK_OPEN = {"authenticated": True, "auth_required": False}
CONFIG_AUTH = {
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


def _mock_server(aioclient_mock, *, auth_check_status=200, auth_check=None):
    """Mock the endpoints the validation path touches."""
    aioclient_mock.get(
        f"{BASE}/api/auth/check",
        status=auth_check_status,
        json=auth_check if auth_check is not None else AUTH_CHECK_AUTH,
    )
    aioclient_mock.get(f"{BASE}/api/home-assistant/config", json=CONFIG_AUTH)
    aioclient_mock.get(f"{BASE}/api/home-assistant/media-player", json=STATE)


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )


def test_domain_matches_manifest() -> None:
    """The integration domain should match the manifest entry."""
    assert DOMAIN == "media_control_ha"


async def test_user_flow_success_with_password(hass: HomeAssistant, aioclient_mock) -> None:
    """A password-protected server validates and stores the password."""
    _mock_server(aioclient_mock)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_PASSWORD: "secret123",
            CONF_PACKAGE_NAME: "com.example.music",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == "secret123"
    assert result["data"][CONF_HOST] == HOST


async def test_user_flow_wrong_password(hass: HomeAssistant, aioclient_mock) -> None:
    """A 401 from the server surfaces as invalid_auth, not cannot_connect."""
    _mock_server(aioclient_mock, auth_check_status=401)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: HOST, CONF_PORT: PORT, CONF_PASSWORD: "wrongpass"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_server_requires_auth_but_no_password(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Password set in the app but none given here is an auth error."""
    _mock_server(aioclient_mock, auth_check_status=401)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: HOST, CONF_PORT: PORT, CONF_PASSWORD: ""},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_no_password_old_app(hass: HomeAssistant, aioclient_mock) -> None:
    """Servers without /api/auth/check (older app) still validate via state."""
    aioclient_mock.get(f"{BASE}/api/auth/check", status=404)
    aioclient_mock.get(f"{BASE}/api/home-assistant/media-player", json=STATE)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: HOST, CONF_PORT: PORT, CONF_PASSWORD: ""},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PASSWORD] == ""


async def test_user_flow_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    """A server error on every endpoint surfaces as cannot_connect."""
    aioclient_mock.get(f"{BASE}/api/auth/check", status=500)
    aioclient_mock.get(f"{BASE}/api/home-assistant/media-player", status=500)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: HOST, CONF_PORT: PORT, CONF_PASSWORD: ""},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow_updates_password(hass: HomeAssistant, aioclient_mock) -> None:
    """After the app password changes, re-auth stores the new one."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_PASSWORD: "oldpass99",
            CONF_PACKAGE_NAME: "com.example.music",
        },
        unique_id=f"{HOST}:{PORT}",
    )
    entry.add_to_hass(hass)

    _mock_server(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "newpass99"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "newpass99"


async def test_options_flow_updates_password(hass: HomeAssistant) -> None:
    """The options flow can rotate the stored password."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_PASSWORD: "secret123",
            CONF_PACKAGE_NAME: "com.example.music",
        },
        unique_id=f"{HOST}:{PORT}",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PASSWORD: "rotated99", CONF_SCAN_INTERVAL: 10},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_INTERVAL] == 10
    assert entry.data[CONF_PASSWORD] == "rotated99"


async def test_entity_setup_and_seek_sends_auth(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """End to end: setup, state parsing, and a seek command with Bearer auth."""
    aioclient_mock.get(f"{BASE}/api/home-assistant/media-player", json=STATE)
    aioclient_mock.post(
        f"{BASE}/api/home-assistant/media-player/command", json={"ok": True}
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: HOST,
            CONF_PORT: PORT,
            CONF_PASSWORD: "secret123",
            CONF_PACKAGE_NAME: "com.example.music",
        },
        unique_id=f"{HOST}:{PORT}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_ids = hass.states.async_entity_ids("media_player")
    assert len(entity_ids) == 1
    state = hass.states.get(entity_ids[0])
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Test Track"
    assert state.attributes["media_artist"] == "Test Artist"
    assert state.attributes["media_duration"] == 240
    assert state.attributes["media_position"] == 42

    await hass.services.async_call(
        "media_player",
        "media_seek",
        {"entity_id": entity_ids[0], "seek_position": 42},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(aioclient_mock.mock_calls) >= 2
    post_calls = [
        call
        for call in aioclient_mock.mock_calls
        if call[0] == "POST"
        and "media-player/command" in str(call[1])
    ]
    assert post_calls, "expected a POST to the command endpoint"
    # aioresponses records (method, url, json_payload, headers).
    payload = post_calls[-1][2]
    headers = post_calls[-1][3]
    assert payload["action"] == "media_seek"
    assert payload["positionMs"] == 42000
    assert payload["seekPosition"] == 42000
    assert headers["Authorization"] == "Bearer secret123"
