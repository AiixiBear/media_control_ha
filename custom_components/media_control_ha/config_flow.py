"""Config flow for Local REST Media Player."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    LocalMediaPlayerApiError,
    LocalMediaPlayerAuthError,
    LocalMediaPlayerClient,
)
from .const import (
    CONF_HOST,
    CONF_PACKAGE_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _client_for(hass: HomeAssistant, data: dict[str, Any]) -> LocalMediaPlayerClient:
    session = async_get_clientsession(hass)
    return LocalMediaPlayerClient(
        session,
        data[CONF_HOST],
        data[CONF_PORT],
        password=data.get(CONF_PASSWORD) or None,
    )


async def _async_validate(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Try real calls to confirm host/port/password are correct.

    Returns the server's config payload (which reports ``requires_auth``).

    Raises:
        LocalMediaPlayerAuthError: wrong password, or the server requires
            a password and none was configured.
        LocalMediaPlayerApiError: host unreachable / other HTTP errors.
    """
    client = _client_for(hass, data)
    try:
        auth = await client.async_check_auth()
    except LocalMediaPlayerAuthError:
        # No usable password for a server that requires one, or the
        # configured password is wrong — same 401 either way.
        raise
    except LocalMediaPlayerApiError:
        # Older app versions have no /api/auth/check endpoint (404), so
        # fall back to the media-player state endpoint, which exists on
        # every version.
        await client.async_get_media_player_state()
        return {"requires_auth": False, "auth_required": False}

    # /api/auth/check answered: if the server requires auth and we got
    # here without a password, that cannot happen (it would be a 401),
    # but keep the explicit check for clarity.
    if auth.get("auth_required") and not client.password_configured:
        raise LocalMediaPlayerAuthError(
            "Server requires a password but none was configured"
        )
    config = await client.async_get_config()
    return config


def _user_schema(
    *,
    host: str | None = None,
    port: int = DEFAULT_PORT,
    password: str = "",
    package_name: str = DEFAULT_PACKAGE_NAME,
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host or ""): str,
            vol.Required(CONF_PORT, default=port): int,
            vol.Optional(CONF_PASSWORD, default=password): str,
            vol.Optional(
                CONF_PACKAGE_NAME, default=package_name
            ): str,
        }
    )


class LocalMediaPlayerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Local REST Media Player."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_PASSWORD] = (user_input.get(CONF_PASSWORD) or "").strip()
            unique_id = f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                await _async_validate(self.hass, user_input)
            except LocalMediaPlayerAuthError:
                errors["base"] = "invalid_auth"
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
            step_id="user", data_schema=_user_schema(), errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Start the re-auth flow (e.g. after the app password changed)."""
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the new password and validate it against the server."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry

        if user_input is not None:
            password = (user_input.get(CONF_PASSWORD) or "").strip()
            data = dict(entry.data)
            data[CONF_PASSWORD] = password
            try:
                await _async_validate(self.hass, data)
            except LocalMediaPlayerAuthError:
                errors["base"] = "invalid_auth"
            except LocalMediaPlayerApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during re-auth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_PASSWORD, default=""): str}
            ),
            errors=errors,
            description_placeholders={
                "host": str(entry.data.get(CONF_HOST, "")),
            },
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "LocalMediaPlayerOptionsFlow":
        return LocalMediaPlayerOptionsFlow(config_entry)


class LocalMediaPlayerOptionsFlow(config_entries.OptionsFlow):
    """Handle options (password and polling interval)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            # Password lives in the entry data, not in options, so a
            # password change here takes effect after the reload.
            new_data = dict(self._config_entry.data)
            if CONF_PASSWORD in user_input:
                new_data[CONF_PASSWORD] = (
                    user_input.pop(CONF_PASSWORD) or ""
                ).strip()
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current_password = self._config_entry.data.get(CONF_PASSWORD, "")
        schema = vol.Schema(
            {
                vol.Optional(CONF_PASSWORD, default=current_password): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=current_interval
                ): vol.All(int, vol.Range(min=1, max=300)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
