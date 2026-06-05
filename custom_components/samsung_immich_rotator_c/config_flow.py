"""Config flow and options flow for Samsung Immich Rotator C."""
from __future__ import annotations

import logging
from datetime import time as dt_time
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import selector

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
    MATTE_OPTIONS,
)
from .immich_client import ImmichClient, ImmichError

_LOGGER = logging.getLogger(__name__)


def _normalize_time(value: object) -> str:
    """Accept a ``datetime.time`` or ``'HH:MM[:SS]'`` string; return ``'HH:MM'``."""
    if value is None:
        return DEFAULT_ROTATION_TIME
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")  # type: ignore[attr-defined]
    if isinstance(value, str):
        s = value.strip()
        if len(s) >= 5 and s[2] == ":":
            return s[:5]
    _LOGGER.warning("Unexpected time value %r, falling back to default", value)
    return DEFAULT_ROTATION_TIME


def _time_to_dt(time_str: str) -> dt_time:
    """Convert a stored 'HH:MM' string to a ``datetime.time`` for use as a selector default."""
    try:
        h, m = (int(x) for x in time_str.split(":")[:2])
        return dt_time(h, m, 0)
    except (ValueError, AttributeError):
        return dt_time(6, 0, 0)


class SamsungImmichRotatorConfigFlow(  # type: ignore[call-arg]
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle the initial setup config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
        """Present the setup form and validate on submit."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            share_url = user_input[CONF_IMMICH_SHARE_URL].strip()
            frame_ip = user_input[CONF_FRAME_IP].strip()
            frame_mac = user_input[CONF_FRAME_MAC].strip()
            client_name = user_input.get(CONF_CLIENT_NAME, DEFAULT_CLIENT_NAME).strip()
            matte = user_input.get(CONF_MATTE, DEFAULT_MATTE)

            # Validate the Immich share URL
            session = async_get_clientsession(self.hass)
            immich = ImmichClient(share_url, session)
            try:
                await immich.validate_share()
            except ImmichError as exc:
                _LOGGER.warning("Immich share validation failed: %s", exc)
                errors["immich_share_url"] = "invalid_immich_share"
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Unexpected error validating Immich share: %s", exc)
                errors["base"] = "unknown"

            if not errors:
                unique_id = f"{share_url}|{frame_ip}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Frame @ {frame_ip}",
                    data={
                        CONF_IMMICH_SHARE_URL: share_url,
                        CONF_FRAME_IP: frame_ip,
                        CONF_FRAME_MAC: frame_mac,
                        CONF_CLIENT_NAME: client_name,
                        CONF_MATTE: matte,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_IMMICH_SHARE_URL): str,
                vol.Required(CONF_FRAME_IP): str,
                vol.Required(CONF_FRAME_MAC): str,
                vol.Optional(CONF_CLIENT_NAME, default=DEFAULT_CLIENT_NAME): str,
                vol.Optional(CONF_MATTE, default=DEFAULT_MATTE): selector(
                    {
                        "select": {
                            "options": MATTE_OPTIONS,
                            "mode": "dropdown",
                        }
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return SamsungImmichRotatorOptionsFlow(config_entry)


class SamsungImmichRotatorOptionsFlow(config_entries.OptionsFlow):
    """Handle runtime option changes (Configure menu)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
        """Show the options form and save on submit."""
        if user_input is not None:
            # Normalise the time field — selector may return datetime.time or string
            raw_time = user_input.get(CONF_ROTATION_TIME)
            user_input[CONF_ROTATION_TIME] = _normalize_time(raw_time)
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options
        current_time_str = current.get(CONF_ROTATION_TIME, DEFAULT_ROTATION_TIME)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ROTATION_TIME,
                    default=_time_to_dt(current_time_str),
                ): selector({"time": {}}),
                vol.Optional(
                    CONF_BRIGHTNESS,
                    default=int(current.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)),
                ): selector(
                    {"number": {"min": 1, "max": 10, "step": 1, "mode": "slider"}}
                ),
                vol.Optional(
                    CONF_DISABLE_AMBIENT,
                    default=bool(current.get(CONF_DISABLE_AMBIENT, DEFAULT_DISABLE_AMBIENT)),
                ): selector({"boolean": {}}),
                vol.Optional(
                    CONF_MOTION_SENSOR,
                    default=current.get(CONF_MOTION_SENSOR, ""),
                ): selector({"entity": {"domain": "binary_sensor"}}),
                vol.Optional(
                    CONF_MOTION_TIMEOUT,
                    default=int(current.get(CONF_MOTION_TIMEOUT, DEFAULT_MOTION_TIMEOUT)),
                ): selector(
                    {"number": {"min": 1, "max": 120, "step": 1, "unit_of_measurement": "min"}}
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
