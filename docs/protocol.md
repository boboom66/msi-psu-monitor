# MSI PSU HID Protocol Documentation

## Overview

MSI power supplies with a USB monitoring interface use a custom HID protocol
over a vendor-defined HID usage page (0xFF00). Communication occurs via 64-byte
HID reports on the interrupt endpoint.

All commands follow a request-response pattern: send a 64-byte report, receive
a 64-byte response. The first byte of the response echoes the command byte,
followed by the data payload.

## Device Identification

The PSU appears as a HID device with:
- Vendor ID: `0x0db0` (Micro Star International)
- Product ID: varies by model (see Supported Hardware table)
- Usage Page: 0xFF00 (vendor-defined)
- Report Size: 64 bytes

## Command Protocol

### Init Handshake

Send: `[0xFA, 0x51, 0x00, ...]`
Response: `[0xFA, 0x51, <product_name>, 0x00, ...]`

The product name is an ASCII string starting at byte 2, null-terminated.
Example: `MPG Ai1600TS`

### Register Read (0x51)

Send: `[0x51, <register>, 0x00, ...]`
Response: `[0x51, <register>, <data_bytes...>, 0x00, ...]`

Reads a single register. The register byte is echoed in the response, followed
by the register data. Most registers return 2 bytes (uint16, little-endian).

### Register Write (0x50)

Send: `[0x50, <register>, <data_bytes...>, 0x00, ...]`
Response: `[0x50, <register>, <data_bytes...>, 0x00, ...]`

Writes to a single register. The response echoes the written data on success.

### NAK (0xFE)

If a command is not supported or an error occurs, the response starts with:
`[0xFE, ...]`

## Register Map

| Register | Address | Size | Description |
|----------|---------|------|-------------|
| VENDOR_STRING | 0x10 | 16 bytes | Vendor name (ASCII) |
| PRODUCT_STRING | 0x11 | 16 bytes | Product name (ASCII) |
| REVISION | 0x12 | 4 bytes | Firmware revision (uint32, BCD) |
| SERIAL | 0x13 | 16 bytes | Serial number (ASCII or binary) |
| IN_VOLTS | 0x20 | 2 bytes | AC input voltage (LINEAR11, mV) |
| VOUT_12V | 0x24 | 2 bytes | 12V rail voltage (LINEAR11, mV) |
| IOUT_12V | 0x25 | 2 bytes | 12V rail current (LINEAR11, mA) |
| VOUT_5V | 0x26 | 2 bytes | 5V rail voltage (LINEAR11, mV) |
| IOUT_5V | 0x27 | 2 bytes | 5V rail current (LINEAR11, mA) |
| VOUT_3V3 | 0x28 | 2 bytes | 3.3V rail voltage (LINEAR11, mV) |
| IOUT_3V3 | 0x29 | 2 bytes | 3.3V rail current (LINEAR11, mA) |
| TOTAL_WATTS | 0x2A | 2 bytes | Total output power (LINEAR11, uW) |
| EFFICIENCY | 0x2B | 2 bytes | Efficiency (LINEAR11, x100) |
| TEMP0 | 0x30 | 2 bytes | Internal temperature (LINEAR11, mC) |
| FAN_RPM | 0x40 | 2 bytes | Fan speed (LINEAR11, unsigned) |
| FAN_MODE | 0x41 | 2 bytes | Fan control mode |
| FAN_DUTY | 0x42 | 2 bytes | Fan duty cycle |
| MULTIRAIL | 0xC0 | 2 bytes | Multi-rail mode (0=single, 1=multi) |
| UPTIME | 0xD0 | 4 bytes | Session uptime (seconds) |
| TOTAL_UPTIME | 0xD1 | 4 bytes | Total lifetime uptime (seconds) |
| READ_EVERYTHING | 0xE0 | varies | Bulk read of all sensor values |

## Bulk Read (0xE0)

The 0xE0 command returns all sensor values in a single bulk payload. The
payload size and layout vary by PSU model:

### MPG Ai1600TS (62 bytes)

Offset | Size | Field | Format
-------|------|-------|-------
0 | 2 | Total +12V current | LINEAR11, mA
2 | 2 | +5V current | LINEAR11, mA
4 | 2 | +3.3V current | LINEAR11, mA
6-28 | 24 | Per-pin currents (12 pins × 2 bytes) | LINEAR11, mA
28 | 2 | Unknown current value | LINEAR11, mA
30 | 2 | Total output power | LINEAR11, uW
32 | 2 | Efficiency | LINEAR11, x100
34 | 2 | Internal temperature | LINEAR11, mC
36 | 2 | Fan speed | LINEAR11, unsigned
38 | 2 | +12V voltage | LINEAR11, mV
40 | 2 | +5V voltage | LINEAR11, mV
42 | 2 | +3.3V voltage | LINEAR11, mV
44-61 | 18 | Zero padding | -

### MEG Ai1600(T) (20 bytes)

Offset | Size | Field | Format
-------|------|-------|-------
0 | 2 | +12V voltage | LINEAR11, mV
2 | 2 | Total +12V current | LINEAR11, mA
4 | 2 | +5V voltage | LINEAR11, mV
6 | 2 | +5V current | LINEAR11, mA
8 | 2 | +3.3V voltage | LINEAR11, mV
10 | 2 | +3.3V current | LINEAR11, mA
12 | 2 | Total output power | LINEAR11, uW
14 | 2 | Efficiency | LINEAR11, x100
16 | 2 | Internal temperature | LINEAR11, mC
18 | 2 | Fan speed | LINEAR11, unsigned

### MEG Ai1300P / MEG Ai1000P (40 bytes)

Offset | Size | Field | Format
-------|------|-------|-------
0-24 | 24 | Per-rail 12V (6 rails × 4 bytes) | 6× (LINEAR11 mV, LINEAR11 mA)
24 | 2 | +5V voltage | LINEAR11, mV
26 | 2 | +5V current | LINEAR11, mA
28 | 2 | +3.3V voltage | LINEAR11, mV
30 | 2 | +3.3V current | LINEAR11, mA
32 | 2 | Total output power | LINEAR11, uW
34 | 2 | Efficiency | LINEAR11, x100
36 | 2 | Internal temperature | LINEAR11, mC
38 | 2 | Fan speed | LINEAR11, unsigned

## LINEAR11 Encoding

SMBus LINEAR11 format encodes a floating-point value in 16 bits:

```
Bit 15-11: Signed exponent (5-bit, two's complement)
Bit 10-0:  Signed mantissa (11-bit, two's complement)

Value = mantissa × 2^exponent
```

The mantissa is scaled by a unit multiplier:
- Voltage: 1000 → result in mV
- Current: 1000 → result in mA
- Power: 1000000 → result in uW
- Efficiency: 100 → result in percent × 100
- Temperature: 1000 → result in m°C

## Per-Pin Current Monitoring (GPU Safeguard+)

The MPG Ai1600TS features GPU Safeguard+ which monitors current on each of the
12 pins across both 12V-2x6 connectors. The 12 per-pin current values are
located at offsets 6-28 of the 0xE0 bulk read payload.

Each pin current is a 16-bit LINEAR11 value in milliamps. The pins are ordered
sequentially: pins 1-6 on connector 1, then pins 1-6 on connector 2.

The sum of all 12 pin currents should approximately equal the total +12V current
minus current drawn through non-GPU 12V loads (e.g., CPU, motherboard).

## Debugfs Interface (kernel module)

When the kernel module is loaded, additional debugfs entries are available at
`/sys/kernel/debug/<hid_device>/`:

- `vendor` - Vendor name string
- `product` - Product name string
- `fw_revision` - Firmware revision
- `serial` - Serial number
- `multirail` - Multi-rail mode (read/write)
- `iout_pins` - Per-pin currents (space-separated, MPG Ai1600TS only)

## References

- Jack Doan's msi-psu kernel driver: https://github.com/JackDoan/msi-psu
- PR #3 (MEG Ai1600(T) support): https://github.com/JackDoan/msi-psu/pull/3
- MSI MPG Ai1600TS product page: https://www.msi.com/Power-Supply/MPG-Ai1600TS-PCIE5
