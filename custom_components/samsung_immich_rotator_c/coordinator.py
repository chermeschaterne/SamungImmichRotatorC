"""
DataUpdateCoordinator for Samsung Immich Rotator C.

Lifecycle:
  __init__           — zero I/O; constructs sub-objects with empty defaults.
  async_load_initial_state — load persisted state + TV token from disk (called from
                             async_setup_entry before the first refresh).
  _async_update_data — called every 30 min by the coordinator; re-fetches the Immich
                       album list and refreshes entity state.
  async_start_listeners  — wire daily timer + optional motion sensor.
  async_stop_listeners   — called on unload; cancel timer + motion listener.
"""
from __future__ import annotations

import asyncio
import logging
import os
import stat
from datetime import datetime, time as dt_time, timedelta, timezone
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
    CONF_MOTION_ENABLED,
    CONF_MOTION_SENSITIVITY,
    CONF_ROTATION_TIME,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CLIENT_NAME,
    DEFAULT_DISABLE_AMBIENT,
    DEFAULT_MATTE,
    DEFAULT_MOTION_ENABLED,
    DEFAULT_MOTION_SENSITIVITY,
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

        # -- Sub-objects constructed with empty defaults (no I/O in __init__)
        session = async_get_clientsession(hass)
        self.immich = ImmichClient(self._share_url, session)
        self.frame = FrameClient(
            host=self._frame_ip,
            mac=self._frame_mac,
            client_name=self._client_name,
            matte=self._matte,
            token=None,  # loaded in async_load_initial_state
            port=FRAME_PORT,
        )
        self.state_store = StateStore(self._state_path)

        # -- Runtime state
        self._rotation_enabled: bool = True
        self._unsub_daily = None

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
    def options_motion_enabled(self) -> bool:
        """Return whether the TV's motion sensor should be enabled."""
        return bool(self.entry.options.get(CONF_MOTION_ENABLED, DEFAULT_MOTION_ENABLED))

    @property
    def options_motion_sensitivity(self) -> int:
        """Return the configured motion sensitivity level (1-3)."""
        return int(self.entry.options.get(CONF_MOTION_SENSITIVITY, DEFAULT_MOTION_SENSITIVITY))

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
        """Load persisted state and TV auth token from disk.

        Must be awaited from ``async_setup_entry`` AFTER construction and
        BEFORE ``async_config_entry_first_refresh``. Never called from __init__.
        """
        await self.state_store.load()
        await self._load_token()

    async def _load_token(self) -> None:
        """Load the TV auth token from disk into the FrameClient."""
        try:
            token = await asyncio.to_thread(self._sync_load_token)
            if token:
                self.frame.token = token
                _LOGGER.info("Loaded TV token from %s", self._token_path)
        except OSError as exc:
            _LOGGER.debug("No saved TV token (%s)", exc)

    def _sync_load_token(self) -> Optional[str]:
        if self._token_path.exists():
            return self._token_path.read_text(encoding="utf-8").strip() or None
        return None

    async def _save_token(self) -> None:
        """Persist the current TV token to disk with restricted permissions."""
        if self.frame.token:
            await asyncio.to_thread(self._sync_save_token, self.frame.token)

    def _sync_save_token(self, token: str) -> None:
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(token, encoding="utf-8")
        os.chmod(self._token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

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
        """Start the daily timer and apply initial motion settings."""
        self._start_daily_timer()
        await self.async_apply_motion_settings()

    @callback
    def async_stop_listeners(self) -> None:
        """Cancel all event listeners (called on entry unload)."""
        if self._unsub_daily is not None:
            self._unsub_daily()
            self._unsub_daily = None

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

    # ------------------------------------------------------------------ event handlers

    @callback
    def _handle_daily_rotation(self, now) -> None:
        """Fire a rotation if the master switch is on."""
        if not self._rotation_enabled:
            _LOGGER.info("Daily rotation skipped — master switch is off")
            return
        _LOGGER.info("Daily rotation triggered at %s", now)
        self.hass.async_create_task(self._run_rotation_task())

    # ------------------------------------------------------------------ action tasks

    async def _run_rotation_task(self) -> None:
        """Wrap the rotation engine and save any new token afterward."""
        from .rotation import run_rotation
        try:
            await run_rotation(self)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Rotation task raised: %s", exc)
        await self._save_token()

    async def _wake_task(self) -> None:
        """Wake the TV and enable art mode."""
        connected = await self.frame.connect(wake_if_needed=True)
        if connected:
            await self.frame.set_art_mode(True)
            await self._save_token()
        await self.frame.close()
        self.async_update_listeners()

    async def _standby_task(self) -> None:
        """Disable art mode (panel off)."""
        connected = await self.frame.connect(wake_if_needed=False)
        if connected:
            await self.frame.set_art_mode(False)
        await self.frame.close()
        self.async_update_listeners()

    async def async_apply_motion_settings(self) -> None:
        """Apply motion sensor settings to the TV (called on setup and options change)."""
        connected = await self.frame.connect(wake_if_needed=False)
        if not connected:
            _LOGGER.warning("Cannot apply motion settings — Frame not reachable")
            return

        await self.frame.set_motion_detection(self.options_motion_enabled)
        if self.options_motion_enabled:
            await self.frame.set_motion_sensitivity(self.options_motion_sensitivity)

        await self.frame.close()
        _LOGGER.info(
            "Applied motion settings: enabled=%s, sensitivity=%d",
            self.options_motion_enabled,
            self.options_motion_sensitivity,
        )

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

    async def async_sync_gallery(self) -> None:
        """Sync the Frame gallery with the Immich album (wipe + repull)."""
        _LOGGER.info("Starting gallery sync (wipe + repull from Immich)")

        # Step 1: Fetch album from Immich
        try:
            assets = await self.immich.list_assets()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Sync gallery: failed to fetch Immich album: %s", exc)
            return

        if not assets:
            _LOGGER.warning("Sync gallery: Immich album is empty — nothing to upload")
            return

        # Step 2: Connect to Frame
        connected = await self.frame.connect(wake_if_needed=True)
        if not connected:
            _LOGGER.error("Sync gallery: Frame unreachable")
            return

        # Step 3: Wipe existing gallery
        try:
            existing = await self.frame.list_available_artworks()
            for art in existing:
                content_id = art.get("content_id")
                if content_id:
                    await self.frame.delete_artwork(content_id)
            _LOGGER.info("Sync gallery: deleted %d existing artworks", len(existing))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Sync gallery: failed to wipe gallery: %s", exc)
            await self.frame.close()
            return

        # Step 4: Upload all assets from Immich
        uploaded_count = 0
        new_uploaded = {}
        for asset in assets:
            try:
                raw_bytes = await self.immich.download_original(asset.id)
                content_id = await self.frame.upload_image(raw_bytes)
                if content_id:
                    new_uploaded[asset.id] = content_id
                    uploaded_count += 1
                    _LOGGER.info("Sync gallery: uploaded %d/%d", uploaded_count, len(assets))
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Sync gallery: failed to upload %s: %s", asset.id, exc)

        await self.frame.close()

        # Step 5: Update state with the new gallery
        asset_ids = [a.id for a in assets]
        await self.state_store.update_assets(asset_ids)

        # Clear old uploaded mapping and set the new one
        self.state_store.state.uploaded = new_uploaded
        await self.state_store.save()

        _LOGGER.info("Sync gallery: complete (%d/%d uploaded)", uploaded_count, len(assets))
        await self.async_refresh()
