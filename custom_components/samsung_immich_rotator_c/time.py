"""Time entity for Samsung Immich Rotator C — rotation schedule picker."""
from __future__ import annotations

import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROTATION_TIME, DEFAULT_ROTATION_TIME, DOMAIN
from .coordinator import RotatorCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities from a config entry."""
    coordinator: RotatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RotationTimeEntity(coordinator)])


class RotationTimeEntity(CoordinatorEntity[RotatorCoordinator], TimeEntity):
    """Time picker for the daily rotation schedule.

    Displayed as a native time control on the HA dashboard.
    Changing the value takes effect immediately — no restart required.
    """

    _attr_has_entity_name = True
    _attr_name = "Rotation Time"
    _attr_icon = "mdi:clock-edit-outline"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_rotation_time"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="Samsung Immich Rotator C",
            manufacturer="Samsung",
            model="The Frame",
        )

    @property
    def native_value(self) -> dt_time | None:
        time_str = self.coordinator.options_rotation_time
        try:
            h, m = (int(x) for x in time_str.split(":")[:2])
            return dt_time(h, m, 0)
        except (ValueError, AttributeError):
            h, m = (int(x) for x in DEFAULT_ROTATION_TIME.split(":"))
            return dt_time(h, m, 0)

    async def async_set_value(self, value: dt_time) -> None:
        """Update the daily rotation time."""
        new_time = value.strftime("%H:%M")
        self.hass.config_entries.async_update_entry(
            self.coordinator.entry,
            options={**self.coordinator.entry.options, CONF_ROTATION_TIME: new_time},
        )
        _LOGGER.info("Rotation time updated to %s", new_time)
        self.async_write_ha_state()
