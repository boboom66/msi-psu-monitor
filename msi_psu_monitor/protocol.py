"""MSI PSU HID protocol constants and communication layer."""

import os
import glob
import struct
import select
import time

# PSU USB vendor/product IDs
PSU_VENDOR_ID = 0x0DB0
PSU_PRODUCT_IDS = [0x808C, 0x56D4, 0xE749, 0xC9EB]

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
REG_MULTIRAIL = 0xC0
REG_UPTIME = 0xD0
REG_TOTAL_UPTIME = 0xD1
REG_READ_EVERYTHING = 0xE0

# 0xE0 bulk read layout offsets for MPG Ai1600TS (62-byte payload)
# First 44 bytes contain data, remaining 18 bytes are zero padding
BULK_IOUT_12V = 0      # u16, LINEAR11 mA
BULK_IOUT_5V = 2       # u16, LINEAR11 mA
BULK_IOUT_3V3 = 4      # u16, LINEAR11 mA
BULK_IOUT_PINS_START = 6   # 12 x u16, LINEAR11 mA (per-pin currents)
BULK_IOUT_PINS_COUNT = 12
BULK_UNKNOWN = 28       # u16, unknown current value
BULK_POWER = 30         # u16, LINEAR11 uW
BULK_EFFICIENCY = 32    # u16, LINEAR11 x100
BULK_TEMP = 34          # u16, LINEAR11 mC
BULK_FAN_RPM = 36       # u16, LINEAR11 (unsigned)
BULK_VOUT_12V = 38      # u16, LINEAR11 mV
BULK_VOUT_5V = 40       # u16, LINEAR11 mV
BULK_VOUT_3V3 = 42      # u16, LINEAR11 mV


def lin11_to_int(v16, scale=1000, signed=True):
    """Convert SMBus LINEAR11 encoded value to integer.

    Args:
        v16: 16-bit raw value from the device
        scale: Multiplier for the mantissa (e.g., 1000 for mV or mA)
        signed: Whether the mantissa is signed (True for voltage/current)

    Returns:
        Integer value in the scaled unit (e.g., microvolts, milliamps)
    """
    exponent = (v16 >> 11) & 0x1f
    if exponent & 0x10:
        exponent |= ~0x1f  # sign extend 5-bit exponent
    if signed:
        mantissa = v16 & 0x7ff
        if mantissa & 0x400:  # sign extend 11-bit mantissa
            mantissa |= ~0x7ff
    else:
        mantissa = v16 & 0x7ff
    val = mantissa * scale
    return val << exponent if exponent >= 0 else val >> -exponent


def detect_device():
    """Auto-detect the PSU's hidraw device by scanning sysfs.

    Searches /sys/class/hidraw/hidraw*/device/uevent for the PSU's
    USB vendor/product ID. Returns the device path (e.g. /dev/hidraw5)
    or None if not found.
    """
    for uevent in glob.glob('/sys/class/hidraw/hidraw*/device/uevent'):
        try:
            with open(uevent) as f:
                content = f.read()
        except OSError:
            continue
        for line in content.splitlines():
            if line.startswith('HID_ID='):
                parts = line.split('=')
                if len(parts) == 2:
                    hid_id = parts[1].strip()
                    # Format: 0003:00000DB0:0000808C
                    try:
                        fields = hid_id.split(':')
                        if len(fields) >= 3:
                            vendor = int(fields[1], 16)
                            product = int(fields[2], 16)
                            if vendor == PSU_VENDOR_ID and product in PSU_PRODUCT_IDS:
                                # Extract hidrawN from the path
                                hidraw_dir = uevent.split('/')[4]
                                dev_path = '/dev/' + hidraw_dir
                                return dev_path
                    except (ValueError, IndexError):
                        continue
    return None


class HIDDevice:
    """Low-level HID communication with the PSU over hidraw."""

    def __init__(self, path=None):
        if path is None:
            path = detect_device()
        self.path = path
        self.fd = None

    def open(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
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
        buf[:len(data)] = data
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
        return struct.unpack('<H', bytes(data[:2]))[0]

    def read_all(self):
        """Read all sensor values via the 0xE0 bulk command.

        Returns:
            Raw bytes of the 62-byte payload, or None on failure
        """
        return self.send_command([PSU_READ, REG_READ_EVERYTHING])


class MSIPSU:
    """High-level interface to an MSI PSU.

    Handles initialization, identification, and sensor reading.
    Supports multiple PSU variants with different 0xE0 payload layouts.
    """

    VARIANTS = {
        'ai1000p': {'name': 'MEG Ai1000P',  'bulk_size': 40},
        'ai1300p': {'name': 'MEG Ai1300P',  'bulk_size': 40},
        'meg_ai1600': {'name': 'MEG Ai1600(T)', 'bulk_size': 20},
        'mpg_ai1600ts': {'name': 'MPG Ai1600TS', 'bulk_size': 62},
    }

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
            self.product = bytes(resp).rstrip(b'\x00').decode('ascii', errors='replace').strip()

        # Read vendor string
        resp = self.hid.read_register(REG_VEND_STR)
        if resp:
            self.vendor = bytes(resp).rstrip(b'\x00').decode('ascii', errors='replace').strip()

        # Read firmware revision
        resp = self.hid.read_register(REG_REVISION)
        if resp and len(resp) >= 4:
            rev = struct.unpack('<I', bytes(resp[:4]))[0]
            self.fw_revision = f"{rev & 0xff}.{(rev >> 8) & 0xff}"

        # Read serial number
        resp = self.hid.read_register(REG_SERIAL)
        if resp and resp[0] >= 0x20 and resp[0] < 0x7f:
            self.serial = bytes(resp).rstrip(b'\x00').decode('ascii', errors='replace').strip()

        # Detect variant from product string
        if 'Ai1600TS' in self.product or 'MPG Ai1600' in self.product:
            self.variant = 'mpg_ai1600ts'
        elif 'Ai1600' in self.product:
            self.variant = 'meg_ai1600'
        elif 'Ai1300' in self.product:
            self.variant = 'ai1300p'
        elif 'Ai1000' in self.product:
            self.variant = 'ai1000p'
        else:
            self.variant = None

        return self.product

    def get_sensors(self):
        """Read all sensor values and return as a dictionary.

        Returns:
            dict with sensor names mapped to (value, unit) tuples
        """
        sensors = {}
        sensors['vendor'] = self.vendor
        sensors['product'] = self.product
        sensors['fw_revision'] = self.fw_revision
        sensors['serial'] = self.serial

        # Read bulk data
        bulk_data = self.hid.read_all()
        if bulk_data is None or len(bulk_data) < 44:
            return sensors

        data = bulk_data[:62]

        # Parse based on variant
        if self.variant == 'mpg_ai1600ts':
            # 62-byte layout with per-pin currents
            sensors['vout_12v'] = (round(lin11_to_int(struct.unpack('<H', data[38:40])[0], 1000, True) / 1000, 3), 'V')
            sensors['vout_5v'] = (round(lin11_to_int(struct.unpack('<H', data[40:42])[0], 1000, True) / 1000, 3), 'V')
            sensors['vout_3v3'] = (round(lin11_to_int(struct.unpack('<H', data[42:44])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_12v_total'] = (round(lin11_to_int(struct.unpack('<H', data[0:2])[0], 1000, True) / 1000, 3), 'A')
            sensors['iout_5v'] = (round(lin11_to_int(struct.unpack('<H', data[2:4])[0], 1000, True) / 1000, 3), 'A')
            sensors['iout_3v3'] = (round(lin11_to_int(struct.unpack('<H', data[4:6])[0], 1000, True) / 1000, 3), 'A')

            # Per-pin currents
            pin_currents = []
            for i in range(12):
                off = 6 + i * 2
                if off + 2 <= len(data):
                    pin_val = round(lin11_to_int(struct.unpack('<H', data[off:off+2])[0], 1000, True) / 1000, 3)
                    pin_currents.append(pin_val)
            sensors['iout_pins'] = (pin_currents, 'A')

            sensors['power_total'] = (round(lin11_to_int(struct.unpack('<H', data[30:32])[0], 1000000, True) / 1000000, 1), 'W')
            eff_raw = lin11_to_int(struct.unpack('<H', data[32:34])[0], 100, True)
            sensors['efficiency'] = (round(eff_raw / 100, 2), '%')
            sensors['temp'] = (round(lin11_to_int(struct.unpack('<H', data[34:36])[0], 1000, True) / 1000, 1), '°C')
            sensors['fan_rpm'] = (int(lin11_to_int(struct.unpack('<H', data[36:38])[0], 1, False)), 'RPM')

        elif self.variant == 'meg_ai1600':
            # 20-byte layout (single combined 12V rail)
            sensors['vout_12v'] = (round(lin11_to_int(struct.unpack('<H', data[0:2])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_12v_total'] = (round(lin11_to_int(struct.unpack('<H', data[2:4])[0], 1000, True) / 1000, 3), 'A')
            sensors['vout_5v'] = (round(lin11_to_int(struct.unpack('<H', data[4:6])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_5v'] = (round(lin11_to_int(struct.unpack('<H', data[6:8])[0], 1000, True) / 1000, 3), 'A')
            sensors['vout_3v3'] = (round(lin11_to_int(struct.unpack('<H', data[8:10])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_3v3'] = (round(lin11_to_int(struct.unpack('<H', data[10:12])[0], 1000, True) / 1000, 3), 'A')
            sensors['power_total'] = (round(lin11_to_int(struct.unpack('<H', data[12:14])[0], 1000000, True) / 1000000, 1), 'W')
            eff_raw = lin11_to_int(struct.unpack('<H', data[14:16])[0], 100, True)
            sensors['efficiency'] = (round(eff_raw / 100, 2), '%')
            sensors['temp'] = (round(lin11_to_int(struct.unpack('<H', data[16:18])[0], 1000, True) / 1000, 1), '°C')
            sensors['fan_rpm'] = (int(lin11_to_int(struct.unpack('<H', data[18:20])[0], 1, False)), 'RPM')

        else:
            # 40-byte layout (Ai1000P/Ai1300P with 6 per-rail 12V)
            sensors['vout_12v'] = (round(lin11_to_int(struct.unpack('<H', data[20:22])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_12v_total'] = (round(lin11_to_int(struct.unpack('<H', data[22:24])[0], 1000, True) / 1000, 3), 'A')
            sensors['vout_5v'] = (round(lin11_to_int(struct.unpack('<H', data[24:26])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_5v'] = (round(lin11_to_int(struct.unpack('<H', data[26:28])[0], 1000, True) / 1000, 3), 'A')
            sensors['vout_3v3'] = (round(lin11_to_int(struct.unpack('<H', data[28:30])[0], 1000, True) / 1000, 3), 'V')
            sensors['iout_3v3'] = (round(lin11_to_int(struct.unpack('<H', data[30:32])[0], 1000, True) / 1000, 3), 'A')
            sensors['power_total'] = (round(lin11_to_int(struct.unpack('<H', data[32:34])[0], 1000000, True) / 1000000, 1), 'W')
            eff_raw = lin11_to_int(struct.unpack('<H', data[34:36])[0], 100, True)
            sensors['efficiency'] = (round(eff_raw / 100, 2), '%')
            sensors['temp'] = (round(lin11_to_int(struct.unpack('<H', data[36:38])[0], 1000, True) / 1000, 1), '°C')
            sensors['fan_rpm'] = (int(lin11_to_int(struct.unpack('<H', data[38:40])[0], 1, False)), 'RPM')

        # Read uptime
        uptime_data = self.hid.read_register(REG_UPTIME)
        if uptime_data and len(uptime_data) >= 4:
            sensors['uptime'] = struct.unpack('<I', bytes(uptime_data[:4]))[0]
        total_uptime_data = self.hid.read_register(REG_TOTAL_UPTIME)
        if total_uptime_data and len(total_uptime_data) >= 4:
            sensors['uptime_total'] = struct.unpack('<I', bytes(total_uptime_data[:4]))[0]

        return sensors
