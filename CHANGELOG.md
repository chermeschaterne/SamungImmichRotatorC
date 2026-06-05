# Changelog

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
