# Samsung Immich Rotator C

A [Home Assistant](https://www.home-assistant.io/) custom integration (HACS) that automatically
rotates images from an **Immich shared album** on a **Samsung Frame TV** (Art Mode) once per day.

Runs inside the user's existing HA container — no separate container, no Supervisor dependency.

## Features

- **Daily rotation** at a configurable time (default 06:00).
- **Round-robin** image selection from your Immich shared album.
- **Upload cache** — images already on the TV are not re-uploaded.
- **Silent updates** — the panel does not wake when rotating; `show=False` is used.
- **Brightness control** — set a fixed brightness level and disable the ambient-light sensor.
- **Wake-on-LAN** fallback when the TV is in deep sleep.
- **Motion-based auto-standby** — go to standby when no motion is detected for N minutes.
- **State persistence** — survives HA restarts; does not re-ask the TV for a connection approval.
- **Master switch** — pause all scheduled rotations without losing the schedule.
- **Manual trigger** button, wake button, and standby button.
- **Status sensors** — album size, current image, next rotation, last rotation time and status.
- **Services** callable from automations: `set_rotation_time`, `rotate`, `wake`, `standby`.

## Requirements

- Home Assistant 2024.4.0 or newer.
- HACS 2.x installed in your HA instance.
- A Samsung Frame TV (Tizen OS) on the same LAN.
- An [Immich](https://immich.app/) instance with a public shared album.

## Installation

### 1. Install via HACS

1. Open HACS → Integrations → ⋮ → **Custom repositories**.
2. Add `https://github.com/chermeschaterne/SamungImmichRotatorC` as category **Integration**.
3. Click **Download** and restart Home Assistant.

### 2. Configure

1. Go to **Settings → Devices & Services → + Add Integration**.
2. Search for **Samsung Immich Rotator C**.
3. Fill in the form:

| Field | Description |
|---|---|
| Immich Share URL | Full URL of the Immich public share, e.g. `https://immich.example.com/share/<key>` |
| Samsung Frame IP | TV's IP address on your local network |
| Samsung Frame MAC | TV's MAC address, used for Wake-on-LAN, e.g. `38:8c:ef:bb:b4:8c` |
| Client name | Stable identifier shown on the TV's "Allow connection?" popup (default: `SamsungImmichRotatorC`) |
| Matte | Frame/matte style (default: `none`) |

4. When prompted, **Allow** the connection on the TV using its remote.
5. The integration is now set up. You should see the device with all entities.

### 3. Runtime options (after setup)

Go to **Settings → Devices & Services → ⋮ → Configure** to change:

- Daily rotation time (default: 06:00)
- Brightness level (1–10, default: 2)
- Disable ambient-light sensor (default: on)
- Motion sensor entity ID (optional)
- Motion timeout in minutes (default: 15)

## Entities

| Entity | Type | Description |
|---|---|---|
| `switch.samsung_immich_rotator_c_rotation_enabled` | Switch | Master on/off for scheduled rotations |
| `button.samsung_immich_rotator_c_rotate_now` | Button | Trigger a rotation immediately |
| `button.samsung_immich_rotator_c_wake_frame` | Button | Wake TV and enable art mode |
| `button.samsung_immich_rotator_c_standby` | Button | Disable art mode (panel off) |
| `sensor.samsung_immich_rotator_c_album_size` | Sensor | Number of images in the album |
| `sensor.samsung_immich_rotator_c_current_image` | Sensor | Immich asset ID currently displayed |
| `sensor.samsung_immich_rotator_c_next_rotation` | Sensor | Timestamp of next scheduled rotation |
| `sensor.samsung_immich_rotator_c_last_rotation` | Sensor | Timestamp of last rotation attempt |
| `sensor.samsung_immich_rotator_c_last_rotation_status` | Sensor | `ok` / `error` / `skipped` |

## Services

| Service | Description |
|---|---|
| `samsung_immich_rotator_c.set_rotation_time` | Change the daily rotation time (parameter: `time` as HH:MM) |
| `samsung_immich_rotator_c.rotate` | Trigger a rotation immediately |
| `samsung_immich_rotator_c.wake` | Wake TV + enable art mode |
| `samsung_immich_rotator_c.standby` | Disable art mode |

## Troubleshooting

### TV does not respond

1. Check the TV is on the same LAN as HA and the IP is correct.
2. Try the **Wake Frame** button — it sends a Wake-on-LAN packet.
3. If the TV's WebSocket state is polluted (happens on some 2023+ Frame models after many rapid
   connections), do a hard power reset: unplug the TV for 3 minutes, wait 10 minutes after
   plugging back in.

### TV asks to Allow connection again after HA restart

This should not happen — the auth token is persisted in
`.storage/samsung_immich_rotator_c/<entry_id>_tv_token`. If it does, check file permissions and
disk space.

### `last_rotation_status` shows `error`

Check the `last_error` attribute on the `last_rotation_status` sensor for the human-readable
error message. Full details are in the HA log at WARNING/ERROR level.

## License

[MIT](LICENSE)
