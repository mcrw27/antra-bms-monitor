"""Antra BMS sensors.""" 
from __future__ import annotations
from homeassistant.const import UnitOfTemperature
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_PORT,
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_BAUD_RATE, CONF_MAX_BATTERIES
from .coordinator import AntraDataCoordinator

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Antra sensor platform."""
    import serial_asyncio

    _LOGGER.debug(
        "Setting up Antra sensor platform with config: port=%s, baud=%s, max_batteries=%s",
        entry.data[CONF_PORT],
        entry.data[CONF_BAUD_RATE],
        entry.data[CONF_MAX_BATTERIES],
    )

    port = entry.data[CONF_PORT]
    baud_rate = entry.data[CONF_BAUD_RATE]
    max_batteries = entry.data[CONF_MAX_BATTERIES]

    try:
        _LOGGER.debug("Opening serial connection to %s at %s baud", port, baud_rate)
        reader, writer = await serial_asyncio.open_serial_connection(url=port, baudrate=baud_rate)
        _LOGGER.debug("Successfully opened serial connection")
    except Exception as err:
        _LOGGER.error("Error opening serial connection: %s", err)
        return

    coordinator = AntraDataCoordinator(
        hass,
        reader,
        writer,
        max_batteries,
        group_number=entry.data.get("group_number", 0),  # 0 for single group
        update_interval=timedelta(seconds=30),
    )

    # Do first update
    _LOGGER.debug("Performing first coordinator refresh")
    await coordinator.async_config_entry_first_refresh()

    entities = []
    
    # Create entities for each battery - user sees batteries 1..max_batteries.
    # We assume coordinator.data is a dict keyed by battery number (1, 2, 3, …)
    for battery_num in range(1, max_batteries + 1):
        _LOGGER.debug("Setting up sensors for battery %d", battery_num)

        # Pack voltage sensor (key "voltage")
        entities.append(
            AntraVoltageSensor(
                coordinator,
                battery_num,
                "voltage",
                "Pack Voltage",
                UnitOfElectricPotential.VOLT,
            )
        )
        #_LOGGER.debug("Added pack voltage sensor for battery %d", battery_num)

        # Current sensor
        entities.append(AntraCurrentSensor(coordinator, battery_num))
        #_LOGGER.debug("Added current sensor for battery %d", battery_num)

        # Cell voltage sensors – use key "cells"
        battery_data = coordinator.data.get(battery_num)
        if battery_data:
            cell_voltages = battery_data.get("cell_voltages", [])
            num_cells = len(cell_voltages)
            #_LOGGER.debug("Battery %d has %d cells", battery_num, num_cells)
            for cell_num in range(num_cells):
                entities.append(AntraCellVoltageSensor(coordinator, battery_num, cell_num))
            #_LOGGER.debug("Added %d cell voltage sensors for battery %d", num_cells, battery_num)
        else:
            _LOGGER.warning("No data available for battery %d during setup", battery_num)
            
        # Additional voltage sensors for descriptive fields (reuse the same voltage sensor class)
        # These keys must be provided by your updated _transform_battery_data method.
        entities.append(
            AntraVoltageSensor(
                coordinator,
                battery_num,
                "max_cell_voltage",
                "Max Cell Voltage",
                "mV",
            )
        )
        entities.append(
            AntraVoltageSensor(
                coordinator,
                battery_num,
                "min_cell_voltage",
                "Min Cell Voltage",
                "mV",
            )
        )
        entities.append(
            AntraVoltageSensor(
                coordinator,
                battery_num,
                "average_cell_voltage",
                "Average Cell Voltage",
                "mV",
            )
        )
        entities.append(
            AntraCapacitySensor(
                coordinator,
                battery_num,
                "total_charge",
                "Total Charge"
            )
        )
        entities.append(
            AntraCapacitySensor(
                coordinator,
                battery_num,
                "total_discharge",
                "Total Discharge"
            )
        )
        #_LOGGER.debug("Added additional voltage sensors for battery %d", battery_num)
        
        # Final batch: Unknown fields (p22, p24, p26, p28, p30) as numeric sensors.
        # We are not sure of their meaning, so we leave them as numeric.
        unknown_fields = [
            ("max_cell_temp", "Max Cell Temp"),
            ("min_cell_temp", "Min Cell Temp"),
            ("unknown_3", "Unknown 3"),
            ("unknown_4", "Unknown 4"),
            ("avg_cell_temp", "Average Cell Temp"),
        ]
        for data_key, friendly_name in unknown_fields:
            add_numeric_sensor(entities, coordinator, battery_num, data_key, friendly_name)
            #_LOGGER.debug("Added %s sensor for battery %d", friendly_name, battery_num)
            
        # --- Temperature Sensors ---

        # Individual temperature sensors:
        entities.append(AntraAmbientTemperatureSensor(coordinator, battery_num))
        #_LOGGER.debug("Added Ambient Temperature sensor for battery %d", battery_num)

        entities.append(AntraPackAvgTemperatureSensor(coordinator, battery_num))
        #_LOGGER.debug("Added Pack Average Temperature sensor for battery %d", battery_num)

        entities.append(AntraMOSTemperatureSensor(coordinator, battery_num))
        #_LOGGER.debug("Added MOS Temperature sensor for battery %d", battery_num)

        # Pack temperature sensors (from the array in "temperatures")
        if battery_data:
            pack_temps = battery_data.get("temperatures", [])
            temp_count = len(pack_temps)
            #_LOGGER.debug("Battery %d has %d pack temperature sensor(s)", battery_num, temp_count)
            for temp_num in range(temp_count):
                sensor_name = f"Pack Temperature Sensor {temp_num + 1}"
                entities.append(
                    AntraTemperatureSensor(coordinator, battery_num, temp_num, sensor_name)
                )
                #_LOGGER.debug("Added %s for battery %d", sensor_name, battery_num)
        else:
            _LOGGER.warning("No battery data available for pack temperature sensors on battery %d", battery_num)

            
        # SOC sensor
        entities.append(AntraSocSensor(coordinator, battery_num))
        #_LOGGER.debug("Added SOC sensor for battery %d", battery_num)

        # Internal Resistance sensor
        entities.append(AntraInternalResistanceSensor(coordinator, battery_num))
        #_LOGGER.debug("Added Internal Resistance sensor for battery %d", battery_num)

        # SOH sensor
        entities.append(AntraSOHSensor(coordinator, battery_num))
        #_LOGGER.debug("Added SOH sensor for battery %d", battery_num)

        # Full Capacity sensor
        entities.append(AntraFullCapacitySensor(coordinator, battery_num))
        #_LOGGER.debug("Added Full Capacity sensor for battery %d", battery_num)

        # Remaining Capacity sensor
        entities.append(AntraRemainingCapacitySensor(coordinator, battery_num))
        #_LOGGER.debug("Added Remaining Capacity sensor for battery %d", battery_num)

        # Cycle Count sensor
        entities.append(AntraCycleCountSensor(coordinator, battery_num))
        #_LOGGER.debug("Added Cycle Count sensor for battery %d", battery_num)

        # Status sensors (voltage, current, temperature, alarm, FET)
        # Status sensors (voltage, current, temperature, alarm, FET)
        status_definitions = [
            ("voltage", "Voltage Status", voltage_status_mapping),
            ("current", "Current Status", current_status_mapping),
            ("temperature", "Temperature Status", temperature_status_mapping),
            ("alarm", "Alarm Status", alarm_status_mapping),
        ]
        for key, name, mapping in status_definitions:
            # Add both raw and decoded sensors
            entities.append(AntraStatusRawSensor(coordinator, battery_num, key, name))
            entities.append(AntraStatusDecodedSensor(coordinator, battery_num, key, name, mapping))

        # Special handling for FET status which has its own format
        entities.append(AntraFETStatusRawSensor(coordinator, battery_num))
        entities.append(AntraFETStatusDecodedSensor(coordinator, battery_num))

        # Protection sensors (overvoltage_protect, undervoltage_protect, overvoltage_alarm, undervoltage_alarm)
        protection_definitions = [
            ("overvoltage_protect", "Overvoltage Protection"),
            ("undervoltage_protect", "Undervoltage Protection"),
            ("overvoltage_alarm", "Overvoltage Alarm"),
            ("undervoltage_alarm", "Undervoltage Alarm"),
            ("balance_status", "Balance Status"),
        ]
        for key, name in protection_definitions:
        # Add both raw and decoded sensors
            entities.append(AntraProtectStatusRawSensor(coordinator, battery_num, key, name))
            entities.append(AntraProtectStatusDecodedSensor(coordinator, battery_num, key, name))
            
    # Add pack header sensors (one sensor per header field)
    for data_key, friendly_name, unit in pack_header_definitions:
        entities.append(AntraPackHeaderSensor(coordinator, data_key, friendly_name, unit))
        _LOGGER.debug("Added pack header sensor: %s", friendly_name)

    _LOGGER.info("Adding %d total Antra entities", len(entities))
    async_add_entities(entities)
    _LOGGER.debug("Completed Antra sensor platform setup")
    
class AntraBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for Antra sensors."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        # We assume the coordinator's data is keyed by battery number (1-based)
        self._display_num = battery_num  # User-facing number (1-based)
        self._battery_num = battery_num   # Use the same key for data lookup
        self._attr_has_entity_name = True
        #_LOGGER.debug(
        #    "Initializing sensor for battery %d (coordinator data available: %s)",
        #    self._display_num,
        #    bool(coordinator.data and (self._battery_num in coordinator.data)),
        #)

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, f"battery_{self._display_num}")},
            "name": f"Antra Battery {self._display_num}",
            "manufacturer": "Antra",
            "model": "US2000/US3000",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        coordinator_data = self.coordinator.data
        is_available = (
            self.coordinator.last_update_success
            and coordinator_data
            and (self._battery_num in coordinator_data)
        )
        if not is_available:
            _LOGGER.debug(
                "Sensor for battery %d unavailable (coordinator success: %s, battery in data: %s)",
                self._display_num,
                self.coordinator.last_update_success,
                bool(coordinator_data and (self._battery_num in coordinator_data)),
            )
        return is_available

class AntraPackHeaderSensor(CoordinatorEntity, SensorEntity):
    """Sensor for one field from the Antra pack header (group) data."""
    
    def __init__(self, coordinator, data_key: str, name: str, unit: str | None = None) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._data_key = data_key
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = True
        
        # For SOC sensor, set it as the device class battery to show in device status
        if data_key == "soc":
            self._attr_device_class = SensorDeviceClass.BATTERY

    @property
    def unique_id(self) -> str:
        """Return unique ID for the sensor."""
        return f"Antra_group_{self._data_key}"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, "Antra_group")},
            "name": "Antra Battery Group",
            "manufacturer": "Antra",
            "model": "US2000/US3000 Group"
        }
        
    @property
    def entity_registry_enabled_default(self) -> bool:
        """Indicate if entity should be enabled by default."""
        # You might want to hide some sensors by default
        return True

    @property 
    def native_value(self):
        """Return the sensor value."""
        group_data = self.coordinator.data.get("group")
        if group_data:
            return group_data.get(self._data_key)
        return None
    
pack_header_definitions = [
    # (data_key, friendly name, unit)
    ("voltage", "System Voltage", UnitOfElectricPotential.VOLT),
    ("current", "System Current", UnitOfElectricCurrent.AMPERE),
    ("total_capacity", "Total Capacity", "Ah"),  
    ("remaining_capacity", "Remaining Capacity", "Ah"),
    ("soc", "System SOC", PERCENTAGE),
    ("max_ambient_temp", "Max Ambient Temperature", UnitOfTemperature.CELSIUS),
    ("min_ambient_temp", "Min Ambient Temperature", UnitOfTemperature.CELSIUS),
    ("max_cell_voltage", "Max Cell Voltage", "mV"),  # assuming proper conversion
    ("min_cell_voltage", "Min Cell Voltage", "mV"),
    ("temperature_min", "Pack Temperature Minimum", UnitOfTemperature.CELSIUS),
    ("temperature_max", "Pack  Temperature Maximum", UnitOfTemperature.CELSIUS),
    ("cell_count", "Cell Count", None),
    ("battery_count", "Battery Count", None),
    ("reserved", "Reserved", None),    
]
    
class AntraCapacitySensor(AntraBaseSensor):
    """Sensor for battery capacity measurements."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._data_key = data_key
        self._attr_name = name
        self._attr_native_unit_of_measurement = "Ah"
        self._attr_device_class = None  # Remove voltage device class
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_{self._data_key}"

    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get(self._data_key)
        return None
    
class AntraVoltageSensor(AntraBaseSensor):
    """Sensor for pack voltage."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str, unit: str) -> None:
        """Initialize the voltage sensor."""
        super().__init__(coordinator, battery_num)
        self._data_key = data_key  # Expecting "voltage"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"Antra_{self._display_num}_{self._data_key}"

    @property
    def native_value(self):
        """Return the pack voltage value."""
        if self.available:
            return self.coordinator.data[self._battery_num].get(self._data_key)
        return None


class AntraCurrentSensor(AntraBaseSensor):
    """Sensor for battery current."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        """Initialize the current sensor."""
        super().__init__(coordinator, battery_num)
        self._attr_name = "Current"
        self._attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
        self._attr_device_class = SensorDeviceClass.CURRENT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"Antra_{self._display_num}_current"

    @property
    def native_value(self):
        """Return the current value with signed conversion if needed."""
        if self.available:
            raw_current = self.coordinator.data[self._battery_num].get("current")
            if raw_current is not None:
                # Assuming the raw value is already converted on the coordinator side,
                # simply return it here.
                return raw_current
        return None


class AntraCellVoltageSensor(AntraBaseSensor):
    """Sensor for individual cell voltages."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, cell_num: int) -> None:
        """Initialize the cell voltage sensor."""
        super().__init__(coordinator, battery_num)
        self._cell_num = cell_num
        self._attr_name = f"Cell {cell_num + 1} Voltage"  # Display cells as 1-based
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"Antra_{self._display_num}_cell_{self._cell_num}_voltage"

    @property
    def native_value(self):
        """Return the cell voltage value."""
        if self.available:
            cell_voltages = self.coordinator.data[self._battery_num].get("cell_voltages", [])
            if 0 <= self._cell_num < len(cell_voltages):
                return cell_voltages[self._cell_num]
        return None


class AntraTemperatureSensor(AntraBaseSensor):
    """Sensor for temperature values."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, temp_num: int, name: str) -> None:
        """Initialize the temperature sensor."""
        super().__init__(coordinator, battery_num)
        self._temp_num = temp_num
        self._attr_name = name
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"Antra_{self._display_num}_temp_{self._temp_num}"

    @property
    def native_value(self):
        """Return the temperature value (already converted on the coordinator side)."""
        if self.available:
            temps = self.coordinator.data[self._battery_num].get("temperatures", [])
            if 0 <= self._temp_num < len(temps):
                return temps[self._temp_num]
        return None
    
from homeassistant.const import PERCENTAGE

# --- Battery Level and Health Sensors ---

class AntraSocSensor(AntraBaseSensor):
    """Sensor for battery State of Charge (SOC)."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "State of Charge"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_soc"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("soc")
        return None


class AntraInternalResistanceSensor(AntraBaseSensor):
    """Sensor for battery internal resistance."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Internal Resistance"
        # Adjust the unit as appropriate (for example, "mΩ" if your value is in milliohms)
        self._attr_native_unit_of_measurement = "mΩ"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_internal_resistance"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("internal_resistance")
        return None


class AntraSOHSensor(AntraBaseSensor):
    """Sensor for battery State of Health (SOH)."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "State of Health"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.BATTERY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_soh"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("soh")
        return None


class AntraFullCapacitySensor(AntraBaseSensor):
    """Sensor for full charge capacity."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Full Charge Capacity"
        # Adjust the unit if necessary (e.g. "Ah")
        self._attr_native_unit_of_measurement = "Ah"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_full_capacity"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("full_capacity")
        return None


class AntraRemainingCapacitySensor(AntraBaseSensor):
    """Sensor for remaining capacity."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Remaining Capacity"
        self._attr_native_unit_of_measurement = "Ah"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_remaining_capacity"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("remaining_capacity")
        return None


class AntraCycleCountSensor(AntraBaseSensor):
    """Sensor for battery cycle count."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Cycle Count"
        # You might use "cycles" as unit if preferred.
        self._attr_native_unit_of_measurement = None
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        
    @property
    
    def unique_id(self):
        return f"Antra_{self._display_num}_cycle_count"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("cycle_count")
        return None

# --- Generic Sensors for Nested Data ---

class AntraStatusSensor(AntraBaseSensor):
    """Generic sensor for a status value from the battery."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, status_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._status_key = status_key
        self._attr_name = name
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_status_{self._status_key}"
    
    @property
    def native_value(self):
        if self.available:
            status = self.coordinator.data[self._battery_num].get("status", {})
            return status.get(self._status_key)
        return None


class AntraProtectionSensor(AntraBaseSensor):
    """Generic sensor for a protection value from the battery."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, protection_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._protection_key = protection_key
        self._attr_name = name
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_protection_{self._protection_key}"
    
    @property
    def native_value(self):
        if self.available:
            protection = self.coordinator.data[self._battery_num].get("protection", {})
            return protection.get(self._protection_key)
        return None


class AntraBalanceSensor(AntraBaseSensor):
    """Generic sensor for a cell balance value from the battery."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, balance_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._balance_key = balance_key
        self._attr_name = name
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_balance_{self._balance_key}"
    
    @property
    def native_value(self):
        if self.available:
            balance = self.coordinator.data[self._battery_num].get("balance", {})
            return balance.get(self._balance_key)
        return None

# --- Additional Status Sensors ---

class AntraMachineStatusSensor(AntraBaseSensor):
    """Sensor for machine status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Machine Status"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_machine_status"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("machine_status")
        return None


class AntraIOStatusSensor(AntraBaseSensor):
    """Sensor for IO status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "IO Status"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_io_status"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("io_status")
        return None

class AntraAdditionalStatusSensor(AntraBaseSensor):
    """Sensor for additional status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Additional Status"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_additional_status"
    
    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("additional_status")
        return None
    
class AntraAmbientTemperatureSensor(AntraBaseSensor):
    """Sensor for ambient temperature."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Ambient Temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_ambient_temperature"

    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("ambient_temperature")
        return None


class AntraPackAvgTemperatureSensor(AntraBaseSensor):
    """Sensor for pack average temperature."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "Pack Average Temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_pack_avg_temperature"

    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("pack_avg_temperature")
        return None

class AntraMOSTemperatureSensor(AntraBaseSensor):
    """Sensor for MOS temperature."""

    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "MOS Temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_mos_temperature"

    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get("mos_temperature")
        return None

def decode_bitmask(bitmask: int, total_cells: int = 16) -> str:
    """Decode a bitmask integer into a comma-separated list of flagged cell numbers."""
    flagged_cells = [str(i + 1) for i in range(total_cells) if bitmask & (1 << i)]
    return ", ".join(flagged_cells)

class AntraBitmaskSensor(AntraBaseSensor, SensorEntity):
    """Generic sensor to decode a 16-bit bitmask for protection/alarm flags.
    
    The sensor’s main state is the raw bitmask (an integer),
    and an extra attribute 'flagged_cells' contains a comma-separated list of cells (1–16)
    whose bits are set.
    """
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str) -> None:
        """
        Args:
            coordinator: The data coordinator.
            battery_num: Battery number.
            data_key: The key in the protection dictionary (e.g. "overvoltage_protect").
            name: A friendly name (e.g. "Overvoltage Protection").
        """
        super().__init__(coordinator, battery_num)
        self._data_key = data_key
        self._attr_name = name
        #self._attr_state_class = SensorStateClass.MEASUREMENT
        self.entity_category = EntityCategory.DIAGNOSTIC
        # Internal cache to store the last raw value
        self._raw_value = None

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_{self._data_key}"

    @property
    def native_value(self):
        """Return the raw bitmask value as the sensor state."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            # Directly retrieve the bitmask from the 'protection' dictionary
            protection = data.get("protection", {})
            bitmask = protection.get(self._data_key)
            #_LOGGER.debug(
            #    "AntraBitmaskSensor (battery %s, key %s): raw bitmask = %s",
            #    self._display_num, self._data_key, bitmask
            #)
            if bitmask is None:
                _LOGGER.debug(
                    "AntraBitmaskSensor (battery %s, key %s): No bitmask value found in 'protection'.",
                    self._display_num, self._data_key
                )
                return None
            self._raw_value = bitmask
            #_LOGGER.debug(
            #    "AntraBitmaskSensor (battery %s, key %s): Using bitmask value: %s",
            #    self._display_num, self._data_key, bitmask
            #)
            return hex(bitmask)
        _LOGGER.debug(
            "AntraBitmaskSensor (battery %s, key %s): Sensor not available.",
            self._display_num, self._data_key
        )
        return None

    @property
    def extra_state_attributes(self):
        """Return a formatted version of the bitmask as a list of flagged cell numbers."""
        attributes = {}
        if self._raw_value is not None:
            flagged_cells = decode_bitmask(self._raw_value)
            #_LOGGER.debug(
            #    "AntraBitmaskSensor (battery %s, key %s): Decoded flagged_cells = %s",
            #    self._display_num, self._data_key, flagged_cells
            #)
            attributes["flagged_cells"] = flagged_cells
        else:
            _LOGGER.debug(
                "AntraBitmaskSensor (battery %s, key %s): No raw value cached for extra attributes.",
                self._display_num, self._data_key
            )
        return attributes

def decode_status_bitmask(bitmask: int, mapping: dict) -> str:
    """
    Decode a status bitmask using the provided mapping.
    
    Args:
        bitmask: The raw bitmask as an integer.
        mapping: A dictionary where the keys are bit positions (int) and the values
                 are the corresponding status labels (str).
                 
    Returns:
        A comma-separated string of status labels for each bit that is set.
    """
    statuses = [label for bit, label in mapping.items() if bitmask & (1 << bit)]
    return ", ".join(statuses)

class AntraStatusBitmaskSensor(AntraBaseSensor, SensorEntity):
    """
    Generic sensor to decode a 16-bit status bitmask.
    
    The sensor’s main state is the raw bitmask (an integer) from the "status" dictionary,
    and an extra attribute 'decoded_status' contains a comma-separated list of status labels.
    """
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str, mapping: dict) -> None:
        """
        Args:
            coordinator: The data coordinator.
            battery_num: Battery number.
            data_key: The key in the status dictionary (e.g. "voltage" or "current").
            name: A friendly name (e.g. "Voltage Status").
            mapping: A dict mapping bit positions to their corresponding labels.
        """
        super().__init__(coordinator, battery_num)
        self._data_key = data_key
        self._attr_name = name
        #self._attr_state_class = SensorStateClass.MEASUREMENT
        self.entity_category = EntityCategory.DIAGNOSTIC
        self._mapping = mapping
        self._raw_value = None  # Cache for the raw bitmask

    @property
    def unique_id(self):
        # Append a prefix "status" so that it does not conflict with the pack voltage sensor
        return f"Antra_{self._display_num}_map_{self._data_key}"

    @property
    def native_value(self):
        """Return the raw bitmask value from the status dictionary."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            status_data = data.get("status", {})
            raw_val = status_data.get(self._data_key)
            #_LOGGER.debug(
            #    "AntraStatusBitmaskSensor (battery %s, key %s): raw value from data = %s",
            #    self._display_num, self._data_key, raw_val
            #)
            if raw_val is None:
                _LOGGER.debug(
                    "AntraStatusBitmaskSensor (battery %s, key %s): No raw value found.",
                    self._display_num, self._data_key
                )
                return None
            try:
                # In case the raw value is a string with commas (e.g., "3,465")
                bitmask = int(str(raw_val).replace(",", ""))
            except ValueError:
                _LOGGER.error(
                    "AntraStatusBitmaskSensor (battery %s, key %s): Unable to convert raw value '%s' to integer.",
                    self._display_num, self._data_key, raw_val
                )
                return None
            self._raw_value = bitmask
            #_LOGGER.debug(
            #    "AntraStatusBitmaskSensor (battery %s, key %s): Using bitmask value: %s",
            #    self._display_num, self._data_key, bitmask
            #)
            return hex(bitmask)
        _LOGGER.debug(
            "AntraStatusBitmaskSensor (battery %s, key %s): Sensor not available.",
            self._display_num, self._data_key
        )
        return None

    @property
    def extra_state_attributes(self):
        """Return a decoded version of the status as a list of active status labels."""
        attributes = {}
        if self._raw_value is not None:
            decoded = decode_status_bitmask(self._raw_value, self._mapping)
            #_LOGGER.debug(
            #    "AntraStatusBitmaskSensor (battery %s, key %s): Decoded statuses = %s",
            #    self._display_num, self._data_key, decoded
            #)
            attributes["decoded_status"] = decoded
        return attributes

# Voltage status mapping:
voltage_status_mapping = {
    0: "Cell Overvoltage Protection",     # B0
    1: "Cell Undervoltage Protection",     # B1
    2: "Pack Overvoltage Protection",        # B2
    3: "Pack Undervoltage Protection",       # B3
    4: "Cell Overvoltage Alarm",             # B4
    5: "Cell Undervoltage Alarm",            # B5
    6: "Pack Overvoltage Alarm",             # B6
    7: "Pack Undervoltage Alarm",            # B7
    8: "Cell Voltage Difference Alarm",      # B8
    15: "System Sleep"                       # B15
}

# Current status mapping:
current_status_mapping = {
    0: "Charging",                           # B0
    1: "Discharging",                        # B1
    2: "Charge Overcurrent Protection",      # B2
    3: "Short Circuit Protection",           # B3
    4: "Discharge Overcurrent 1 Protection",   # B4
    5: "Discharge Overcurrent 2 Protection",   # B5
    6: "Charge Overcurrent Alarm",           # B6
    7: "Discharge Overcurrent Alarm"         # B7
}

# Mapping for Temperature Status (each bit position corresponds to a specific temperature protection/alarm)
temperature_status_mapping = {
    0: "Charge Over Temperature Protection",    # B0
    1: "Charge Under Temperature Protection",    # B1
    2: "Discharge Over Temperature Protection",  # B2
    3: "Discharge Under Temperature Protection", # B3
    4: "Ambient Over Temperature Protection",    # B4
    5: "Ambient Under Temperature Protection",   # B5
    6: "MOS Over Temperature Protection",        # B6
    7: "MOS Under Temperature Protection",       # B7
    8: "Charge Over Temperature Alarm",          # B8
    9: "Charge Under Temperature Alarm",         # B9
    10: "Discharge Over Temperature Alarm",       # B10
    11: "Discharge Under Temperature Alarm",      # B11
    12: "Ambient Over Temperature Alarm",         # B12
    13: "Ambient Under Temperature Alarm",        # B13
    14: "MOS Over Temperature Alarm",             # B14
    15: "MOS Under Temperature Alarm",            # B15
}

# Mapping for Alarm Status
alarm_status_mapping = {
    0: "Cell Voltage Differential Alarm",  # B0
    1: "Charge MOS Damage Alarm",            # B1
    2: "External SD Card Failure Alarm",     # B2
    3: "SPI Communication Failure Alarm",    # B3
    4: "EEPROM Failure Alarm",               # B4
    5: "LED Alarm Enable",                   # B5
    6: "Buzzer Alarm Enable",                # B6
    7: "Low Battery Alarm",                  # B7
    8: "MOS Over Temperature Protection",    # B8
    9: "MOS Over Temperature Alarm",         # B9
    10: "Current Limiting Board Failure",    # B10
    11: "Sampling Failure",                  # B11
    12: "Battery Failure",                   # B12
    13: "NTC Failure",                       # B13
    14: "Charge MOS Failure",                # B14
    15: "Discharge MOS Failure",             # B15
}

def decode_fet_status(bitmask: int) -> str:
    """
    Decode FET Status bitmask into a comma-separated string.
    
    Bit assignments:
      - Bit 0: Charge MOS status (1 = on, 0 = off)
      - Bit 1: Disharge MOS status (1 = on, 0 = off)
      - Bit 2: Discharge MOS failure (1 = damaged)
      - Bit 3: Charge MOS failure (assumed; 1 = damaged)
      - Bits 4-5: Current limiting mode:
           00: No current limit
           01: Current limit 5A
           10: Current limit 10A
           11: Current limit 25A
      - Bits 6-10: Reserved (ignored)
      - Bit 11: LED alarm enable (1 = enabled)
      - Bit 12: Beep enable (1 = enabled)
      - Bits 13-15: Reserved (ignored)
    """
    statuses = []
    
    # Bit 0: Discharge MOS status
    if bitmask & (1 << 0):
        statuses.append("Charge MOS: On")
    else:
        statuses.append("Charge MOS: Off")
    
    # Bit 1: Charge MOS status
    if bitmask & (1 << 1):
        statuses.append("Disharge MOS: On")
    else:
        statuses.append("Disharge MOS: Off")
    
    # Bit 2: Discharge MOS failure
    if bitmask & (1 << 2):
        statuses.append("Discharge MOS Failure")
    
    # Bit 3: Charge MOS failure (assumed)
    if bitmask & (1 << 3):
        statuses.append("Charge MOS Failure")
    
    # Bits 4-5: Current limiting mode (always decode)
    current_limiting = (bitmask >> 4) & 0b11  # extract bits 4 and 5
    current_limiting_mapping = {
        0: "No current limit",
        1: "Current limit 5A",
        2: "Current limit 10A",
        3: "Current limit 25A",
    }
    statuses.append(current_limiting_mapping[current_limiting])
    
    # Bits 6-10 are reserved; we ignore them.
    
    # Bit 11: LED alarm enable
    if bitmask & (1 << 11):
        statuses.append("LED alarm enabled")
    
    # Bit 12: Beep enable
    if bitmask & (1 << 12):
        statuses.append("Beep enabled")
    
    # Bits 13-15 are reserved; ignore.
    return ", ".join(statuses)

class AntraFETStatusSensor(AntraBaseSensor, SensorEntity):
    """
    Sensor to decode FET Status.
    
    - The native state is the raw integer (bitmask) value.
    - An extra attribute 'decoded_status' provides a comma-separated
      string with the decoded information.
    
    Expected raw data should be available under the status dictionary with a key
    (e.g., "fet") that you must ensure is provided by your transformation function.
    """
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        """Initialize the FET Status sensor."""
        super().__init__(coordinator, battery_num)
        self._attr_name = "FET Status"
        #self._attr_state_class = SensorStateClass.MEASUREMENT
        self.entity_category = EntityCategory.DIAGNOSTIC
        self._raw_value = None

    @property
    def unique_id(self):
        # Use a unique ID that distinguishes this sensor from others.
        return f"Antra_{self._display_num}_fet_status"

    @property
    def native_value(self):
        """Return the raw bitmask value for FET Status."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            status_data = data.get("status", {})
            # Use the key "fet" for FET Status.
            raw_val = status_data.get("fet")
            #_LOGGER.debug(
            #    "AntraFETStatusSensor (battery %s): raw value from data = %s",
            #    self._display_num, raw_val
            #)
            if raw_val is None:
                _LOGGER.debug(
                    "AntraFETStatusSensor (battery %s): No value found for FET Status.",
                    self._display_num
                )
                return None
            try:
                # Remove any commas and convert to integer.
                bitmask = int(str(raw_val).replace(",", ""))
            except ValueError:
                _LOGGER.error(
                    "AntraFETStatusSensor (battery %s): Unable to convert raw value '%s' to integer.",
                    self._display_num, raw_val
                )
                return None
            self._raw_value = bitmask
            #_LOGGER.debug(
            #    "AntraFETStatusSensor (battery %s): Using bitmask value: %s",
            #    self._display_num, bitmask
            #)
            return hex(bitmask)
        _LOGGER.debug(
            "AntraFETStatusSensor (battery %s): Sensor not available.",
            self._display_num
        )
        return None

    @property
    def extra_state_attributes(self):
        """Return the decoded FET Status as a comma-separated list."""
        attributes = {}
        if self._raw_value is not None:
            decoded = decode_fet_status(self._raw_value)
            #_LOGGER.debug(
            #    "AntraFETStatusSensor (battery %s): Decoded FET Status = %s",
            #    self._display_num, decoded
            #)
            attributes["decoded_status"] = decoded
        else:
            _LOGGER.debug(
                "AntraFETStatusSensor (battery %s): No raw value cached for decoding.",
                self._display_num
            )
        return attributes
    
def add_numeric_sensor(entities, coordinator, battery_num, data_key, friendly_name, unit=None):
    """Helper to create and add a generic numeric sensor."""
    sensor = AntraNumberSensor(coordinator, battery_num, data_key, friendly_name, unit)
    entities.append(sensor)
    
class AntraNumberSensor(AntraBaseSensor, SensorEntity):
    """Generic sensor for numeric values from Antra data."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str, unit: str | None = None) -> None:
        super().__init__(coordinator, battery_num)
        self._data_key = data_key
        self._attr_name = name
        # Optionally set a unit if known; otherwise leave as None.
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_{self._data_key}"

    @property
    def native_value(self):
        if self.available:
            return self.coordinator.data[self._battery_num].get(self._data_key)
        return None

class AntraStatusRawSensor(AntraBaseSensor, SensorEntity):
    """Raw hex value sensor for status bitmasks."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._data_key = data_key
        self._attr_name = f"{name} Raw"
        self.entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_{self._data_key}_raw"

    @property
    def native_value(self):
        """Return the raw hex value."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            status_data = data.get("status", {})
            raw_val = status_data.get(self._data_key)
            if raw_val is not None:
                try:
                    bitmask = int(str(raw_val).replace(",", ""))
                    return hex(bitmask)
                except ValueError:
                    return None
        return None

class AntraStatusDecodedSensor(AntraBaseSensor, SensorEntity):
    """Decoded value sensor for status bitmasks."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, data_key: str, name: str, mapping: dict) -> None:
        super().__init__(coordinator, battery_num)
        self._data_key = data_key
        self._attr_name = f"{name} Decoded"
        self.entity_category = EntityCategory.DIAGNOSTIC
        self._mapping = mapping

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_{self._data_key}_decoded"

    @property
    def native_value(self):
        """Return the decoded status string."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            status_data = data.get("status", {})
            raw_val = status_data.get(self._data_key)
            if raw_val is not None:
                try:
                    bitmask = int(str(raw_val).replace(",", ""))
                    return decode_status_bitmask(bitmask, self._mapping) or "None"
                except ValueError:
                    return None
        return None
    
class AntraFETStatusRawSensor(AntraBaseSensor, SensorEntity):
    """Raw hex value sensor for FET status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "FET Status Raw"
        self.entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_fet_status_raw"

    @property
    def native_value(self):
        """Return the raw hex value."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            status_data = data.get("status", {})
            raw_val = status_data.get("fet")
            if raw_val is not None:
                try:
                    bitmask = int(str(raw_val).replace(",", ""))
                    return hex(bitmask)
                except ValueError:
                    return None
        return None


class AntraFETStatusDecodedSensor(AntraBaseSensor, SensorEntity):
    """Decoded value sensor for FET status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int) -> None:
        super().__init__(coordinator, battery_num)
        self._attr_name = "FET Status Decoded"
        self.entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_fet_status_decoded"

    @property
    def native_value(self):
        """Return the decoded FET status string."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            status_data = data.get("status", {})
            raw_val = status_data.get("fet")
            if raw_val is not None:
                try:
                    bitmask = int(str(raw_val).replace(",", ""))
                    return decode_fet_status(bitmask)
                except ValueError:
                    return None
        return None
    
class AntraProtectStatusRawSensor(AntraBaseSensor, SensorEntity):
    """Raw hex value sensor for protection status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, protection_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._protection_key = protection_key 
        self._attr_name = f"{name} Raw"
        self.entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_protection_{self._protection_key}_raw"

    @property
    def native_value(self):
        """Return the raw hex value."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            protection = data.get("protection", {})
            raw_val = protection.get(self._protection_key)
            if raw_val is not None:
                try:
                    bitmask = int(str(raw_val).replace(",", ""))
                    return hex(bitmask)
                except ValueError:
                    return None
        return None

class AntraProtectStatusDecodedSensor(AntraBaseSensor, SensorEntity):
    """Decoded value sensor for protection status."""
    
    def __init__(self, coordinator: AntraDataCoordinator, battery_num: int, protection_key: str, name: str) -> None:
        super().__init__(coordinator, battery_num)
        self._protection_key = protection_key
        self._attr_name = f"{name} Decoded"
        self.entity_category = EntityCategory.DIAGNOSTIC

    @property
    def unique_id(self):
        return f"Antra_{self._display_num}_protection_{self._protection_key}_decoded"

    @property
    def native_value(self):
        """Return the decoded protection status as a list of affected cells."""
        if self.available:
            data = self.coordinator.data[self._battery_num]
            protection = data.get("protection", {})
            raw_val = protection.get(self._protection_key)
            if raw_val is not None:
                try:
                    bitmask = int(str(raw_val).replace(",", ""))
                    return decode_bitmask(bitmask) or "None"
                except ValueError:
                    return None
        return None