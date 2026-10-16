"""MSI PSU HID protocol constants and communication layer."""

import fcntl
import os
import glob
import struct
import select
import time

# PSU USB vendor/product IDs
PSU_VENDOR_ID = 0x0DB0
# 0x808C = Ai1600TS (1600W), 0xAA6F = Ai1300TS (1300W) per CWT REV6 spec.
# 0x56D4/0xE749/0xC9EB = legacy MEG/Ai-P models (layouts unverified, read-only compat).
PSU_PRODUCT_IDS = [0x808C, 0xAA6F, 0x56D4, 0xE749, 0xC9EB]

HIDRAW_PATH = None  # auto-detected
CMD_TIMEOUT_MS = 250
CMD_BUFFER_SIZE = 64
REPLY_SIZE = 40

# Protocol commands
PSU_INIT = 0xFA
PSU_READ = 0x51
PSU_WRITE = 0x50
PSU_NAK = 0xFE

# Register map
REG_VEND_STR = 0x10
REG_PROD_STR = 0x11
REG_REVISION = 0x12
REG_SERIAL = 0x13
REG_IN_VOLTS = 0x20
REG_VOUT_12V = 0x24
REG_IOUT_12V = 0x25
REG_VOUT_5V = 0x26
REG_IOUT_5V = 0x27
REG_VOUT_3V = 0x28
REG_IOUT_3V = 0x29
REG_TOTAL_WATTS = 0x2A
REG_EFFICIENCY = 0x2B
REG_TEMP0 = 0x30
REG_FAN_RPM = 0x40
REG_FAN_MODE = 0x41
REG_FAN_DUTY = 0x42
REG_IOUT_PINS = 0x2C
REG_ZERO_FAN = 0x43
REG_OCP_CONFIG = 0xC0
REG_OCP_STATE = 0xC1
REG_BUZZER_OFF = 0xC2
REG_ALERT_STATUS = 0xE1
REG_SAVE_SETTING = 0xF1
REG_MULTIRAIL = 0xC0
REG_UPTIME = 0xD0
REG_TOTAL_UPTIME = 0xD1
REG_READ_EVERYTHING = 0xE0

# E1h alert bitmap order (REV6 READ_ALERTSTATUS, 18 bytes, 0=OK 1=alert)
ALERT_NAMES = (
    "ocp_12v",
    "ocp_5v",
    "ocp_3v3",
    "ocp_pin1",
    "ocp_pin2",
    "ocp_pin3",
    "ocp_pin4",
    "ocp_pin5",
    "ocp_pin6",
    "ocp_pin7",
    "ocp_pin8",
    "ocp_pin9",
    "ocp_pin10",
    "ocp_pin11",
    "ocp_pin12",
    "opp",
    "otp",
    "fan",
)

# 0xE0 bulk read layout offsets for MPG Ai1600TS (62-byte payload)
# First 44 bytes contain data, remaining 18 bytes are zero padding
BULK_IOUT_12V = 0  # u16, LINEAR11 mA
BULK_IOUT_5V = 2  # u16, LINEAR11 mA
BULK_IOUT_3V3 = 4  # u16, LINEAR11 mA
BULK_IOUT_PINS_START = 6  # 12 x u16, LINEAR11 mA (per-pin currents)
BULK_IOUT_PINS_COUNT = 12
BULK_UNKNOWN = 28  # u16, unknown current value
BULK_POWER = 30  # u16, LINEAR11 uW
BULK_EFFICIENCY = 32  # u16, LINEAR11 x100
BULK_TEMP = 34  # u16, LINEAR11 mC
BULK_FAN_RPM = 36  # u16, LINEAR11 (unsigned)
BULK_VOUT_12V = 38  # u16, LINEAR11 mV
BULK_VOUT_5V = 40  # u16, LINEAR11 mV
BULK_VOUT_3V3 = 42  # u16, LINEAR11 mV


def lin11_to_int(v16, scale=1000, signed=True):
    """Convert SMBus LINEAR11 encoded value to integer.

    Args:
        v16: 16-bit raw value from the device
        scale: Multiplier for the mantissa (e.g., 1000 for mV or mA)
        signed: Whether the mantissa is signed (True for voltage/current)

    Returns:
        Integer value in the scaled unit (e.g., microvolts, milliamps)
    """
    exponent = (v16 >> 11) & 0x1F
    if exponent & 0x10:
        exponent |= ~0x1F  # sign extend 5-bit exponent
    if signed:
        mantissa = v16 & 0x7FF
        if mantissa & 0x400:  # sign extend 11-bit mantissa
            mantissa |= ~0x7FF
    else:
        mantissa = v16 & 0x7FF
    val = mantissa * scale
    return val << exponent if exponent >= 0 else val >> -exponent


def detect_devices():
    """Auto-detect all PSU hidraw devices by scanning sysfs.

    Searches /sys/class/hidraw/hidraw*/device/uevent for the PSU's
    USB vendor/product ID. Returns device paths in a stable (sorted)
    order, e.g. ['/dev/hidraw5'].
    """
    found = []
    for uevent in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        try:
            with open(uevent) as f:
                content = f.read()
        except OSError:
            continue
        for line in content.splitlines():
            if line.startswith("HID_ID="):
                parts = line.split("=")
                if len(parts) == 2:
                    hid_id = parts[1].strip()
                    # Format: 0003:00000DB0:0000808C
                    try:
                        fields = hid_id.split(":")
                        if len(fields) >= 3:
                            vendor = int(fields[1], 16)
                            product = int(fields[2], 16)
                            if vendor == PSU_VENDOR_ID and product in PSU_PRODUCT_IDS:
                                # Extract hidrawN from the uevent path
                                hidraw_dir = os.path.basename(os.path.dirname(uevent))
                                found.append("/dev/" + hidraw_dir)
                    except (ValueError, IndexError):
                        continue
    return found


def detect_device():
    """Auto-detect the PSU's hidraw device; return the first match or None."""
    devices = detect_devices()
    return devices[0] if devices else None


class DeviceBusyError(OSError):
    """Raised when the PSU hidraw device is locked by another process."""


class HIDDevice:
    """Low-level HID communication with the PSU over hidraw."""

    def __init__(self, path=None):
        if path is None:
            path = detect_device()
        self.path = path
        self.fd = None

    def open(self):
        """Open the hidraw device and take an exclusive flock.

        Raises:
            DeviceBusyError: when another process (CLI or daemon) holds the lock.
        """
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            raise DeviceBusyError(self.path)
        except OSError:
            # flock unsupported on this fd type: proceed without the lock
            pass
        return self

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def send_command(self, data, timeout_ms=CMD_TIMEOUT_MS):
        """Send a command and return the response data (excluding echo header).

        Args:
            data: List of bytes to send
            timeout_ms: Maximum time to wait for response in milliseconds

        Returns:
            Response bytes starting after the 2-byte echo header, or None on failure
        """
        # Drain any pending data
        try:
            while os.read(self.fd, CMD_BUFFER_SIZE):
                pass
        except (BlockingIOError, OSError):
            pass

        # Send command
        buf = bytearray(CMD_BUFFER_SIZE)
        buf[: len(data)] = data
        os.write(self.fd, bytes(buf))

        # Wait for response
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            r, _, _ = select.select([self.fd], [], [], 0.01)
            if r:
                resp = os.read(self.fd, CMD_BUFFER_SIZE)
                if resp and len(resp) >= 2:
                    # Check for NAK
                    if len(resp) >= 3 and resp[2] == PSU_NAK:
                        return None
                    return resp[2:]  # Skip 2-byte echo header
        return None

    def read_register(self, reg):
        """Read a single register and return raw bytes."""
        return self.send_command([PSU_READ, reg])

    def read_u16(self, reg):
        """Read a register and return as uint16."""
        data = self.read_register(reg)
        if data is None or len(data) < 2:
            return None
        return struct.unpack("<H", bytes(data[:2]))[0]

    def read_all(self):
        """Read all sensor values via the 0xE0 bulk command.

        Returns:
            Raw bytes of the 62-byte payload, or None on failure
        """
        return self.send_command([PSU_READ, REG_READ_EVERYTHING])

    def write_command(self, data, timeout_ms=CMD_TIMEOUT_MS):
        """Send a write command (0x50) and check the reply.

        Replies to writes echo command and register, then ACK (0xFC) or
        NAK (0xFE) as the first payload byte. send_command() maps NAK
        to None, so a non-None reply means the write was accepted.

        Args:
            data: List of bytes to send (command, register, payload...)
            timeout_ms: Maximum time to wait for the reply

        Returns:
            True when the PSU acknowledged the write, False otherwise.
        """
        reply = self.send_command([PSU_WRITE] + list(data), timeout_ms)
        return reply is not None


class MSIPSU:
    """High-level interface to an MSI PSU.

    Handles initialization, identification, and sensor reading.
    Supports multiple PSU variants with different 0xE0 payload layouts.
    """

    VARIANTS = {
        "ai1000p": {"name": "MEG Ai1000P", "bulk_size": 40},
        "ai1300p": {"name": "MEG Ai1300P", "bulk_size": 40},
        "meg_ai1600": {"name": "MEG Ai1600(T)", "bulk_size": 20},
        "mpg_ai1300ts": {"name": "MPG Ai1300TS", "bulk_size": 62},
        "mpg_ai1600ts": {"name": "MPG Ai1600TS", "bulk_size": 62},
    }
    SEVEN_ZPU_VARIANTS = ("mpg_ai1600ts", "mpg_ai1300ts")

    def __init__(self, hid_device=None):
        self.hid = hid_device or HIDDevice()
        self.vendor = ""
        self.product = ""
        self.fw_revision = ""
        self.serial = ""
        self.variant = None

    def open(self):
        self.hid.open()
        return self

    def close(self):
        self.hid.close()

    def init(self):
        """Initialize the PSU and read identification strings."""
        # Init handshake: [0xFA, 0x51] returns product name
        resp = self.hid.send_command([PSU_INIT, 0x51])
        if resp:
            self.product = (
                bytes(resp).rstrip(b"\x00").decode("ascii", errors="replace").strip()
            )

        # Read vendor string
        resp = self.hid.read_register(REG_VEND_STR)
        if resp:
            self.vendor = (
                bytes(resp).rstrip(b"\x00").decode("ascii", errors="replace").strip()
            )

        # Read firmware revision (REV6 MFR_REVISION: ASCII, e.g. '1.0')
        resp = self.hid.read_register(REG_REVISION)
        if resp:
            self.fw_revision = (
                bytes(resp).rstrip(b"\x00").decode("ascii", errors="replace").strip()
            )

        # Read serial number (REV6 MFR_SERIAL: Byte1 = length prefix)
        resp = self.hid.read_register(REG_SERIAL)
        if resp and len(resp) >= 2:
            body = bytes(resp)
            if body[0] < 0x20 and 1 + body[0] <= len(body):
                body = body[1 : 1 + body[0]]
            self.serial = body.rstrip(b"\x00").decode("ascii", errors="replace").strip()

        # Detect variant from product string. Ai1300TS must be checked before
        # the generic Ai1300 match: it is 7ZPU (44-byte E0 layout), not ai1300p.
        if "Ai1600TS" in self.product or "MPG Ai1600" in self.product:
            self.variant = "mpg_ai1600ts"
        elif "Ai1300TS" in self.product:
            self.variant = "mpg_ai1300ts"
        elif "Ai1600" in self.product:
            self.variant = "meg_ai1600"
        elif "Ai1300" in self.product:
            self.variant = "ai1300p"
        elif "Ai1000" in self.product:
            self.variant = "ai1000p"
        else:
            self.variant = None

        return self.product

    def get_sensors(self):
        """Read all sensor values and return as a dictionary.

        Returns:
            dict with sensor names mapped to (value, unit) tuples
        """
        sensors = {}
        sensors["vendor"] = self.vendor
        sensors["product"] = self.product
        sensors["fw_revision"] = self.fw_revision
        sensors["serial"] = self.serial

        # Read uptime (unconditional: ident-only and error paths keep it too)
        uptime_data = self.hid.read_register(REG_UPTIME)
        if uptime_data and len(uptime_data) >= 4:
            sensors["uptime"] = struct.unpack("<I", bytes(uptime_data[:4]))[0]
        total_uptime_data = self.hid.read_register(REG_TOTAL_UPTIME)
        if total_uptime_data and len(total_uptime_data) >= 4:
            sensors["uptime_total"] = struct.unpack("<I", bytes(total_uptime_data[:4]))[
                0
            ]

        # Read bulk data
        bulk_data = self.hid.read_all()
        if bulk_data is None or len(bulk_data) < 44:
            return sensors

        data = bulk_data[:62]

        # Parse based on variant
        if self.variant in MSIPSU.SEVEN_ZPU_VARIANTS:
            # 7ZPU 44-byte layout (REV6 E0h) with per-pin currents
            sensors["vout_12v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[38:40])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["vout_5v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[40:42])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["vout_3v3"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[42:44])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_12v_total"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[0:2])[0], 1000, False) / 1000,
                    3,
                ),
                "A",
            )
            sensors["iout_5v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[2:4])[0], 1000, False) / 1000,
                    3,
                ),
                "A",
            )
            sensors["iout_3v3"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[4:6])[0], 1000, False) / 1000,
                    3,
                ),
                "A",
            )

            # Per-pin currents
            pin_currents = []
            for i in range(12):
                off = 6 + i * 2
                if off + 2 <= len(data):
                    pin_val = round(
                        lin11_to_int(
                            struct.unpack("<H", data[off : off + 2])[0], 1000, False
                        )
                        / 1000,
                        3,
                    )
                    pin_currents.append(pin_val)
            sensors["iout_pins"] = (pin_currents, "A")

            sensors["power_total"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[30:32])[0], 1000000, False)
                    / 1000000,
                    1,
                ),
                "W",
            )
            eff_raw = lin11_to_int(struct.unpack("<H", data[32:34])[0], 100, False)
            sensors["efficiency"] = (round(eff_raw / 100, 2), "%")
            sensors["temp"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[34:36])[0], 1000, False)
                    / 1000,
                    1,
                ),
                "°C",
            )
            sensors["fan_rpm"] = (
                int(lin11_to_int(struct.unpack("<H", data[36:38])[0], 1, False)),
                "RPM",
            )

        elif self.variant == "meg_ai1600":
            # 20-byte layout (single combined 12V rail)
            sensors["vout_12v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[0:2])[0], 1000, False) / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_12v_total"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[2:4])[0], 1000, False) / 1000,
                    3,
                ),
                "A",
            )
            sensors["vout_5v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[4:6])[0], 1000, False) / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_5v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[6:8])[0], 1000, False) / 1000,
                    3,
                ),
                "A",
            )
            sensors["vout_3v3"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[8:10])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_3v3"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[10:12])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "A",
            )
            sensors["power_total"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[12:14])[0], 1000000, False)
                    / 1000000,
                    1,
                ),
                "W",
            )
            eff_raw = lin11_to_int(struct.unpack("<H", data[14:16])[0], 100, False)
            sensors["efficiency"] = (round(eff_raw / 100, 2), "%")
            sensors["temp"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[16:18])[0], 1000, False)
                    / 1000,
                    1,
                ),
                "°C",
            )
            sensors["fan_rpm"] = (
                int(lin11_to_int(struct.unpack("<H", data[18:20])[0], 1, False)),
                "RPM",
            )

        elif self.variant in ("ai1000p", "ai1300p"):
            # 40-byte layout (Ai1000P/Ai1300P with 6 per-rail 12V)
            sensors["vout_12v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[20:22])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_12v_total"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[22:24])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "A",
            )
            sensors["vout_5v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[24:26])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_5v"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[26:28])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "A",
            )
            sensors["vout_3v3"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[28:30])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "V",
            )
            sensors["iout_3v3"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[30:32])[0], 1000, False)
                    / 1000,
                    3,
                ),
                "A",
            )
            sensors["power_total"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[32:34])[0], 1000000, False)
                    / 1000000,
                    1,
                ),
                "W",
            )
            eff_raw = lin11_to_int(struct.unpack("<H", data[34:36])[0], 100, False)
            sensors["efficiency"] = (round(eff_raw / 100, 2), "%")
            sensors["temp"] = (
                round(
                    lin11_to_int(struct.unpack("<H", data[36:38])[0], 1000, False)
                    / 1000,
                    1,
                ),
                "°C",
            )
            sensors["fan_rpm"] = (
                int(lin11_to_int(struct.unpack("<H", data[38:40])[0], 1, False)),
                "RPM",
            )

        else:
            sensors["error"] = (
                f"unsupported PSU variant (product={self.product!r}, "
                "variant=None): refusing to parse E0 payload"
            )

        return sensors

    def read_alert_status(self):
        """Read the E1h alert bitmap (REV6 READ_ALERTSTATUS, 18 bytes).

        Returns:
            Dict mapping alert name to bool (True = alert active),
            or None when the PSU does not answer.
        """
        data = self.hid.read_register(REG_ALERT_STATUS)
        if data is None or len(data) < len(ALERT_NAMES):
            return None
        return {name: bool(data[i]) for i, name in enumerate(ALERT_NAMES)}

    def _parse_pin_currents(self, data, offset, count=6):
        """Decode count LINEAR11 pin currents (mA) from data at offset."""
        currents = []
        for i in range(count):
            off = offset + i * 2
            raw = struct.unpack("<H", bytes(data[off : off + 2]))[0]
            currents.append(round(lin11_to_int(raw, 1000, False) / 1000, 3))
        return currents

    def read_ocp_state(self):
        """Read C1h real-time 12+4 alert state (InfoID 0x00, 42 bytes).

        Returns:
            Dict with per-set status codes, run/total times and the 12
            pin currents (5-second averages, mA), or None on failure.
            Status: 0 normal, 1 OCP point, 2 current-difference, 3 instant OC.
        """
        data = self.hid.send_command([PSU_READ, REG_OCP_STATE, 0x00])
        if data is None or len(data) < 42:
            return None
        body = bytes(data)
        return {
            "status_12v5": body[0],
            "run_time": struct.unpack("<I", body[1:5])[0],
            "total_time": struct.unpack("<I", body[5:9])[0],
            "pins_1_6": self._parse_pin_currents(body, 9),
            "status_12v3": body[21],
            "run_time_2": struct.unpack("<I", body[22:26])[0],
            "total_time_2": struct.unpack("<I", body[26:30])[0],
            "pins_7_12": self._parse_pin_currents(body, 30),
        }

    def read_blackbox(self, max_records=10):
        """Read C1h black-box logs (InfoID 1..max_records, 26 bytes each).

        Returns:
            List of record dicts, oldest last. Stops at the first
            missing/short record.
        """
        records = []
        for info_id in range(1, max_records + 1):
            data = self.hid.send_command([PSU_READ, REG_OCP_STATE, info_id])
            if data is None or len(data) < 26:
                break
            body = bytes(data)
            records.append(
                {
                    "info_id": info_id,
                    "pin_set": body[0],
                    "status": body[1],
                    "run_time": struct.unpack("<I", body[2:6])[0],
                    "total_time": struct.unpack("<I", body[6:10])[0],
                    "pins_1_6": self._parse_pin_currents(body, 10),
                    "total_count": struct.unpack("<I", body[22:26])[0],
                }
            )
        return records

    @staticmethod
    def _lin11_float(v16):
        """Decode a LINEAR11 word to float (unsigned mantissa per REV6)."""
        exponent = (v16 >> 11) & 0x1F
        if exponent & 0x10:  # sign extend 5-bit exponent
            exponent |= ~0x1F
        mantissa = v16 & 0x7FF
        return mantissa * (2.0**exponent)

    def read_fan_setting(self):
        """Read FAN_SETTING (41h, 3 bytes: [mode, x, customize duty]).

        Returns:
            (mode, duty) or None. Mode 1 = default (auto),
            3 = customize.
        """
        data = self.hid.read_register(REG_FAN_MODE)
        if data is None or len(data) < 3:
            return None
        return (data[0], data[2])

    def read_fan_duty(self):
        """Read READ_FANDUTY (42h, 4 bytes).

        Returns:
            (current duty, MCU duty, software duty, zero_fan_on) or None.
        """
        data = self.hid.read_register(REG_FAN_DUTY)
        if data is None or len(data) < 4:
            return None
        return (data[0], data[1], data[2], bool(data[3]))

    def read_fan_state(self):
        """Read the fan mode (41h) plus the duty tuple (42h) in one call.

        Returns:
            {'mode': int|None, 'duty': int|None, 'zero_fan': bool|None};
            missing halves stay None instead of failing the whole read.
        """
        state = {'mode': None, 'duty': None, 'zero_fan': None}
        setting = self.read_fan_setting()
        if setting is not None:
            state['mode'], state['duty'] = setting
        duty = self.read_fan_duty()
        if duty is not None:
            state['zero_fan'] = duty[3]
        return state

    def set_fan_mode(self, mode, duty=0):
        """Write FAN_SETTING (41h) then SAVE_SETTING (F1h).

        Args:
            mode: 1 = default (auto), 3 = customize.
            duty: 0-100 customize duty (ignored by the PSU in auto mode).

        Returns:
            True when both the write and the save were acknowledged.
        """
        if not self.hid.write_command([REG_FAN_MODE, mode & 0xFF, 0x00, duty & 0xFF]):
            return False
        return self.hid.write_command([REG_SAVE_SETTING, 0x00])

    @property
    def supports_ocp_config(self):
        """True when the model answers OCP12+4_CONFIG (C0h).

        Only the 12V-2x6 models do: ``CPSU.cs:843`` returns false for every
        MEG PID (Ai1000P / Ai1300P / Ai1600T) before it even sends the read,
        so probe the variant instead of provoking a NAK.
        """
        return self.variant in MSIPSU.SEVEN_ZPU_VARIANTS

    def read_ocp_thresholds(self):
        """Read OCP12+4_CONFIG (C0h, 8 bytes).

        Layout per ``CPSU.cs:840-856``: byte 0 = enable, bytes 1-2 and 3-4
        are LINEAR11 (exponent -4) pin-OCP point and pin-difference in
        amps, then OCP trigger, difference trigger and warning times in
        whole seconds. Factory values: 12 A / 5 A / 20 s / 20 s / 180 s.

        Returns:
            Dict with on/off, OCP point (A), current difference (A),
            OCP trigger (s), difference trigger (s) and warning time (s),
            or None on failure. The amps stay unrounded so callers can
            decide how much precision to show.
        """
        data = self.hid.read_register(REG_OCP_CONFIG)
        if data is None or len(data) < 8:
            return None
        body = bytes(data)
        return {
            "enabled": body[0] == 1,
            "point_a": self._lin11_float(struct.unpack("<H", body[1:3])[0]),
            "diff_a": self._lin11_float(struct.unpack("<H", body[3:5])[0]),
            "trigger_s": body[5],
            "diff_trigger_s": body[6],
            "warning_s": body[7],
        }
