"""Button entities for Samsung Immich Rotator C."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RotatorCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    coordinator: RotatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RotateNowButton(coordinator),
            WakeFrameButton(coordinator),
            StandbyButton(coordinator),
        ]
    )


def _device_info(coordinator: RotatorCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.entry.entry_id)},
        name="Samsung Immich Rotator C",
        manufacturer="Samsung",
        model="The Frame",
    )


class RotateNowButton(CoordinatorEntity[RotatorCoordinator], ButtonEntity):
    """Trigger a rotation immediately (ignores master switch)."""

    _attr_has_entity_name = True
    _attr_name = "Rotate Now"
    _attr_icon = "mdi:image-sync"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_rotate_now"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        """Execute a rotation right now."""
        _LOGGER.info("Rotate Now button pressed")
        await self.coordinator.async_rotate_now()


class WakeFrameButton(CoordinatorEntity[RotatorCoordinator], ButtonEntity):
    """Send Wake-on-LAN and enable art mode."""

    _attr_has_entity_name = True
    _attr_name = "Wake Frame"
    _attr_icon = "mdi:television-play"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_wake_frame"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        """Wake the TV and enable art mode."""
        _LOGGER.info("Wake Frame button pressed")
        await self.coordinator.async_wake()


class StandbyButton(CoordinatorEntity[RotatorCoordinator], ButtonEntity):
    """Disable art mode (panel off, but still addressable)."""

    _attr_has_entity_name = True
    _attr_name = "Standby"
    _attr_icon = "mdi:television-off"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_standby"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        """Put the TV in standby."""
        _LOGGER.info("Standby button pressed")
        await self.coordinator.async_standby()
