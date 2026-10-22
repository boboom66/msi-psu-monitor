"""Tests for the read-only 12V-2x6 OCP inspection (C0h thresholds + C1h state).

Covers the phase-1 scope from 需求分析.md:66 ("OCP 閾值檢視, 一期只读展示") plus
the variant gate that MSI Center applies (CPSU.cs returns false for every MEG PID
before it even sends the 0xC0 read).
"""

import json

import pytest

from msi_psu_monitor import demo
from msi_psu_monitor import monitor
from msi_psu_monitor.monitor import EXIT_ERROR, EXIT_OK
from msi_psu_monitor.protocol import MSIPSU

# Factory 12V-2x6 OCP configuration as shipped by MSI (CPSU.cs defaults).
# Encoding for the amp fields is LINEAR11 with exponent -4: value << 4 in the
# low byte, 0xE0 in the high byte, i.e. 12 A -> 0xE0C0 and 5 A -> 0xE050.
FACTORY_C0 = bytes([1, 0xC0, 0xE0, 0x50, 0xE0, 20, 20, 180])


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


def _psu(product='MPG Ai1300TS', **overrides):
    registers = {
        0x10: b'MSI\x00',
        0x11: product.encode() + b'\x00',
        0x12: b'1.0',
        0x13: bytes([8]) + b'SN123456',
    }
    registers.update(overrides.get('registers', {}))
    commands = {(0xFA, 0x51): product.encode() + b'\x00'}
    commands.update(overrides.get('commands', {}))
    psu = MSIPSU(FakeHID(registers=registers, commands=commands))
    psu.init()
    return psu


def _lin11(amps, exponent=-1):
    """Encode an ampere reading the way the PSU does (LINEAR11, exp -1 here)."""
    return (((exponent & 0x1F) << 11) | int(amps * (1 << -exponent))).to_bytes(2, 'little')


def _ocp_state_payload():
    """C1h state block laid out exactly like CPSU.cs GET_OCP12V2x6_STATE."""
    body = bytearray(42)
    body[0] = 0  # connector 1 normal
    body[1:5] = (100).to_bytes(4, 'little')
    body[5:9] = (5000).to_bytes(4, 'little')
    for i in range(6):
        body[9 + i * 2 : 11 + i * 2] = _lin11(8.0 + i * 0.5)
    body[21] = 2  # connector 2: current-difference warning
    body[22:26] = (200).to_bytes(4, 'little')
    body[26:30] = (6000).to_bytes(4, 'little')
    for i in range(6):
        body[30 + i * 2 : 32 + i * 2] = _lin11(6.0 + i * 0.5)
    return bytes(body)


# ---- protocol decoding --------------------------------------------------


def test_lin11_threshold_words_match_msi_center_encoding():
    # ValueCalc(Low, High) in CPSU.cs == mantissa * 2**exponent.
    assert MSIPSU._lin11_float(0xE0C0) == 12.0
    assert MSIPSU._lin11_float(0xE050) == 5.0
    assert MSIPSU._lin11_float(0xE0A0) == 10.0
    assert MSIPSU._lin11_float(0xE080) == 8.0


def test_read_ocp_thresholds_decodes_factory_values():
    psu = _psu(registers={0xC0: FACTORY_C0})
    config = psu.read_ocp_thresholds()
    assert config == {
        'enabled': True,
        'point_a': 12.0,
        'diff_a': 5.0,
        'trigger_s': 20,
        'diff_trigger_s': 20,
        'warning_s': 180,
    }


def test_read_ocp_thresholds_disabled_flag():
    payload = bytes([0]) + FACTORY_C0[1:]
    assert _psu(registers={0xC0: payload}).read_ocp_thresholds()['enabled'] is False


def test_read_ocp_thresholds_missing_or_short():
    assert _psu().read_ocp_thresholds() is None
    assert _psu(registers={0xC0: b'\x01\xc0'}).read_ocp_thresholds() is None


@pytest.mark.parametrize(
    ('product', 'expected'),
    [
        ('MPG Ai1600TS', True),
        ('MPG Ai1300TS', True),
        ('MEG Ai1600T', False),
        ('MEG Ai1300P', False),
        ('MEG Ai1000P', False),
    ],
)
def test_supports_ocp_config_only_on_12v_2x6_models(product, expected):
    assert _psu(product=product).supports_ocp_config is expected


def test_unknown_variant_has_no_ocp_config():
    assert _psu(product='Mystery 9000').supports_ocp_config is False


# ---- formatters ---------------------------------------------------------


def test_ocp_text_lists_values_ranges_and_state():
    text = monitor.format_ocp_text(
        _psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds(),
        _psu(commands={(0x51, 0xC1, 0x00): _ocp_state_payload()}).read_ocp_state(),
        'MPG Ai1300TS',
    )
    assert 'MSI PSU: MPG Ai1300TS' in text
    assert '12V-2x6 OCP configuration (0xC0):' in text
    assert 'Pin OCP point   : 12.0 A   (range 10-14)' in text
    assert 'Pin difference  : 5.0 A   (range 4-8)' in text
    assert 'OCP trigger     : 20 s   (range 5-30)' in text
    assert 'Warning time    : 180 s   (range 30-240)' in text
    assert 'Conn1: Normal' in text
    assert 'Conn2: Current difference' in text
    assert 'Pin currents (A): 8.0  8.5  9.0  9.5  10.0  10.5' in text


def test_ocp_text_without_state():
    text = monitor.format_ocp_text(
        _psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds(), None, ''
    )
    assert '0xC1' not in text
    assert 'MSI PSU' in text


def test_ocp_json_payload_shape():
    payload = json.loads(
        monitor.format_ocp_json(
            _psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds(),
            _psu(commands={(0x51, 0xC1, 0x00): _ocp_state_payload()}).read_ocp_state(),
            'MPG Ai1300TS',
        )
    )
    assert payload['product'] == 'MPG Ai1300TS'
    assert payload['ocp_config']['point_a'] == 12.0
    assert payload['ocp_config']['warning_s'] == 180
    connectors = payload['ocp_state']['connectors']
    assert [conn['status_name'] for conn in connectors] == ['Normal', 'Current difference']
    assert connectors[0]['pins'] == [8.0, 8.5, 9.0, 9.5, 10.0, 10.5]
    assert connectors[1]['total_time'] == 6000


def test_ocp_prometheus_gauges():
    text = monitor.format_ocp_prometheus(
        _psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds(),
        _psu(commands={(0x51, 0xC1, 0x00): _ocp_state_payload()}).read_ocp_state(),
        'MPG Ai1300TS',
    )
    assert 'msi_psu_ocp_enabled{} 1' in text
    assert 'msi_psu_ocp_pin_point_a{} 12.0' in text
    assert 'msi_psu_ocp_pin_diff_a{} 5.0' in text
    assert 'msi_psu_ocp_warning_s{} 180' in text
    assert 'msi_psu_ocp_status{connector="1"} 0' in text
    assert 'msi_psu_ocp_status{connector="2"} 2' in text
    assert 'msi_psu_ocp_total_time{connector="2"} 6000' in text


# ---- CLI path -----------------------------------------------------------


class StubPSU:
    """PSU surface for run_ocp: config, state and the variant gate."""

    def __init__(self, config, state=None, supported=True, product='MPG Ai1600TS'):
        self._config = config
        self._state = state
        self.supports_ocp_config = supported
        self.product = product
        self.state_reads = 0
        self.supports_multirail_ocp = False

    def read_ocp_thresholds(self):
        return self._config

    def read_ocp_state(self):
        self.state_reads += 1
        return self._state


def _args(argv=()):
    """Parse ``--ocp`` args with the format resolved, as main() leaves them."""
    args = monitor.build_parser().parse_args(list(argv) + ['--ocp'])
    if args.format is None:
        args.format = 'text'
    return args


@pytest.fixture(autouse=True)
def diagnostics_on_captured_stderr(capsys):
    """Bind the logger to capsys' stderr the way main() does via setup_logging."""
    monitor.setup_logging()
    yield
    monitor.logger.handlers.clear()  # never leak a handler into another test module


def test_run_ocp_text_returns_ok(capsys):
    psu = StubPSU(_psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds())
    assert monitor.run_ocp(psu, _args()) == EXIT_OK
    assert 'Pin OCP point   : 12.0 A' in capsys.readouterr().out


def test_run_ocp_json_format(capsys):
    psu = StubPSU(_psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds())
    assert monitor.run_ocp(psu, _args(['-f', 'json'])) == EXIT_OK
    assert json.loads(capsys.readouterr().out)['ocp_config']['point_a'] == 12.0


def test_run_ocp_unsupported_model_is_not_an_error(capsys):
    psu = StubPSU(None, supported=False, product='MEG Ai1300P')
    assert monitor.run_ocp(psu, _args()) == EXIT_OK
    out = capsys.readouterr().out
    assert 'MEG Ai1300P' in out
    assert monitor.OCP_UNSUPPORTED in out

    # Dump/load is the C0h threshold path, not the read-only --ocp view: an
    # unsupported model must fail it (the read-only command stays exit 0).
    dump_args = monitor.build_parser().parse_args(['--dump-thresholds'])
    dump_args.format = 'text'
    assert monitor.run_ocp_thresholds(psu, dump_args) == EXIT_ERROR
    assert monitor.OCP_UNSUPPORTED in capsys.readouterr().err


def test_run_ocp_unsupported_model_json(capsys):
    psu = StubPSU(None, supported=False, product='MEG Ai1300P')
    assert monitor.run_ocp(psu, _args(['-f', 'json'])) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload == {'product': 'MEG Ai1300P', 'supported': False}


def test_run_ocp_unsupported_model_prometheus(capsys):
    psu = StubPSU(None, supported=False, product='MEG Ai1300P')
    assert monitor.run_ocp(psu, _args(['-f', 'prometheus'])) == EXIT_OK
    out = capsys.readouterr().out
    # A prometheus comment, not a bogus metric with a metric-looking name.
    assert out.startswith('# ')
    assert 'msi_psu_ocp_enabled{' not in out
    assert monitor.OCP_UNSUPPORTED in out


def test_run_ocp_read_failure_is_an_error(capsys):
    assert monitor.run_ocp(StubPSU(None), _args()) == EXIT_ERROR
    assert '0xC0' in capsys.readouterr().err


# ---- multirail flag (MEG P models) --------------------------------------


class MultiRailStub(StubPSU):
    """A MEG P model: no 12V-2x6 config, but it answers the multirail flag."""

    def __init__(self, multirail=True, product='MEG Ai1300P'):
        super().__init__(None, supported=False, product=product)
        self.supports_multirail_ocp = True
        self._multirail = multirail

    def read_multirail_ocp(self):
        if self._multirail is None:
            return None
        return self._multirail


def test_read_multirail_ocp_decodes_the_enable_value():
    # CPSU.cs:829 -- RxData[3] == 2 means per-rail protection is on.
    assert _psu(product='MEG Ai1300P', registers={0xC0: b'\x02'}).read_multirail_ocp() is True
    assert _psu(product='MEG Ai1300P', registers={0xC0: b'\x01'}).read_multirail_ocp() is False


def test_read_multirail_ocp_missing_or_empty():
    assert _psu(product='MEG Ai1300P').read_multirail_ocp() is None
    assert _psu(product='MEG Ai1300P', registers={0xC0: b''}).read_multirail_ocp() is None


@pytest.mark.parametrize('product', ['MPG Ai1600TS', 'MPG Ai1300TS', 'MEG Ai1600T'])
def test_read_multirail_ocp_stays_none_on_models_without_the_flag(product):
    """0xC0 is the 8-byte 12V-2x6 config there; byte 0 is its OCP *enable* flag.

    Reading it as the multirail answer turned "config enabled" (the factory
    default, 1) into "one combined rail" -- a protection mode these models do
    not have.
    """
    assert (
        _psu(product=product, registers={0xC0: b'\x01' + b'\x00' * 7}).read_multirail_ocp() is None
    )


@pytest.mark.parametrize(
    'product,expected',
    [
        ('MEG Ai1300P', True),
        ('MEG Ai1000P', True),
        ('MPG Ai1600TS', False),
        ('MPG Ai1300TS', False),
        ('MEG Ai1600T', False),
    ],
)
def test_supports_multirail_ocp_only_on_the_meg_p_models(product, expected):
    assert _psu(product=product).supports_multirail_ocp is expected


def test_multirail_text_reports_the_protection_mode():
    text = monitor.format_multirail_text(True, 'MEG Ai1300P')
    assert 'MSI PSU: MEG Ai1300P' in text
    assert 'Multirail OCP (0xC0):' in text
    assert 'enabled   (per-rail protection)' in text
    assert 'disabled' in monitor.format_multirail_text(False, '')


def test_multirail_json_payload_shape():
    payload = json.loads(monitor.format_multirail_json(False, 'MEG Ai1000P'))
    assert payload == {'product': 'MEG Ai1000P', 'multirail_ocp': {'enabled': False}}


def test_multirail_prometheus_gauge():
    out = monitor.format_multirail_prometheus(True, 'MEG Ai1300P')
    assert 'msi_psu_multirail_ocp{} 1' in out
    assert monitor.format_multirail_prometheus(False, '').endswith('{} 0')


def test_run_ocp_on_a_meg_p_model_shows_the_multirail_flag(capsys):
    """--ocp is meaningful on every model but the Ai1600T."""
    assert monitor.run_ocp(MultiRailStub(), _args()) == EXIT_OK
    out = capsys.readouterr().out
    assert 'Multirail OCP' in out
    assert monitor.OCP_UNSUPPORTED not in out


def test_run_ocp_on_a_meg_p_model_json(capsys):
    assert monitor.run_ocp(MultiRailStub(multirail=False), _args(['-f', 'json'])) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload['multirail_ocp'] == {'enabled': False}


def test_run_ocp_multirail_read_failure_is_an_error(capsys):
    assert monitor.run_ocp(MultiRailStub(multirail=None), _args()) == EXIT_ERROR
    assert '0xC0' in capsys.readouterr().err


def test_run_ocp_on_the_ai1600t_still_explains_the_absence(capsys):
    """The Ai1600T answers neither 0xC0 view, so it keeps the old message."""
    psu = StubPSU(None, supported=False, product='MEG Ai1600T')
    assert monitor.run_ocp(psu, _args()) == EXIT_OK
    assert monitor.OCP_UNSUPPORTED in capsys.readouterr().out


def test_run_ocp_survives_a_failing_state_read(capsys):
    class Exploding(StubPSU):
        def read_ocp_state(self):
            raise RuntimeError('NAK')

    psu = Exploding(_psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds())
    assert monitor.run_ocp(psu, _args()) == EXIT_OK
    assert 'Pin OCP point' in capsys.readouterr().out


def test_run_ocp_without_state_surface(capsys):
    class NoState:
        supports_ocp_config = True
        product = 'MPG Ai1600TS'

        def read_ocp_thresholds(self):
            return _psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds()

    assert monitor.run_ocp(NoState(), _args()) == EXIT_OK
    assert '0xC1' not in capsys.readouterr().out


def test_run_ocp_writes_to_output_file(tmp_path):
    target = tmp_path / 'ocp.txt'
    psu = StubPSU(_psu(registers={0xC0: FACTORY_C0}).read_ocp_thresholds())
    assert monitor.run_ocp(psu, _args(['-O', str(target)])) == EXIT_OK
    assert 'Pin OCP point' in target.read_text()


def _parse(argv):
    parser = monitor.build_parser()
    args = parser.parse_args(argv)
    monitor._validate_args(parser, args)


@pytest.mark.parametrize(
    'argv',
    [
        ['--ocp', '--watch', '1'],
        ['--ocp', '--export', '--from', '2h'],
        ['--ocp', '--show-log'],
        ['--ocp', '--dashboard'],
        ['--ocp', '--fan-duty', '50'],
        ['--ocp', '--fan-mode', 'auto'],
    ],
)
def test_ocp_conflicts_are_rejected(argv):
    with pytest.raises(SystemExit) as exc:
        _parse(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    'argv',
    [
        ['--ocp'],
        ['--ocp', '-f', 'json'],
        ['--ocp', '-f', 'prometheus'],
        ['--ocp', '-O', '/tmp/x'],
        ['--ocp', '--no-alerts'],
    ],
)
def test_ocp_valid_combinations(argv):
    _parse(argv)  # must not raise


# ---- demo mode ----------------------------------------------------------


def test_demo_ocp_thresholds_match_the_msi_factory_defaults():
    config = demo.DemoPSU().read_ocp_thresholds()
    assert config == {
        'enabled': True,
        'point_a': 12.0,
        'diff_a': 5.0,
        'trigger_s': 20,
        'diff_trigger_s': 20,
        'warning_s': 180,
    }
    assert demo.DemoPSU().supports_ocp_config is True


def test_demo_ocp_state_tracks_the_reported_pin_currents(monkeypatch):
    monkeypatch.delenv('MSI_PSU_DEMO_ALERT', raising=False)
    psu = demo.DemoPSU()
    state = psu.read_ocp_state()
    assert state['status_12v5'] == 0
    assert state['status_12v3'] == 0
    pins = state['pins_1_6'] + state['pins_7_12']
    assert len(pins) == 12
    reported = psu.get_sensors()['iout_pins'][0]
    # Both paths split the same 12V total, so the sums must agree closely.
    assert abs(sum(pins) - sum(reported)) < 0.5 * sum(reported)


@pytest.mark.parametrize(
    ('alert_name', 'conn1', 'conn2'),
    [
        ('ocp_pin3', 1, 0),
        ('ocp_pin9', 0, 2),
    ],
)
def test_demo_ocp_state_never_contradicts_a_stuck_alert(monkeypatch, alert_name, conn1, conn2):
    monkeypatch.setenv('MSI_PSU_DEMO_ALERT', alert_name)
    state = demo.DemoPSU().read_ocp_state()
    assert (state['status_12v5'], state['status_12v3']) == (conn1, conn2)


def test_demo_ocp_inspection_runs_end_to_end(monkeypatch, capsys):
    monkeypatch.setenv('MSI_PSU_DEMO', '1')
    psu = demo.DemoPSU()
    assert monitor.run_ocp(psu, _args()) == EXIT_OK
    assert 'Pin OCP point   : 12.0 A' in capsys.readouterr().out


# ---- threshold write (C0h 8 bytes + F1h save) ---------------------------


class WriteHID(FakeHID):
    """FakeHID that also records write_command() calls."""

    def __init__(self, registers=None, commands=None, results=None):
        super().__init__(registers=registers, commands=commands)
        self.writes = []
        self.results = list(results or [])

    def write_command(self, data, timeout_ms=250):
        self.writes.append(tuple(data))
        if self.results:
            return self.results.pop(0)
        return True


def _write_psu(results=None):
    psu = _psu()
    psu.hid = WriteHID(results=results)
    return psu


CONFIG = {
    'enabled': True,
    'point_a': 13,
    'diff_a': 6,
    'trigger_s': 10,
    'diff_trigger_s': 12,
    'warning_s': 60,
}


def test_set_ocp_thresholds_writes_msi_bytes_then_saves():
    psu = _write_psu()
    assert psu.set_ocp_thresholds(CONFIG) is True
    assert psu.hid.writes == [
        (0xC0, 1, 0xD0, 0xE0, 0x60, 0xE0, 10, 12, 60),
        (0xF1,),
    ]


def test_set_ocp_thresholds_refuses_out_of_range_and_unknown_models():
    psu = _write_psu()
    assert psu.set_ocp_thresholds(dict(CONFIG, point_a=15)) is False
    assert psu.set_ocp_thresholds(dict(CONFIG, diff_a=3)) is False
    assert psu.set_ocp_thresholds(dict(CONFIG, trigger_s=4)) is False
    assert psu.set_ocp_thresholds(dict(CONFIG, warning_s=241)) is False
    assert psu.set_ocp_thresholds({'enabled': True}) is False
    assert psu.hid.writes == []

    meg = _psu(product='MEG Ai1300P')
    meg.hid = WriteHID()
    assert meg.set_ocp_thresholds(CONFIG) is False
    assert meg.hid.writes == []


def test_set_ocp_thresholds_needs_both_the_write_and_the_save():
    psu = _write_psu(results=[True, False])
    assert psu.set_ocp_thresholds(CONFIG) is False
    assert psu.hid.writes == [
        (0xC0, 1, 0xD0, 0xE0, 0x60, 0xE0, 10, 12, 60),
        (0xF1,),
    ]


def test_demo_ocp_thresholds_round_trip():
    psu = demo.DemoPSU()
    assert psu.read_ocp_thresholds()['point_a'] == 12.0
    assert psu.set_ocp_thresholds(CONFIG) is True
    config = psu.read_ocp_thresholds()
    assert config['point_a'] == 13.0
    assert config['warning_s'] == 60
    assert config['trigger_s'] == 10


def test_demo_ocp_thresholds_are_refused_on_a_meg_model():
    psu = demo.DemoPSU(variant='ai1300p')
    assert psu.set_ocp_thresholds(CONFIG) is False


def test_read_ocp_thresholds_rejects_an_undefined_enable_byte():
    """0/1 are the only defined enable values; 2/0xFF must not read as 'disabled'."""
    for value in (2, 0xFF):
        payload = bytes([value]) + FACTORY_C0[1:]
        assert _psu(registers={0xC0: payload}).read_ocp_thresholds() is None, value
