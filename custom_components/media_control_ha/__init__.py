"""The Local REST Media Player integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    LocalMediaPlayerApiError,
    LocalMediaPlayerAuthError,
    LocalMediaPlayerClient,
)
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["media_player"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Local REST Media Player from a config entry."""
    session = async_get_clientsession(hass)
    client = LocalMediaPlayerClient(
        session,
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        password=entry.data.get(CONF_PASSWORD) or None,
    )

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    async def _async_update_data():
        try:
            return await client.async_get_media_player_state()
        except LocalMediaPlayerAuthError as err:
            # The password changed in the app (or was set after setup):
            # stop polling with a bad password and ask the user to
            # re-authenticate instead of spamming the server.
            _LOGGER.warning(
                "Authentication failed for %s:%s — the password in the "
                "app may have changed; starting re-auth: %s",
                entry.data[CONF_HOST],
                entry.data[CONF_PORT],
                err,
            )
            try:
                entry.async_start_reauth(hass)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Could not start re-auth flow for %s", entry.entry_id
                )
            raise UpdateFailed(
                "Authentication failed — check the password in the app"
            ) from err
        except LocalMediaPlayerApiError as err:
            raise UpdateFailed(str(err)) from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=_async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (e.g. scan interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
