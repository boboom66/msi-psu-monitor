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

CMD_TIMEOUT_MS = 250
CMD_BUFFER_SIZE = 64

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
# E1h alert bitmap. The byte order is **model-specific**: MSI Center picks one
# of three index arrays from the PID before it names a bit (``CPSU.cs:1046``),
# so byte 0 means 12V OVP on a MEG PSU and 12V OCP on a MPG TS. Reading every
# model with one table mislabels every alert on the MEG units.
#
# Indices refer to ``AlertStatus`` (``CPSU.cs:287-350``):
#   0-2   OVP 12V / 5V / 3.3V      3-5   UVP 12V / 5V / 3.3V
#   6-8   OCP 12V / 5V / 3.3V      9-13  OCP 12V1..12V5 (multi-rail MEG only)
#   14-17 OPP / OTP / Fan / AC     18-29 OCP of the 12 pins of 12V-2x6 #1/#2
_ALERT_ENUM_NAMES = (
    "ovp_12v",
    "ovp_5v",
    "ovp_3v3",
    "uvp_12v",
    "uvp_5v",
    "uvp_3v3",
    "ocp_12v",
    "ocp_5v",
    "ocp_3v3",
    "ocp_12v1",
    "ocp_12v2",
    "ocp_12v3",
    "ocp_12v4",
    "ocp_12v5",
    "opp",
    "otp",
    "fan",
    "ac",
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
)

# Byte -> alert, per model (the three ``Alert_Index_*`` arrays, in order).
ALERT_INDEXES = {
    "mpg_ai1600ts": (6, 7, 8, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 14, 15, 16),
    "mpg_ai1300ts": (6, 7, 8, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 14, 15, 16),
    "ai1000p": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
    "ai1300p": (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
    "meg_ai1600": (0, 1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17),
}
ALERT_NAMES = {
    variant: tuple(_ALERT_ENUM_NAMES[i] for i in indexes)
    for variant, indexes in ALERT_INDEXES.items()
}
# The TS order is the one the CLI was written against and the only one whose
# 12V-2x6 pins are individually reported.
ALERT_NAMES_TS = ALERT_NAMES["mpg_ai1600ts"]

# 0xE0 bulk read layout for MPG Ai1600TS / Ai1300TS (62-byte payload).
# The first 44 bytes carry data, the remaining 18 bytes are zero padding; a
# shorter payload cannot be decoded (see ``get_sensors``). The order matches
# ``CPSU.cs GET_ALL`` for ``PID_MPG_Ai1300TS``/``PID_MPG_Ai1600TS``.
BULK_IOUT_12V = 0  # u16, LINEAR11 mA
BULK_IOUT_5V = 2  # u16, LINEAR11 mA
BULK_IOUT_3V3 = 4  # u16, LINEAR11 mA
BULK_IOUT_PINS_START = 6  # 12 x u16, LINEAR11 mA (per-pin currents)
BULK_IOUT_PINS_COUNT = 12
BULK_POWER = 30  # u16, LINEAR11 uW
BULK_EFFICIENCY = 32  # u16, LINEAR11 x100
BULK_TEMP = 34  # u16, LINEAR11 mC
BULK_FAN_RPM = 36  # u16, LINEAR11 (unsigned)
BULK_VOUT_12V = 38  # u16, LINEAR11 mV
BULK_VOUT_5V = 40  # u16, LINEAR11 mV
BULK_VOUT_3V3 = 42  # u16, LINEAR11 mV
BULK_DATA_SIZE = 44  # bytes of real data (the rest of the frame is zero padding)
BULK_FRAME_SIZE = 62  # bytes returned by the device for a 0xE0 read


def _is_truncated_ts_name(product):
    """True for "MPG Ai1300T": an 11-byte read of the 12-byte TS model name.

    MSI Center asks ``GET_MFR_MODEL`` for 12 bytes on the TS PIDs and 11 on the
    MEGs (``CPSU.cs``), so a short read loses exactly the trailing "S" -- and the
    generic ``Ai1300`` / ``Ai1600`` branches would then decode the frame with the
    MEG payload layout, silently, because "MPG Ai1300T" still matches "Ai1300".
    Refusing to guess is the only honest answer here.
    """
    name = (product or '').upper()
    if 'MPG' not in name or name.rstrip().endswith('S'):
        return False
    return any(f'AI{model}T' in name for model in ('1300', '1600'))


def lin11_to_int(v16, scale=1000, signed=False):
    """Convert SMBus LINEAR11 encoded value to integer.

    Mirrors MSI's ``ValueCalc`` (``CPSU.cs:1248``): the 5-bit exponent is
    two's complement, the 11-bit mantissa is **not** — ``Mantissa = ((High & 7)
    << 8) + Low`` never sign-extends, and REV6 agrees. Keep ``signed`` at its
    default for every device value; it exists for encodings that really do use
    a two's-complement mantissa.

    Args:
        v16: 16-bit raw value from the device
        scale: Multiplier for the mantissa (e.g., 1000 for mV or mA)
        signed: Whether the mantissa is two's complement (default: unsigned)

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


def _bulk_lin11(data, offset, scale=1000, signed=False):
    """Decode one LINEAR11 word at ``offset`` of a 0xE0 payload.

    ``scale`` matches ``lin11_to_int``: 1000 for mV/mA/mC, 100 for the x100
    efficiency, 1000000 for uW and 1 for the fan's raw RPM. REV6 leaves the
    mantissa unsigned, so ``signed`` stays False unless a variant says otherwise.
    """
    raw = struct.unpack("<H", data[offset : offset + 2])[0]
    return lin11_to_int(raw, scale, signed)


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
            FileNotFoundError: when no PSU was found and no path was given.
        """
        if self.path is None:
            # os.open(None) would raise TypeError, which no caller expects:
            # "no device" is an OSError-shaped failure everywhere else here.
            raise FileNotFoundError("no MSI PSU hidraw device found")
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

        A device error is a failure, never an exception: an unplugged PSU makes
        ``os.write``/``os.read`` raise ``OSError`` (ENODEV), and a vanished fd
        makes ``select`` raise, so all of it maps to ``None`` like a NAK. The
        daemon's rescan logic counts those, and a crash loop would never reach it.

        Args:
            data: List of bytes to send
            timeout_ms: Maximum time to wait for response in milliseconds

        Returns:
            Response bytes starting after the 2-byte echo header, or None on failure
        """
        if self.fd is None:
            return None

        # Drain any pending data (BlockingIOError is an OSError subclass).
        try:
            while os.read(self.fd, CMD_BUFFER_SIZE):
                pass
        except OSError:
            pass

        # Send command
        buf = bytearray(CMD_BUFFER_SIZE)
        buf[: len(data)] = data
        try:
            os.write(self.fd, bytes(buf))
        except OSError:
            return None

        # Wait for response
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0.01)
                if not ready:
                    continue
                resp = os.read(self.fd, CMD_BUFFER_SIZE)
            except (OSError, ValueError):
                return None
            if resp and len(resp) >= 2:
                # Check for NAK. An unsupported register answers with only two
                # bytes, [command, NAK] (msi-psu.c:186-198), for reads and writes
                # alike; a *refused write* to a real register instead echoes the
                # register first, [cmd, reg, NAK]. Both mean the PSU did not
                # accept the command, and the 2-byte form used to fall through as
                # b"" and read as success on a write.
                #
                # The byte-2 test is for writes only. On a read, byte 2 is the
                # first byte of the payload, and 0xFE is an ordinary data value
                # there: the low byte of a 12 V LINEAR11 word (11.984 V is
                # 0xCEFE) or of the uptime counter is 0xFE once every 256
                # seconds -- testing it on reads threw away measured data and
                # reported a healthy 0xE0 read as a failure.
                refused_write = (
                    data[0] == PSU_WRITE and len(resp) >= 3 and resp[2] == PSU_NAK
                )
                if resp[1] == PSU_NAK or refused_write:
                    return None
                return resp[2:]  # Skip 2-byte echo header
        return None

    def read_register(self, reg):
        """Read a single register and return raw bytes."""
        return self.send_command([PSU_READ, reg])

    def read_all(self):
        """Read all sensor values via the 0xE0 bulk command.

        Returns:
            Raw bytes of the 0xE0 bulk frame (44 bytes of data on the TS models,
            the whole frame on the MEG models), or None on failure
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

    # ``bulk_size`` is the frame the device returns for 0xE0; ``payload_size``
    # is the shortest frame that can still be decoded (the MPG models pad their
    # 44-byte payload out to 62 bytes).
    VARIANTS = {
        # ``pid`` is the USB product ID; tests/test_pid_consistency.py keeps it in
        # step with PSU_PRODUCT_IDS, the udev rule, the installer and the README.
        "ai1000p": {"name": "MEG Ai1000P", "pid": 0xE749, "bulk_size": 40, "payload_size": 40},
        "ai1300p": {"name": "MEG Ai1300P", "pid": 0x56D4, "bulk_size": 40, "payload_size": 40},
        "meg_ai1600": {"name": "MEG Ai1600(T)", "pid": 0xC9EB, "bulk_size": 20, "payload_size": 20},
        "mpg_ai1300ts": {
            "name": "MPG Ai1300TS",
            "pid": 0xAA6F,
            "bulk_size": 62,
            "payload_size": 44,
        },
        "mpg_ai1600ts": {
            "name": "MPG Ai1600TS",
            "pid": 0x808C,
            "bulk_size": 62,
            "payload_size": 44,
        },
    }
    SEVEN_ZPU_VARIANTS = ("mpg_ai1600ts", "mpg_ai1300ts")
    # Only the MEG P models answer the 1-byte multirail OCP flag (`CPSU.cs:823`);
    # the MPG TS models use the 8-byte 12V-2x6 config at the same address instead.
    MULTIRAIL_VARIANTS = ("ai1000p", "ai1300p")
    # Ai1000P/Ai1300P expose five discrete 12V rails plus a combined rail.
    RAIL_COUNT = 5

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

        # Read firmware revision (REV6 MFR_REVISION: two ASCII digits, "10" = 1.0).
        # MSI Center supplies the decimal point itself: CPSU.cs:497-507 reads two
        # bytes and calls GetString(...).Insert(1, "."), and the upstream README's
        # real capture "FW: 49.48" is those two digits ('1','0') printed as numbers.
        resp = self.hid.read_register(REG_REVISION)
        if resp:
            revision = bytes(resp).rstrip(b"\x00")
            # Exactly two digits: `>= 2` would truncate a longer digit-leading
            # payload (`b'1234'` -> "1.2") and report a revision the device never
            # sent, which is the opposite of what this branch promises.
            if len(revision) == 2 and revision.isdigit():
                self.fw_revision = f"{chr(revision[0])}.{chr(revision[1])}"
            else:
                # Anything else is passed through instead of turned into a guess.
                self.fw_revision = revision.decode("ascii", errors="replace").strip()

        # Read serial number (REV6 MFR_SERIAL: Byte1 = length prefix)
        resp = self.hid.read_register(REG_SERIAL)
        if resp and len(resp) >= 2:
            body = bytes(resp)
            if body[0] < 0x20 and 1 + body[0] <= len(body):
                body = body[1 : 1 + body[0]]
            self.serial = body.rstrip(b"\x00").decode("ascii", errors="replace").strip()

        # A name that lost its trailing "S" is a short read, not another model:
        # decoded as a MEG it would yield wrong bytes with no error at all.
        if _is_truncated_ts_name(self.product):
            self.variant = None
            return self.product

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

        # An unknown model cannot be decoded at any length: bail out before the
        # payload check so the reason is explicit rather than a generic "short
        # read" (the byte order of every register is model-dependent).
        if self.variant is None:
            sensors["error"] = (
                f"unsupported PSU variant (product={self.product!r}, "
                "variant=None): refusing to parse E0 payload"
            )
            return sensors

        # Read bulk data
        bulk_data = self.hid.read_all()
        payload_size = self.VARIANTS.get(self.variant, {}).get('payload_size', BULK_DATA_SIZE)
        if bulk_data is None or len(bulk_data) < payload_size:
            # A short frame cannot be decoded: reading zeros out of the padding
            # would look like a healthy PSU (REQ-P0-2). Distinguish "no answer"
            # from "answered but too short" so a wrong-length device is
            # diagnosable instead of looking like a dead link.
            if bulk_data is not None:
                sensors["payload_error"] = (
                    f"0xE0 payload too short for {self.variant}: "
                    f"got {len(bulk_data)} of {payload_size} bytes"
                )
            return sensors

        data = bulk_data[:BULK_FRAME_SIZE]

        # Parse based on variant
        if self.variant in MSIPSU.SEVEN_ZPU_VARIANTS:
            # 7ZPU 44-byte layout (REV6 E0h) with per-pin currents
            sensors["vout_12v"] = (
                round(_bulk_lin11(data, BULK_VOUT_12V) / 1000, 3),
                "V",
            )
            sensors["vout_5v"] = (
                round(_bulk_lin11(data, BULK_VOUT_5V) / 1000, 3),
                "V",
            )
            sensors["vout_3v3"] = (
                round(_bulk_lin11(data, BULK_VOUT_3V3) / 1000, 3),
                "V",
            )
            sensors["iout_12v_total"] = (
                round(_bulk_lin11(data, BULK_IOUT_12V) / 1000, 3),
                "A",
            )
            sensors["iout_5v"] = (
                round(_bulk_lin11(data, BULK_IOUT_5V) / 1000, 3),
                "A",
            )
            sensors["iout_3v3"] = (
                round(_bulk_lin11(data, BULK_IOUT_3V3) / 1000, 3),
                "A",
            )

            # Per-pin currents
            pin_currents = []
            for i in range(BULK_IOUT_PINS_COUNT):
                off = BULK_IOUT_PINS_START + i * 2
                pin_currents.append(round(_bulk_lin11(data, off) / 1000, 3))
            sensors["iout_pins"] = (pin_currents, "A")

            sensors["power_total"] = (
                round(_bulk_lin11(data, BULK_POWER, 1000000) / 1000000, 1),
                "W",
            )
            eff_raw = _bulk_lin11(data, BULK_EFFICIENCY, 100)
            sensors["efficiency"] = (round(eff_raw / 100, 2), "%")
            sensors["temp"] = (
                round(_bulk_lin11(data, BULK_TEMP) / 1000, 1),
                "°C",
            )
            sensors["fan_rpm"] = (
                int(_bulk_lin11(data, BULK_FAN_RPM, 1)),
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
            # 40-byte layout: 12V1..12V5 as (voltage, current) pairs, then the
            # combined 12V rail, then 5V/3.3V/power/efficiency/temp/fan
            # (CPSU.cs GET_ALL, PID_MEG_Ai1000P/PID_MEG_Ai1300P).
            rail_voltages = []
            rail_currents = []
            for rail in range(MSIPSU.RAIL_COUNT):
                rail_voltages.append(round(_bulk_lin11(data, rail * 4) / 1000, 3))
                rail_currents.append(round(_bulk_lin11(data, rail * 4 + 2) / 1000, 3))
            sensors["vout_12v_rails"] = (rail_voltages, "V")
            sensors["iout_12v_rails"] = (rail_currents, "A")
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

        return sensors

    @property
    def alert_names(self):
        """E1h byte order for this model, ``()`` when the model is unknown.

        Never guess: byte 0 is 12V OVP on a MEG and 12V OCP on a TS, so an
        unnamed byte would be reported as the wrong protection.
        """
        return ALERT_NAMES.get(self.variant, ())

    def read_alert_status(self):
        """Read the E1h alert bitmap (REV6 READ_ALERTSTATUS).

        The payload is as long as the model's index array: 18 bytes for the
        MPG TS and MEG P units, 13 for the MEG Ai1600T (``CPSU.cs:1046``).

        Returns:
            Dict mapping alert name to bool (True = alert active),
            or None when the model is unknown or the PSU does not answer.
        """
        names = self.alert_names
        if not names:
            return None
        data = self.hid.read_register(REG_ALERT_STATUS)
        if data is None or len(data) < len(names):
            return None
        return {name: bool(data[i]) for i, name in enumerate(names)}

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
            List of record dicts in device slot order (InfoID ascending), which
            is what the register returns; ``format_blackbox`` sorts them newest
            first using each record's own cumulative counters, because the
            firmware's slot direction is not documented. Stops at the first
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
        """Read READ_FANDUTY (42h).

        Only the first two bytes are defined for every model (current duty, the
        duty the MCU calculated). MSI Center returns before it looks at bytes 5
        and 6 on the MEG units (``CPSU.cs:810``), so the software-set duty and
        the Zero Fan flag are reported as ``None`` there rather than read out of
        bytes the reference implementation refuses to interpret.

        Returns:
            (current duty, MCU duty, software duty, zero_fan_on), or None when
            the model is unknown or the PSU does not answer.
        """
        if self.variant in MSIPSU.SEVEN_ZPU_VARIANTS:
            length, tail = 4, True
        elif self.variant is not None:
            length, tail = 2, False
        else:
            return None
        data = self.hid.read_register(REG_FAN_DUTY)
        if data is None or len(data) < length:
            return None
        if not tail:
            return (data[0], data[1], None, None)
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

    @property
    def supports_multirail_ocp(self):
        """True when the model answers the 1-byte multirail flag (C0h).

        ``CPSU.cs:823`` rejects the MEG Ai1600T and both MPG TS PIDs, so only the
        multi-rail MEG models reach the read.
        """
        return self.variant in MSIPSU.MULTIRAIL_VARIANTS

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

    def read_multirail_ocp(self):
        """Read the multirail OCP flag (C0h, 1 byte, MEG P models only).

        The same register that carries the 8-byte 12V-2x6 configuration on the
        MPG TS models answers this single byte on the Ai1000P/Ai1300P. ``2``
        means the PSU protects each 12V rail separately, ``1`` means it falls
        back to one combined rail (`CPSU.cs:823-832`).

        Returns:
            True/False for per-rail protection, or None when the model does not
            answer (MEG Ai1600T and the MPG TS models) or the read failed.
        """
        if self.variant not in self.MULTIRAIL_VARIANTS:
            # On these models 0xC0 is the 8-byte 12V-2x6 configuration instead; its
            # first byte is the OCP enable flag (1 by default), which would be read
            # as "one combined rail" on a model that has no multirail flag at all.
            return None
        data = self.hid.read_register(REG_MULTIRAIL)
        if data is None or len(data) < 1:
            return None
        return data[0] == 2
