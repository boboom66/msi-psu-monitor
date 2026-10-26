"""Terminal dashboard: ANSI rendering and CLI contract (no browser involved)."""

import io
import re
import sys
import types

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor import termdash
from msi_psu_monitor.monitor import EXIT_OK


class FakeTTY(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def sensors(**extra):
    base = {
        'product': 'MPG Ai1600TS',
        'serial': 'SN1',
        'vout_12v': (12.09, 'V'),
        'vout_5v': (5.05, 'V'),
        'vout_3v3': (3.31, 'V'),
        'power_total': (425.6, 'W'),
        'efficiency': (93.6, '%'),
        'temp': (44.0, 'C'),
        'fan_rpm': (1240, 'RPM'),
        'iout_pins': ([8.1, 8.0, 8.2, 8.1, 8.0, 8.1, 8.0, 8.1, 8.2, 8.0, 8.1, 8.0], 'A'),
        'status': 'Normal',
    }
    base.update(extra)
    return base


def test_render_draws_values_without_escape_codes_when_color_is_off():
    frame = termdash.render(sensors(), width=100, height=30, color=False)
    assert 'MSI PSU Monitor' in frame
    assert '+12V' in frame and '12.090 V' in frame
    assert 'POWER' in frame and '425.6 W' in frame
    assert 'Conn1' in frame and 'Conn2' in frame
    assert 'Normal' in frame
    assert '\x1b' not in frame


def test_render_uses_colour_on_a_terminal():
    frame = termdash.render(sensors(), width=100, height=30, color=True)
    assert '\x1b[' in frame


def test_render_paints_an_overcurrent_pin_red():
    frame = termdash.render(
        sensors(iout_pins=([11.0] + [8.0] * 11, 'A')), width=100, height=30, color=True
    )
    assert termdash.RED in frame


def test_render_marks_unknown_status_yellow():
    frame = termdash.render(sensors(status='Unknown'), width=100, height=30, color=True)
    assert termdash.YELLOW in frame


def test_render_survives_missing_readings_and_pins():
    frame = termdash.render({'product': 'MEG Ai1600T', 'serial': 'SN9'}, width=80, height=24)
    assert 'MSI PSU Monitor' in frame
    assert 'MEG Ai1600T' in frame
    assert 'Conn1' not in frame


def test_render_fits_the_requested_height():
    frame = termdash.render(sensors(), width=100, height=10)
    assert len(frame.splitlines()) <= 10


def test_ascii_mode_uses_plain_box_characters():
    frame = termdash.render(sensors(), width=80, height=24, color=False, ascii_only=True)
    assert frame.startswith('+')
    assert '┌' not in frame
    assert '█' not in frame and '░' not in frame
    assert '#' in frame and '-' in frame


def test_vga_console_defaults_to_ascii_bars():
    assert termdash.ascii_only_default({'TERM': 'linux'}) is True
    assert termdash.ascii_only_default({'TERM': 'xterm'}) is False
    frame = termdash.render(sensors(), width=80, height=24, color=False, ascii_only=True)
    assert '█' not in frame and '░' not in frame


def test_colour_disabled_by_no_color(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    assert termdash.colour_enabled(FakeTTY(True)) is False


def _run_main(monkeypatch, argv, stub=None):
    monkeypatch.setattr(monitor, 'detect_device', lambda: '/dev/hidraw9')
    monkeypatch.setattr(
        monitor,
        'HIDDevice',
        lambda path: types.SimpleNamespace(open=lambda: None, close=lambda: None),
    )
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: stub)
    monkeypatch.setattr(sys, 'argv', ['prog'] + argv)
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    return exc.value.code


@pytest.mark.parametrize(
    'argv',
    [
        ['--dashboard-text', '--once'],
        ['--dashboard-text', '--watch', '1'],
        ['--dashboard-text', '--dashboard'],
        ['--dashboard-text', '--export'],
        ['--dashboard-text', '--show-log'],
        ['--dashboard-text', '-f', 'json'],
        ['--dashboard-text', '-O', '/tmp/out.txt'],
        ['--dashboard-text', '--port', '9000'],
    ],
)
def test_dashboard_text_rejects_conflicting_modes(monkeypatch, capsys, argv):
    code = _run_main(monkeypatch, argv)
    assert code == 2
    assert '--dashboard-text' in capsys.readouterr().err


class FramePSU:
    def __init__(self, frames):
        self._frames = frames
        self.calls = 0

    def get_sensors(self):
        if self.calls >= len(self._frames):
            raise KeyboardInterrupt
        frame = self._frames[self.calls]
        self.calls += 1
        return dict(frame)

    def read_fan_state(self):
        return {'mode': 1, 'duty': 30, 'zero_fan': True}


def test_dashboard_loop_renders_and_restores_the_cursor(monkeypatch):
    out = FakeTTY(True)
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.setattr(monitor, '_watch_ansi', lambda stream=None: True)
    monkeypatch.setattr(monitor, '_terminal_size', lambda stream=None: (100, 32))
    args = types.SimpleNamespace(
        interval=0.01,
        watch=monitor.WATCH_FROM_CONFIG,
        output=None,
        quiet=True,
        no_alerts=True,
        dashboard_text=True,
    )
    cfg = {'interval': 0.01, 'retention_days': 30}
    code = monitor.run_dashboard_text(FramePSU([sensors(), sensors()]), args, cfg, None, None)
    text = out.getvalue()
    assert code == EXIT_OK
    assert '\x1b[?25l' in text and '\x1b[?25h' in text
    assert 'MSI PSU Monitor' in text
    assert text.count('MSI PSU Monitor') >= 2


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _visible(line):
    """Column count with SGR sequences removed (what the terminal measures)."""
    return len(_ANSI.sub('', line))


def test_colour_does_not_shift_the_box():
    """Padding by len() counted escape bytes; the right border used to wander."""
    frame = termdash.render(sensors(), width=80, height=24, color=True)
    widths = {_visible(line) for line in frame.splitlines()}
    assert len(widths) == 1, widths


def test_colour_pins_and_alerts_keep_the_box_aligned():
    data = sensors()
    data['threshold_alerts'] = ['power_high']
    frame = termdash.render(data, width=100, height=30, color=True)
    widths = {_visible(line) for line in frame.splitlines()}
    assert len(widths) == 1, widths


def test_long_identity_does_not_leak_partial_escape():
    """A header cut through a colour sequence garbled the rest of the frame."""
    data = sensors()
    data['product'] = 'MPG Ai1600TS ' + 'X' * 200
    data['serial'] = 'S' * 120
    frame = termdash.render(data, width=80, height=24, color=True)
    lines = frame.splitlines()
    assert len({_visible(line) for line in lines}) == 1
    for line in lines:
        assert not re.search(r'\x1b\[[0-9;]*$', line), repr(line[-12:])
    # The box frame wraps everything: line 0 is the top rule, the header is line 1.
    assert 'MSI PSU Monitor' in lines[1]


def test_long_rows_cannot_escape_the_box():
    """A wide range/row used to push past the right border (pad went negative)."""
    history = [
        {
            '12v': 12.0001 + index * 0.00001,
            '5v': 5.0,
            '3v3': 3.3,
            'power': 100.0 + index,
            'eff': 90.0,
            'temp': 40.0,
            'fan': 1200,
        }
        for index in range(60)
    ]
    frame = termdash.render(sensors(), history=history, width=44, height=24, color=False)
    widths = {len(line) for line in frame.splitlines()}
    assert len(widths) == 1, widths
