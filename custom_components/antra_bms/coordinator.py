"""Antra BMS coordinator.""" 
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryNotReady

_LOGGER = logging.getLogger(__name__)

def convert_signed(decoded: str, pos: int, length: int, scale: float = 1.0) -> float:
    """
    Extracts a substring from the decoded hex string starting at 'pos' with 'length' hex digits,
    converts it to an integer, and returns its signed value (using two's complement).
    The result is divided by 'scale' (default 1.0) to allow for unit conversion.

    Args:
    decoded (str): The full hex string containing the data.
    pos (int): The starting position in the string.
    length (int): The number of hex digits to process (e.g., 4 for a 2-byte field).
    scale (float): A scaling factor to divide the value by (default 1.0).

    Returns:
        float: The signed and scaled value.
    """
    # Convert the specified substring to an integer.
    raw = int(decoded[pos:pos+length], 16)
    # Calculate the number of bits in the field (each hex digit is 4 bits).
    bits = length * 4
    # The sign bit is at position bits-1.
    sign_bit = 1 << (bits - 1)
    # If the raw value is greater than or equal to the sign bit,
    # subtract the full range (1 << bits) to get the negative value.
    if raw >= sign_bit:
        raw -= 1 << bits
    # Return the (possibly signed) value divided by the scaling factor.
    return raw / scale

class AntraDataCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Antra data."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        reader, 
        writer, 
        battery_count: int,
        group_number: int = 0,  # 0 for single group, 1-7 for multi-group
        update_interval: timedelta = timedelta(seconds=30)
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Antra Battery",
            update_interval=update_interval,
        )
        self._reader = reader
        self._writer = writer
        self._battery_count = min(battery_count, 12)  # Max 12 batteries per group
        self._group_number = group_number
        self._lock = asyncio.Lock()
        self.data = {}
        self.protocol_version = None
        _LOGGER.debug(
            "Initialized AntraDataCoordinator (group=%d, batteries=%d)", 
            group_number, 
            battery_count
        )

    def _calculate_checksum(self, data: bytes) -> int:
        """Calculate checksum for command."""
        sum_val = sum(data[1:-3])  # Exclude SOI, CHKSUM and EOI
        remainder = sum_val % 65536
        return (remainder ^ 0xFFFF) + 1

    def _calculate_address(self, battery_number: int | None = None) -> int:
        """Calculate address based on battery number and group.
        
        For single battery queries:
            ADR = 0x0n + 0x10*m where:
                n is battery position (2-13)
                m is group number (0 for single group, 1-7 for multi-group)
            
        For system queries:
            ADR = 0x02 + 0x10*m
        """
        if battery_number is None:
            # System query - always uses base address 0x02
            return 0x0 + (0x10 * self._group_number)
            
        # Battery numbers start at 2 (master battery)
        position = battery_number
        return position + (0x10 * self._group_number)

    def _verify_known_checksum(self):
        """Verify checksum calculation against known working command."""
        # Known working command: ~22004A42E002FFFCFE
        data = "22004A42E002FF"
        sum_val = sum(ord(c) for c in data)
        _LOGGER.debug("Known command checksum calculation:")
        _LOGGER.debug("  Data to sum: %s", data)
        _LOGGER.debug("  Sum: %04X", sum_val)
        remainder = sum_val % 65536
        _LOGGER.debug("  Remainder (mod 65536): %04X", remainder)
        expected = (remainder ^ 0xFFFF) + 1
        _LOGGER.debug("  Calculated checksum: %04X (Command has FCFE)", expected)
        return expected

    def _build_command(self, 
        command: bytes, 
        battery_number: int | None = None, 
        info_byte: bytes | None = None
    ) -> bytes:
        """Build a command packet according to protocol."""
        # First verify known checksum
        #self._verify_known_checksum()

        frame = bytearray()
        frame.append(0x7E)  # SOI
        frame.extend(b"22")  # VER
        
        # Calculate and add address
        address = self._calculate_address(battery_number)
        frame.extend(f"{address:02X}".encode())
        
        frame.extend(b"4A")  # CID1
        frame.extend(command)  # CID2
        
        # For most commands, info matches address
        # For system queries, info is 0xFF
        if info_byte is None:
            info_byte = b"FF" if battery_number is None else f"{address:02X}".encode()
        info_byte = b"FF"
            
        frame.extend(b"E002")  # LENGTH
        frame.extend(info_byte)  # INFO

        # Show data being checksummed
        data_to_sum = frame[1:].decode('ascii')  # Everything after SOI
        #_LOGGER.debug("Our command checksum calculation:")
        #_LOGGER.debug("  Data to sum: %s", data_to_sum)
        sum_val = sum(ord(c) for c in data_to_sum)
        #_LOGGER.debug("  Sum: %04X", sum_val)
        remainder = sum_val % 65536
        #_LOGGER.debug("  Remainder (mod 65536): %04X", remainder)
        checksum = (remainder ^ 0xFFFF) + 1
        #_LOGGER.debug("  Calculated checksum: %04X", checksum)
        
        frame.extend(f"{checksum:04X}".encode())
        frame.append(0x0D)  # EOI

        # Show full command
        _LOGGER.debug("Full command: %s", frame.hex())
        return bytes(frame)
    
    def _format_message(self, data: bytes) -> str:
        """Convert ASCII hex bytes to hex string format.
        Example: b'323230353441' -> '22054A'
        """
        try:
            # Skip SOI and CR
            hex_str = data[1:-1].decode('ascii')
            formatted = [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]
            return '~' + ''.join(f'{b:02X}' for b in formatted)
        except Exception as err:
            _LOGGER.error("Error formatting message: %s (data: %s)", err, data.hex())
            return f"~ERROR({data.hex()})"

    def _get_battery_address(self, response: bytes) -> int | None:
        """Get battery address from response."""
        try:
            # Convert ascii hex to int, position 2-3 contains address
            hex_str = response[1:-1].decode('ascii')
            return int(hex_str[2:4], 16)
        except Exception as err:
            _LOGGER.debug("Could not get battery address: %s", err)
            return None

    def _is_42h_response(self, response: bytes) -> bool:
        """Check if this is a 42h response."""
        try:
            hex_str = response[1:-1].decode('ascii')
            return len(hex_str) > 6 and hex_str[4:6] == "42"
        except Exception:
            return False

    def _verify_checksum(self, data: bytes) -> bool:
        """Verify message checksum.
        Format: ~...XXXX\r where XXXX is the checksum in hex.
        
        Sum ASCII values of all characters except SOI, CHKSUM and EOI.
        Take modulus 65536 of sum, invert and add 1.
        """
        try:
            # Get ASCII data without SOI, CHKSUM and EOI
            hex_str = data[1:-1].decode('ascii')
            data_str = hex_str[:-4]  # Remove checksum
            msg_checksum = int(hex_str[-4:], 16)
            
            # Sum ASCII values of data characters
            sum_val = sum(ord(c) for c in data_str)
            _LOGGER.debug("Checksum calculation: sum=%04X", sum_val)
            
            remainder = sum_val % 65536
            expected = (remainder ^ 0xFFFF) + 1
            
            if msg_checksum != expected:
                _LOGGER.debug(
                    "Checksum details: data='%s', sum=%04X, mod=%04X, expected=%04X, got=%04X", 
                    data_str,
                    sum_val,
                    remainder,
                    expected,
                    msg_checksum
                )
                return False
                
            return True
            
        except Exception as err:
            _LOGGER.error("Error verifying checksum: %s", err)
            return False
        
    def _get_rtn_description(self, rtn: str) -> str:
        """Get description of return code."""
        rtn_codes = {
            "00": "Normal",
            "01": "VER error",
            "02": "CHKSUM error",
            "03": "LCHKSUM error",
            "04": "CID2 invalidation",
            "05": "Command format error",
            "06": "Invalid data",
            "90": "ADR error",
            "91": "Communication error"
        }
        return rtn_codes.get(rtn, "Unknown RTN code")

    def _decode_frame(self, data: bytes, direction: str = "TX") -> None:
        """Decode and log frame structure.
        
        For commands (TX):
            CID2 = command type (42h, 4Fh etc)
        For responses (RX):
            CID2 = RTN (return code)
        """
        try:
            hex_str = data[1:-1].decode('ascii')
            
            # Break down into fields
            frame = {
                "SOI": "7E",
                "VER": hex_str[0:2],
                "ADR": hex_str[2:4],
                "CID1": hex_str[4:6],
                "CID2": hex_str[6:8],
                "LENGTH": hex_str[8:12],
                "INFO": hex_str[12:-4],
                "CHKSUM": hex_str[-4:],
                "EOI": "0D"
            }
            
            # Interpret common values
            adr_int = int(frame["ADR"], 16)
            info_len = len(frame["INFO"]) // 2  # Each byte is 2 hex chars
            
            if direction == "TX":
                # Sending a command
                cmd_desc = ""
                if frame["CID2"] == "42":
                    cmd_desc = f"Get analog values from battery {adr_int}"
                elif frame["CID2"] == "4F":
                    cmd_desc = "Get protocol version"
                
                _LOGGER.debug("TX Frame: VER=%s ADR=%s(%d) CID1=%s CMD=%s LEN=%s(%d) INFO=%s CHKSUM=%s", 
                    frame["VER"],
                    frame["ADR"], 
                    adr_int,
                    frame["CID1"],
                    frame["CID2"],
                    frame["LENGTH"],
                    info_len,
                    frame["INFO"],
                    frame["CHKSUM"]
                )
                if cmd_desc:
                    _LOGGER.debug("  Command: %s", cmd_desc)
                    
            else:
                # Receiving a response
                rtn_desc = self._get_rtn_description(frame["CID2"])
                
                _LOGGER.debug("RX Frame: VER=%s ADR=%s(%d) CID1=%s RTN=%s(%s) LEN=%s(%d) INFO=%s CHKSUM=%s", 
                    frame["VER"],
                    frame["ADR"], 
                    adr_int,
                    frame["CID1"],
                    frame["CID2"],
                    rtn_desc,
                    frame["LENGTH"],
                    info_len,
                    frame["INFO"],
                    frame["CHKSUM"]
                )
            
        except Exception as err:
            _LOGGER.error("Error decoding frame: %s", err)
            
    def _validate_response(self, response: bytes) -> bool:
        """Validate response frame and return code.
        
        Returns:
            bool: True if response is valid and RTN is normal (00)
        """
        try:
            # Get basic frame parts
            hex_str = response[1:-1].decode('ascii')
            rtn = hex_str[6:8]  # CID2 position contains RTN for responses
            
            # Check return code
            rtn_codes = {
                "00": "Normal",
                "01": "VER error",
                "02": "CHKSUM error",
                "03": "LCHKSUM error", 
                "04": "CID2 invalidation",
                "05": "Command format error",
                "06": "Invalid data",
                "90": "ADR error",
                "91": "Communication error"
            }
            
            if rtn not in rtn_codes:
                _LOGGER.warning("Unknown return code: %s", rtn)
                return False
                
            if rtn != "00":
                _LOGGER.error("Error response received: %s", rtn_codes[rtn])
                return False
                
            return True
            
        except Exception as err:
            _LOGGER.error("Error validating response: %s", err)
            return False

    async def _read_response(self, timeout: float = 2.0) -> bytes | None:
        """Read response with timeout."""
        try:
            async with asyncio.timeout(timeout):
                while True:
                    response = await self._reader.readuntil(b"\r")
                    
                    # Decode for logging
                    self._decode_frame(response, "RX")
                    
                    # Basic frame validation
                    if not response.startswith(b"~") or not response.endswith(b"\r"):
                        _LOGGER.warning("Invalid frame format")
                        continue
                        
                    # Verify checksum
                    if not self._verify_checksum(response):
                        _LOGGER.warning("Dropping frame with invalid checksum")
                        continue
                        
                    # Skip short (polling) messages
                    if len(response) < 30:
                        _LOGGER.debug("Skipping short message (master polling)")
                        continue
                        
                    # Validate RTN code
                    if not self._validate_response(response):
                        _LOGGER.warning("Invalid response received, retrying...")
                        continue
                    
                    return response
                    
        except asyncio.TimeoutError:
            _LOGGER.warning("Timeout waiting for response")
            return None
        except Exception as err:
            _LOGGER.error("Error reading response: %s", err)
            return None

    def _parse_header_block(self, decoded: str, pos: int = 12) -> tuple[dict, int]:
        """Parse system header block starting at given position.
        
        Format:
        Bytes   Field               Scale   Example
        0-3     System Voltage      /100    15A5 = 55.41V
        4-7     System Current      raw     0000 = 0A
        8-11    Total Capacity      raw     01A4 = 420Ah
        12-15   Remaining Capacity  raw     01A4 = 420Ah
        16-19   System SOC          raw     0064 = 100%
        20-23   Max Ambient Temp        /10     00A0 = 16.0°C
        24-27   Min Ambient Temp       /10     0096 = 15.0°C
        28-31   Max Cell Voltage    /1000   0E2A = 3.626V
        32-35   Min Cell Voltage    /1000   0D1A = 3.354V
        36-39   Temperature Min      /10     0082 = 13.0
        40-43   Temperature Max      /10     0050 = 8.0
        44-61   Reserved            -       20 bytes zeros
        62-63   Cell Count         raw      10 = 16 cells
        64-65   Battery Count      raw      04 = 4 batteries
        Args:
            decoded: Full hex string response
            pos: Starting position of header block (default 22 after protocol header)
            
        Returns:
            Tuple of (header_data dict, new position after header)
        """
        try:
            header = {}
            
            _LOGGER.debug("Header frame: %s", decoded[pos:pos+66])
            
            # System voltage and current
            header["voltage"] = int(decoded[pos:pos+4], 16) / 100
            header["current"] = convert_signed(decoded, pos+4, 4, scale=1);
            _LOGGER.debug("current: %s -> %d", decoded[pos+4:pos+8], header["current"])

                
            # Voltage readings
            header["total_capacity"] = int(decoded[pos+8:pos+12], 16)
            header["remaining_capacity"] = int(decoded[pos+12:pos+16], 16)
            
            # State of charge
            header["soc"] = int(decoded[pos+16:pos+20], 16)
            
            # Temperature readings
            header["max_ambient_temp"] = convert_signed(decoded, pos+20, 4, scale=10)
            header["min_ambient_temp"] = convert_signed(decoded, pos+24, 4, scale=10)
            
            # Cell voltage extremes
            header["max_cell_voltage"] = int(decoded[pos+28:pos+32], 16) 
            header["min_cell_voltage"] = int(decoded[pos+32:pos+36], 16) 
            
            # Additional parameters
            header["temperature_max"] = convert_signed(decoded, pos+40, 4, scale=10)
            header["temperature_min"] = convert_signed(decoded, pos+44, 4, scale=10)
            
            # Store reserved bytes
            header["reserved"] = decoded[pos+44:pos+62]
                    
            # System configuration
            header["cell_count"] = int(decoded[pos+62:pos+64], 16)
            _LOGGER.debug("Cell Count: %s -> %d", decoded[pos+62:pos+64], header["cell_count"])
            header["battery_count"] = int(decoded[pos+64:pos+66], 16)
            
            _LOGGER.debug(
                "Parsed header: V=%.2fV I=%.2fA SOC=%d%% Batt=%d Cells=%d MaxCell=%.3fV MinCell=%.3fV", 
                header["voltage"], header["current"], header["soc"],
                header["battery_count"], header["cell_count"],
                header["max_cell_voltage"], header["min_cell_voltage"],
                header["temperature_min"], header["temperature_min"]
            )
            
            return header, pos + 66  # Return data and new position
            
        except Exception as err:
            _LOGGER.error("Error parsing header block: %s", err)
            raise
            
    def _parse_battery_block(self, decoded: str, pos: int) -> tuple[dict, int]:
        """
        Parse a single battery block starting at the given position.
        
        Expected layout (positions in hex digits; 2 hex digits = 1 byte):
        
        Bytes      Field
        0–3        Battery Header (2 bytes, raw)
        4–5        State of Charge (SOC, 1 byte, raw) 
        6–9        Pack Voltage (2 bytes, /100) 
        10–11      Cell Count (1 byte, raw)
        12–75      16 Cell Voltages (16×2 bytes, each /1000)
        76–79      Ambient Temperature (2 bytes, /10)
        80–83      Pack Average Temperature (2 bytes, /10)
        84–87      MOS Temperature (2 bytes, /10)
        88–89      Pack Temp Sensor Count (1 byte, raw)
        90–97      Pack Temp Sensors (4×2 bytes, each /10)
        98–101     Charging/Discharging Current (2 bytes, /100)
        102–105    Pack Internal Resistance (2 bytes, raw)
        106–109    Pack Health Status (SOH, 2 bytes, raw)
        110–111    User–Defined Number (1 byte, raw)
        112–115    Full Charge Capacity (2 bytes, /100)
        116–119    Remaining Capacity (2 bytes, /100)
        120–123    Number of Cycles (2 bytes, raw)
        124–127    Voltage Status (2 bytes, raw)
        128–131    Current Status (2 bytes, raw)
        132–135    Temperature Status (2 bytes, raw)
        136–139    Alarm Status (2 bytes, raw)
        140–143    FET Status (2 bytes, raw)          
        144–147    Overvoltage Protect (2 bytes, raw)
        148–151    Undervoltage Protect (2 bytes, raw)
        152–155    Overvoltage Alarm (2 bytes, raw)
        156–159    Undervoltage Alarm (2 bytes, raw)
        160–163    Cell Balance Low (2 bytes, raw)
        164–167    Cell Balance High (2 bytes, raw)
        168–169    Machine Status (1 byte, raw, bitflags)
        170–173    IO Status (2 bytes, raw, bitflags)
        174–177    Additional Status (2 bytes, raw)
 
        Total length = 93 bytes (186 hex digits).
        
        Args:
            decoded: Full hex string response.
            pos: Starting position (index into the hex string) of this battery block.
            
        Returns:
            Tuple of (battery_data dict, new position after block)
        """
        try:
            battery = {}
            start_pos = pos
            _LOGGER.debug("Starting battery block parse at pos: %d", pos)
            _LOGGER.debug("Battery frame: %s", decoded[pos:pos+212])
            
            # Battery Header (2 bytes = 4 hex digits)
            # Only take the first byte for the battery number.
            battery["number"] = int(decoded[pos:pos+2], 16)
            _LOGGER.debug("Battery header: %s -> %d", decoded[pos:pos+2], battery["number"])
            pos += 4  # Skip both bytes (first is battery number, second is reserved)
            #_LOGGER.debug("After battery header, pos offset: %d", pos - start_pos)
            
            # SOC (1 byte = 2 hex digits)
            battery["soc"] = int(decoded[pos:pos+2], 16)
            _LOGGER.debug("SOC: %s -> %d", decoded[pos:pos+2], battery["soc"])
            pos += 2
            #_LOGGER.debug("After SOC, pos offset: %d", pos - start_pos)
            
            # Pack Voltage (2 bytes, /100)
            battery["voltage"] = int(decoded[pos:pos+4], 16) / 100
            _LOGGER.debug("Pack Voltage: %s -> %.2f V", decoded[pos:pos+4], battery["voltage"])
            pos += 4
            #_LOGGER.debug("After Pack Voltage, pos offset: %d", pos - start_pos)
            
            # Cell Count (1 byte)
            cell_count = int(decoded[pos:pos+2], 16)
            battery["cell_count"] = cell_count
            _LOGGER.debug("Cell Count: %s -> %d", decoded[pos:pos+2], cell_count)
            pos += 2
            #_LOGGER.debug("After Cell Count, pos offset: %d", pos - start_pos)
            
            # 16 Cell Voltages (each 2 bytes, /1000)
            cells = []
            for i in range(cell_count):
                cell_hex = decoded[pos:pos+4]
                cell_voltage = int(cell_hex, 16) / 1000
                cells.append(cell_voltage)
                _LOGGER.debug("Cell %d Voltage: %s -> %.3f V", i+1, cell_hex, cell_voltage)
                pos += 4
            battery["cells"] = cells
            #_LOGGER.debug("After Cell Voltages, pos offset: %d", pos - start_pos)
            
            # Ambient Temperature (2 bytes, /10)
            battery["ambient_temperature"] = convert_signed(decoded, pos, 4, scale=10)
            _LOGGER.debug("Ambient Temperature: %s -> %.1f °C", decoded[pos:pos+4], battery["ambient_temperature"])
            pos += 4
            #_LOGGER.debug("After Ambient Temperature, pos offset: %d", pos - start_pos)
            
            # Pack Average Temperature (2 bytes, /10)
            battery["pack_avg_temperature"] = convert_signed(decoded, pos, 4, scale=10)
            _LOGGER.debug("Pack Average Temperature: %s -> %.1f °C", decoded[pos:pos+4], battery["pack_avg_temperature"])
            pos += 4
            #_LOGGER.debug("After Pack Average Temperature, pos offset: %d", pos - start_pos)
            
            # MOS Temperature (2 bytes, /10)
            battery["mos_temperature"] = convert_signed(decoded, pos, 4, scale=10)
            _LOGGER.debug("MOS Temperature: %s -> %.1f °C", decoded[pos:pos+4], battery["mos_temperature"])
            pos += 4
            #_LOGGER.debug("After MOS Temperature, pos offset: %d", pos - start_pos)
            
            # Pack Temp Sensor Count (1 byte)
            temp_sensor_count = int(decoded[pos:pos+2], 16)
            battery["pack_temp_sensor_count"] = temp_sensor_count
            _LOGGER.debug("Pack Temp Sensor Count: %s -> %d", decoded[pos:pos+2], temp_sensor_count)
            pos += 2
            #_LOGGER.debug("After Pack Temp Sensor Count, pos offset: %d", pos - start_pos)
            
            # Pack Temp Sensors (each 2 bytes, /10)
            pack_temps = []
            for i in range(temp_sensor_count):
                pack_temp = convert_signed(decoded, pos, 4, scale=10)
                pack_temps.append(pack_temp)
                _LOGGER.debug("Pack Temp Sensor %d: %s -> %.1f °C", i+1, decoded[pos:pos+4], pack_temp)
                pos += 4
            battery["pack_temperatures"] = pack_temps
            #_LOGGER.debug("After Pack Temp Sensors, pos offset: %d", pos - start_pos)
            
            # Charging/Discharging Current (2 bytes, /100)
            battery["current"] = convert_signed(decoded, pos, 4, scale=100)
            _LOGGER.debug("Charging/Discharging Current: %s -> %.2f", decoded[pos:pos+4], battery["current"])
            pos += 4
            #_LOGGER.debug("After Current, pos offset: %d", pos - start_pos)
            
            # Pack Internal Resistance (2 bytes, raw)
            battery["internal_resistance"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Internal Resistance: %s -> %d", decoded[pos:pos+4], battery["internal_resistance"])
            pos += 4
            #_LOGGER.debug("After Internal Resistance, pos offset: %d", pos - start_pos)
            
            # Pack Health Status (SOH) (2 bytes, raw)
            battery["soh"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("SOH: %s -> %d", decoded[pos:pos+4], battery["soh"])
            pos += 4
            #_LOGGER.debug("After SOH, pos offset: %d", pos - start_pos)
            
            # User–Defined Number (1 byte)
            battery["user_defined"] = int(decoded[pos:pos+2], 16)
            _LOGGER.debug("User Defined Number: %s -> %d", decoded[pos:pos+2], battery["user_defined"])
            pos += 2
            _LOGGER.debug("After User Defined Number, pos offset: %d", pos - start_pos)
                        
            # Full Charge Capacity (2 bytes, /100)
            battery["full_charge_capacity"] = int(decoded[pos:pos+4], 16) / 100
            _LOGGER.debug("Full Charge Capacity: %s -> %.2f", decoded[pos:pos+4], battery["full_charge_capacity"])
            pos += 4
            #_LOGGER.debug("After Full Charge Capacity, pos offset: %d", pos - start_pos)
            
            # Remaining Capacity (2 bytes, /100)
            battery["remaining_capacity"] = int(decoded[pos:pos+4], 16) / 100
            _LOGGER.debug("Remaining Capacity: %s -> %.2f", decoded[pos:pos+4], battery["remaining_capacity"])
            pos += 4
            #_LOGGER.debug("After Remaining Capacity, pos offset: %d", pos - start_pos)
            
            # Number of Cycles (2 bytes, raw)
            battery["cycle_count"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Cycle Count: %s -> %d", decoded[pos:pos+4], battery["cycle_count"])
            pos += 4
            _LOGGER.debug("After Cycle Count, pos offset: %d", pos - start_pos)
                        
            # New Descriptive Fields:
            # Assume the following order:
            # 1. Maximum Cell Voltage (2 bytes, raw mV) – corresponds to original p18
            battery["max_cell_voltage"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Max Cell Voltage: %s -> %d", decoded[pos:pos+4], battery["max_cell_voltage"])
            pos += 4

            # 2. Minimum Cell Voltage (2 bytes, raw mV) – corresponds to original p20
            battery["min_cell_voltage"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Min Cell Voltage: %s -> %d", decoded[pos:pos+4], battery["min_cell_voltage"])
            pos += 4

            # Unknown Fields (each 2 bytes, raw)
            battery["max_cell_temp"] = convert_signed(decoded, pos, 4, scale=10)
            _LOGGER.debug("Max Cell Temp: %s -> %d", decoded[pos:pos+4], battery["max_cell_temp"])
            pos += 4

            battery["min_cell_temp"] = convert_signed(decoded, pos, 4, scale=10)
            _LOGGER.debug("Min Cell Temp: %s -> %d", decoded[pos:pos+4], battery["min_cell_temp"])
            pos += 4

            battery["unknown_3"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Unknown 3: %s -> %d", decoded[pos:pos+4], battery["unknown_3"])
            pos += 4

            battery["unknown_4"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Unknown 4: %s -> %d", decoded[pos:pos+4], battery["unknown_4"])
            pos += 4

            battery["avg_cell_temp"] = convert_signed(decoded, pos, 4, scale=10)
            _LOGGER.debug("Average Cell Temp?: %s -> %d", decoded[pos:pos+4], battery["avg_cell_temp"])
            pos += 4

            # 3. Average Cell Voltage (2 bytes) – corresponds to original p32
            battery["average_cell_voltage"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Average Cell Voltage: %s -> %d", decoded[pos:pos+4], battery["average_cell_voltage"])
            pos += 4

            # 4. Historical Maximum Pack Voltage (2 bytes) – corresponds to original p34
            battery["total_charge"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Total charge Ah: %s -> %d", decoded[pos:pos+4], battery["total_charge"])
            pos += 4

            # 5. Historical Maximum Cell Voltage (2 bytes) – corresponds to original p36
            battery["total_discharge"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Total Discharge Ah: %s -> %d", decoded[pos:pos+4], battery["total_discharge"])
            pos += 4

            # Voltage Status (2 bytes, raw)
            battery["voltage_status"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Voltage Status: %s -> %d", decoded[pos:pos+4], battery["voltage_status"])
            pos += 4
            #_LOGGER.debug("After Voltage Status, pos offset: %d", pos - start_pos)
            
            # Current Status (2 bytes, raw)
            battery["current_status"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Current Status: %s -> %d", decoded[pos:pos+4], battery["current_status"])
            pos += 4
            #_LOGGER.debug("After Current Status, pos offset: %d", pos - start_pos)
            
            # Temperature Status (2 bytes, raw)
            battery["temperature_status"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Temperature Status: %s -> %d", decoded[pos:pos+4], battery["temperature_status"])
            pos += 4
            #_LOGGER.debug("After Temperature Status, pos offset: %d", pos - start_pos)
            
            # Alarm Status (2 bytes, raw)
            battery["alarm_status"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Alarm Status: %s -> %d", decoded[pos:pos+4], battery["alarm_status"])
            pos += 4
            #_LOGGER.debug("After Alarm Status, pos offset: %d", pos - start_pos)
            
            # FET Status (2 bytes, raw)
            battery["fet_status"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("FET Status: %s -> %d", decoded[pos:pos+4], battery["fet_status"])
            pos += 4
            #_LOGGER.debug("After FET Status, pos offset: %d", pos - start_pos)
            
            # Final fields immediately following FET Status:
            # Overvoltage Protect (2 bytes, raw)
            battery["overvoltage_protect"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Overvoltage Protect: %s -> %d", decoded[pos:pos+4], battery["overvoltage_protect"])
            pos += 4
            #_LOGGER.debug("After Overvoltage Protect, pos offset: %d", pos - start_pos)
            
            # Undervoltage Protect (2 bytes, raw)
            battery["undervoltage_protect"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Undervoltage Protect: %s -> %d", decoded[pos:pos+4], battery["undervoltage_protect"])
            pos += 4
            #_LOGGER.debug("After Undervoltage Protect, pos offset: %d", pos - start_pos)
            
            # Overvoltage Alarm (2 bytes, raw)
            battery["overvoltage_alarm"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Overvoltage Alarm: %s -> %d", decoded[pos:pos+4], battery["overvoltage_alarm"])
            pos += 4
            #_LOGGER.debug("After Overvoltage Alarm, pos offset: %d", pos - start_pos)
            
            # Undervoltage Alarm (2 bytes, raw)
            battery["undervoltage_alarm"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Undervoltage Alarm: %s -> %d", decoded[pos:pos+4], battery["undervoltage_alarm"])
            pos += 4
            #_LOGGER.debug("After Undervoltage Alarm, pos offset: %d", pos - start_pos)

            # Balance status (2 bytes, raw)
            battery["balance_status"] = int(decoded[pos:pos+4], 16)
            _LOGGER.debug("Balance status: %s -> %d", decoded[pos:pos+4], battery["balance_status"])
            pos += 4
            #_LOGGER.debug("Balance status, pos offset: %d", pos - start_pos)
            
            expected_length = 212  # total hex digits (93 bytes)
            if pos - start_pos != expected_length:
                _LOGGER.warning("Battery block parse length mismatch: expected %d hex digits, got %d", 
                                expected_length, pos - start_pos)
            
            _LOGGER.debug("Final parsed pos offset: %d", pos - start_pos)
            _LOGGER.debug("Parsed battery: %s", battery)
            
            return battery, pos

        except Exception as err:
            _LOGGER.error("Error parsing battery block: %s", err)
            raise


    async def _send_command(self, command: bytes, battery_number: int | None = None) -> bytes | None:
        """Send command and get response."""
        cmd_packet = self._build_command(command, battery_number)
        formatted_cmd = self._format_message(cmd_packet)
        _LOGGER.debug("Sending command: %s", formatted_cmd)
        
        try:
            self._writer.write(cmd_packet)
            await self._writer.drain()
            
            # Protocol requires 850ms minimum between commands
            await asyncio.sleep(0.9)
            
            response = await self._read_response()
            if response:
                _LOGGER.debug("Got complete response")
                return response
            
            return None
            
        except Exception as err:
            _LOGGER.error("Error sending command: %s", err)
            return None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from battery BMS."""
        _LOGGER.debug("Starting data update cycle")
        
        async with self._lock:
            try:
                # Send query command and get response
                response = await self._send_command(b'42')
                if not response:
                    _LOGGER.error("No response received from BMS")
                    return self.data

                # Convert response to hex string, removing SOI (~) and EOI (\r)
                decoded = response[1:-1].decode('ascii', errors='ignore')
                _LOGGER.debug("Decoded response length: %d", len(decoded))

                # Clear existing data 
                self.data = {}

                try:
                    # Parse system header first
                    header_data, pos = self._parse_header_block(decoded)
                    # Store both raw and transformed data
                    self.data["raw_system"] = header_data  # Keep raw data for debugging
                    self.data["group"] = self._transform_group_data(header_data)  # For sensors
                    
                    battery_count = header_data["battery_count"]
                    _LOGGER.debug("Found %d batteries in system", battery_count)

                    # Parse each battery block
                    for i in range(battery_count):
                        try:
                            battery_data, pos = self._parse_battery_block(decoded, pos)
                            # Transform data for sensors and store using 1-based numbering
                            self.data[i + 1] = self._transform_battery_data(battery_data, i + 1)
                        except Exception as err:
                            _LOGGER.error("Failed to parse battery %d: %s", i + 1, err)
                            continue

                except Exception as err:
                    _LOGGER.error("Failed to parse header block: %s", err)
                    return self.data

                return self.data

            except Exception as err:
                _LOGGER.error("Error in update cycle: %s", err)
                return self.data
            
    def _transform_group_data(self, header_data: dict) -> dict:
        """Transform parsed header data into sensor-compatible format.
    
        Args:
            header_data: Raw parsed header data from first 68 bytes
        """
        return {
            # System measurements (0-7)
            "voltage": header_data["voltage"],  # 0-3 System average voltage
            "current": header_data["current"],  # 4-7 System total current
        
            # Voltage fields (8-15)
            "total_capacity": header_data["total_capacity"],  # 8-11
            "remaining_capacity": header_data["remaining_capacity"],  # 12-15
        
            # System state (16-19)
            "soc": header_data["soc"],  # 16-19 System SOC
        
            # Temperature readings (20-27)
            "max_ambient_temp": header_data["max_ambient_temp"],  # 20-23
            "min_ambient_temp": header_data["min_ambient_temp"],  # 24-27
        
            # Cell voltage range (28-35)
            "max_cell_voltage": header_data["max_cell_voltage"],  # 28-31
            "min_cell_voltage": header_data["min_cell_voltage"],  # 32-35
        
            # Additional parameters (36-43)
            "temperature_min": header_data["temperature_min"],  # 36-39
            "temperature_max": header_data["temperature_max"],  # 40-43
        
            # Reserved bytes stored as hex (44-63)
            "reserved": header_data["reserved"],  # 44-63
        
            # System configuration (64-67)
            "cell_count": header_data["cell_count"],  # 64-65
            "battery_count": header_data["battery_count"],  # 66-67
        }

    def _transform_battery_data(self, battery_data: dict, battery_num: int) -> dict:
        """Transform parsed battery data into sensor-compatible format.

        Args:
            battery_data: Raw parsed battery data from the battery block.
            battery_num: Battery number (1-based)

        Returns:
            A dictionary with sensor-compatible keys.
        """
        
         # Adjust the battery number from the parsed data (0-based) to the sensor's numbering (1-based)
        parsed_battery_num = battery_data.get("number", 0)
        adjusted_battery_num = parsed_battery_num + 1
        _LOGGER.debug("Adjusting battery number from parsed %d to sensor number %d", parsed_battery_num, adjusted_battery_num)
        battery_data["number"] = adjusted_battery_num
        
        return {
            # Basic Info (0-9)
            "number": battery_data["number"],  # Battery header (0-3)
            "soc": battery_data["soc"],  # SOC (4–5)
            "voltage": battery_data["voltage"],  # Pack Voltage (6–9)
            "cell_count": len(battery_data["cells"]),  # Number of cells

            # Cell Data (10-73)
            "cell_voltages": battery_data["cells"],  # List of cell voltages (each as a float)

            # Temperature Data (74-91)
            "temp_count": battery_data["pack_temp_sensor_count"],  # Number of temperature sensors
            "temperatures": battery_data["pack_temperatures"],  # List of sensor temperatures
            
            # Individual Temperature Sensors 
            "ambient_temperature": battery_data.get("ambient_temperature"),
            "pack_avg_temperature": battery_data.get("pack_avg_temperature"),
            "mos_temperature": battery_data.get("mos_temperature"),

            # Current and Resistance (92-99)
            "current": battery_data["current"],  # Charging/Discharging Current
            "internal_resistance": battery_data["internal_resistance"],

            # Battery Health (100-105)
            "soh": battery_data["soh"],  # State of Health
            "user_defined": battery_data["user_defined"],

            # Capacity Info (106-117)
            "full_capacity": battery_data["full_charge_capacity"],
            "remaining_capacity": battery_data["remaining_capacity"],
            "cycle_count": battery_data["cycle_count"],
            
            # New Descriptive Fields (extracted by the parser)
            "max_cell_voltage": battery_data["max_cell_voltage"],
            "min_cell_voltage": battery_data["min_cell_voltage"],
            "average_cell_voltage": battery_data["average_cell_voltage"],
            "total_charge": battery_data["total_charge"],
            "total_discharge": battery_data["total_discharge"],
            
            # Unknown Fields
            "max_cell_temp": battery_data["max_cell_temp"],
            "min_cell_temp": battery_data["min_cell_temp"],
            "unknown_3": battery_data["unknown_3"],
            "unknown_4": battery_data["unknown_4"],
            "avg_cell_temp": battery_data["avg_cell_temp"],

            # Status Values (118-143) combined into a single dict:
            "status": {
                "voltage": battery_data["voltage_status"],
                "current": battery_data["current_status"],
                "temperature": battery_data["temperature_status"],
                "alarm": battery_data["alarm_status"],
                "fet": battery_data["fet_status"],
            },

            # Protection States (final fields 144–159)
            "protection": {
                "overvoltage_protect": battery_data["overvoltage_protect"],
                "undervoltage_protect": battery_data["undervoltage_protect"],
                "overvoltage_alarm": battery_data["overvoltage_alarm"],
                "undervoltage_alarm": battery_data["undervoltage_alarm"],
                "balance_status": battery_data["balance_status"],
            }
        }

    async def async_get_protocol_version(self) -> str:
        """Get protocol version from BMS."""
        try:
            response = await self._send_command(b"4F", battery_number=0)  # Query master battery
            if not response:
                raise ValueError("No response received")
                
            decoded = response.decode("ascii", errors="ignore")[1:].strip()
            _LOGGER.debug("Protocol response: %s", self._format_message(response))
            
            # Protocol version is in the VER field (bytes 2-3)
            version = decoded[0:2]
            self.protocol_version = version
            _LOGGER.info("Protocol version: %s", version)
            return version
            
        except Exception as err:
            _LOGGER.error("Error getting protocol version: %s", err)
            raise
        