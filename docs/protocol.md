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
| FAN_MODE | 0x41 | 3 bytes | Fan control mode + 自订占空比 `[mode, x, duty]`（1=auto，3=customized；一期读写，写走 `--fan-mode/--fan-duty` + F1h 保存） |
| FAN_DUTY | 0x42 | 2 or 4 bytes | 前两字节全机型有效：`[实际占空比, MCU 算出的占空比]`。后两字节（`[软件设定值, ZeroFan==1]`）**只有 MPG TS 系有定义**——MSI Center 在 MEG 机型上读到第 2 个字节就返回（`CPSU.cs:810`），因此本实现对 MEG 报 `None`，不去解释参考实现拒绝解释的字节（一期读；TS 的 ZeroFan 进 text 显示） |
| MULTIRAIL / OCP12V2x6_CONFIG | 0xC0 | 1 or 8 bytes | **重载寄存器**，同一地址两条命令、机型门互补：MEG Ai1000P/Ai1300P 读 1 字节多轨开关（`==2` 为多轨，`CPSU.cs:823-832`）；MPG Ai1300TS/Ai1600TS 读 8 字节 12V-2x6 OCP 阈值（`CPSU.cs:840-856`）；MEG Ai1600T 两条都不支持。12V-2x6 载荷 `[enable, 单针A, 针差A, 触发s, 针差触发s, 警告s]`，前两个 A 值为 LINEAR11（exp -4，即 `value<<4` 低字节 + `0xE0` 高字节，12A→`0xE0C0`、5A→`0xE050`）；出厂 12A/5A/20s/20s/180s。一期只读展示走 `--ocp`，写（8B + F1h）三期专批 |
| ALERT_STATUS | 0xE1 | 18 / 18 / 13 bytes | GPU Safeguard+ 状态。**字节序按机型查表**（MSI Center 三张索引数组，`CPSU.cs:1046-1057`）：MPG TS `{6,7,8,18..29,14,15,16}`（18B）、MEG P `{0..17}`（18B）、MEG Ai1600T `{0..8,14,15,16,17}`（13B）。同一个字节在 MEG 是 `OVP_12V`、在 TS 是 `OCP_12V`，**绝不共用一张表**；未知机型拒答（返回 None）而非猜。Status 行 + exit 2 来源；待真机复核 |
| ALERT_LOG | 0xC1 | 26B×10 | GPU Safeguard+ 黑盒（`--show-log` 来源，最近 10 条新→旧；待真机复核） |
| OCP12V2x6_STATE | 0xC1 | 42 bytes | InfoID `0x00`：12V-2x6 实时状态（`--ocp` 第二段来源）。`[0]=Conn1 状态, 1-4=运行计时, 5-8=总计时, 9-20=6 针电流, 21=Conn2 状态, 22-25=运行计时, 26-29=总计时, 30-41=6 针电流]`；状态码 `0` 正常 / `1` 单针 OCP / `2` 针差 / `3` 瞬时 OC(>18A)。注意 MSI Center 此处有个 bug：`I_Out_2_6 = ValueCalc(RxData[43], RxData[43])`（应为 44/45），本实现按正确偏移取 12 针 |
| UPTIME | 0xD0 | 4 bytes | Session uptime (seconds) |
| TOTAL_UPTIME | 0xD1 | 4 bytes | Total lifetime uptime (seconds) |
| SAVE_SETTING | 0xF1 | 1 byte | Persist the preceding `0x50` write to NVRAM (`[0x50, 0xF1, 0x00]`) |
| READ_EVERYTHING | 0xE0 | varies | Bulk read of all sensor values |

## Bulk Read (0xE0)

The 0xE0 command returns all sensor values in a single bulk payload. The
payload size and layout vary by PSU model. Each layout below is a payload of
its own right:

- the MPG models return 62 bytes of which only the first 44 are data, so
  `payload_size` is 44;
- the MEG Ai1600T returns 20 bytes — MSI Center's `i = 10` merely offsets its
  *output array*, it does not skip a prefix of the payload;
- the MEG Ai1000P/Ai1300P return 40 bytes.

A shorter frame than the variant's `payload_size` is rejected outright rather
than decoded from zero padding.

### MPG Ai1600TS / Ai1300TS (44 bytes of data in a 62-byte frame)

Offset | Size | Field | Format
-------|------|-------|-------
0 | 2 | Total +12V current | LINEAR11, mA
2 | 2 | +5V current | LINEAR11, mA
4 | 2 | +3.3V current | LINEAR11, mA
6-29 | 24 | Per-pin currents (12 pins × 2 bytes) | LINEAR11, mA
30 | 2 | Total output power | LINEAR11, uW
32 | 2 | Efficiency | LINEAR11, x100
34 | 2 | Internal temperature | LINEAR11, mC
36 | 2 | Fan speed | LINEAR11, unsigned
38 | 2 | +12V voltage | LINEAR11, mV
40 | 2 | +5V voltage | LINEAR11, mV
42 | 2 | +3.3V voltage | LINEAR11, mV
44-61 | 18 | Zero padding | -

### MEG Ai1600T (20 bytes)

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
0-19 | 20 | 12V1..12V5, each (voltage, current) | 5× (LINEAR11 mV, LINEAR11 mA)
20 | 2 | Combined +12V voltage | LINEAR11, mV
22 | 2 | Combined +12V current | LINEAR11, mA
24 | 2 | +5V voltage | LINEAR11, mV
26 | 2 | +5V current | LINEAR11, mA
28 | 2 | +3.3V voltage | LINEAR11, mV
30 | 2 | +3.3V current | LINEAR11, mA
32 | 2 | Total output power | LINEAR11, uW
34 | 2 | Efficiency | LINEAR11, x100
36 | 2 | Internal temperature | LINEAR11, mC
38 | 2 | Fan speed | LINEAR11, unsigned

## LINEAR11 Encoding

LINEAR11 packs a floating-point value into 16 bits:

```
Bit 15-11: Signed exponent (5-bit, two's complement)
Bit 10-0:  Mantissa (11-bit, UNSIGNED — REV6 and MSI both decode it that way)
Value = mantissa × 2^exponent
```

`lin11_to_int(v16, scale=1000, signed=False)` — the default **must** stay
unsigned: MSI writes `Mantissa = ((High & 7) << 8) + Low` with no sign
extension, so a mantissa with bit 10 set is a large positive number, not a
negative one. Reading it as two's complement turns a 2050 RPM fan into −2046
and any near-full-scale current into a nonsense negative.
`tests/test_protocol_lin11.py` cross-checks every word against a transcription
of `ValueCalc`, so the default cannot drift back.

MSI Center's decoder is literally `Mantissa * Math.Pow(2, Exponent)`
(`CPSU.cs:1248`), i.e. the value is returned in whatever unit the exponent
implies. This implementation keeps an integer path instead — the mantissa is
multiplied by a unit scale before the shift and divided back out afterwards —
which yields the same number:

- Voltage: 1000 → result in mV
- Current: 1000 → result in mA
- Power: 1000000 → result in uW
- Efficiency: 100 → result in percent × 100
- Temperature: 1000 → result in m°C

Because the mantissa is only 11 bits, the exponent decides the resolution: the
3.3 V rail cannot be expressed with a 1 mV or 500 mV LSB, only with a
sufficiently negative exponent (1/128 LSB gives 3.296 V). The OCP amp fields
use exponent −4 in the setter (`value << 4` with a `0xE0` high byte).
## Per-Pin Current Monitoring (GPU Safeguard+)

The MPG Ai1600TS features GPU Safeguard+ which monitors current on each of the
12 pins across both 12V-2x6 connectors. The 12 per-pin current values are
located at offsets 6-29 of the 0xE0 bulk read payload.

Each pin current is a 16-bit LINEAR11 value in milliamps. The pins are ordered
sequentially: pins 1-6 on connector 1, then pins 1-6 on connector 2.

The sum of all 12 pin currents should approximately equal the total +12V current
minus current drawn through non-GPU 12V loads (e.g., CPU, motherboard).


## OCP Configuration and State (0xC0 / 0xC1)

`msi-psu-monitor --ocp` renders the read-only protection view: the 12V-2x6 view on
the MPG TS models and the multirail flag on the MEG P models (the Ai1600T answers
neither and prints why, still exiting 0).

- **0xC0 `OCP12V2x6_CONFIG`** (8 bytes) — the configured thresholds. The two amp
  fields use LINEAR11 with exponent -4, which the setter in `CPSU.cs:184-207` builds as
  `low = value << 4`, `high = 0xE0`. So 12 A is the word `0xE0C0` and 5 A is `0xE050`.
  Note 0xC0 is overloaded: the MEG P models read the *multirail* flag (1 byte, `==2`
  meaning per-rail protection, `1` meaning one combined rail) from the same address,
  and the MEG Ai1600T answers neither — reject on the variant, never on the payload
  length alone. Both getters gate in `CPSU.cs:823` and `:840` with complementary
  model sets.
- **0xC1 InfoID `0x00` `OCP12V2x6_STATE`** (42 bytes) — the live state: per-connector
  status code, seconds spent in an alert state, total powered seconds and the twelve
  pin currents as 5-second averages. InfoID `1..10` on the same register is the
  black-box log used by `--show-log`, so the two readers must never be swapped.

The threshold write path (`0xC0` 8 bytes + `0xF1` save, with clamping to
10-14 A / 4-8 A / 5-30 s / 5-30 s / 30-240 s) stays frozen for a later, separately
approved batch.

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
