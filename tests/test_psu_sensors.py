"""Reader tests for ident strings, E1h alerts and C1h state (FakeHID, no hardware)."""

import struct

import pytest

from msi_psu_monitor.protocol import ALERT_NAMES, MSIPSU


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


def _psu_1300p(**overrides):
    """MEG Ai1300P: multi-rail 12V (PID 0x56D4 in MSI Center)."""
    registers = {
        0xFA: None,
        0x10: b'MSI\x00',
        0x11: b'MEG Ai1300P\x00',
        0x12: b'1.0',
        0x13: bytes([8]) + b'SN1300P1',
    }
    registers.update(overrides.get('registers', {}))
    commands = {(0xFA, 0x51): b'MEG Ai1300P\x00'}
    commands.update(overrides.get('commands', {}))
    psu = MSIPSU(FakeHID(registers=registers, commands=commands))
    psu.init()
    return psu


def _rail(volts, amps, exponent=-7):
    """Encode one rail pair as LINEAR11 words (mantissa = value x 2^-exponent).

    Exponent -7 (1/128 LSB) is fine enough to express the 3.3 V rail inside the
    11-bit mantissa; coarser exponents can only land on 3.0 or 3.5 V.
    """
    scale = 1 << -exponent
    exp_bits = exponent & 0x1F
    return _u16(_encode(int(volts * scale), exp_bits)) + _u16(_encode(int(amps * scale), exp_bits))


def _e0_payload_multi_rail():
    """40-byte 0xE0 payload: 12V1..12V5 (V,I), combined 12V, then the rest."""
    payload = bytearray(40)
    rails = ((12.0, 0.5), (12.0, 2.0), (12.0, 3.0), (12.0, 1.0), (12.0, 4.0))
    for index, (volts, amps) in enumerate(rails):
        payload[index * 4 : index * 4 + 4] = _rail(volts, amps)
    payload[20:24] = _rail(12.0, 10.5)
    payload[24:28] = _rail(5.0, 1.0)
    payload[28:32] = _rail(3.3, 0.5)
    payload[32:34] = _u16(_encode(300, 0))
    payload[34:36] = _u16(_encode(92, 0))
    payload[36:38] = _u16(_encode(45, 0))
    payload[38:40] = _u16(_encode(900, 0))
    return bytes(payload)


def test_multi_rail_bulk_keeps_every_discrete_rail():
    psu = _psu_1300p(commands={(0x51, 0xE0): _e0_payload_multi_rail()})
    sensors = psu.get_sensors()
    assert psu.variant == 'ai1300p'
    assert sensors['vout_12v_rails'] == ([12.0] * 5, 'V')
    assert sensors['iout_12v_rails'] == ([0.5, 2.0, 3.0, 1.0, 4.0], 'A')
    # The combined rail sits behind the five discrete ones, so it must not be
    # mistaken for rail 6.
    assert sensors['vout_12v'] == (12.0, 'V')
    assert sensors['iout_12v_total'] == (10.5, 'A')


def test_multi_rail_bulk_reads_the_shared_tail():
    psu = _psu_1300p(commands={(0x51, 0xE0): _e0_payload_multi_rail()})
    sensors = psu.get_sensors()
    assert sensors['vout_5v'] == (5.0, 'V')
    assert sensors['iout_5v'] == (1.0, 'A')
    assert sensors['vout_3v3'] == (3.296, 'V')
    assert sensors['iout_3v3'] == (0.5, 'A')
    assert sensors['power_total'] == (300.0, 'W')
    assert sensors['efficiency'] == (92.0, '%')
    assert sensors['temp'] == (45.0, '°C')
    assert sensors['fan_rpm'] == (900, 'RPM')


def test_multi_rail_short_payload_is_not_decoded():
    psu = _psu_1300p(commands={(0x51, 0xE0): bytes(40 - 1)})
    sensors = psu.get_sensors()
    assert 'iout_12v_rails' not in sensors
    assert 'vout_12v' not in sensors


def test_single_rail_model_reports_no_discrete_rails():
    psu = _psu_1300ts(commands={(0x51, 0xE0): _e0_payload()})
    sensors = psu.get_sensors()
    assert 'iout_12v_rails' not in sensors
    assert 'vout_12v_rails' not in sensors


def _psu_1600t(**overrides):
    """MEG Ai1600T: one combined 12V rail, 20-byte 0xE0 payload (PID 0xC9EB)."""
    registers = {
        0xFA: None,
        0x10: b'MSI\x00',
        0x11: b'MEG Ai1600T\x00',
        0x12: b'1.0',
        0x13: bytes([8]) + b'SN1600T1',
    }
    registers.update(overrides.get('registers', {}))
    commands = {(0xFA, 0x51): b'MEG Ai1600T\x00'}
    commands.update(overrides.get('commands', {}))
    psu = MSIPSU(FakeHID(registers=registers, commands=commands))
    psu.init()
    return psu


def _e0_payload_single_rail():
    """20-byte 0xE0 payload of the MEG Ai1600T."""
    payload = bytearray(20)
    payload[0:2] = _u16(_encode(12 * 128, 0x19))  # 12.0 V
    payload[2:4] = _u16(_encode(int(10.5 * 128), 0x19))  # 10.5 A
    payload[4:6] = _u16(_encode(5 * 128, 0x19))  # 5.0 V
    payload[6:8] = _u16(_encode(1 * 128, 0x19))  # 1.0 A
    payload[8:10] = _u16(_encode(int(3.3 * 128), 0x19))  # 3.296 V
    payload[10:12] = _u16(_encode(int(0.5 * 128), 0x19))  # 0.5 A
    payload[12:14] = _u16(_encode(300, 0))
    payload[14:16] = _u16(_encode(92, 0))
    payload[16:18] = _u16(_encode(45, 0))
    payload[18:20] = _u16(_encode(900, 0))
    return bytes(payload)


def test_ai1600t_decodes_its_own_20_byte_payload():
    """The 20-byte layout is a payload in its own right, not a prefix of 62.

    MSI Center's ``i = 10`` only offsets the *output* array, so a hard 44-byte
    gate would silently drop every sensor of this model.
    """
    psu = _psu_1600t(commands={(0x51, 0xE0): _e0_payload_single_rail()})
    sensors = psu.get_sensors()
    assert psu.variant == 'meg_ai1600'
    assert sensors['vout_12v'] == (12.0, 'V')
    assert sensors['iout_12v_total'] == (10.5, 'A')
    assert sensors['vout_5v'] == (5.0, 'V')
    assert sensors['iout_5v'] == (1.0, 'A')
    assert sensors['vout_3v3'] == (3.296, 'V')
    assert sensors['iout_3v3'] == (0.5, 'A')
    assert sensors['power_total'] == (300.0, 'W')
    assert sensors['efficiency'] == (92.0, '%')
    assert sensors['temp'] == (45.0, '°C')
    assert sensors['fan_rpm'] == (900, 'RPM')
    # No discrete rails on this model, so the export keeps N/A.
    assert 'iout_12v_rails' not in sensors


def test_ai1600t_truncated_payload_is_not_decoded():
    psu = _psu_1600t(commands={(0x51, 0xE0): bytes(19)})
    assert 'vout_12v' not in psu.get_sensors()


def _bitmap(**set_bytes):
    raw = bytearray(30)
    for index, value in set_bytes.items():
        raw[int(index)] = value
    return bytes(raw)


# MSI Center names an E1h bit with a per-PID index array (CPSU.cs:1046-1057),
# so the same byte is a different protection on each family. Hardcoded here as
# the reference: reading all models with the TS table silently relabels every
# MEG alert (byte 0 would print as "12V OCP" instead of "12V OVP").
_CS_ALERT_INDEX_P = tuple(range(18))
_CS_ALERT_INDEX_T = (0, 1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17)
_CS_ALERT_INDEX_TS = (6, 7, 8, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 14, 15, 16)
_CS_ALERT_ENUM = (
    'ovp_12v',
    'ovp_5v',
    'ovp_3v3',
    'uvp_12v',
    'uvp_5v',
    'uvp_3v3',
    'ocp_12v',
    'ocp_5v',
    'ocp_3v3',
    'ocp_12v1',
    'ocp_12v2',
    'ocp_12v3',
    'ocp_12v4',
    'ocp_12v5',
    'opp',
    'otp',
    'fan',
    'ac',
    'ocp_pin1',
    'ocp_pin2',
    'ocp_pin3',
    'ocp_pin4',
    'ocp_pin5',
    'ocp_pin6',
    'ocp_pin7',
    'ocp_pin8',
    'ocp_pin9',
    'ocp_pin10',
    'ocp_pin11',
    'ocp_pin12',
)


@pytest.mark.parametrize(
    ('variant_id', 'index_array'),
    [
        ('TS', _CS_ALERT_INDEX_TS),
        ('T', _CS_ALERT_INDEX_T),
        ('P', _CS_ALERT_INDEX_P),
    ],
)
def test_alert_names_follow_the_msi_center_index_array(variant_id, index_array):
    factory = {'TS': _psu_1300ts, 'T': _psu_1600t, 'P': _psu_1300p}[variant_id]
    assert factory().alert_names == tuple(_CS_ALERT_ENUM[i] for i in index_array)


def test_meg_p_model_does_not_reuse_the_ts_alert_order():
    """The two families disagree on byte 0, 3 and 13 — a shared table is a lie."""
    raw = _bitmap(**{'0': 1, '3': 1, '13': 1})
    status = _psu_1300p(registers={0xE1: raw}).read_alert_status()
    assert [name for name, active in status.items() if active] == [
        'ovp_12v',
        'uvp_12v',
        'ocp_12v5',
    ]
    assert 'ocp_pin1' not in status


def test_meg_t_model_reads_13_bytes_and_reports_ac():
    raw = _bitmap(**{'12': 1})
    status = _psu_1600t(registers={0xE1: raw}).read_alert_status()
    assert len(status) == 13
    assert [name for name, active in status.items() if active] == ['ac']
    # Two bytes short of the TS payload is still a complete T payload.
    assert _psu_1600t(registers={0xE1: raw[:13]}).read_alert_status() is not None


def test_unknown_variant_refuses_to_name_alert_bits():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai9999X\x00'}, registers={0x11: b'MEG Ai9999X\x00'}
    )
    assert psu.variant is None
    assert psu.alert_names == ()
    assert psu.read_alert_status() is None


def test_every_alert_name_has_a_description():
    """A name without a description leaks a raw identifier into the UI."""
    from msi_psu_monitor.alerts import describe

    for names in ALERT_NAMES.values():
        for name in names:
            assert describe(name) != name, name


# MSI Center's GET_FAN_DUTY returns before it reads bytes 5/6 on the MEG units
# (CPSU.cs:810), so those bytes are undefined there: reporting a Zero Fan state
# out of them would be inventing a reading.
def test_ts_fan_duty_reports_the_full_quadruple():
    psu = _psu_1300ts(registers={0x42: bytes([40, 42, 38, 1])})
    assert psu.read_fan_duty() == (40, 42, 38, True)
    assert psu.read_fan_state()['zero_fan'] is True
    assert _psu_1300ts(registers={0x42: bytes([40, 42])}).read_fan_duty() is None


@pytest.mark.parametrize('factory', [_psu_1300p, _psu_1600t])
def test_meg_fan_duty_ignores_the_undefined_tail(factory):
    """Two bytes are all a MEG defines; a stray ``1`` in byte 4 is not Zero Fan."""
    psu = factory(registers={0x42: bytes([40, 42, 38, 1])})
    assert psu.read_fan_duty() == (40, 42, None, None)
    assert psu.read_fan_state()['zero_fan'] is None
    # The two defined bytes still decode, so the duty display survives.
    assert psu.read_fan_duty()[:2] == (40, 42)
    assert factory(registers={0x42: bytes([40])}).read_fan_duty() is None


def test_unknown_variant_does_not_read_fan_duty():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai9999X\x00'}, registers={0x11: b'MEG Ai9999X\x00'}
    )
    assert psu.variant is None
    assert psu.read_fan_duty() is None
