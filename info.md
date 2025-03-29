# Antra BMS Monitor

A Home Assistant custom component that monitors Battery Management Systems (BMS) using the Antra/Pylontech protocol, supporting Pylontech, Basen, and other compatible BMS systems.

## Features

- Track total energy discharged and charged with counter rollover handling
- Monitor energy usage since last charge
- Estimate time needed to recharge based on current usage
- Track the current charge rate and status
- Monitor stored energy levels for each battery
- Automatically detect Antra/Pylontech/Basen battery entities
- Support for multiple batteries in a system

## Configuration

The integration can be configured through the Home Assistant UI:

1. Go to Configuration -> Integrations
2. Click the "+ ADD INTEGRATION" button
3. Search for either "Battery Energy Tracker" or "Antra BMS" and select it
4. Follow the configuration flow to set up the integration

## Services

- **reset_counters**: Reset all energy counters to zero
- **reset_energy_since_charge**: Reset only the energy since last charge counter
- **set_charge_state**: Manually set the battery charging state
- **adjust_counters**: Adjust the energy counter values
- **set_battery_stored_energy**: Set the current stored energy for a specific battery
- **set_battery_to_full**: Set the stored energy to full capacity for one or all batteries
- **set_battery_capacity**: Set the maximum capacity for a specific battery

For more details, see the [full documentation on GitHub](https://github.com/mcrw27/antra-bms-monitor).