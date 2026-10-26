"""Numbered menu: every entry prints its command and runs the same function."""

import builtins
import copy
import io
import os
import pty
import sys
import termios
import types

import pytest

from msi_psu_monitor import config
from msi_psu_monitor import menu
from msi_psu_monitor import monitor
from msi_psu_monitor.monitor import EXIT_OK


class StubPSU:
    def get_sensors(self):
        return {
            'product': 'MPG Ai1600TS',
            'serial': 'SN1',
            'vendor': 'MSI',
            'fw_revision': '1.0',
            'vout_12v': (12.09, 'V'),
            'power_total': (425.6, 'W'),
            'temp': (44.0, 'C'),
        }

    def read_fan_state(self):
        return {'mode': 1, 'duty': 30, 'zero_fan': True}


def _args():
    return types.SimpleNamespace(no_alerts=True, format='text', output=None, quiet=True)


def test_the_menu_prints_each_command_and_runs_it(monkeypatch, capsys):
    answers = iter(['1', '0'])
    monkeypatch.setattr(builtins, 'input', lambda *a: next(answers))
    code = menu.run_menu(StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None)
    out = capsys.readouterr().out
    assert 'msi-psu-monitor --once' in out
    assert '-> single snapshot' in out
    assert '$ msi-psu-monitor --once' in out
    assert 'MSI PSU: MPG Ai1600TS' in out
    assert code == EXIT_OK


def test_an_invalid_choice_is_reported_and_the_menu_continues(monkeypatch, capsys):
    answers = iter(['x', '?', '0'])
    monkeypatch.setattr(builtins, 'input', lambda *a: next(answers))
    code = menu.run_menu(StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None)
    out = capsys.readouterr().out
    assert 'invalid choice: x' in out
    assert out.count('MSI PSU Monitor - menu') >= 2  # '?' reprints it on demand
    assert code == EXIT_OK


def test_eof_ends_the_menu_cleanly(monkeypatch):
    def eof(*_a):
        raise EOFError

    monkeypatch.setattr(builtins, 'input', eof)
    assert (
        menu.run_menu(StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None)
        == EXIT_OK
    )


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def test_a_tty_clears_the_screen_between_actions(monkeypatch):
    """The dialog/whiptail contract: clear, redraw the menu, wait for a choice."""
    out = FakeTTY()
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setenv('TERM', 'xterm')

    def fake_page(text):
        out.write(text + '\n')
        menu._pause()

    monkeypatch.setattr(menu, '_page', fake_page)
    answers = iter(['1', '', '0'])  # action, pause, quit

    def fake_input(prompt=''):
        out.write(prompt)
        return next(answers)

    monkeypatch.setattr(builtins, 'input', fake_input)
    code = menu.run_menu(StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None)
    text = out.getvalue()
    assert menu._CLEAR in text
    assert text.count('MSI PSU Monitor - menu') >= 2
    assert code == EXIT_OK


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(monitor, 'detect_device', lambda: '/dev/hidraw9')
    monkeypatch.setattr(
        monitor,
        'HIDDevice',
        lambda path: types.SimpleNamespace(open=lambda: None, close=lambda: None),
    )
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: StubPSU())
    monkeypatch.setattr('sys.argv', ['prog'] + argv)
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    return exc.value.code


@pytest.mark.parametrize(
    'argv',
    [
        ['--menu', '--once'],
        ['--menu', '--watch', '1'],
        ['--menu', '--dashboard'],
        ['--menu', '--export'],
        ['--menu', '-f', 'json'],
        ['--menu', '-O', '/tmp/x'],
    ],
)
def test_menu_rejects_conflicting_modes(monkeypatch, capsys, argv):
    assert _run_main(monkeypatch, argv) == 2
    assert '--menu' in capsys.readouterr().err


def test_dump_config_entry_prints_the_effective_config(capsys):
    cfg = copy.deepcopy(config.DEFAULTS)
    code = menu._run('config', StubPSU(), _args(), cfg, None, None)
    out = capsys.readouterr().out
    assert code == monitor.EXIT_OK
    assert '[monitor]' in out
    assert '[alerts]' in out


def test_local_menu_actions_do_not_open_a_device(monkeypatch, capsys):
    args = _args()
    args.output = None
    args.from_spec = None
    args.columns = None
    args.format = 'text'
    args.once = False
    args.watch = None
    cfg = copy.deepcopy(config.DEFAULTS)
    called = []

    def forbidden_factory():
        called.append(True)
        raise AssertionError('local action must not open hidraw')

    code = menu._execute('config', None, args, cfg, None, None, forbidden_factory)
    assert code == monitor.EXIT_OK
    assert '[monitor]' in capsys.readouterr().out
    assert called == []


def test_hardware_action_lazily_opens_and_closes_device(monkeypatch, capsys):
    class ClosablePSU(StubPSU):
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    psu = ClosablePSU()
    opened = []

    def factory():
        opened.append(True)
        return psu

    code = menu._execute('once', None, _args(), {'retention_days': 30}, None, None, factory)
    assert code == monitor.EXIT_OK
    assert opened == [True]
    assert psu.closed is True
    assert 'MSI PSU: MPG Ai1600TS' in capsys.readouterr().out


def test_truncate_marks_the_cut():
    assert menu._truncate('abcdef', 4) == 'ab..'
    assert menu._truncate('abc', 10) == 'abc'
    assert menu._truncate('abc', 0) == ''


def test_decode_key_covers_arrows_enter_quit_and_digits():
    assert menu._decode_key(b'\x1b[A') == 'up'
    assert menu._decode_key(b'\x1b[B') == 'down'
    assert menu._decode_key(b'\x1b[5~') == 'pgup'
    assert menu._decode_key(b'\r') == 'enter'
    assert menu._decode_key(b'q') == 'quit'
    assert menu._decode_key(b'3') == '3'
    assert menu._decode_key(b'x') is None


def test_render_shows_groups_selection_and_scrolls():
    frame, offset = menu.render_menu(menu.ITEMS, 0, 0, 80, 24, color=False)
    assert 'Monitor' in frame and 'History' in frame and 'System' in frame
    assert '> 1)' in frame
    assert 'Up/Down move' in frame
    assert 'Snapshot: single snapshot' in frame
    assert offset == 0

    frame, offset = menu.render_menu(menu.ITEMS, 6, 0, 80, 8, color=False)
    assert '7)' in frame
    assert offset > 0


def test_render_highlights_with_reverse_video_in_colour_mode():
    frame, _ = menu.render_menu(menu.ITEMS, 2, 0, 80, 24, color=True)
    assert menu._REVERSE in frame
    assert menu._RESET in frame


class FakeIO(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


def test_read_key_decodes_a_sequence_and_times_out():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b'\x1b[B')
        assert menu._read_key(read_fd, timeout=0.1) == 'down'
        assert menu._read_key(read_fd, timeout=0.05) is None
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_cbreak_disables_canonical_mode_and_restores_it():
    master, slave = pty.openpty()
    try:
        before = termios.tcgetattr(slave)
        old = menu._cbreak(slave)
        during = termios.tcgetattr(slave)
        assert not during[3] & termios.ICANON
        assert not during[3] & termios.ECHO
        menu._restore_tty(slave, old)
        after = termios.tcgetattr(slave)
        assert after[3] & termios.ICANON
        assert after[3] == before[3]
    finally:
        os.close(master)
        os.close(slave)


def test_interactive_menu_draws_and_restores_the_terminal(monkeypatch):
    master, slave = pty.openpty()
    stdin = os.fdopen(os.dup(slave), 'r', encoding='utf-8', buffering=1)
    stdout = FakeIO(True)
    monkeypatch.setattr(menu.sys, 'stdin', stdin)
    monkeypatch.setattr(menu.sys, 'stdout', stdout)
    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.setattr(menu, '_size', lambda fd=None: (80, 24))
    keys = iter(('down', 'up', 'enter', 'quit'))
    calls = []
    monkeypatch.setattr(menu, '_read_key', lambda fd: next(keys))
    monkeypatch.setattr(menu, '_run', lambda action, *args: calls.append(action) or monitor.EXIT_OK)
    try:
        code = menu.run_menu(
            StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None
        )
        assert code == monitor.EXIT_OK
        assert calls == ['once']
        assert menu._CLEAR in stdout.getvalue()
        assert '\x1b[?25l' in stdout.getvalue()
        assert '\x1b[?25h' in stdout.getvalue()
    finally:
        stdin.close()
        stdout.close()
        attrs = termios.tcgetattr(slave)
        assert attrs[3] & termios.ICANON
        assert attrs[3] & termios.ECHO
        os.close(master)
        os.close(slave)


def test_tiny_terminal_falls_back_to_numbered_input(monkeypatch):
    master, slave = pty.openpty()
    stdin = os.fdopen(os.dup(slave), 'r', encoding='utf-8', buffering=1)
    stdout = os.fdopen(os.dup(slave), 'w', encoding='utf-8', buffering=1)
    monkeypatch.setattr(menu.sys, 'stdin', stdin)
    monkeypatch.setattr(menu.sys, 'stdout', stdout)
    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.setattr(menu, '_size', lambda fd=None: (20, 6))
    monkeypatch.setattr(menu, '_interactive', lambda: True)
    monkeypatch.setattr(menu, '_line_menu', lambda *a: monitor.EXIT_OK)
    try:
        assert (
            menu.run_menu(StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None)
            == monitor.EXIT_OK
        )
        attrs = termios.tcgetattr(slave)
        assert attrs[3] & termios.ICANON
        assert attrs[3] & termios.ECHO
    finally:
        stdin.close()
        stdout.close()
        os.close(master)
        os.close(slave)


def test_pause_prompts_on_a_terminal(monkeypatch):
    out = FakeIO(True)
    monkeypatch.setattr(menu.sys, 'stdin', FakeIO(True))
    monkeypatch.setattr(menu.sys, 'stdout', out)

    def fake_input(prompt=''):
        out.write(prompt)
        return ''

    monkeypatch.setattr(builtins, 'input', fake_input)
    menu._pause()
    assert 'Press Enter to return to the menu' in out.getvalue()


def test_page_prints_short_text_and_pauses(monkeypatch):
    out = FakeIO(True)
    monkeypatch.setattr(menu.sys, 'stdout', out)
    paused = []
    monkeypatch.setattr(menu, '_pause', lambda: paused.append(True))
    menu._page('line one\nline two')
    assert 'line one' in out.getvalue()
    assert paused == [True]


def test_zero_quits_in_the_interactive_keymap():
    """The line prompt quits on 0; the arrow-key map used to swallow it."""
    assert menu._decode_key(b'0') == 'quit'


def test_item_numbers_are_dense_and_the_alert_log_entry_is_local():
    numbers = [item.number for item in menu.ITEMS]
    assert numbers == [str(n) for n in range(1, len(menu.ITEMS) + 1)]
    item = menu.ITEMS[-1]
    assert item.action == 'alerts'
    assert '--show-alert-log' in item.command
    # The alert log reads local state files; opening hidraw for it would steal
    # the device from a running daemon just to print a file.
    assert item.action not in menu._DEVICE_ACTIONS
    assert f'1-{len(menu.ITEMS)} jump' in menu._footer_text()


def test_alert_log_entry_runs_the_local_viewer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        monitor,
        'run_show_alert_log',
        lambda args, cfg: calls.append(args.show_alert_log) or monitor.EXIT_OK,
    )
    args = _args()
    args.output = None
    args.format = 'text'
    code = menu._run('alerts', None, args, copy.deepcopy(config.DEFAULTS), None, None)
    assert code == monitor.EXIT_OK
    assert calls == [True]


def test_help_toggle_renders_the_key_legend():
    plain, _ = menu.render_menu(menu.ITEMS, 0, 0, 80, 24, color=False)
    assert 'returns to the list' not in plain
    frame, _ = menu.render_menu(
        menu.ITEMS, 0, 0, 80, 24, color=False, help_mode=True
    )
    assert 'Up/Down move' in frame
    assert 'q quit' in frame
    assert 'returns to the list' in frame


def test_line_prompt_range_follows_the_item_count(monkeypatch, capsys):
    """Adding an entry must not leave the prompt advertising a stale range."""
    prompts = []

    def fake_input(prompt=''):
        prompts.append(prompt)
        return '0'

    monkeypatch.setattr(builtins, 'input', fake_input)
    code = menu._line_menu(None, _args(), copy.deepcopy(config.DEFAULTS), None, None, None)
    assert code == monitor.EXIT_OK
    assert prompts == [menu._line_prompt()]
    assert prompts[0] == f'[1-{len(menu.ITEMS)}, ?=menu, 0=quit] choice: '
