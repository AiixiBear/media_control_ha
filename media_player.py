"""Media player platform for Local REST Media Player."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import LocalMediaPlayerApiError, LocalMediaPlayerClient
from .const import (
    ACTION_NEXT,
    ACTION_PAUSE,
    ACTION_PLAY,
    ACTION_PLAY_PAUSE,
    ACTION_PREVIOUS,
    ACTION_SEEK,
    CONF_PACKAGE_NAME,
    DEFAULT_PACKAGE_NAME,
    DOMAIN,
    STATE_MAP,
)

_LOGGER = logging.getLogger(__name__)

# How long we trust our own optimistic guess before giving up and
# accepting whatever the server reports, even if it looks stale.
OPTIMISTIC_TIMEOUT = timedelta(seconds=10)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LocalRestMediaPlayer(entry, data["client"], data["coordinator"])])


class LocalRestMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of the remote media player as a real HA entity."""

    _attr_has_entity_name = True
    _attr_name = None  # use device name
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, entry: ConfigEntry, client: LocalMediaPlayerClient, coordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._client = client
        self._package_name = entry.data.get(CONF_PACKAGE_NAME, DEFAULT_PACKAGE_NAME)
        remote_entity_id = (coordinator.data or {}).get("entity_id")
        self._attr_unique_id = remote_entity_id or f"{entry.entry_id}_media_player"
        friendly_name = (coordinator.data or {}).get("attributes", {}).get(
            "friendly_name"
        ) or f"Local Media Player ({entry.data.get('host')})"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=friendly_name,
            manufacturer="Local REST Server",
            model="Home Assistant Style API",
        )
        # --- optimistic-update state ---
        # Holds a locally-predicted value until the next coordinator
        # refresh confirms (or overrides) it with the real server state.
        self._optimistic_state: str | None = None
        self._optimistic_position_ms: int | None = None
        self._optimistic_position_time = None
        self._optimistic_state_set_at = None

    def _handle_coordinator_update(self) -> None:
        """Reconcile optimistic guesses with real data, then render."""
        now = dt_util.utcnow()

        # Position: only trust the server once it reports a position
        # timestamp newer than the one we set locally, OR once our guess
        # has been outstanding long enough that we give up waiting.
        if self._optimistic_position_ms is not None:
            raw = self._data.get("attributes", {}).get("media_position_updated_at")
            server_time = dt_util.parse_datetime(raw) if raw else None
            server_has_caught_up = (
                server_time is not None
                and self._optimistic_position_time is not None
                and server_time > self._optimistic_position_time
            )
            timed_out = (
                self._optimistic_position_time is not None
                and now - self._optimistic_position_time > OPTIMISTIC_TIMEOUT
            )
            if server_has_caught_up or timed_out:
                self._optimistic_position_ms = None
                self._optimistic_position_time = None

        # State (play/pause/buffering): same idea, but we don't get a
        # dedicated timestamp for it, so just give it a short grace
        # window before trusting whatever the server says.
        if self._optimistic_state is not None:
            timed_out = (
                self._optimistic_state_set_at is not None
                and now - self._optimistic_state_set_at > OPTIMISTIC_TIMEOUT
            )
            real_state = STATE_MAP.get(self._data.get("state"))
            already_matches = real_state == self._optimistic_state
            if timed_out or already_matches:
                self._optimistic_state = None
                self._optimistic_state_set_at = None

        super()._handle_coordinator_update()

    # ---- helpers -----------------------------------------------------

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def _attributes(self) -> dict[str, Any]:
        return self._data.get("attributes", {})

    # ---- state ---------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        if self._optimistic_state is not None:
            return MediaPlayerState(self._optimistic_state)
        raw_state = self._data.get("state")
        mapped = STATE_MAP.get(raw_state)
        if mapped is None:
            return None
        return MediaPlayerState(mapped)

    @property
    def media_title(self) -> str | None:
        return self._attributes.get("media_title")

    @property
    def media_artist(self) -> str | None:
        return self._attributes.get("media_artist")

    @property
    def media_album_name(self) -> str | None:
        # Server sends "" when unknown; treat empty string as None.
        return self._attributes.get("media_album_name") or None

    @property
    def media_duration(self) -> int | None:
        # Server reports milliseconds; HA expects seconds.
        ms = self._attributes.get("media_duration")
        return round(ms / 1000) if ms is not None else None

    @property
    def media_position(self) -> int | None:
        if self._optimistic_position_ms is not None:
            return round(self._optimistic_position_ms / 1000)
        ms = self._attributes.get("media_position")
        return round(ms / 1000) if ms is not None else None

    @property
    def media_position_updated_at(self):
        # Lets HA extrapolate/animate the progress bar between polls.
        if self._optimistic_position_time is not None:
            return self._optimistic_position_time
        raw = self._attributes.get("media_position_updated_at")
        if not raw:
            return None
        return dt_util.parse_datetime(raw)

    @property
    def media_content_type(self) -> str | None:
        # Needed so the frontend renders "artist - title" as a subtitle
        # instead of just showing the title alone.
        return MediaType.MUSIC

    @property
    def app_name(self) -> str | None:
        return self._attributes.get("app_name")

    @property
    def media_image_hash(self) -> str | None:
        # HA only bothers calling async_get_media_image() if this returns
        # a non-None value. We hash a fingerprint of the current track so
        # it changes (and the image reloads) whenever the song changes.
        raw = self._attributes.get("artwork_url")
        if not raw:
            return None
        fingerprint = f"{self.media_title}|{self.media_artist}|{raw[:64]}"
        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"package_name": self._current_package_name}

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Decode the base64 artwork the server embeds inline."""
        raw = self._attributes.get("artwork_url")
        if not raw:
            return None, None
        # Handle both a bare base64 string and a data: URI.
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        try:
            return base64.b64decode(raw), "image/png"
        except (binascii.Error, ValueError):
            _LOGGER.debug("Could not decode artwork_url as base64 PNG")
            return None, None

    # ---- commands --------------------------------------------------------

    @property
    def _current_package_name(self) -> str:
        """Prefer the package name reported live by the server."""
        return self._attributes.get("package_name") or self._package_name

    async def _async_send(
        self,
        action: str,
        *,
        optimistic_state: str | None = None,
        optimistic_position_ms: int | None = None,
        **extra: Any,
    ) -> None:
        now = dt_util.utcnow()

        # 1) Reflect the change immediately in the UI.
        if optimistic_state is not None:
            self._optimistic_state = optimistic_state
            self._optimistic_state_set_at = now
        if optimistic_position_ms is not None:
            self._optimistic_position_ms = optimistic_position_ms
            self._optimistic_position_time = now
        if optimistic_state is not None or optimistic_position_ms is not None:
            self.async_write_ha_state()

        # 2) Send the real command to the server.
        payload = {
            "action": action,
            "packageName": self._current_package_name,
            **extra,
        }
        try:
            await self._client.async_send_command(payload)
        except LocalMediaPlayerApiError as err:
            _LOGGER.error("Failed to send %s: %s", action, err)
            # Roll back the optimistic guess since the command failed.
            self._optimistic_state = None
            self._optimistic_position_ms = None
            self._optimistic_position_time = None
            self._optimistic_state_set_at = None
            self.async_write_ha_state()
            return

        # 3) Give the remote device a beat to actually apply the change
        # before we ask it for fresh data — otherwise we tend to read
        # back the pre-command state and it looks like our UI "reverted".
        await asyncio.sleep(1)
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self._async_send(ACTION_PLAY, optimistic_state=MediaPlayerState.PLAYING)

    async def async_media_pause(self) -> None:
        await self._async_send(ACTION_PAUSE, optimistic_state=MediaPlayerState.PAUSED)

    async def async_media_play_pause(self) -> None:
        currently_playing = self.state == MediaPlayerState.PLAYING
        next_state = (
            MediaPlayerState.PAUSED if currently_playing else MediaPlayerState.PLAYING
        )
        await self._async_send(ACTION_PLAY_PAUSE, optimistic_state=next_state)

    async def async_media_next_track(self) -> None:
        # We don't know the next track's title/artwork yet, but at least
        # show the player as "buffering" instead of appearing frozen.
        await self._async_send(ACTION_NEXT, optimistic_state=MediaPlayerState.BUFFERING)

    async def async_media_previous_track(self) -> None:
        await self._async_send(
            ACTION_PREVIOUS, optimistic_state=MediaPlayerState.BUFFERING
        )

    async def async_media_seek(self, position: float) -> None:
        # HA gives position in seconds; the server expects milliseconds.
        position_ms = int(position * 1000)
        await self._async_send(
            ACTION_SEEK,
            optimistic_position_ms=position_ms,
            seekPosition=position_ms,
        )