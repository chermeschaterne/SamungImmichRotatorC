"""Constants for Samsung Immich Rotator C."""
from __future__ import annotations

DOMAIN = "samsung_immich_rotator_c"

PLATFORMS = ["sensor", "switch", "button"]

# Config-flow keys (stored in entry.data — NOT changed after initial setup)
CONF_IMMICH_SHARE_URL = "immich_share_url"
CONF_FRAME_IP = "frame_ip"
CONF_FRAME_MAC = "frame_mac"
CONF_CLIENT_NAME = "client_name"
CONF_MATTE = "matte"

# Options-flow keys (stored in entry.options — changeable after setup)
CONF_ROTATION_TIME = "rotation_time"
CONF_BRIGHTNESS = "brightness"
CONF_DISABLE_AMBIENT = "disable_ambient"
CONF_MOTION_SENSOR = "motion_sensor"
CONF_MOTION_TIMEOUT = "motion_timeout"

# Defaults
DEFAULT_CLIENT_NAME = "SamsungImmichRotatorC"
DEFAULT_MATTE = "none"
DEFAULT_ROTATION_TIME = "06:00"
DEFAULT_BRIGHTNESS = 2
DEFAULT_DISABLE_AMBIENT = True
DEFAULT_MOTION_TIMEOUT = 15

MATTE_OPTIONS = [
    "none",
    "moderndark",
    "modernwhite",
    "classicantique",
    "classicbrown",
    "classicgray",
    "classicblue",
    "naturalpine",
    "naturalcherry",
    "naturaloak",
]

# Storage sub-directory (under .storage/)
STORAGE_DIR = DOMAIN

# Frame TV port
FRAME_PORT = 8002

# Image dimensions
FRAME_W = 3840
FRAME_H = 2160
FRAME_QUALITY = 92

# Timeout constants (seconds)
ART_OP_TIMEOUT = 10
UPLOAD_TIMEOUT = 60
WOL_WAIT_SECONDS = 30
WOL_POLL_INTERVAL = 2
