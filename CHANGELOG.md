# Changelog

All notable changes to this project will be documented in this file.

## [0.1.4] - 2025-09-07

### Fixed
- Corrected pack header sensor mappings:
  - Position 44-47: `temperature_min` sensor now correctly shows alarm status (raw value)
  - Position 40-43: `temperature_max` sensor now correctly shows pack temperature (°C)
  - Position 62-63: `cell_count` sensor now correctly shows current status (raw value)
- Updated sensor names to reflect their actual data content
- Fixed data parsing positions in `_parse_header_block` function
- Updated debug messages and docstrings to match correct field positions

### Breaking Changes
- Historical data will be lost for the three renamed sensors as they will have new entity IDs:
  - `sensor.antra_battery_group_pack_temperature_minimum` → `sensor.antra_battery_group_alarm_status`
  - `sensor.antra_battery_group_pack_temperature_maximum` → `sensor.antra_battery_group_pack_temperature`
  - `sensor.antra_battery_group_cell_count` → `sensor.antra_battery_group_current_status`

## [0.1.3] - 2025-03-29

### Changed
- Renamed battery model
- Changed defaults and workflow

## [0.1.2] - 2025-03-29

### Changed
- Rename and revamp

## [0.1.1] - 2025-03-29

### Added
- [Initial improvements and bug fixes]

## [0.1.0] - Initial Release

### Added
- Initial release with Antra/Pylontech BMS monitoring functionality
- Support for multiple batteries (up to 15)
- Serial port communication with configurable baud rate
- Pack header sensors for system-level monitoring
- Individual battery sensors including:
  - Cell voltages
  - Temperature sensors
  - Current and voltage monitoring
  - State of charge (SOC) and state of health (SOH)
  - Capacity and cycle count tracking
  - Status and protection monitoring
- Config flow for easy setup through Home Assistant UI
- Coordinator-based data updates with 30-second intervals
- Support for Antra BLF-48105H and compatible BMS systems