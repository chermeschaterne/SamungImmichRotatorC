"""Sensor entities for Samsung Immich Rotator C."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
    """Set up sensor entities from a config entry."""
    coordinator: RotatorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlbumSizeSensor(coordinator),
            CurrentImageSensor(coordinator),
            NextRotationSensor(coordinator),
            LastRotationSensor(coordinator),
            LastRotationStatusSensor(coordinator),
        ]
    )


def _device_info(coordinator: RotatorCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.entry.entry_id)},
        name="Samsung Immich Rotator C",
        manufacturer="Samsung",
        model="The Frame",
    )


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string to a tz-aware datetime.

    Handles both ``+00:00`` (preferred) and legacy ``Z`` suffix formats.
    Falls back to UTC for naive datetimes so HA's timestamp sensor never
    raises ``ValueError: Invalid datetime: missing timezone information``.
    """
    if not value:
        return None
    try:
        raw = value
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


class _RotatorSensorBase(CoordinatorEntity[RotatorCoordinator], SensorEntity):
    """Shared base for all rotator sensors."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RotatorCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = _device_info(coordinator)


class AlbumSizeSensor(_RotatorSensorBase):
    """Number of images in the Immich album."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:image-multiple"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator, "album_size", "Album Size")

    @property
    def native_value(self) -> Optional[int]:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("album_size")

    @property
    def native_unit_of_measurement(self) -> str:
        return "images"


class CurrentImageSensor(_RotatorSensorBase):
    """Current Immich asset ID being displayed on the Frame."""

    _attr_icon = "mdi:image"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator, "current_image", "Current Image")

    @property
    def native_value(self) -> Optional[str]:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("current_immich_id")


class NextRotationSensor(_RotatorSensorBase):
    """Timestamp of the next scheduled rotation."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator, "next_rotation", "Next Rotation")

    @property
    def native_value(self) -> Optional[datetime]:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("next_rotation")


class LastRotationSensor(_RotatorSensorBase):
    """Timestamp of the last rotation attempt."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator, "last_rotation", "Last Rotation")

    @property
    def native_value(self) -> Optional[datetime]:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get("last_rotation")
        return _parse_dt(raw)


class LastRotationStatusSensor(_RotatorSensorBase):
    """Last rotation status: ok / error / skipped."""

    _attr_icon = "mdi:information-outline"

    def __init__(self, coordinator: RotatorCoordinator) -> None:
        super().__init__(coordinator, "last_rotation_status", "Last Rotation Status")

    @property
    def native_value(self) -> Optional[str]:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("last_rotation_status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "last_error": data.get("last_rotation_error"),
            "album_size": data.get("album_size"),
            "current_index": data.get("current_index"),
        }
