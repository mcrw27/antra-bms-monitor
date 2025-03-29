# Antra BMS Monitor for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

A Home Assistant custom component that monitors Battery Management Systems (BMS) using the Antra/Pylontech protocol. This integration works with Pylontech, Basen, and other compatible BMS systems, providing rich data about battery status, charge cycles, and energy usage.

## Features

- Track total energy discharged and charged with counter rollover handling
- Monitor energy usage since last charge
- Estimate time needed to recharge based on current usage
- Track the current charge rate and status
- Monitor stored energy levels for each battery
- Automatically detect Pylontech battery entities
- Support for multiple batteries in a system

## Supported Devices

- Pylontech US2000/US3000 battery systems
- Basen battery systems
- Other BMS systems using the Antra/Pylontech protocol
- Any battery system with compatible sensors for the energy tracking functionality

## Installation

### HACS Installation (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed
2. Go to HACS -> Integrations -> Click on the three dots in the top right corner
3. Select "Custom repositories"
4. Add this repository URL (`https://github.com/YOUR_USERNAME/antra-bms-monitor`) and select "Integration" as the category
5. Click "ADD"
6. Search for "Antra BMS Monitor" and install it
7. Restart Home Assistant

### Manual Installation

1. Copy both the `custom_components/battery_energy_tracker` and `custom_components/antra_bms` directories from this repository to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

The integration can be configured through the Home Assistant UI:

1. Go to Configuration -> Integrations
2. Click the "+ ADD INTEGRATION" button
3. Search for either "Battery Energy Tracker" or "Antra BMS" and select it
4. Follow the configuration flow to set up the integration

### Configuration Options

- **Number of batteries**: The number of batteries in your system (1-16)
- **Charging rate**: The charging rate in Watts (default: 1500W)
- **Startup delay**: Delay in seconds before starting entity detection (useful for systems that take time to initialize)
- **Scale factor**: Scale factor for counter values

## Services

The integration provides several services to control the battery tracking:

- **reset_counters**: Reset all energy counters to zero
- **reset_energy_since_charge**: Reset only the energy since last charge counter
- **set_charge_state**: Manually set the battery charging state
- **adjust_counters**: Adjust the energy counter values
- **set_battery_stored_energy**: Set the current stored energy for a specific battery
- **set_battery_to_full**: Set the stored energy to full capacity for one or all batteries
- **set_battery_capacity**: Set the maximum capacity for a specific battery

## Sensors

The integration creates the following sensors:

- **Total Discharge Energy**: Total energy discharged from the batteries
- **Total Charge Energy**: Total energy charged into the batteries
- **Energy Since Last Charge**: Energy used since the last completed charge
- **Estimated Charge Time**: Estimated time needed to recharge the battery
- **Charge Status**: Current battery charging status
- **Charge Rate**: Current charging rate in Watts
- **Total Stored Energy**: Total energy stored across all batteries
- **Battery X Stored Energy**: Energy stored in each individual battery

## Troubleshooting

If the integration cannot find your battery entities:

1. Check that your Pylontech batteries are properly connected and sending data to Home Assistant
2. Verify that the battery entities are available in Home Assistant (check in Developer Tools -> States)
3. Increase the startup delay to give your system more time to initialize
4. Check the Home Assistant logs for any errors or warnings from the integration

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.