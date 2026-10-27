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
    frame, offset = menu.render_menu(menu.ITEMS, 0, 0, 80, 40, color=False)
    assert all(group in frame for group in menu.GROUPS)
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


def test_item_numbers_are_dense_and_match_the_visual_order():
    numbers = [item.number for item in menu.ITEMS]
    assert numbers == [str(n) for n in range(1, len(menu.ITEMS) + 1)]
    # The number is the jump key, so the printed order must agree with it.
    # The alert log used to sit at 8 while 7 (Config) rendered first.
    printed = []
    for group in menu.GROUPS:
        for item in menu.ITEMS:
            if item.group == group:
                printed.append(int(item.number))
    assert printed == sorted(printed)
    alerts = next(item for item in menu.ITEMS if item.action == 'alerts')
    assert '--show-alert-log' in alerts.command
    # The alert log reads local state files; opening hidraw for it would steal
    # the device from a running daemon just to print a file.
    assert alerts.action not in menu._DEVICE_ACTIONS
    assert f'1-{min(len(menu.ITEMS), 9)} jump' in menu._footer_text()


def test_the_thresholds_entry_is_a_read_only_device_dump():
    item = next(item for item in menu.ITEMS if item.action == 'thresholds')
    assert '--dump-thresholds' in item.command
    # The C0h dump answers from the PSU, not from a local file: it must open
    # the device like the other hardware views, never silently read a cache.
    assert item.action in menu._DEVICE_ACTIONS
    assert menu.ACTIONS[item.action].needs_device is True


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
    frame, _ = menu.render_menu(menu.ITEMS, 0, 0, 80, 24, color=False, help_mode=True)
    assert 'Up/Down move' in frame
    assert 'q/Esc quit' in frame
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


def test_application_cursor_arrow_keys_are_understood():
    """tmux/vim leftovers leave the terminal in application cursor mode."""
    assert menu._decode_key(b'\x1bOA') == 'up'
    assert menu._decode_key(b'\x1bOB') == 'down'
    assert menu._decode_key(b'\x1bOH') == 'home'
    assert menu._decode_key(b'\x1bOF') == 'end'
    # Right/left are consumed so they cannot garble the next key, but the
    # single-level menu has no horizontal movement to bind them to.
    assert menu._decode_key(b'\x1bOC') is None
    assert menu._decode_key(b'\x1bOD') is None


def test_an_arrow_does_not_swallow_the_next_key_in_application_mode():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b'\x1bOBq')
        assert menu._read_key(read_fd, timeout=0.1) == 'down'
        assert menu._read_key(read_fd, timeout=0.05) == 'quit'
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_a_lone_escape_is_the_escape_action():
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, b'\x1b')
        assert menu._read_key(read_fd, timeout=0.1) == 'escape'
    finally:
        os.close(read_fd)
        os.close(write_fd)


def _drive_interactive(monkeypatch, keys, run=None, size=(80, 24), env=None):
    """Drive the interactive loop over a pty; returns (stdout text, exit code).

    ``size`` may be a single (width, height) pair or a list of pairs, one per
    ``_size()`` call — the loop sizes the terminal once at startup and again on
    every wake-up — to drive the resize path.
    """
    master, slave = pty.openpty()
    stdin = os.fdopen(os.dup(slave), 'r', encoding='utf-8', buffering=1)
    stdout = FakeIO(True)
    monkeypatch.setattr(menu.sys, 'stdin', stdin)
    monkeypatch.setattr(menu.sys, 'stdout', stdout)
    monkeypatch.setenv('TERM', (env or {}).get('TERM', 'xterm'))
    if env and 'NO_COLOR' in env:
        monkeypatch.setenv('NO_COLOR', env['NO_COLOR'])
    else:
        monkeypatch.delenv('NO_COLOR', raising=False)
    sizes = iter(size if isinstance(size, list) else [size])
    final_size = size[-1] if isinstance(size, list) else size
    monkeypatch.setattr(menu, '_size', lambda fd=None: next(sizes, final_size))
    key_stream = iter(keys)
    monkeypatch.setattr(menu, '_read_key', lambda fd: next(key_stream))
    monkeypatch.setattr(menu, '_run', run or (lambda action, *args: monitor.EXIT_OK))
    monkeypatch.setattr(menu, '_pause', lambda: None)
    try:
        code = menu.run_menu(
            StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None
        )
        # getvalue() must run while the fake stdout is still open: the finally
        # below closes it, and a closed StringIO answers getvalue() with
        # "I/O operation on closed file" instead of the frame.
        text = stdout.getvalue()
    finally:
        stdin.close()
        stdout.close()
        os.close(master)
        os.close(slave)
    return text, code


def test_escape_closes_the_help_overlay_before_quitting(monkeypatch):
    # Keys here are decoded action names: '?' reaches the loop as 'help'.
    out, code = _drive_interactive(monkeypatch, ('help', 'escape', 'quit'))
    assert code == monitor.EXIT_OK
    assert out.count('returns to the list') == 1


def test_escape_quits_the_menu_when_help_is_closed(monkeypatch):
    calls = []

    def run(action, *args):
        calls.append(action)
        return monitor.EXIT_OK

    out, code = _drive_interactive(monkeypatch, ('escape',), run=run)
    assert code == monitor.EXIT_OK
    assert calls == []
    assert '$ ' not in out


def test_the_header_reports_the_last_action_as_ok(monkeypatch):
    out, code = _drive_interactive(monkeypatch, ('enter', 'quit'))
    assert code == monitor.EXIT_OK
    assert 'last: Snapshot ok' in out


def test_the_header_reports_a_nonzero_exit(monkeypatch):
    out, code = _drive_interactive(
        monkeypatch, ('enter', 'quit'), run=lambda action, *a: monitor.EXIT_ALERT
    )
    assert code == monitor.EXIT_OK  # the menu itself still exits cleanly
    assert 'last: Snapshot exit 2' in out


def test_an_interrupted_action_is_reported_as_stopped(monkeypatch):
    def interrupted(action, *args):
        raise KeyboardInterrupt

    out, code = _drive_interactive(monkeypatch, ('enter', 'quit'), run=interrupted)
    assert code == monitor.EXIT_OK
    assert 'last: Snapshot stopped' in out


def test_the_alternate_screen_is_entered_and_restored(monkeypatch):
    out, code = _drive_interactive(monkeypatch, ('enter', 'quit'))
    assert code == monitor.EXIT_OK
    # One enter/exit pair around the whole menu, one pair around the action,
    # so the action output survives on the normal screen after quitting.
    assert out.count('\x1b[?1049h') == 2
    assert out.count('\x1b[?1049l') == 2


def test_the_linux_console_keeps_the_main_screen(monkeypatch):
    """The VGA console never supported 1049 reliably; stay on the main screen."""
    out, code = _drive_interactive(monkeypatch, ('quit',), env={'TERM': 'linux'})
    assert code == monitor.EXIT_OK
    assert '\x1b[?1049' not in out


def test_no_color_removes_the_selection_bar(monkeypatch):
    out, code = _drive_interactive(monkeypatch, ('quit',), env={'NO_COLOR': '1'})
    assert code == monitor.EXIT_OK
    assert menu._REVERSE not in out
    assert menu._BOLD not in out


def test_a_resize_redraws_at_the_new_width(monkeypatch):
    # Startup sizes the terminal once, the loop again on every wake-up; the
    # duplicated first pair covers that, then the resize happens.
    out, code = _drive_interactive(monkeypatch, (None, 'quit'), size=[(80, 24), (80, 24), (46, 12)])
    assert code == monitor.EXIT_OK
    assert '-' * 80 in out
    assert '-' * 46 in out


def test_the_thresholds_entry_dumps_the_c0h_configuration(monkeypatch, capsys):
    seen = {}

    def fake_run_ocp_thresholds(psu, args):
        seen['dump_thresholds'] = args.dump_thresholds
        seen['format'] = args.format
        seen['output'] = args.output
        print('OCP thresholds: point 12.0 A')
        return monitor.EXIT_OK

    monkeypatch.setattr(monitor, 'run_ocp_thresholds', fake_run_ocp_thresholds)
    code = menu._run('thresholds', StubPSU(), _args(), {'retention_days': 30}, None, None)
    assert code == monitor.EXIT_OK
    assert seen == {'dump_thresholds': True, 'format': 'text', 'output': None}
    assert 'OCP thresholds' in capsys.readouterr().out


def test_the_thresholds_entry_opens_the_device_lazily(monkeypatch):
    class ClosablePSU(StubPSU):
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    psu = ClosablePSU()
    opened = []
    monkeypatch.setattr(monitor, 'run_ocp_thresholds', lambda p, a: monitor.EXIT_OK)

    def factory():
        opened.append(True)
        return psu

    code = menu._execute('thresholds', None, _args(), {'retention_days': 30}, None, None, factory)
    assert code == monitor.EXIT_OK
    assert opened == [True]
    assert psu.closed is True


def test_real_pty_keystrokes_drive_the_interactive_menu(monkeypatch):
    """End-to-end through the real key reader, not a stubbed ``_read_key``.

    The other interactive tests replace ``_read_key``, so select()/os.read()/
    termios and the escape-sequence splitter were only unit-tested in isolation.
    This drives the shipped loop from a pty master: ESC [ B (down), Enter (run
    "Live view"), then q (quit).
    """
    master, slave = pty.openpty()
    stdin = os.fdopen(os.dup(slave), 'r', encoding='utf-8', buffering=1)
    stdout = FakeIO(True)
    monkeypatch.setattr(menu.sys, 'stdin', stdin)
    monkeypatch.setattr(menu.sys, 'stdout', stdout)
    monkeypatch.setenv('TERM', 'xterm')
    monkeypatch.setattr(menu, '_size', lambda fd=None: (80, 24))
    monkeypatch.setattr(menu, '_pause', lambda: None)
    runs = []
    monkeypatch.setattr(menu, '_run', lambda action, *args: runs.append(action) or monitor.EXIT_OK)
    os.write(master, b'\x1b[B\rq')  # down, enter, quit
    try:
        code = menu.run_menu(
            StubPSU(), _args(), {'retention_days': 30, 'interval': 1.0}, None, None
        )
        text = stdout.getvalue()  # before the finally closes the fake stdout
    finally:
        stdin.close()
        stdout.close()
        os.close(master)
        os.close(slave)
    assert code == monitor.EXIT_OK
    assert runs == ['once_json']
    assert 'last:' in text


def test_the_word_menu_is_a_shorthand_for_the_flag(monkeypatch):
    """`msi-psu-monitor menu` must behave exactly like `--menu`."""
    from msi_psu_monitor import menu as menu_module

    opened = []
    monkeypatch.setattr(
        menu_module,
        'run_menu',
        lambda *args, **kwargs: opened.append(True) or monitor.EXIT_OK,
    )
    assert _run_main(monkeypatch, ['menu']) == monitor.EXIT_OK
    assert opened == [True]


def test_the_word_menu_still_rejects_a_conflicting_mode(monkeypatch, capsys):
    assert _run_main(monkeypatch, ['menu', '--once']) == 2
    assert '--menu' in capsys.readouterr().err


def test_every_cli_action_is_reachable_from_the_menu():
    """The menu is the product's front door for hardware work: no action may be
    reachable only by remembering a flag."""
    referenced = {item.action for item in menu.ITEMS}
    assert referenced == set(menu.ACTIONS)
    assert len(menu.ITEMS) == 22
    for action in (
        'once',
        'once_json',
        'once_prometheus',
        'watch',
        'watch_custom',
        'dashboard',
        'dashboard_web',
        'export',
        'export_custom',
        'ocp',
        'thresholds',
        'log',
        'alerts',
        'fan_auto',
        'fan_duty',
        'zero_fan',
        'buzzer',
        'rail',
        'ocp_write',
        'ocp_load',
        'config',
        'serial',
    ):
        assert action in referenced, action


def test_fan_duty_entry_prompts_and_writes(monkeypatch):
    answers = iter(['55', 'y'])
    monkeypatch.setattr(builtins, 'input', lambda *a: next(answers))
    written = []
    monkeypatch.setattr(
        monitor,
        'run_write_controls',
        lambda psu, args: written.append(args) or monitor.EXIT_OK,
    )
    code = menu._run(
        'fan_duty',
        StubPSU(),
        monitor.build_parser().parse_args([]),
        {'retention_days': 30},
        None,
        None,
    )
    assert code == monitor.EXIT_OK
    assert written[0].fan_mode == monitor.FAN_MODE_CUSTOMIZED
    assert written[0].fan_duty == 55


def test_a_write_entry_is_cancelled_without_confirmation(monkeypatch, capsys):
    answers = iter(['55', 'n'])
    monkeypatch.setattr(builtins, 'input', lambda *a: next(answers))

    def bomb(*_a):
        raise AssertionError('a cancelled write must not run')

    monkeypatch.setattr(monitor, 'run_write_controls', bomb)
    code = menu._run(
        'fan_duty',
        StubPSU(),
        monitor.build_parser().parse_args([]),
        {'retention_days': 30},
        None,
        None,
    )
    assert code == monitor.EXIT_OK
    assert 'Cancelled.' in capsys.readouterr().out


def test_buzzer_entry_writes_after_confirmation(monkeypatch):
    monkeypatch.setattr(builtins, 'input', lambda *a: 'y')
    written = []
    monkeypatch.setattr(
        monitor,
        'run_write_controls',
        lambda psu, args: written.append(args) or monitor.EXIT_OK,
    )
    assert (
        menu._run(
            'buzzer',
            StubPSU(),
            monitor.build_parser().parse_args([]),
            {'retention_days': 30},
            None,
            None,
        )
        == monitor.EXIT_OK
    )
    assert written[0].buzzer_off is True


def test_ocp_write_entry_validates_then_confirms(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        monitor,
        'run_ocp_thresholds',
        lambda psu, args: calls.append(args) or monitor.EXIT_OK,
    )
    answers = iter(['1,2,3,4,5'])
    monkeypatch.setattr(builtins, 'input', lambda *a: next(answers))
    assert (
        menu._run(
            'ocp_write',
            StubPSU(),
            monitor.build_parser().parse_args([]),
            {'retention_days': 30},
            None,
            None,
        )
        == monitor.EXIT_ERROR
    )
    assert calls == []
    assert 'Error:' in capsys.readouterr().out

    answers = iter(['12,5,20,20,180,on', 'y'])
    monkeypatch.setattr(builtins, 'input', lambda *a: next(answers))
    assert (
        menu._run(
            'ocp_write',
            StubPSU(),
            monitor.build_parser().parse_args([]),
            {'retention_days': 30},
            None,
            None,
        )
        == monitor.EXIT_OK
    )
    assert calls[0].ocp_set['point_a'] == 12
    assert calls[0].ocp_set['enabled'] is True


def test_serial_entry_sets_the_filter(monkeypatch):
    args = monitor.build_parser().parse_args([])
    monkeypatch.setattr(builtins, 'input', lambda *a: 'SN-42')
    assert menu._run('serial', None, args, {'retention_days': 30}, None, None) == monitor.EXIT_OK
    assert args.serial == 'SN-42'


def test_the_psu_command_defaults_to_the_menu(monkeypatch):
    from msi_psu_monitor import psu

    seen = []
    monkeypatch.setattr(psu.monitor, 'main', lambda: seen.append(list(sys.argv)))
    monkeypatch.setattr(sys, 'argv', ['psu'])
    psu.main()
    assert seen == [['psu', 'menu']]


def test_the_psu_command_passes_explicit_arguments_through(monkeypatch):
    from msi_psu_monitor import psu

    seen = []
    monkeypatch.setattr(psu.monitor, 'main', lambda: seen.append(list(sys.argv)))
    monkeypatch.setattr(sys, 'argv', ['psu', '--version'])
    psu.main()
    assert seen == [['psu', '--version']]
