"""Config flow for Local REST Media Player."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LocalMediaPlayerApiError, LocalMediaPlayerClient
from .const import (
    CONF_HOST,
    CONF_PACKAGE_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_PACKAGE_NAME, default=DEFAULT_PACKAGE_NAME): str,
    }
)


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Try a real GET call to confirm host/port are reachable."""
    session = async_get_clientsession(hass)
    client = LocalMediaPlayerClient(session, data[CONF_HOST], data[CONF_PORT])
    await client.async_get_media_player_state()


class LocalMediaPlayerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Local REST Media Player."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await _async_validate(self.hass, user_input)
            except LocalMediaPlayerApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating connection")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Media Player ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "LocalMediaPlayerOptionsFlow":
        return LocalMediaPlayerOptionsFlow(config_entry)


class LocalMediaPlayerOptionsFlow(config_entries.OptionsFlow):
    """Handle options (e.g. polling interval)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_interval
                ): vol.All(int, vol.Range(min=1, max=300)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
