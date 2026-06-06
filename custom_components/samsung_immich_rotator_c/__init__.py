"""Samsung Immich Rotator C — HACS custom integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_ROTATION_TIME,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import RotatorCoordinator

_LOGGER = logging.getLogger(__name__)


def _normalize_time(value: object) -> str:
    """Accept ``datetime.time`` or ``'HH:MM[:SS]'`` string; return ``'HH:MM'``."""
    if value is None:
        raise ValueError("time value is required")
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")  # type: ignore[attr-defined]
    if isinstance(value, str):
        s = value.strip()
        if len(s) >= 5 and s[2] == ":":
            return s[:5]
    raise ValueError(f"Invalid time value: {value!r} (expected time object or 'HH:MM[:SS]' string)")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register integration-level services (called once when the domain is loaded)."""
    hass.data.setdefault(DOMAIN, {})

    async def _handle_set_rotation_time(call: ServiceCall) -> None:
        try:
            new_time = _normalize_time(call.data.get("time"))
        except ValueError as exc:
            _LOGGER.error("set_rotation_time: %s", exc)
            return
        for entry in hass.config_entries.async_entries(DOMAIN):
            hass.config_entries.async_update_entry(
                entry,
                options={**entry.options, CONF_ROTATION_TIME: new_time},
            )
            _LOGGER.info("set_rotation_time → %s (entry %s)", new_time, entry.entry_id)

    async def _handle_rotate(call: ServiceCall) -> None:
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if isinstance(coordinator, RotatorCoordinator):
                _LOGGER.info("Service rotate → entry %s", entry_id)
                await coordinator.async_rotate_now()

    async def _handle_wake(call: ServiceCall) -> None:
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if isinstance(coordinator, RotatorCoordinator):
                _LOGGER.info("Service wake → entry %s", entry_id)
                await coordinator.async_wake()

    async def _handle_standby(call: ServiceCall) -> None:
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if isinstance(coordinator, RotatorCoordinator):
                _LOGGER.info("Service standby → entry %s", entry_id)
                await coordinator.async_standby()

    async def _handle_sync_gallery(call: ServiceCall) -> None:
        for entry_id, coordinator in hass.data.get(DOMAIN, {}).items():
            if isinstance(coordinator, RotatorCoordinator):
                _LOGGER.info("Service sync_gallery → entry %s", entry_id)
                await coordinator.async_sync_gallery()

    hass.services.async_register(DOMAIN, "set_rotation_time", _handle_set_rotation_time)
    hass.services.async_register(DOMAIN, "rotate", _handle_rotate)
    hass.services.async_register(DOMAIN, "wake", _handle_wake)
    hass.services.async_register(DOMAIN, "standby", _handle_standby)
    hass.services.async_register(DOMAIN, "sync_gallery", _handle_sync_gallery)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = RotatorCoordinator(hass, entry)

    # Load persisted state + token BEFORE the first refresh.
    # async_load_initial_state does all disk I/O in worker threads.
    await coordinator.async_load_initial_state()

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await coordinator.async_start_listeners()

    entry.async_on_unload(coordinator.async_stop_listeners)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply option changes without reloading — just restart the affected listeners."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(coordinator, RotatorCoordinator):
        coordinator._start_daily_timer()
        await coordinator.async_apply_motion_settings()
