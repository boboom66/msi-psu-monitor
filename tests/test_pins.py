"""CLI tests for the 0x2C per-pin current view (``--pins``)."""

import json

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor.monitor import EXIT_ERROR, EXIT_OK

PINS = {
    'pins_1_6': [8.0, 8.5, 9.0, 8.0, 7.5, 8.0],
    'pins_7_12': [7.0, 7.5, 8.0, 7.0, 6.5, 7.0],
}
_UNSET = object()


class StubPSU:
    """PSU surface for ``run_pins``: the variant gate plus the 0x2C read."""

    def __init__(self, pins=_UNSET, supported=True, product='MPG Ai1600TS'):
        self._pins = PINS if pins is _UNSET else pins
        self.supports_pin_currents = supported
        self.product = product

    def read_pin_currents(self):
        return self._pins


def _args(fmt='text'):
    """Parse ``--pins`` args with the format resolved, as main() leaves them."""
    args = monitor.build_parser().parse_args(['--pins'])
    args.format = fmt
    return args


@pytest.fixture(autouse=True)
def diagnostics_on_captured_stderr(capsys):
    """Bind the logger to capsys' stderr the way main() does via setup_logging."""
    monitor.setup_logging()
    yield
    monitor.logger.handlers.clear()  # never leak a handler into another test module


def test_run_pins_text_shows_both_connectors_and_their_summary(capsys):
    assert monitor.run_pins(StubPSU(), _args()) == EXIT_OK
    out = capsys.readouterr().out
    assert '12V-2x6 per-pin currents (0x2C, 5 s averages)' in out
    assert 'Conn1 (12V5):' in out
    assert 'Conn2 (12V3):' in out
    assert '49.00 A' in out  # connector 1 total
    assert '43.00 A' in out  # connector 2 total
    assert '1.50 A' in out  # min/max spread of both connectors


def test_run_pins_json_carries_the_register_and_average_window(capsys):
    assert monitor.run_pins(StubPSU(), _args('json')) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload['product'] == 'MPG Ai1600TS'
    section = payload['pin_currents']
    assert section['register'] == '0x2C'
    assert section['average_seconds'] == 5
    assert section['pins'] == PINS['pins_1_6'] + PINS['pins_7_12']
    assert section['connectors'][0] == {
        'connector': 1,
        'rail': '12V5',
        'pins': PINS['pins_1_6'],
        'total_a': 49.0,
        'min_a': 7.5,
        'max_a': 9.0,
        'imbalance_a': 1.5,
    }
    assert section['connectors'][1]['rail'] == '12V3'


def test_run_pins_prometheus_exposes_pins_totals_and_imbalance(capsys):
    assert monitor.run_pins(StubPSU(), _args('prometheus')) == EXIT_OK
    out = capsys.readouterr().out
    assert 'msi_psu_pin_current_available{} 1' in out
    assert 'msi_psu_pin_current{connector="1",pin="1"} 8.0' in out
    assert 'msi_psu_pin_current{connector="2",pin="6"} 7.0' in out
    assert 'msi_psu_connector_current{connector="1"} 49.0' in out
    assert 'msi_psu_connector_current{connector="2"} 43.0' in out
    assert 'msi_psu_connector_current_imbalance{connector="1"} 1.5' in out


def test_run_pins_writes_to_the_requested_file(tmp_path):
    target = tmp_path / 'pins.txt'
    args = monitor.build_parser().parse_args(['--pins', '-O', str(target)])
    args.format = 'text'
    assert monitor.run_pins(StubPSU(), args) == EXIT_OK
    text = target.read_text(encoding='utf-8')
    assert 'Conn1 (12V5)' in text


def test_run_pins_unsupported_model_is_not_an_error(capsys):
    psu = StubPSU(supported=False, product='MEG Ai1300P')
    assert monitor.run_pins(psu, _args()) == EXIT_OK
    out = capsys.readouterr().out
    assert 'MEG Ai1300P' in out
    assert monitor.PINS_UNSUPPORTED in out


def test_run_pins_unsupported_model_json_and_prometheus(capsys):
    psu = StubPSU(supported=False, product='MEG Ai1300P')
    assert monitor.run_pins(psu, _args('json')) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload['supported'] is False
    assert monitor.PINS_UNSUPPORTED in payload['reason']

    assert monitor.run_pins(psu, _args('prometheus')) == EXIT_OK
    out = capsys.readouterr().out
    assert 'msi_psu_pin_current_available{} 0' in out
    assert 'msi_psu_pin_current{' not in out


def test_run_pins_read_failure_is_an_error(capsys):
    assert monitor.run_pins(StubPSU(pins=None), _args()) == EXIT_ERROR
    assert '0x2C' in capsys.readouterr().err


@pytest.mark.parametrize(
    'argv',
    [
        ['--pins', '--once'],
        ['--pins', '--watch', '1'],
        ['--pins', '--ocp'],
        ['--pins', '--dump-thresholds'],
        ['--pins', '--export', '--from', '1h'],
        ['--pins', '--show-log'],
        ['--pins', '--show-alert-log'],
        ['--pins', '--dashboard'],
        ['--pins', '--dashboard-text'],
        ['--pins', '--dump-config'],
        ['--pins', '--fan-mode', 'auto'],
        ['--pins', '--ocp-set', '12,5,20,20,180'],
        ['--pins', '--menu'],
        ['--pins', '--port', '9000'],
        ['--pins', '--from', '1h'],
    ],
)
def test_pins_rejects_other_modes(argv):
    parser = monitor.build_parser()
    args = parser.parse_args(argv)
    with pytest.raises(SystemExit) as exc:
        monitor._validate_args(parser, args)
    assert exc.value.code == 2


@pytest.mark.parametrize(
    'argv',
    [
        ['--pins'],
        ['--pins', '-f', 'json'],
        ['--pins', '-f', 'prometheus'],
        ['--pins', '-O', '/tmp/pins.txt'],
        ['--pins', '--serial', 'SN1'],
        ['--pins', '--config', '/tmp/monitor.conf'],
    ],
)
def test_pins_accepts_its_own_options(argv):
    parser = monitor.build_parser()
    monitor._validate_args(parser, parser.parse_args(argv))  # must not raise
