"""Switch entities for Samsung Immich Rotator C."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
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
    """Set up switch entities from a config entry."""
    coordinator: RotatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RotationEnabledSwitch(coordinator), ArtModeSwitch(coordinator)])


class RotationEnabledSwitch(CoordinatorEntity[RotatorCoordinator], SwitchEntity):
    """Master switch — enable or disable all scheduled rotations."""

    _attr_has_entity_name = True
    _attr_name = "Rotation Enabled"
    _attr_icon = "mdi:rotate-right"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_rotation_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Samsung Immich Rotator C",
            manufacturer="Samsung",
            model="The Frame",
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.rotation_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable scheduled rotations."""
        self.coordinator.rotation_enabled = True
        _LOGGER.info("Rotation master switch: ON")
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable scheduled rotations (does not cancel a rotation in progress)."""
        self.coordinator.rotation_enabled = False
        _LOGGER.info("Rotation master switch: OFF")
        self.async_write_ha_state()


class ArtModeSwitch(CoordinatorEntity[RotatorCoordinator], SwitchEntity):
    """Switch between Art Mode (on) and TV/standby (off)."""

    _attr_has_entity_name = True
    _attr_name = "Art Mode"
    _attr_icon = "mdi:television-ambient-light"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_art_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Samsung Immich Rotator C",
            manufacturer="Samsung",
            model="The Frame",
        )

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.art_mode_on

    @property
    def assumed_state(self) -> bool:
        return self.coordinator.art_mode_on is None

    async def async_turn_on(self, **kwargs) -> None:
        """Enable art mode (Wake-on-LAN + set art mode on)."""
        _LOGGER.info("Art Mode switch: ON")
        await self.coordinator.async_wake()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable art mode (panel off, TV mode)."""
        _LOGGER.info("Art Mode switch: OFF")
        await self.coordinator.async_standby()
