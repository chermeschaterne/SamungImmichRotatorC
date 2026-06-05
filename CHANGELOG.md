# Changelog

## [1.3.0] - 2026-06-05

### Added
- **`time.rotation_time` entity** — a native HA time-picker control that appears directly on
  the device dashboard. Set the daily rotation time by clicking the entity; no buried Configure
  menu required.

### Changed
- Options updates (rotation time, motion sensor, etc.) no longer trigger a full integration
  reload. The daily timer and motion listener are restarted in-place, so changes take effect
  immediately and all other state (art mode, rotation status, etc.) is preserved.

## [1.2.0] - 2026-06-05

### Changed
- **"Wake Frame" and "Standby" buttons replaced by "Art Mode" switch.** Toggling the switch on
  enables Art Mode (with Wake-on-LAN fallback); toggling it off switches the TV back to
  TV/standby mode. The switch state is tracked optimistically after each action.

### Added
- **README: How to set the rotation time** — step-by-step instructions for both the Configure
  menu (Settings → Devices & Services → Configure) and the `set_rotation_time` service.

### Removed
- `button.wake_frame` and `button.standby` entities (replaced by `switch.art_mode`).

## [1.1.0] - 2026-06-05

### Fixed
- **`manifest.json`**: Changed requirement from `samsungtvws>=2.0.0` to
  `samsungtvws[async,encrypted]>=3.0.0`. Without the `[encrypted]` extra, HA
  installs a build of the library that cannot open port-8002 encrypted WebSocket
  connections. All Frame 2022+ TVs require port 8002, so every connection attempt
  failed silently before this fix.
- **`rotation.py`**: Changed both `select_image(show=False)` calls to
  `select_image(show=True)`. With `show=False` the TV acknowledges the selection
  internally but does not update the panel — the image change was invisible.
  Using `show=True` (matching the validated test script) makes the Frame actually
  display the newly selected image while in art mode.
- **`frame_client.py`**: Switched from `token=<string>` to `token_file=<path>`,
  letting the `samsungtvws` library handle token reads and writes automatically.
  This matches the pattern used in the validated test script and eliminates the
  risk of losing the auth token on HA restart before the first rotation completed.
- **`frame_client.py`**: Removed `_prime_connection()` / `KEY_POWER` priming.
  Sending `KEY_POWER` to a Frame that is already in art mode toggles it to standby
  — the integration was turning the TV off on every rotation attempt.
- **`coordinator.py`**: Removed manual token-load/save logic (`_load_token`,
  `_save_token`, etc.) — now redundant since the library manages the token file.

## [1.0.0] - 2024-06-05

### Added
- Initial release.
- Daily image rotation from Immich shared album to Samsung Frame TV (Art Mode).
- Config flow: Immich share URL, TV IP, MAC, client name, matte style.
- Options flow: rotation time, brightness, ambient-light sensor, motion sensor entity, motion timeout.
- Master switch to pause/resume scheduled rotations.
- Buttons: Rotate Now, Wake Frame, Standby.
- Sensors: album size, current image, next rotation, last rotation timestamp and status.
- Services: `set_rotation_time`, `rotate`, `wake`, `standby`.
- Wake-on-LAN fallback when TV is in deep sleep.
- State persistence across HA restarts (token + rotation state).
- Motion-based auto-standby via configurable HA binary sensor.
- English and German translations.
