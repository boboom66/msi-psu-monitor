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


def test_fw_revision_is_two_digits_with_the_msi_decimal_point():
    """The device answers "10"; MSI Center inserts the dot itself.

    ``CPSU.cs:497-507`` reads two bytes and calls ``GetString(...).Insert(1, '.')``,
    and the upstream README's real capture "FW: 49.48" is exactly those two bytes
    ('1','0') printed as numbers -- decoding them verbatim displayed "10".
    """
    psu = _psu_1300ts(registers={0x12: b'10\x00'})
    assert psu.fw_revision == '1.0'


def test_fw_revision_falls_back_for_a_payload_that_is_not_two_digits():
    """A non-conforming answer is passed through, minus non-printable bytes.

    The pass-through rule stops the code from inventing a revision; the
    printable-ASCII filter then keeps a hostile payload out of journald, the
    CSV export and a Prometheus label (CRA ST-008).
    """
    assert _psu_1300ts(registers={0x12: b'1.0'}).fw_revision == '1.0'
    assert _psu_1300ts(registers={0x12: b'7'}).fw_revision == '7'
    assert _psu_1300ts(registers={0x12: b'\xff\xfe'}).fw_revision == ''


def test_fw_revision_does_not_truncate_a_longer_digit_leading_payload():
    """The rule is "exactly two digits", not "starts with two digits".

    `>= 2` turned a device that answered `b'1234'` into the revision "1.2" -- a
    number it never sent -- while docs/protocol.md promises pass-through for any
    payload that is not two digits.
    """
    assert _psu_1300ts(registers={0x12: b'1234'}).fw_revision == '1234'
    assert _psu_1300ts(registers={0x12: b'100'}).fw_revision == '100'
    assert _psu_1300ts(registers={0x12: b'10\x00\x00'}).fw_revision == '1.0'


def test_ai1300ts_detected_as_7zpu_variant():
    psu = _psu_1300ts()
    assert psu.product == 'MPG Ai1300TS'
    assert psu.variant == 'mpg_ai1300ts'


@pytest.mark.parametrize('name', ['MPG Ai1600T', 'MPG Ai1300T'])
def test_a_truncated_ts_model_name_is_refused_instead_of_guessed(name):
    """An 11-byte read of a 12-byte TS name would decode as a MEG, silently.

    MSI Center asks GET_MFR_MODEL for 12 bytes on the TS PIDs and 11 on the MEGs
    (``CPSU.cs``), so the trailing "S" is exactly what a short read loses -- and
    the generic ``Ai1300``/``Ai1600`` branch still matches what is left.
    """
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): (name + '\x00').encode()},
        registers={0x11: None},
    )
    assert psu.variant is None
    assert 'error' in psu.get_sensors()


@pytest.mark.parametrize(
    'name,variant', [('MPG Ai1600TS', 'mpg_ai1600ts'), ('MPG Ai1300TS', 'mpg_ai1300ts')]
)
def test_a_complete_ts_model_name_still_dispatches(name, variant):
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): (name + '\x00').encode()},
        registers={0x11: (name + '\x00').encode()},
    )
    assert psu.variant == variant


def test_a_meg_model_name_is_not_mistaken_for_a_truncated_ts_name():
    """The real MEG Ai1600T ends in "T" too; only the MPG prefix marks a short read."""
    psu = _psu_1600t()
    assert psu.product == 'MEG Ai1600T'
    assert psu.variant == 'meg_ai1600'


def test_serial_strips_length_prefix():
    psu = _psu_1300ts()
    assert psu.serial == 'SN123456'


def test_serial_legacy_printable_first_byte():
    psu = _psu_1300ts(registers={0x13: b'ABC123\x00\x00'})
    assert psu.serial == 'ABC123'


def test_a_meg_serial_is_cut_to_the_msi_fixed_length():
    """MSI reads exactly 24 serial bytes on the MEG models (CPSU.cs:515-523).

    The previous fallback used the whole 0x13 reply and relied on the report
    being zero-padded after byte 24. A non-zero tail would have been appended to
    the serial, which then lands in logs/Prometheus labels.
    """
    length = 24
    serial = b'SN' + b'0' * (length - 2)
    psu = _psu_1600t(registers={0x13: serial + b'NOT-THE-SERIAL'})
    assert psu.serial == serial.decode('ascii')


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
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'Mystery 9000\x00'},
        registers={0x11: b'Mystery 9000\x00'},
    )
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


def test_multi_rail_short_payload_names_the_length_mismatch():
    """A wrong-length device must be diagnosable, not look like a dead link."""
    psu = _psu_1300p(commands={(0x51, 0xE0): bytes(40 - 1)})
    sensors = psu.get_sensors()
    assert 'payload_error' in sensors
    assert 'got 39 of 40 bytes' in sensors['payload_error']
    assert 'error' not in sensors  # answered, so not a hard protocol error


def test_no_answer_at_all_is_not_reported_as_a_length_mismatch():
    """None means the PSU stayed silent: no payload_error, keep it transient."""
    psu = _psu_1300p()
    sensors = psu.get_sensors()
    assert 'payload_error' not in sensors
    assert 'error' not in sensors


def test_a_short_payload_for_an_unknown_model_stays_an_error():
    """Unknown model: refuse on the variant, whatever the payload length is."""
    registers = {
        0x10: b'MSI\x00',
        0x11: b'MSI PSU 9000\x00',
        0x12: b'1.0',
        0x13: bytes([4]) + b'SN01',
    }
    psu = MSIPSU(
        FakeHID(
            registers=registers,
            commands={(0xFA, 0x51): b'MSI PSU 9000\x00', (0x51, 0xE0): bytes(8)},
        )
    )
    psu.init()
    assert psu.variant is None
    sensors = psu.get_sensors()
    assert 'error' in sensors
    assert 'payload_error' not in sensors


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


def _dead_device():
    """A real HIDDevice whose fd points at a just-unplugged PSU."""
    from msi_psu_monitor.protocol import HIDDevice

    device = HIDDevice('dead:0')
    device.fd = 0  # as if open() had succeeded before the cable came out
    return device


def test_send_command_maps_a_device_error_to_none(monkeypatch):
    """Unplugging raises OSError out of os.write/select; that is a NAK, not a crash."""
    import os

    def dead_read(fd, size):
        raise OSError(19, 'No such device')

    def dead_write(fd, data):
        raise OSError(19, 'No such device')

    def dead_select(rlist, wlist, xlist, timeout):
        raise OSError(9, 'Bad file descriptor')

    monkeypatch.setattr(os, 'read', dead_read)
    monkeypatch.setattr(os, 'write', dead_write)
    monkeypatch.setattr('select.select', dead_select)

    device = _dead_device()
    assert device.send_command([0x51, 0xE0]) is None
    assert device.read_all() is None
    assert device.read_register(0xE1) is None
    assert device.write_command([0x41, 0x01, 0x00, 0x40]) is False


def test_send_command_without_an_open_fd_is_a_failure():
    """A closed handle must report a failure instead of raising TypeError."""
    device = _dead_device()
    device.fd = None
    assert device.send_command([0x51, 0xE0]) is None
    assert device.write_command([0x41, 0x01, 0x00, 0x40]) is False


@pytest.mark.parametrize(
    'command,reply,expected',
    [
        # Unsupported register, read or write: the reply is [cmd, NAK] with no
        # register echo, so there is nothing to mistake for a payload.
        ([0x51, 0xE0], b'\x51\xfe', None),
        ([0x50, 0x69], b'\x50\xfe', None),
        # Accepted write: echoed register, then ACK as the status byte.
        ([0x50, 0x41, 0x55, 0x55, 0x55], b'\x50\x41\xfc', b'\xfc'),
        # Rejected write to a real register: echoed register, then NAK.
        ([0x50, 0x41, 0x55, 0x55, 0x55], b'\x50\x41\xfe', None),
        # A *read* whose first payload byte is 0xFE is data, not a NAK: byte 2
        # carries the low byte of a 12 V LINEAR11 word (11.984 V = 0xCDFE) or of
        # the uptime counter, so the byte-2 test must not run on reads.
        ([0x51, 0x69], b'\x51\x69\xfe', b'\xfe'),
        ([0x51, 0xE0], b'\x51\xe0\xfe\xce' + bytes(4), b'\xfe\xce' + bytes(4)),
    ],
)
def test_every_documented_nak_reply_shape_is_a_failure(monkeypatch, command, reply, expected):
    """``msi-psu.c:186-198``: [cmd, NAK] for any unsupported register, and an
    echoed register + NAK for a refused write.

    The 2-byte form used to come back as ``b""``, so ``write_command`` reported
    success for a register the PSU had just refused (``reply is not None``). The
    byte-2 test that fixed that must not be applied to reads: there byte 2 is
    the first payload byte.
    """
    import os

    calls = {'n': 0}

    def fake_read(fd, size):
        # The drain probe runs first and must report "nothing pending"; every
        # following read is the reply itself.
        calls['n'] += 1
        return b'' if calls['n'] % 2 else reply

    monkeypatch.setattr(os, 'read', fake_read)
    monkeypatch.setattr(os, 'write', lambda fd, data: len(data))
    monkeypatch.setattr('select.select', lambda r, w, x, timeout: (r, [], []))

    device = _dead_device()
    assert device.send_command(command) == expected


def test_opening_without_a_detected_device_is_an_oserror():
    """No PSU and no path must fail like every other device error.

    ``os.open(None, ...)`` raises ``TypeError``, which no caller (the daemon's
    ``except (OSError, DeviceBusyError)`` or ``monitor.main``) treats as a device
    failure.
    """
    from msi_psu_monitor.protocol import HIDDevice

    device = HIDDevice('unused:0')
    device.path = None
    with pytest.raises(FileNotFoundError):
        device.open()


def _answering_device(monkeypatch, replies):
    """A real HIDDevice wired to ``replies`` keyed by the 2-byte (cmd, reg) sent.

    Unlike ``FakeHID`` this runs the real framing code in ``send_command``, which
    is where the NAK rule lives. The written command is a zero-padded 64-byte
    buffer, so the reply key is its first two bytes.
    """
    import os

    from msi_psu_monitor.protocol import HIDDevice

    state = {'reply': b'', 'n': 0}

    def fake_write(fd, data):
        # The reply repeats the command/register it answers, exactly like the
        # device does (``msi-psu.c``: "at the start of the reply is an echo of
        # the send command/address in the same order it was sent").
        key = tuple(bytes(data).rstrip(b'\x00')[:2])
        state['reply'] = replies.get(key, b'')
        return len(data)

    def fake_read(fd, size):
        # The drain probe runs first and must report "nothing pending"; every
        # following read is the reply itself.
        state['n'] += 1
        return b'' if state['n'] % 2 else state['reply']

    monkeypatch.setattr(os, 'read', fake_read)
    monkeypatch.setattr(os, 'write', fake_write)
    monkeypatch.setattr('select.select', lambda r, w, x, timeout: (r, [], []))
    device = HIDDevice('fake:0')
    device.fd = 0
    return device


def test_a_meg_frame_whose_first_payload_byte_is_0xfe_is_still_decoded(monkeypatch):
    """11.984 V is 0xCDFE in LINEAR11, so byte 2 of a valid 0xE0 reply is 0xFE.

    The read path used to treat any reply whose byte 2 was 0xFE as a NAK, so a
    perfectly healthy 20-byte MEG frame was discarded: ``get_sensors`` returned an
    ident-only dict and the daemon exported ``msi_psu_up 0`` for a PSU that had
    just answered. One sample in every 256 also lost its uptime this way.
    """
    from msi_psu_monitor.protocol import HIDDevice, MSIPSU  # noqa: F401

    payload = _u16(_encode(1534, 0x19)) + bytes(18)  # 11.984 V, then zeros
    assert payload[0] == 0xFE
    replies = {
        (0xFA, 0x51): b'MEG Ai1600T\x00',
        (0x51, 0x10): b'MSI\x00',
        (0x51, 0x11): b'MEG Ai1600T\x00',
        (0x51, 0x12): b'10',
        (0x51, 0x13): bytes([1]) + b'S',
        (0x51, 0xE0): payload,
    }
    replies = {key: bytes(key) + value for key, value in replies.items()}
    psu = MSIPSU(_answering_device(monkeypatch, replies))
    psu.init()
    sensors = psu.get_sensors()
    assert 'error' not in sensors and 'payload_error' not in sensors
    assert sensors['vout_12v'] == (11.984, 'V')


class RecordingHID(FakeHID):
    """FakeHID that records 0x50 writes and ACKs them."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.writes = []
        self.accept = True

    def write_command(self, data, timeout_ms=250):
        # Same shape HIDDevice sends: the 0x50 command byte, then the payload.
        self.writes.append(tuple([0x50] + list(data)))
        return self.accept


def test_set_zero_fan_writes_43_then_saves():
    psu = _psu_1300ts()
    psu.hid = RecordingHID()
    assert psu.set_zero_fan(True) is True
    assert psu.hid.writes == [(0x50, 0x43, 1), (0x50, 0xF1)]


def test_set_zero_fan_off_writes_zero():
    psu = _psu_1300ts()
    psu.hid = RecordingHID()
    assert psu.set_zero_fan(False) is True
    assert psu.hid.writes == [(0x50, 0x43, 0), (0x50, 0xF1)]


def test_a_refused_zero_fan_write_returns_false():
    psu = _psu_1300ts()
    psu.hid = RecordingHID()
    psu.hid.accept = False
    assert psu.set_zero_fan(True) is False


def test_zero_fan_and_buzzer_are_refused_on_a_meg_model():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai1300P' + bytes([0])},
        registers={0x11: b'MEG Ai1300P' + bytes([0])},
    )
    psu.hid = RecordingHID()
    assert psu.set_zero_fan(True) is False
    assert psu.silence_buzzer() is False
    assert psu.hid.writes == []


def test_silence_buzzer_sends_c2_without_a_payload():
    psu = _psu_1300ts()
    psu.hid = RecordingHID()
    assert psu.silence_buzzer() is True
    assert psu.hid.writes == [(0x50, 0xC2)]


def test_read_zero_fan_uses_the_fourth_fanduty_byte():
    psu = _psu_1300ts(registers={0x42: bytes([0x1E, 0x1E, 0x32, 0x01])})
    assert psu.read_zero_fan() is True
    psu = _psu_1300ts(registers={0x42: bytes([0x1E, 0x1E, 0x32, 0x00])})
    assert psu.read_zero_fan() is False


def test_set_multirail_ocp_writes_c0_then_saves():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai1300P' + bytes([0])},
        registers={0x11: b'MEG Ai1300P' + bytes([0])},
    )
    psu.hid = RecordingHID()
    assert psu.set_multirail_ocp(True) is True
    assert psu.hid.writes == [(0x50, 0xC0, 2), (0x50, 0xF1)]
    psu.hid.writes.clear()
    assert psu.set_multirail_ocp(False) is True
    assert psu.hid.writes == [(0x50, 0xC0, 1), (0x50, 0xF1)]


def test_set_multirail_ocp_is_refused_on_a_ts_model():
    psu = _psu_1300ts()
    psu.hid = RecordingHID()
    assert psu.set_multirail_ocp(True) is False
    assert psu.hid.writes == []


def test_read_multirail_ocp_gates_on_the_model():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai1300P' + bytes([0])},
        registers={0x11: b'MEG Ai1300P' + bytes([0])},
    )
    psu.hid = RecordingHID(registers={0xC0: bytes([2])})
    assert psu.read_multirail_ocp() is True
    psu.hid = RecordingHID(registers={0xC0: bytes([1])})
    assert psu.read_multirail_ocp() is False
    psu = _psu_1300ts()
    psu.hid = RecordingHID(registers={0xC0: bytes([2])})
    assert psu.read_multirail_ocp() is None


def test_read_multirail_ocp_refuses_an_undefined_byte():
    """Only 1 (combined) and 2 (per-rail) are defined; 0/3+ is not a mode.

    Reporting an undefined byte as "single rail" invented a protection state the
    PSU never sent -- the 8-byte 0xC0 read already refuses an invalid enable byte
    the same way.
    """
    psu = _psu_1300p()
    for value in (0, 3, 0xFF):
        psu.hid = RecordingHID(registers={0xC0: bytes([value])})
        assert psu.read_multirail_ocp() is None


def test_read_vin_decodes_volts_on_a_non_ts_model():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai1300P' + bytes([0])},
        registers={0x11: b'MEG Ai1300P' + bytes([0])},
    )
    psu.hid = RecordingHID(registers={0x20: bytes([0x73, 0x08])})
    assert psu.read_vin() == (230.0, 'V')


def test_read_vin_keeps_sub_volt_precision():
    """LINEAR11 is floating: 461 x 2**-1 V is 230.5 V, not 230 V.

    MSI's ValueCalc multiplies the mantissa by 2**exponent (CPSU.cs:1248), so the
    device may encode a fractional mains voltage with a negative exponent; the
    integer shift used before truncated it while the display claims 0.1 V.
    """
    psu = _psu_1300p()
    psu.hid = RecordingHID(registers={0x20: bytes([0xCD, 0xF9])})  # 0xF9CD = 461 x 2**-1
    assert psu.read_vin() == (230.5, 'V')


def test_read_vin_is_refused_on_a_ts_model():
    psu = _psu_1300ts()
    psu.hid = RecordingHID(registers={0x20: bytes([0x73, 0x08])})
    assert psu.read_vin() is None


def test_read_alert_status_refuses_a_truncated_bitmap():
    """A partial E1h reply must not label a prefix of the alert list as truth.

    Returning None keeps the caller's status at Unknown instead of reporting the
    first bytes as the whole answer.
    """
    psu = _psu_1300ts()
    psu.hid = RecordingHID(registers={0xE1: bytes(17)})
    assert psu.read_alert_status() is None
    psu.hid = RecordingHID(registers={0xE1: bytes(18)})
    status = psu.read_alert_status()
    assert len(status) == 18
    assert not any(status.values())


def test_read_alert_status_accepts_the_ai1600t_13_byte_bitmap():
    """The Ai1600T sends 13 bytes for its 13 names — not the TS's 18."""
    psu = _psu_1600t()
    psu.hid = RecordingHID(registers={0xE1: bytes(13)})
    status = psu.read_alert_status()
    assert len(status) == 13
    assert not any(status.values())


def test_get_sensors_includes_vin_on_a_non_ts_model():
    psu = _psu_1300ts(
        commands={(0xFA, 0x51): b'MEG Ai1300P' + bytes([0])},
        registers={0x11: b'MEG Ai1300P' + bytes([0])},
    )
    psu.hid = RecordingHID(registers={0x20: bytes([0x73, 0x08])})
    psu.hid.read_all = lambda: bytes(64)
    sensors = psu.get_sensors()
    assert sensors['vin'] == (230, 'V')


def test_control_characters_are_stripped_from_device_identity():
    psu = _psu_1300ts(
        registers={
            0x11: b'MPG\x00Ai1300TS\x01\x00',
            0x13: bytes([10]) + b'SN12\r\n3456',
        }
    )
    assert psu.product == 'MPG Ai1300TS'
    assert psu.serial == 'SN123456'


def test_the_identity_cap_bounds_a_hostile_serial():
    psu = _psu_1300ts(registers={0x13: bytes([64]) + b'A' * 64})
    assert len(psu.serial) == 64


@pytest.mark.parametrize(
    'bulk',
    [
        b'',
        b'\x00' * 3,
        b'\xff' * 20,
        b'\xff' * 40,
        b'\xff' * 44,
        b'\xff' * 62,
        b'\xfe' * 64,
        bytes(range(64)),
    ],
)
def test_short_or_garbage_bulk_frames_never_raise(bulk):
    psu = _psu_1300ts(commands={(0x51, 0xE0): bulk})
    sensors = psu.get_sensors()
    assert isinstance(sensors, dict)
    if len(bulk) < 44:
        assert 'power_total' not in sensors
        assert 'iout_pins' not in sensors


@pytest.mark.parametrize('payload', [b'', b'\x00', b'\xff' * 3, b'\xfe' * 18, bytes(range(18))])
def test_short_or_garbage_alert_bitmaps_never_raise(payload):
    psu = _psu_1300ts(registers={0xE1: payload})
    status = psu.read_alert_status()
    assert status is None or isinstance(status, dict)


@pytest.mark.parametrize('payload', [b'', b'\x00', b'\xff' * 7, b'\xff' * 8, bytes(range(8))])
def test_short_or_garbage_ocp_config_never_raises(payload):
    psu = _psu_1300ts(registers={0xC0: payload})
    config = psu.read_ocp_thresholds()
    assert config is None or isinstance(config, dict)


@pytest.mark.parametrize('payload', [b'', b'\x00', b'\xff' * 41, b'\xff' * 42, bytes(range(42))])
def test_short_or_garbage_ocp_state_never_raises(payload):
    psu = _psu_1300ts(registers={0xC1: payload})
    state = psu.read_ocp_state()
    assert state is None or isinstance(state, dict)


@pytest.mark.parametrize('payload', [b'', b'\x00', b'\xff' * 3, b'\xff' * 4, bytes(range(6))])
def test_short_fan_registers_never_raise(payload):
    psu = _psu_1300ts(registers={0x41: payload, 0x42: payload})
    assert psu.read_fan_setting() is None or isinstance(psu.read_fan_setting(), tuple)
    assert psu.read_fan_duty() is None or isinstance(psu.read_fan_duty(), tuple)


def test_a_short_blackbox_record_is_skipped_not_invented():
    psu = _psu_1300ts(commands={(0x51, 0xC1, 1): b'\xff' * 3})
    assert psu.read_blackbox() == []


# ---- handshake retry (REQ-18) -------------------------------------------


class FlakyHandshakeHID(FakeHID):
    """FakeHID whose 0xFA51 handshake fails a given number of times first."""

    def __init__(self, failures, registers=None, commands=None):
        super().__init__(registers=registers, commands=commands)
        self.failures = failures
        self.calls = 0

    def send_command(self, data, timeout_ms=250):
        if tuple(data) == (0xFA, 0x51):
            self.calls += 1
            if self.calls <= self.failures:
                return None
            return b'MPG Ai1600TS\x00'
        return super().send_command(data, timeout_ms)


def test_the_init_handshake_retries_three_times_with_exponential_backoff(monkeypatch):
    import msi_psu_monitor.protocol as protocol

    sleeps = []
    monkeypatch.setattr(protocol.time, 'sleep', lambda seconds: sleeps.append(seconds))
    hid = FlakyHandshakeHID(failures=2)
    psu = MSIPSU(hid)
    psu.init()
    assert psu.product == 'MPG Ai1600TS'
    assert hid.calls == 3
    assert sleeps == [0.5, 1.0]


def test_the_init_handshake_stops_after_three_failed_attempts(monkeypatch):
    import msi_psu_monitor.protocol as protocol

    sleeps = []
    monkeypatch.setattr(protocol.time, 'sleep', lambda seconds: sleeps.append(seconds))
    hid = FlakyHandshakeHID(failures=99)
    psu = MSIPSU(hid)
    psu.init()
    assert psu.product == ''
    assert hid.calls == 3
    assert sleeps == [0.5, 1.0]


# ---- REV6 0x11 / 0x2C and the per-register fallback ----------------------


def _scalar_register_payloads():
    """Valid LINEAR11 words for every register the fallback reads."""
    return {
        0x24: _u16(_encode(96, -3)),  # 12.0 V
        0x25: _u16(_encode(50, -1)),  # 25.0 A
        0x26: _u16(_encode(40, -3)),  # 5.0 V
        0x27: _u16(_encode(6, -1)),  # 3.0 A
        0x28: _u16(_encode(211, -6)),  # 3.296875 V -> 3.297
        0x29: _u16(_encode(4, -1)),  # 2.0 A
        0x2A: _u16(_encode(300, 0)),  # 300 W
        0x2B: _u16(_encode(92, 0)),  # 92 %
        0x30: _u16(_encode(45, 0)),  # 45 C
        0x40: _u16(_encode(900, 0)),  # 900 RPM
    }


def _pin_payload(values):
    return b''.join(_u16(_encode(int(round(value * 2)), -1)) for value in values)


PIN_VALUES = [8.0, 8.5, 9.0, 8.0, 7.5, 8.0, 7.0, 7.5, 8.0, 7.0, 6.5, 7.0]


def test_iout_12_4_decodes_both_pin_sets():
    psu = _psu_1300ts()
    psu.hid = FakeHID(registers={0x2C: _pin_payload(PIN_VALUES)})
    assert psu.supports_pin_currents
    assert psu.read_pin_currents() == {
        'pins_1_6': PIN_VALUES[:6],
        'pins_7_12': PIN_VALUES[6:],
    }


@pytest.mark.parametrize('payload', [None, b'', bytes(23)])
def test_iout_12_4_rejects_a_missing_or_short_reply(payload):
    psu = _psu_1300ts()
    psu.hid = FakeHID(registers={0x2C: payload})
    assert psu.read_pin_currents() is None


def test_iout_12_4_is_not_probed_on_a_meg_model():
    psu = _psu_1300p()
    psu.hid = FakeHID(registers={0x2C: _pin_payload(PIN_VALUES)})
    assert not psu.supports_pin_currents
    assert psu.read_pin_currents() is None


def test_the_model_register_repairs_a_truncated_handshake():
    """0x11 is the 12-byte source of truth; the handshake may stop at 11."""
    psu = _psu_1300ts(commands={(0xFA, 0x51): b'MPG Ai1300T\x00'})
    assert psu.product == 'MPG Ai1300TS'
    assert psu.variant == 'mpg_ai1300ts'


def test_a_non_model_product_register_does_not_override_the_handshake():
    psu = _psu_1300ts(registers={0x11: b'MSI\x00'})
    assert psu.product == 'MPG Ai1300TS'
    assert psu.variant == 'mpg_ai1300ts'


def test_read_model_caps_the_documented_twelve_bytes_and_cleans_the_text():
    psu = _psu_1300ts()
    psu.hid = FakeHID(registers={0x11: b'MPG Ai1600TS EXTRA'})
    assert psu.read_model() == 'MPG Ai1600TS'
    psu.hid = FakeHID(registers={0x11: b'MPG Ai1300TS\x01'})
    assert psu.read_model() == 'MPG Ai1300TS'


def test_read_model_stops_at_the_first_nul():
    """A NUL ends the ASCII string; text after it is not part of the model."""
    psu = _psu_1300ts()
    psu.hid = FakeHID(registers={0x11: b'MPG\x00Ai1300TS\x01'})
    assert psu.read_model() == 'MPG'


def test_read_model_is_none_when_the_register_naks():
    psu = _psu_1300ts()
    psu.hid = FakeHID()
    assert psu.read_model() is None


def test_register_fallback_replaces_a_missing_bulk_frame():
    registers = _scalar_register_payloads()
    registers[0x2C] = _pin_payload(PIN_VALUES)
    psu = _psu_1300ts(commands={(0x51, 0xE0): None}, registers=registers)
    sensors = psu.get_sensors()
    assert sensors['read_mode'] == 'registers'
    assert 'payload_error' not in sensors
    assert sensors['vout_12v'] == (12.0, 'V')
    assert sensors['iout_12v_total'] == (25.0, 'A')
    assert sensors['vout_5v'] == (5.0, 'V')
    assert sensors['iout_5v'] == (3.0, 'A')
    assert sensors['vout_3v3'] == (3.296, 'V')
    assert sensors['iout_3v3'] == (2.0, 'A')
    assert sensors['power_total'] == (300.0, 'W')
    assert sensors['efficiency'] == (92.0, '%')
    assert sensors['temp'] == (45.0, '\u00b0C')
    assert sensors['fan_rpm'] == (900, 'RPM')
    assert sensors['iout_pins'] == (PIN_VALUES, 'A')


def test_register_fallback_keeps_the_short_frame_reason():
    psu = _psu_1300ts(
        commands={(0x51, 0xE0): bytes(10)},
        registers=_scalar_register_payloads(),
    )
    sensors = psu.get_sensors()
    assert 'got 10 of 44 bytes' in sensors['payload_error']
    assert sensors['read_mode'] == 'registers'
    assert sensors['vout_12v'] == (12.0, 'V')


def test_register_fallback_omits_registers_that_do_not_answer():
    psu = _psu_1300ts(
        commands={(0x51, 0xE0): None},
        registers={0x24: _u16(_encode(96, -3))},
    )
    sensors = psu.get_sensors()
    assert sensors['read_mode'] == 'registers'
    assert sensors['vout_12v'] == (12.0, 'V')
    assert 'iout_12v_total' not in sensors
    assert 'power_total' not in sensors
    assert 'iout_pins' not in sensors


def test_register_fallback_is_skipped_for_an_unknown_model():
    """The register byte order is model-dependent, so an unknown model stays refused."""
    registers = {
        0x10: b'MSI\x00',
        0x11: b'MSI PSU 9000\x00',
        0x12: b'1.0',
        0x13: bytes([4]) + b'SN01',
        0x24: _u16(_encode(96, -3)),
    }
    psu = MSIPSU(FakeHID(registers=registers, commands={(0xFA, 0x51): b'MSI PSU 9000\x00'}))
    psu.init()
    assert psu.variant is None
    sensors = psu.get_sensors()
    assert 'error' in sensors
    assert 'vout_12v' not in sensors
    assert 'read_mode' not in sensors
