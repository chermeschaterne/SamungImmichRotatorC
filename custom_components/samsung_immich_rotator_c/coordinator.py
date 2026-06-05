"""
DataUpdateCoordinator for Samsung Immich Rotator C.

Lifecycle:
  __init__           — zero I/O; constructs sub-objects with empty defaults.
  async_load_initial_state — load persisted rotation state from disk (called from
                             async_setup_entry before the first refresh).
  _async_update_data — called every 30 min by the coordinator; re-fetches the Immich
                       album list and refreshes entity state.
  async_start_listeners  — wire daily timer + optional motion sensor.
  async_stop_listeners   — called on unload; cancel timer + motion listener.

TV auth token handling:
  The ``samsungtvws`` library reads and writes the token automatically via the
  ``token_file`` parameter — no manual load/save is needed here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BRIGHTNESS,
    CONF_CLIENT_NAME,
    CONF_DISABLE_AMBIENT,
    CONF_FRAME_IP,
    CONF_FRAME_MAC,
    CONF_IMMICH_SHARE_URL,
    CONF_MATTE,
    CONF_MOTION_SENSOR,
    CONF_MOTION_TIMEOUT,
    CONF_ROTATION_TIME,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CLIENT_NAME,
    DEFAULT_DISABLE_AMBIENT,
    DEFAULT_MATTE,
    DEFAULT_MOTION_TIMEOUT,
    DEFAULT_ROTATION_TIME,
    DOMAIN,
    FRAME_PORT,
    STORAGE_DIR,
)
from .frame_client import FrameClient
from .immich_client import ImmichClient
from .state import StateStore

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=30)


class RotatorCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Central coordinator for one configured entry.

    Manages the Immich client, Frame client, state store, daily timer,
    motion listener, and rotation scheduling.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry

        # -- Config-flow data (immutable after setup)
        data = entry.data
        self._frame_ip: str = data[CONF_FRAME_IP]
        self._frame_mac: str = data[CONF_FRAME_MAC]
        self._client_name: str = data.get(CONF_CLIENT_NAME, DEFAULT_CLIENT_NAME)
        self._matte: str = data.get(CONF_MATTE, DEFAULT_MATTE)
        self._share_url: str = data[CONF_IMMICH_SHARE_URL]

        # -- Paths (no I/O here)
        storage_root = Path(hass.config.path(".storage")) / STORAGE_DIR
        self._state_path = storage_root / f"{entry.entry_id}_state.json"
        self._token_path = storage_root / f"{entry.entry_id}_tv_token"
        # Ensure the storage directory exists so the library can write the token file
        storage_root.mkdir(parents=True, exist_ok=True)

        # -- Sub-objects constructed with empty defaults (no I/O in __init__)
        session = async_get_clientsession(hass)
        self.immich = ImmichClient(self._share_url, session)
        self.frame = FrameClient(
            host=self._frame_ip,
            mac=self._frame_mac,
            token_path=str(self._token_path),  # library handles token read/write
            client_name=self._client_name,
            matte=self._matte,
            port=FRAME_PORT,
        )
        self.state_store = StateStore(self._state_path)

        # -- Runtime state
        self._rotation_enabled: bool = True
        self._unsub_daily = None
        self._unsub_motion = None
        self._motion_standby_active: bool = False
        self._motion_timer_handle = None

    # ------------------------------------------------------------------ options helpers

    @property
    def options_rotation_time(self) -> str:
        """Return the configured rotation time as 'HH:MM'."""
        return self.entry.options.get(CONF_ROTATION_TIME, DEFAULT_ROTATION_TIME)

    @property
    def options_brightness(self) -> int:
        """Return the configured brightness level (1-10)."""
        return int(self.entry.options.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS))

    @property
    def options_disable_ambient(self) -> bool:
        """Return whether the ambient-light sensor should be disabled."""
        return bool(self.entry.options.get(CONF_DISABLE_AMBIENT, DEFAULT_DISABLE_AMBIENT))

    @property
    def options_motion_sensor(self) -> str:
        """Return the configured motion sensor entity_id, or empty string."""
        return self.entry.options.get(CONF_MOTION_SENSOR, "")

    @property
    def options_motion_timeout(self) -> int:
        """Return the motion timeout in minutes."""
        return int(self.entry.options.get(CONF_MOTION_TIMEOUT, DEFAULT_MOTION_TIMEOUT))

    @property
    def rotation_enabled(self) -> bool:
        return self._rotation_enabled

    @rotation_enabled.setter
    def rotation_enabled(self, value: bool) -> None:
        self._rotation_enabled = value

    # ------------------------------------------------------------------ next rotation timestamp

    def next_rotation_dt(self) -> Optional[datetime]:
        """Return the next scheduled rotation as a tz-aware datetime, or None."""
        try:
            h, m = (int(x) for x in self.options_rotation_time.split(":")[:2])
        except (ValueError, AttributeError):
            return None
        now = datetime.now(timezone.utc)
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)
        return candidate

    # ------------------------------------------------------------------ async init (called from __init__.py)

    async def async_load_initial_state(self) -> None:
        """Load persisted rotation state from disk.

        Must be awaited from ``async_setup_entry`` AFTER construction and
        BEFORE ``async_config_entry_first_refresh``. Never called from __init__.
        The TV auth token is managed by the samsungtvws library (token_file).
        """
        await self.state_store.load()

    # ------------------------------------------------------------------ coordinator data refresh

    async def _async_update_data(self) -> Dict[str, Any]:
        """Refresh album asset list and build the data dict for entities.

        Called every UPDATE_INTERVAL. Does NOT trigger a rotation.
        Raises ``UpdateFailed`` on unrecoverable errors.
        """
        try:
            assets = await self.immich.list_assets()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to refresh Immich album: %s", exc)
            raise UpdateFailed(f"Immich unreachable: {exc}") from exc

        asset_ids = [a.id for a in assets]
        await self.state_store.update_assets(asset_ids)

        s = self.state_store.state
        return {
            "album_size": len(assets),
            "current_immich_id": s.current_immich_id,
            "next_rotation": self.next_rotation_dt(),
            "last_rotation": s.last_rotation,
            "last_rotation_status": s.last_rotation_status,
            "last_rotation_error": s.last_rotation_error,
            "current_index": s.current_index,
            "rotation_enabled": self._rotation_enabled,
        }

    # ------------------------------------------------------------------ listeners

    async def async_start_listeners(self) -> None:
        """Start the daily timer and optional motion listener."""
        self._start_daily_timer()
        self._start_motion_listener()

    @callback
    def async_stop_listeners(self) -> None:
        """Cancel all event listeners (called on entry unload)."""
        if self._unsub_daily is not None:
            self._unsub_daily()
            self._unsub_daily = None
        if self._unsub_motion is not None:
            self._unsub_motion()
            self._unsub_motion = None
        if self._motion_timer_handle is not None:
            self._motion_timer_handle.cancel()
            self._motion_timer_handle = None

    def _start_daily_timer(self) -> None:
        if self._unsub_daily is not None:
            self._unsub_daily()
            self._unsub_daily = None

        try:
            h, m = (int(x) for x in self.options_rotation_time.split(":")[:2])
        except (ValueError, AttributeError):
            _LOGGER.error(
                "Invalid rotation_time %r — daily timer not started",
                self.options_rotation_time,
            )
            return

        self._unsub_daily = async_track_time_change(
            self.hass,
            self._handle_daily_rotation,
            hour=h,
            minute=m,
            second=0,
        )
        _LOGGER.info("Daily rotation timer set for %02d:%02d:00", h, m)

    def _start_motion_listener(self) -> None:
        if self._unsub_motion is not None:
            self._unsub_motion()
            self._unsub_motion = None

        entity_id = self.options_motion_sensor
        if not entity_id:
            return

        self._unsub_motion = async_track_state_change_event(
            self.hass,
            [entity_id],
            self._handle_motion_event,
        )
        _LOGGER.info("Motion listener attached to %s (timeout=%d min)", entity_id, self.options_motion_timeout)

    # ------------------------------------------------------------------ event handlers

    @callback
    def _handle_daily_rotation(self, now) -> None:
        """Fire a rotation if the master switch is on."""
        if not self._rotation_enabled:
            _LOGGER.info("Daily rotation skipped — master switch is off")
            return
        _LOGGER.info("Daily rotation triggered at %s", now)
        self.hass.async_create_task(self._run_rotation_task())

    @callback
    def _handle_motion_event(self, event: Event) -> None:
        """React to motion sensor state changes."""
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        state_value = new_state.state

        if state_value == "on":
            # Motion detected — cancel standby timer, wake TV if needed
            if self._motion_timer_handle is not None:
                self._motion_timer_handle.cancel()
                self._motion_timer_handle = None
            if self._motion_standby_active:
                _LOGGER.info("Motion detected — waking Frame")
                self.hass.async_create_task(self._wake_task())
        elif state_value == "off":
            # Motion cleared — start countdown to standby
            timeout_seconds = self.options_motion_timeout * 60
            _LOGGER.debug(
                "Motion off — standby in %d min", self.options_motion_timeout
            )
            if self._motion_timer_handle is not None:
                self._motion_timer_handle.cancel()
            self._motion_timer_handle = self.hass.loop.call_later(
                timeout_seconds, self._motion_standby_callback
            )

    @callback
    def _motion_standby_callback(self) -> None:
        """Put the TV in standby after the motion timeout fires."""
        self._motion_timer_handle = None
        _LOGGER.info("Motion timeout elapsed — putting Frame in standby")
        self.hass.async_create_task(self._standby_task())

    # ------------------------------------------------------------------ action tasks

    async def _run_rotation_task(self) -> None:
        from .rotation import run_rotation
        try:
            await run_rotation(self)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Rotation task raised: %s", exc)

    async def _wake_task(self) -> None:
        """Wake the TV and enable art mode."""
        connected = await self.frame.connect(wake_if_needed=True)
        if connected:
            await self.frame.set_art_mode(True)
            self._motion_standby_active = False
        await self.frame.close()
        self.async_update_listeners()

    async def _standby_task(self) -> None:
        """Disable art mode (panel off)."""
        connected = await self.frame.connect(wake_if_needed=False)
        if connected:
            await self.frame.set_art_mode(False)
            self._motion_standby_active = True
        await self.frame.close()
        self.async_update_listeners()

    # ------------------------------------------------------------------ public action API (called by entities/services)

    async def async_rotate_now(self) -> None:
        """Trigger a rotation immediately (ignores master switch)."""
        await self._run_rotation_task()
        await self.async_refresh()

    async def async_wake(self) -> None:
        """Send WoL + enable art mode."""
        await self._wake_task()

    async def async_standby(self) -> None:
        """Disable art mode (panel off)."""
        await self._standby_task()
