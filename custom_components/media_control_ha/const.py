"""Constants for the Local REST Media Player integration."""

DOMAIN = "media_control_ha"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_PASSWORD = "password"
CONF_PACKAGE_NAME = "package_name"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 8080
DEFAULT_SCAN_INTERVAL = 5  # seconds
DEFAULT_PACKAGE_NAME = "com.example.music"

# --- API paths on the local server ---
API_PATH_CONFIG = "/api/home-assistant/config"
API_PATH_MEDIA_PLAYER = "/api/home-assistant/media-player"
API_PATH_MEDIA_PLAYER_COMMAND = "/api/home-assistant/media-player/command"
API_PATH_AUTH_CHECK = "/api/auth/check"

# --- Actions supported by the remote server (see its docs) ---
ACTION_PLAY = "media_play"
ACTION_PAUSE = "media_pause"
ACTION_PLAY_PAUSE = "media_play_pause"
ACTION_NEXT = "media_next_track"
ACTION_PREVIOUS = "media_previous_track"
ACTION_SEEK = "media_seek"

# --- Mapping from the server's "state" string to HA MediaPlayerState ---
# Confirmed from a real payload: {"state": "playing", ...}
STATE_MAP = {
    "playing": "playing",
    "paused": "paused",
    "idle": "idle",
    "stopped": "idle",
    "off": "off",
    "buffering": "buffering",
}

# The server reports media_duration / media_position in MILLISECONDS.
POSITION_UNIT_MS = True
