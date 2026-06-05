# Samsung Immich Rotator C

A [Home Assistant](https://www.home-assistant.io/) custom integration (HACS) that automatically
rotates images from an **Immich shared album** on a **Samsung Frame TV** (Art Mode) once per day.

Runs inside the user's existing HA container — no separate container, no Supervisor dependency.

## Features

- **Daily rotation** at a configurable time (default 06:00).
- **Round-robin** image selection from your Immich shared album.
- **Upload cache** — images already on the TV are not re-uploaded.
- **Brightness control** — set a fixed brightness level and disable the ambient-light sensor.
- **Wake-on-LAN** fallback when the TV is in deep sleep.
- **Motion-based auto-standby** — go to standby when no motion is detected for N minutes.
- **State persistence** — survives HA restarts; does not re-ask the TV for a connection approval.
- **Master switch** — pause all scheduled rotations without losing the schedule.
- **Art Mode switch** — toggle the Frame between Art Mode and TV/standby from the HA dashboard.
- **Manual rotate** button to trigger a rotation immediately.
- **Status sensors** — album size, current image, next rotation, last rotation time and status.
- **Services** callable from automations: `set_rotation_time`, `rotate`, `wake`, `standby`.

## Requirements

- Home Assistant 2024.4.0 or newer.
- HACS 2.x installed in your HA instance.
- A Samsung Frame TV (Tizen OS, 2022 or newer) on the same LAN.
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

### 3. Set the daily rotation time

**Option A — Rotation Time entity (recommended):**

The **Rotation Time** entity appears directly on the device dashboard as a time picker.
Click it, pick a time, confirm — the schedule updates instantly, no restart needed.

**Option B — via the `set_rotation_time` service:**

Call the service from **Developer Tools → Services** or from an automation:

```yaml
service: samsung_immich_rotator_c.set_rotation_time
data:
  time: "07:30"
```

The `time` value must be in `HH:MM` format (24-hour).

### 4. Runtime options (after setup)

All options are available under **Settings → Devices & Services → Configure**:

| Option | Default | Description |
|---|---|---|
| Daily Rotation Time | `06:00` | Time of day for the automatic image rotation |
| Brightness Level | `2` | Art mode brightness 1 (very dim) to 10 (maximum) |
| Disable Ambient Light Sensor | on | Use fixed brightness instead of the TV sensor |
| Motion Sensor | — | Optional `binary_sensor` entity for auto-standby |
| Motion Timeout | `15 min` | Minutes without motion before going to standby |

## Entities

| Entity | Type | Description |
|---|---|---|
| `time.samsung_immich_rotator_c_rotation_time` | Time | Daily rotation time — click to change with a time picker |
| `switch.samsung_immich_rotator_c_art_mode` | Switch | Toggle Art Mode on (Frame shows art) / off (TV mode) |
| `switch.samsung_immich_rotator_c_rotation_enabled` | Switch | Master on/off for scheduled rotations |
| `button.samsung_immich_rotator_c_rotate_now` | Button | Trigger a rotation immediately |
| `sensor.samsung_immich_rotator_c_album_size` | Sensor | Number of images in the Immich album |
| `sensor.samsung_immich_rotator_c_current_image` | Sensor | Immich asset ID currently displayed |
| `sensor.samsung_immich_rotator_c_next_rotation` | Sensor | Timestamp of next scheduled rotation |
| `sensor.samsung_immich_rotator_c_last_rotation` | Sensor | Timestamp of last rotation attempt |
| `sensor.samsung_immich_rotator_c_last_rotation_status` | Sensor | `ok` / `error` / `skipped` |

## Services

| Service | Parameters | Description |
|---|---|---|
| `samsung_immich_rotator_c.set_rotation_time` | `time: "HH:MM"` | Change the daily rotation time |
| `samsung_immich_rotator_c.rotate` | — | Trigger a rotation immediately |
| `samsung_immich_rotator_c.wake` | — | Wake TV + enable art mode |
| `samsung_immich_rotator_c.standby` | — | Disable art mode (TV mode) |

## Troubleshooting

### TV does not respond

1. Check the TV is on the same LAN as HA and the IP is correct.
2. Toggle the **Art Mode** switch on — it sends a Wake-on-LAN packet before connecting.
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
