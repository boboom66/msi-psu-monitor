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

Writes to a single register. The response echoes the written data on success; a
reply whose first payload byte is `0xFC` (ACK) means accepted, `0xFE` (NAK) means
the device refused the value.

Implemented writes (frozen scope: fan control only; `0xC0` OCP writes are a later
batch):

| What | Command | Notes |
|------|---------|-------|
| Fan setting | `[0x50, 0x41, <mode>, 0x00, <duty>]` | `mode` 1 = auto (duty ignored), 3 = manual; `duty` 0-100, the PSU clamps out-of-range values |
| Persist settings | `[0x50, 0xF1, 0x00]` | Sent right after the fan write; without it the setting is lost on power-off |

`msi-psu-monitor --fan-mode/--fan-duty` does write → read-back verify (up to 3
attempts) → report `EXIT_ERROR` on a mismatch.

### NAK (0xFE)

If a command is not supported or an error occurs, the response starts with:
`[0xFE, ...]`

## Register Map

| Register | Address | Size | Description |
|----------|---------|------|-------------|
| VENDOR_STRING | 0x10 | 16 bytes | Vendor name (ASCII) |
| PRODUCT_STRING | 0x11 | 16 bytes | Product name (ASCII) |
| REVISION | 0x12 | 4 bytes | Firmware revision（冻结：TS 按 2B ASCII 透传如 `1.0`，非可打印再回退；旧 `<I` 十进制拼法废弃） |
| SERIAL | 0x13 | 16 bytes | Serial number（冻结：TS 按首字节长度切片，后面才是号码，别把长度当号码） |
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
| FAN_MODE | 0x41 | 2 bytes | Fan control mode（1=auto，3=manual；一期只读） |
| FAN_DUTY | 0x42 | 2 bytes | Fan duty 四元组[实际, MCU算, 软件设, ZeroFan==1]（一期读写：显示进 text，写走 `--fan-mode/--fan-duty` 0-100 单值 + F1h 保存，钳制 + 读回） |
| MULTIRAIL | 0xC0 | 8 bytes | OCP/告警阈值块（冻结：读 `==2` 为多轨，以 MSI Center 源码为准；旧 0/1 描述废弃；出厂单针 12A、针差 5A、触发 20s、警告 180s；写三期专批） |
| ALERT_STATUS | 0xE1 | 18 bytes | GPU Safeguard+ 状态（索引 `{6,7,8,18..29,14,15,16}`，失败回退 C1 state；Status 行 + exit 2 来源；待真机复核） |
| ALERT_LOG | 0xC1 | 26B×10 | GPU Safeguard+ 黑盒（`--show-log` 来源，最近 10 条新→旧；待真机复核） |
| UPTIME | 0xD0 | 4 bytes | Session uptime (seconds) |
| TOTAL_UPTIME | 0xD1 | 4 bytes | Total lifetime uptime (seconds) |
| SAVE_SETTING | 0xF1 | 1 byte | Persist the preceding `0x50` write to NVRAM (`[0x50, 0xF1, 0x00]`) |
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
