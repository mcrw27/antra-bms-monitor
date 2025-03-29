"""Config flow for Antra BMS.""" 
from __future__ import annotations

import logging
import voluptuous as vol
import serial.tools.list_ports

from typing import Any
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_PORT
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_BAUD_RATE,
    CONF_MAX_BATTERIES,
    DEFAULT_BAUD_RATE,
    DEFAULT_MAX_BATTERIES,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_PORT): str,
    vol.Required(CONF_BAUD_RATE, default=DEFAULT_BAUD_RATE): vol.In(
        [9600, 19200, 38400, 57600, 115200]
    ),
    vol.Required(CONF_MAX_BATTERIES, default=DEFAULT_MAX_BATTERIES): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=15)
    ),
})

class AntraConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Antra."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._ports = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        # Get available ports
        ports = []
        try:
            ports = await self.hass.async_add_executor_job(
                serial.tools.list_ports.comports
            )
            self._ports = [port.device for port in ports]
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Error getting serial ports")
            errors["base"] = "cannot_get_ports"
            self._ports = []

        if user_input is not None:
            # Validate port
            if user_input[CONF_PORT] not in self._ports:
                errors[CONF_PORT] = "invalid_port"
            
            if not errors:
                return self.async_create_entry(
                    title=f"Antra ({user_input[CONF_PORT]})",
                    data=user_input
                )

        schema = self.add_suggested_values_to_schema(
            DATA_SCHEMA,
            user_input or {}
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
