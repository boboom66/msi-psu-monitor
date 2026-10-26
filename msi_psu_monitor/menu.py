"""Numbered CLI menu (``msi-psu-monitor --menu``).

Interaction model follows mature MIT terminal menus (simple-term-menu,
console-menu): arrow keys move a highlighted selection, Enter runs it, digits
jump to an entry, ``q`` quits, the list scrolls when the terminal is short and
the screen is cleared between actions.  The implementation here is original
stdlib-only code -- no third-party menu library is vendored or required -- so
the project keeps its zero-runtime-dependency promise and its MIT-only
compliance is unchanged.

Non-interactive stdout/stdin (pipes, tests, ``TERM=dumb``) falls back to the
numbered line prompt, which is also what the automated tests drive.
"""

import contextlib
import copy
import io
import os
import pydoc
import select
import shutil
import subprocess
import sys
import termios
from dataclasses import dataclass

from msi_psu_monitor import monitor

#: ANSI home + erase-screen.  Only emitted on a real terminal; pipes and tests
#: keep printable output (the same rule --watch follows).
_CLEAR = '\x1b[H\x1b[2J'
_REVERSE = '\x1b[7m'
_BOLD = '\x1b[1m'
_DIM = '\x1b[2m'
_RESET = '\x1b[0m'


@dataclass(frozen=True)
class Item:
    number: str
    group: str
    label: str
    command: str
    purpose: str
    action: str


ITEMS = (
    Item('1', 'Monitor', 'Snapshot', 'msi-psu-monitor --once', 'single snapshot', 'once'),
    Item('2', 'Monitor', 'Live view', 'msi-psu-monitor --watch 1', 'refresh 1s (Ctrl-C)', 'watch'),
    Item(
        '3',
        'Monitor',
        'Dashboard',
        'msi-psu-monitor --dashboard-text',
        'coloured terminal view (Ctrl-C)',
        'dashboard',
    ),
    Item(
        '4',
        'History',
        'Export CSV',
        'msi-psu-monitor --export --from 1h',
        'last hour of history',
        'export',
    ),
    Item('5', 'History', 'OCP', 'msi-psu-monitor --ocp', 'thresholds + state (TS)', 'ocp'),
    Item(
        '6', 'History', 'Black box', 'msi-psu-monitor --show-log', 'trip log, newest first', 'log'
    ),
    Item(
        '7',
        'System',
        'Config',
        'msi-psu-monitor --dump-config',
        'effective configuration',
        'config',
    ),
    Item(
        '8',
        'History',
        'Alert log',
        'msi-psu-monitor --show-alert-log',
        'local alert audit trail (no PSU needed)',
        'alerts',
    ),
)
GROUPS = ('Monitor', 'History', 'System')


def _footer_text():
    """Key legend; the jump range follows the item count."""
    return f'Up/Down move   Enter run   1-{len(ITEMS)} jump   q quit   ? keys'
MIN_WIDTH = 40
MIN_HEIGHT = 8


def _is_tty(stream=None):
    stream = sys.stdin if stream is None else stream
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _interactive():
    """Both ends must be a terminal; otherwise the line prompt is used."""
    if not (_is_tty(sys.stdin) and _is_tty(sys.stdout)):
        return False
    return os.environ.get('TERM', '').strip().lower() not in ('', 'dumb')


def _clear():
    """Clear between actions, like dialog/whiptail; never in a pipe."""
    if not _is_tty(sys.stdout):
        return
    if os.environ.get('TERM', '').strip().lower() in ('', 'dumb'):
        return
    try:
        sys.stdout.write(_CLEAR)
        sys.stdout.flush()
    except OSError:
        pass


def _size(fd=None):
    try:
        if fd is None:
            fd = sys.stdout.fileno()
        size = os.get_terminal_size(fd)
        return max(1, size.columns), max(1, size.lines)
    except (AttributeError, OSError, ValueError):
        return 80, 24


def _truncate(text, width):
    """Cut to ``width`` columns, marking the cut so it is not read as data."""
    if width <= 0:
        return ''
    if len(text) <= width:
        return text
    if width <= 2:
        return text[:width]
    return text[: width - 2] + '..'


def _line_for(item, width, selected, color):
    marker = '>' if selected else ' '
    head = f'{marker} {item.number}) {item.label:11s}'
    tail = f'  {item.command}'
    text = _truncate(head + tail, width)
    if selected and color:
        return _REVERSE + text + _RESET
    return text


def _body_lines(items, selected, width, color):
    """Return (lines, index of the selected line) with group headings."""
    lines = []
    selected_line = 0
    for group in GROUPS:
        lines.append(f' {_BOLD}{group}{_RESET}' if color else f' {group}')
        for item in items:
            if item.group != group:
                continue
            if item is items[selected]:
                selected_line = len(lines)
            lines.append(_line_for(item, width, item is items[selected], color))
        lines.append('')
    return lines, selected_line


def render_menu(items, selected, offset, width, height, *, color=True, help_mode=False):
    """Pure renderer: returns (frame, new_offset) for tests and the loop."""
    inner = max(MIN_WIDTH, min(width, 100))
    header = ' MSI PSU Monitor - menu'
    rule = '-' * inner
    body, selected_line = _body_lines(items, selected, inner, color)

    available = max(1, height - 5)  # header, two rules, detail, footer
    offset = max(0, min(offset, max(0, len(body) - available)))
    if selected_line < offset:
        offset = selected_line
    elif selected_line >= offset + available:
        offset = selected_line - available + 1
    window = body[offset : offset + available]
    item = items[selected]
    if help_mode:
        # The detail slot is the most readable place for the key legend; the
        # footer keeps its usual shape so the frame height never changes.
        detail = ' ' + _truncate(_footer_text(), inner - 1)
        footer = ' ' + _truncate('? returns to the list', inner - 1)
    else:
        detail = ' ' + _truncate(f'{item.label}: {item.purpose}', inner - 1)
        footer = ' ' + _truncate(_footer_text(), inner - 1)
    frame = [header, rule, *window, rule, detail, footer]
    return '\n'.join(frame), offset


#: Complete escape sequences; reading stops as soon as one matches so a key
#: pressed immediately after an arrow is not swallowed into the same read.
_SEQUENCE_KEYS = frozenset(
    {
        b'\x1b[A',
        b'\x1b[B',
        b'\x1b[H',
        b'\x1b[F',
        b'\x1b[1~',
        b'\x1b[4~',
        b'\x1b[5~',
        b'\x1b[6~',
    }
)


def _decode_key(data):
    """Translate a raw key sequence to an action name; None means ignore."""
    mapping = {
        b'\x1b[A': 'up',
        b'\x1b[B': 'down',
        b'\x1b[H': 'home',
        b'\x1b[F': 'end',
        b'\x1b[1~': 'home',
        b'\x1b[4~': 'end',
        b'\x1b[5~': 'pgup',
        b'\x1b[6~': 'pgdn',
        b'k': 'up',
        b'j': 'down',
        b'\r': 'enter',
        b'\n': 'enter',
        b'q': 'quit',
        b'Q': 'quit',
        # The line prompt quits on 0; the interactive map must agree.
        b'0': 'quit',
        b'?': 'help',
    }
    if data in mapping:
        return mapping[data]
    if len(data) == 1 and data.isdigit():
        return data.decode()
    return None


def _read_key(fd, timeout=0.25):
    """Read one key without blocking forever; None means 'redraw'."""
    try:
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        data = os.read(fd, 1)
        if data == b'\x1b':
            # Stop at a complete sequence: reading the whole burst swallowed the
            # next key (e.g. the q that follows an arrow) and lost it.
            while len(data) < 8 and select.select([fd], [], [], 0.01)[0]:
                data += os.read(fd, 1)
                if data in _SEQUENCE_KEYS:
                    break
        return _decode_key(data)
    except OSError:
        return 'quit'


def _cbreak(fd):
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[3] &= ~(termios.ICANON | termios.ECHO)
    new[6][termios.VMIN] = 1
    new[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    return old


def _restore_tty(fd, old):
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (OSError, termios.error):
        pass


def _page(text):
    if not _is_tty(sys.stdout):
        print(text)
        return
    lines = text.count('\n') + 1
    try:
        rows = os.get_terminal_size(sys.stdout.fileno()).lines
    except (OSError, ValueError):
        rows = 24
    if lines < max(3, rows - 2):
        print(text)
        _pause()
        return
    if shutil.which('less'):
        try:
            # -X keeps the output on screen after q; without it less restores
            # the previous screen and the user never sees what they paged.
            subprocess.run(['less', '-R', '-X'], input=text, text=True, check=False)
            return
        except OSError:
            pass
    pydoc.pager(text)
    _pause()


def _pause():
    if not _is_tty(sys.stdin) or not _is_tty(sys.stdout):
        return
    try:
        input('Press Enter to return to the menu...')
    except (EOFError, KeyboardInterrupt):
        pass


def _paged(action, *args):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = action(*args)
    text = buffer.getvalue()
    if text:
        _page(text.rstrip('\n'))
    return code


def _run(action, psu, args, cfg, monitor_state, engine):
    if action == 'once':
        return _paged(monitor.run_once, psu, copy.copy(args), cfg, monitor_state, engine)
    if action == 'export':
        local = copy.copy(args)
        local.export = True
        local.format = 'text'
        local.from_spec = '1h'
        local.columns = None
        local.output = None
        return _paged(monitor.run_export, local, cfg)
    if action == 'ocp':
        local = copy.copy(args)
        local.ocp = True
        local.format = 'text'
        return _paged(monitor.run_ocp, psu, local)
    if action == 'log':
        _paged(lambda: monitor.emit(monitor.format_blackbox(psu.read_blackbox()), None))
        return monitor.EXIT_OK
    if action == 'config':
        _paged(lambda: monitor.emit(monitor._dump_effective_config(cfg, 'text'), None))
        return monitor.EXIT_OK
    if action == 'alerts':
        local = copy.copy(args)
        local.show_alert_log = True
        local.format = 'text'
        local.output = None
        return _paged(monitor.run_show_alert_log, local, cfg)
    if action == 'watch':
        local = copy.copy(args)
        local.watch = 1
        local.interval = None
        local.dashboard_text = False
        local.output = None
        return monitor.run_watch(psu, local, cfg, monitor_state, engine)
    if action == 'dashboard':
        local = copy.copy(args)
        local.watch = monitor.WATCH_FROM_CONFIG
        local.interval = 1.0
        local.dashboard_text = True
        local.output = None
        return monitor.run_dashboard_text(psu, local, cfg, monitor_state, engine)
    raise AssertionError(f'unknown menu action: {action}')


def _line_show():
    print()
    print('============== MSI PSU Monitor - menu ==============')
    current = None
    for item in ITEMS:
        if item.group != current:
            current = item.group
            print(f' {current}')
        print(f' {item.number}) {item.command}')
        print(f'    -> {item.purpose}')
    print('  0) quit')
    print('=====================================================')


def _line_prompt():
    return f'[1-{len(ITEMS)}, ?=menu, 0=quit] choice: '


_DEVICE_ACTIONS = frozenset({'once', 'watch', 'dashboard', 'ocp', 'log'})


def _execute(action, psu, args, cfg, monitor_state, engine, psu_factory):
    """Run a menu action, acquiring/releasing HID only for hardware actions."""
    owned = False
    active_psu = psu
    if action in _DEVICE_ACTIONS and active_psu is None:
        if psu_factory is None:
            print('Error: this action requires a connected MSI PSU.')
            return monitor.EXIT_ERROR
        try:
            active_psu = psu_factory()
        except Exception as exc:
            print(f'Error: could not open MSI PSU: {exc}')
            return monitor.EXIT_ERROR
        if active_psu is None:
            print('Error: MSI PSU not found or could not be opened.')
            return monitor.EXIT_ERROR
        owned = True
    try:
        return _run(action, active_psu, args, cfg, monitor_state, engine)
    finally:
        if owned and active_psu is not None:
            try:
                active_psu.close()
            except OSError as exc:
                print(f'Warning: could not close PSU: {exc}', file=sys.stderr)


def _line_menu(psu, args, cfg, monitor_state, engine, psu_factory=None):
    actions = {item.number: item.action for item in ITEMS}
    while True:
        _clear()
        _line_show()
        try:
            choice = input(_line_prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return monitor.EXIT_OK
        if choice in ('0', 'q', 'quit', 'exit'):
            return monitor.EXIT_OK
        if choice in ('?', 'h', 'help', ''):
            continue
        action = actions.get(choice)
        if action is None:
            print(f'invalid choice: {choice}')
            _pause()
            continue
        item = next(i for i in ITEMS if i.number == choice)
        print(f'\n$ {item.command}')
        try:
            code = _execute(action, psu, args, cfg, monitor_state, engine, psu_factory)
        except KeyboardInterrupt:
            code = monitor.EXIT_OK
        if code not in (None, monitor.EXIT_OK):
            print(f'exit={code}')
            _pause()


def _interactive_menu(psu, args, cfg, monitor_state, engine, psu_factory=None):
    fd = sys.stdin.fileno()
    selected = 0
    offset = 0
    help_mode = False
    signals = monitor._watch_enable_soft_termination()
    old_tty = None
    cursor_hidden = False
    try:
        old_tty = _cbreak(fd)
        width, height = _size(fd)
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            _restore_tty(fd, old_tty)
            old_tty = None
            print(
                f'Warning: terminal is {width}x{height}; the interactive menu '
                f'needs at least {MIN_WIDTH}x{MIN_HEIGHT}. Using numbered input.'
            )
            return _line_menu(psu, args, cfg, monitor_state, engine, psu_factory)
        sys.stdout.write('\x1b[?25l')
        sys.stdout.flush()
        cursor_hidden = True
        dirty = True
        last_size = None
        while True:
            size = _size(fd)
            if size != last_size:
                last_size = size
                dirty = True
            if dirty:
                width, height = size
                frame, offset = render_menu(
                    ITEMS, selected, offset, width, height, help_mode=help_mode
                )
                _clear()
                sys.stdout.write(frame + '\n')
                sys.stdout.flush()
                dirty = False
            key = _read_key(fd)
            if key is None:
                # A select() timeout only exists to notice a resize; without a
                # state change there is nothing to redraw (redrawing on every
                # timeout made the screen flash several times a second).
                continue
            if key == 'quit':
                return monitor.EXIT_OK
            if key == 'help':
                # ``?`` was decoded but silently ignored (it fell into the
                # generic redraw path); it now toggles the key legend.
                help_mode = not help_mode
                dirty = True
                continue
            if key in ('up', 'k'):
                selected = (selected - 1) % len(ITEMS)
            elif key in ('down', 'j'):
                selected = (selected + 1) % len(ITEMS)
            elif key == 'home':
                selected = 0
            elif key == 'end':
                selected = len(ITEMS) - 1
            elif key in ('pgup', 'pgdn'):
                step = max(1, len(ITEMS) // 2)
                if key == 'pgup':
                    selected = max(0, selected - step)
                else:
                    selected = min(len(ITEMS) - 1, selected + step)
            elif key in [item.number for item in ITEMS]:
                selected = next(i for i, item in enumerate(ITEMS) if item.number == key)
                key = 'enter'
                # Digits used to run the entry immediately; keep that contract
                # in the interactive menu too.
            if key != 'enter':
                dirty = True
                continue

            item = ITEMS[selected]
            _restore_tty(fd, old_tty)
            try:
                _clear()
                print(f'$ {item.command}')
                try:
                    code = _execute(
                        item.action,
                        psu,
                        args,
                        cfg,
                        monitor_state,
                        engine,
                        psu_factory,
                    )
                except KeyboardInterrupt:
                    code = monitor.EXIT_OK
                if code not in (None, monitor.EXIT_OK):
                    print(f'exit={code}')
                    _pause()
            finally:
                old_tty = _cbreak(fd)
            dirty = True
            help_mode = False
    finally:
        if old_tty is not None:
            _restore_tty(fd, old_tty)
        monitor._watch_restore_signals(signals)
        if cursor_hidden:
            try:
                sys.stdout.write('\x1b[?25h')
                sys.stdout.flush()
            except OSError:
                pass


def run_menu(psu, args, cfg, monitor_state, engine, psu_factory=None):
    """Interactive menu on a terminal, numbered line prompt otherwise."""
    if _interactive():
        try:
            return _interactive_menu(psu, args, cfg, monitor_state, engine, psu_factory)
        except KeyboardInterrupt:
            return monitor.EXIT_OK
        except (OSError, termios.error, ValueError) as exc:
            try:
                print(
                    f'Warning: interactive terminal mode unavailable ({exc}); using numbered input.',
                    file=sys.stderr,
                )
            except OSError:
                pass
    return _line_menu(psu, args, cfg, monitor_state, engine, psu_factory)
