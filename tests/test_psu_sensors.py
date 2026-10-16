"""Reader tests for ident strings, E1h alerts and C1h state (FakeHID, no hardware)."""

import struct

from msi_psu_monitor.protocol import MSIPSU


def _encode(mantissa_u11, exponent_s5):
    return ((exponent_s5 & 0x1F) << 11) | (mantissa_u11 & 0x7FF)


def _u16(value):
    return struct.pack('<H', value)


class FakeHID:
    def __init__(self, registers=None, commands=None):
        self.registers = registers or {}
        self.commands = commands or {}

    def send_command(self, data, timeout_ms=250):
        return self.commands.get(tuple(data))

    def read_register(self, reg):
        return self.registers.get(reg)

    def read_all(self):
        return self.commands.get((0x51, 0xE0))

    def open(self):
        return self

    def close(self):
        pass


def _psu_1300ts(**overrides):
    registers = {
        0xFA: None,
        0x10: b'MSI\x00',
        0x11: b'MPG Ai1300TS\x00',
        0x12: b'1.0',
        0x13: bytes([8]) + b'SN123456',
    }
    registers.update(overrides.get('registers', {}))
    commands = {(0xFA, 0x51): b'MPG Ai1300TS\x00'}
    commands.update(overrides.get('commands', {}))
    psu = MSIPSU(FakeHID(registers=registers, commands=commands))
    psu.init()
    return psu


def test_fw_revision_decoded_as_ascii():
    psu = _psu_1300ts()
    assert psu.fw_revision == '1.0'


def test_ai1300ts_detected_as_7zpu_variant():
    psu = _psu_1300ts()
    assert psu.product == 'MPG Ai1300TS'
    assert psu.variant == 'mpg_ai1300ts'


def test_serial_strips_length_prefix():
    psu = _psu_1300ts()
    assert psu.serial == 'SN123456'


def test_serial_legacy_printable_first_byte():
    psu = _psu_1300ts(registers={0x13: b'ABC123\x00\x00'})
    assert psu.serial == 'ABC123'


def test_read_alert_status_bitmap():
    raw = bytearray(18)
    raw[3] = 1
    raw[17] = 1
    psu = _psu_1300ts(registers={0xE1: bytes(raw)})
    status = psu.read_alert_status()
    assert status['ocp_pin1'] is True
    assert status['fan'] is True
    assert status['ocp_12v'] is False
    assert status['opp'] is False
    assert len(status) == 18


def test_read_alert_status_short_or_missing():
    assert _psu_1300ts(registers={0xE1: b'\x00' * 5}).read_alert_status() is None
    assert _psu_1300ts().read_alert_status() is None


def _ocp_state_payload():
    body = bytearray(42)
    body[0] = 2
    body[1:5] = struct.pack('<I', 1234)
    body[5:9] = struct.pack('<I', 99999)
    for i in range(6):
        body[9 + i * 2 : 11 + i * 2] = _u16(_encode(1500 + i, 0x1F))
    body[21] = 1
    body[22:26] = struct.pack('<I', 4321)
    body[26:30] = struct.pack('<I', 88888)
    for i in range(6):
        body[30 + i * 2 : 32 + i * 2] = _u16(_encode(1000, 0x1F))
    return bytes(body)


def test_read_ocp_state_realtime():
    psu = _psu_1300ts(commands={(0x51, 0xC1, 0x00): _ocp_state_payload()})
    state = psu.read_ocp_state()
    assert state['status_12v5'] == 2
    assert state['run_time'] == 1234
    assert state['total_time'] == 99999
    assert state['pins_1_6'][0] == 750.0
    assert state['status_12v3'] == 1
    assert state['run_time_2'] == 4321
    assert state['pins_7_12'][0] == 500.0


def test_read_ocp_state_short():
    psu = _psu_1300ts(commands={(0x51, 0xC1, 0x00): b'\x00' * 10})
    assert psu.read_ocp_state() is None


def _blackbox_record(pin_set=1, status=2, count=7):
    body = bytearray(26)
    body[0] = pin_set
    body[1] = status
    body[2:6] = struct.pack('<I', 100)
    body[6:10] = struct.pack('<I', 200)
    for i in range(6):
        body[10 + i * 2 : 12 + i * 2] = _u16(_encode(800, 0x1F))
    body[22:26] = struct.pack('<I', count)
    return bytes(body)


def test_read_blackbox_stops_at_gap():
    psu = _psu_1300ts(
        commands={
            (0x51, 0xC1, 1): _blackbox_record(count=7),
            (0x51, 0xC1, 2): _blackbox_record(pin_set=2, status=1, count=3),
        }
    )
    records = psu.read_blackbox()
    assert len(records) == 2
    assert records[0]['info_id'] == 1
    assert records[0]['total_count'] == 7
    assert records[0]['pins_1_6'][0] == 400.0
    assert records[1]['pin_set'] == 2
    assert records[1]['status'] == 1


def test_unknown_variant_refuses_to_parse():
    psu = _psu_1300ts(commands={(0xFA, 0x51): b'Mystery 9000\x00'})
    assert psu.variant is None
    bulk = {(0x51, 0xE0): bytes(62)}
    psu.hid.commands.update(bulk)
    sensors = psu.get_sensors()
    assert 'error' in sensors
    assert 'vout_12v' not in sensors


def _e0_payload():
    payload = bytearray(44)
    payload[0:2] = _u16(_encode(5, 0x1F))
    payload[30:32] = _u16(_encode(500, 0))
    payload[32:34] = _u16(_encode(90, 0))
    payload[34:36] = _u16(_encode(51, 0))
    payload[36:38] = _u16(_encode(536, 0))
    payload[38:40] = _u16(_encode(12, 0))
    return bytes(payload)


def test_7zpu_bulk_happy_path():
    psu = _psu_1300ts(commands={(0x51, 0xE0): _e0_payload()})
    sensors = psu.get_sensors()
    assert sensors['iout_12v_total'] == (2.5, 'A')
    assert sensors['vout_12v'] == (12.0, 'V')
    assert sensors['power_total'] == (500.0, 'W')
    assert sensors['efficiency'] == (90.0, '%')
    assert sensors['temp'] == (51.0, '°C')
    assert sensors['fan_rpm'] == (536, 'RPM')
    assert sensors['fw_revision'] == '1.0'
    assert 'error' not in sensors
