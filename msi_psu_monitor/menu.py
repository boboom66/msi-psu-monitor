"""Numbered CLI menu (``msi-psu-monitor --menu``).

Interaction model follows mature MIT terminal menus (simple-term-menu,
console-menu, pick, PyTermGUI — all four licence files were verified against
the sdist before this design was fixed): arrow keys move a highlighted
selection, Enter runs it, digits 1-9 jump to an entry, ``q``/``Esc`` quit, ``?``
toggles the key legend, the list scrolls when the terminal is short, the
screen is cleared between actions and the last action's result stays visible
in the header.

The implementation here is original stdlib-only code — no third-party menu
library is vendored or required — so the project keeps its
zero-runtime-dependency promise and its MIT-only compliance is unchanged.
The candidate libraries were ruled out on architecture, not licence: each one
is a runtime dependency, which this project forbids (tests/test_stdlib_only.py,
self-contained release binaries).

Non-interactive stdout/stdin (pipes, tests, ``TERM=dumb``) falls back to the
numbered line prompt, which is also what the automated tests drive.
"""

import argparse
import contextlib
import copy
import io
import math
import os
import pydoc
import re
import select
import shutil
import subprocess
import sys
import termios
import unicodedata
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

from msi_psu_monitor import monitor, termdash

#: ANSI home + erase-screen.  Only emitted on a real terminal; pipes and tests
#: keep printable output (the same rule --watch follows).
_CLEAR = '\x1b[H\x1b[2J'
_REVERSE = '\x1b[7m'
_BOLD = '\x1b[1m'
_DIM = '\x1b[2m'
_RESET = '\x1b[0m'
# Menu palette: standard 8/16-colour SGR only, so it works over SSH, tmux and
# the Linux VGA console without requiring 256-colour support.
_COLOR_BORDER = '\x1b[36m'
_COLOR_TITLE = '\x1b[1;36m'
_COLOR_GROUP = '\x1b[1;34m'
_COLOR_NUMBER = '\x1b[33m'
_COLOR_LABEL = '\x1b[1;37m'
_COLOR_COMMAND = '\x1b[2;37m'
_COLOR_DETAIL = '\x1b[36m'
_COLOR_FOOTER = '\x1b[2;37m'
_COLOR_OK = '\x1b[32m'
_COLOR_WARN = '\x1b[33m'
_COLOR_ERROR = '\x1b[31m'

#: xterm-style alternate screen buffer.  The menu is resident, so it draws on
#: the alternate screen and restores the shell's view on exit (what
#: dialog/whiptail do).  Skipped on the VGA console (``TERM=linux``), which
#: never supported 1049 reliably — the same terminal termdash treats specially.
_ALT_ENTER = '\x1b[?1049h'
_ALT_EXIT = '\x1b[?1049l'
_ALT_UNSUPPORTED_TERMS = frozenset({'', 'dumb', 'linux'})


@dataclass(frozen=True)
class Item:
    number: str
    group: str
    label: str
    command: str
    purpose: str
    action: str


# The numbers match the on-screen order exactly, group by group.  They used to
# drift (the alert log sat at ``8`` while ``7`` rendered first), which broke the
# digit-jump contract for anyone reading top-down.  Every CLI action has an
# entry: the read-only views first, then the control writes (which ask for their
# parameters and a confirmation before touching the PSU), then system helpers.
ITEMS = (
    Item('1', 'Monitor', 'Snapshot', 'msi-psu-monitor --once', 'single snapshot', 'once'),
    Item(
        '2',
        'Monitor',
        'Snapshot JSON',
        'msi-psu-monitor --once -f json',
        'machine-readable snapshot',
        'once_json',
    ),
    Item(
        '3',
        'Monitor',
        'Snapshot Prom',
        'msi-psu-monitor --once -f prometheus',
        'textfile-collector format',
        'once_prometheus',
    ),
    Item(
        '4',
        'Monitor',
        'Live 1 s',
        'msi-psu-monitor --watch 1',
        'refresh 1s (Ctrl-C)',
        'watch',
    ),
    Item(
        '5',
        'Monitor',
        'Live custom',
        'msi-psu-monitor --watch <seconds>',
        'prompt for the interval (Ctrl-C)',
        'watch_custom',
    ),
    Item(
        '6',
        'Monitor',
        'Term dashboard',
        'msi-psu-monitor --dashboard-text',
        'coloured terminal view (Ctrl-C)',
        'dashboard',
    ),
    Item(
        '7',
        'Monitor',
        'Web dashboard',
        'msi-psu-monitor --dashboard',
        'browser on 127.0.0.1 (Ctrl-C)',
        'dashboard_web',
    ),
    Item(
        '8',
        'History',
        'Export 1 h',
        'msi-psu-monitor --export --from 1h',
        'last hour of history',
        'export',
    ),
    Item(
        '9',
        'History',
        'Export custom',
        'msi-psu-monitor --export --from <window> --columns <cols>',
        'prompt window and columns',
        'export_custom',
    ),
    Item('10', 'History', 'OCP', 'msi-psu-monitor --ocp', 'thresholds + state (TS)', 'ocp'),
    Item(
        '11',
        'History',
        'Pin currents',
        'msi-psu-monitor --pins',
        'per-pin 5 s averages (MPG TS)',
        'pins',
    ),
    Item(
        '12',
        'History',
        'Thresholds',
        'msi-psu-monitor --dump-thresholds',
        'read-only C0h dump (MPG TS)',
        'thresholds',
    ),
    Item(
        '13',
        'History',
        'Black box',
        'msi-psu-monitor --show-log',
        'trip log, newest first',
        'log',
    ),
    Item(
        '14',
        'History',
        'Alert log',
        'msi-psu-monitor --show-alert-log',
        'local alert audit trail (no PSU needed)',
        'alerts',
    ),
    Item(
        '15',
        'Writes',
        'Fan auto',
        'msi-psu-monitor --fan-mode auto',
        'PSU curve (41h + F1h)',
        'fan_auto',
    ),
    Item(
        '16',
        'Writes',
        'Fan duty',
        'msi-psu-monitor --fan-mode customized --fan-duty <0-100>',
        'prompt the duty, then write + verify',
        'fan_duty',
    ),
    Item(
        '17',
        'Writes',
        'Zero Fan',
        'msi-psu-monitor --zero-fan on|off',
        '43h + F1h (12+4 models)',
        'zero_fan',
    ),
    Item(
        '18',
        'Writes',
        'Buzzer',
        'msi-psu-monitor --buzzer-toggle',
        'C2h switch, no read-back',
        'buzzer',
    ),
    Item(
        '19',
        'Writes',
        'Rail mode',
        'msi-psu-monitor --set-rail multi|single',
        '0xC0 1 byte + F1h (MEG P)',
        'rail',
    ),
    Item(
        '20',
        'Writes',
        'OCP write',
        'msi-psu-monitor --ocp-set <5 values[,on|off]>',
        'C0h + F1h, verified read-back',
        'ocp_write',
    ),
    Item(
        '21',
        'Writes',
        'OCP load',
        'msi-psu-monitor --load-thresholds <file>',
        'write values from a JSON dump',
        'ocp_load',
    ),
    Item(
        '22',
        'System',
        'Config',
        'msi-psu-monitor --dump-config',
        'effective configuration',
        'config',
    ),
    Item(
        '23',
        'System',
        'Serial',
        'msi-psu-monitor --serial <serial>',
        'filter later actions to one PSU',
        'serial',
    ),
)
GROUPS = ('Monitor', 'History', 'Writes', 'System')


class Action(NamedTuple):
    """One dispatchable menu command: whether it opens hidraw and how it runs."""

    needs_device: bool
    runner: Callable


def _action_once(psu, args, cfg, monitor_state, engine):
    return _paged(monitor.run_once, psu, copy.copy(args), cfg, monitor_state, engine)


def _action_watch(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.watch = 1
    local.interval = None
    local.dashboard_text = False
    local.output = None
    return monitor.run_watch(psu, local, cfg, monitor_state, engine)


def _action_dashboard(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.watch = monitor.WATCH_FROM_CONFIG
    local.interval = 1.0
    local.dashboard_text = True
    local.output = None
    return monitor.run_dashboard_text(psu, local, cfg, monitor_state, engine)


def _action_export(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.export = True
    local.format = 'text'
    local.from_spec = '1h'
    local.columns = None
    local.output = None
    return _paged(monitor.run_export, local, cfg)


def _action_ocp(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.ocp = True
    local.format = 'text'
    return _paged(monitor.run_ocp, psu, local)


def _action_pins(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.pins = True
    local.format = 'text'
    local.output = None
    return _paged(monitor.run_pins, psu, local)


def _action_thresholds(psu, args, cfg, monitor_state, engine):
    # Read-only C0h dump; on a MEG this reports why the model does not answer
    # that register, exactly like the CLI does.
    local = copy.copy(args)
    local.dump_thresholds = True
    local.format = 'text'
    local.output = None
    return _paged(monitor.run_ocp_thresholds, psu, local)


def _action_log(psu, args, cfg, monitor_state, engine):
    _paged(lambda: monitor.emit(monitor.format_blackbox(psu.read_blackbox()), None))
    return monitor.EXIT_OK


def _action_config(psu, args, cfg, monitor_state, engine):
    _paged(lambda: monitor.emit(monitor._dump_effective_config(cfg, 'text'), None))
    return monitor.EXIT_OK


def _action_alerts(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.show_alert_log = True
    local.format = 'text'
    local.output = None
    return _paged(monitor.run_show_alert_log, local, cfg)


# ---- read-only variants -------------------------------------------------


def _action_once_json(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.format = 'json'
    return _paged(monitor.run_once, psu, local, cfg, monitor_state, engine)


def _action_once_prometheus(psu, args, cfg, monitor_state, engine):
    local = copy.copy(args)
    local.format = 'prometheus'
    return _paged(monitor.run_once, psu, local, cfg, monitor_state, engine)


def _action_watch_custom(psu, args, cfg, monitor_state, engine):
    raw = _ask('Refresh interval in seconds (e.g. 2): ')
    if raw is None:
        return _cancelled()
    try:
        interval = float(raw) if raw is not None else None
    except ValueError:
        interval = None
    if interval is None or not math.isfinite(interval) or interval <= 0:
        print('Error: the interval must be a positive number.')
        return monitor.EXIT_ERROR
    local = copy.copy(args)
    local.watch = interval
    local.interval = None
    local.dashboard_text = False
    local.output = None
    return monitor.run_watch(psu, local, cfg, monitor_state, engine)


def _action_dashboard_web(psu, args, cfg, monitor_state, engine):
    """Serve the browser page; reads history files, never touches hidraw."""
    local = copy.copy(args)
    local.port = local.port or cfg.get('port')
    return monitor.run_dashboard(local, cfg)


def _action_export_custom(psu, args, cfg, monitor_state, engine):
    window_raw = _ask('Window (e.g. 30m, 2h, 7d; empty = 1h): ')
    if window_raw is None:
        return _cancelled()
    columns_raw = _ask('Columns (e.g. cpu,gpu,temp; empty = all): ')
    if columns_raw is None:
        return _cancelled()
    local = copy.copy(args)
    local.export = True
    local.format = 'text'
    local.from_spec = window_raw or '1h'
    local.columns = columns_raw or None
    local.output = None
    return _paged(monitor.run_export, local, cfg)


# ---- control writes (parameter prompts + explicit confirmation) ---------


def _action_fan_auto(psu, args, cfg, monitor_state, engine):
    if not _confirm('Write fan mode auto/performance (41h + F1h)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.fan_mode = monitor.FAN_MODE_AUTO
    local.fan_duty = None
    return monitor.run_write_controls(psu, local)


def _action_fan_duty(psu, args, cfg, monitor_state, engine):
    raw = _ask('Fan duty in percent (0-100): ')
    if raw is None:
        return _cancelled()
    try:
        duty = int(raw)
    except ValueError:
        duty = -1
    if not 0 <= duty <= 100:
        print('Error: the duty must be an integer between 0 and 100.')
        return monitor.EXIT_ERROR
    if not _confirm(f'Write fan mode customized with duty {duty}% (41h + F1h)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.fan_mode = monitor.FAN_MODE_CUSTOMIZED
    local.fan_duty = duty
    return monitor.run_write_controls(psu, local)


def _action_zero_fan(psu, args, cfg, monitor_state, engine):
    raw = _ask('Zero Fan state (on/off): ')
    if raw is None:
        return _cancelled()
    raw = raw.lower()
    if raw not in ('on', 'off'):
        print('Error: choose on or off.')
        return monitor.EXIT_ERROR
    if not _confirm(f'Write Zero Fan {raw} (43h + F1h)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.zero_fan = raw
    return monitor.run_write_controls(psu, local)


def _action_buzzer(psu, args, cfg, monitor_state, engine):
    if not _confirm('Toggle the C2h buzzer switch (no read-back)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.buzzer_off = True
    return monitor.run_write_controls(psu, local)


def _action_rail(psu, args, cfg, monitor_state, engine):
    raw = _ask('Rail protection mode (multi/single): ')
    if raw is None:
        return _cancelled()
    raw = raw.lower()
    if raw not in (monitor.RAIL_MODE_MULTI, monitor.RAIL_MODE_SINGLE):
        print('Error: choose multi or single.')
        return monitor.EXIT_ERROR
    if not _confirm(f'Write rail mode {raw} (0xC0 + F1h, read-back verified)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.set_rail = raw
    return monitor.run_write_controls(psu, local)


def _action_ocp_write(psu, args, cfg, monitor_state, engine):
    raw = _ask('POINT_A,DIFF_A,TRIGGER_S,DIFF_TRIGGER_S,WARNING_S[,on|off]: ')
    if raw is None:
        return _cancelled()
    if not raw:
        print('Error: five values are required (see --help for the ranges).')
        return monitor.EXIT_ERROR
    try:
        parsed = monitor._ocp_setting(raw)
    except argparse.ArgumentTypeError as exc:
        print(f'Error: {exc}')
        return monitor.EXIT_ERROR
    if not _confirm('Write OCP thresholds (C0h + F1h, read-back verified)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.dump_thresholds = False
    local.ocp_set = parsed
    local.load_thresholds = None
    local.format = 'text'
    local.output = None
    return monitor.run_ocp_thresholds(psu, local)


def _action_ocp_load(psu, args, cfg, monitor_state, engine):
    path = _ask('JSON file with the thresholds (dump -f json output): ')
    if path is None:
        return _cancelled()
    if not path:
        print('Error: a file path is required.')
        return monitor.EXIT_ERROR
    if not _confirm(f'Write the thresholds from {path} (C0h + F1h, read-back verified)'):
        print('Cancelled.')
        return monitor.EXIT_OK
    local = copy.copy(args)
    local.dump_thresholds = False
    local.ocp_set = None
    local.load_thresholds = path
    local.format = 'text'
    local.output = None
    return monitor.run_ocp_thresholds(psu, local)


def _action_serial(psu, args, cfg, monitor_state, engine):
    """Set the serial filter used by later device actions in this session."""
    raw = _ask('PSU serial (empty = first attached PSU): ')
    if raw is None:
        return _cancelled()
    args.serial = raw or None
    print(f'Serial filter: {args.serial or "first attached PSU"}')
    return monitor.EXIT_OK


#: Action name -> spec.  Adding a menu command means one Item above, one
#: entry here and nothing else; the footer, the prompt range and the device
#: set are all derived.
ACTIONS = {
    'once': Action(needs_device=True, runner=_action_once),
    'once_json': Action(needs_device=True, runner=_action_once_json),
    'once_prometheus': Action(needs_device=True, runner=_action_once_prometheus),
    'watch': Action(needs_device=True, runner=_action_watch),
    'watch_custom': Action(needs_device=True, runner=_action_watch_custom),
    'dashboard': Action(needs_device=True, runner=_action_dashboard),
    'dashboard_web': Action(needs_device=False, runner=_action_dashboard_web),
    'export': Action(needs_device=False, runner=_action_export),
    'export_custom': Action(needs_device=False, runner=_action_export_custom),
    'ocp': Action(needs_device=True, runner=_action_ocp),
    'pins': Action(needs_device=True, runner=_action_pins),
    'thresholds': Action(needs_device=True, runner=_action_thresholds),
    'log': Action(needs_device=True, runner=_action_log),
    'alerts': Action(needs_device=False, runner=_action_alerts),
    'fan_auto': Action(needs_device=True, runner=_action_fan_auto),
    'fan_duty': Action(needs_device=True, runner=_action_fan_duty),
    'zero_fan': Action(needs_device=True, runner=_action_zero_fan),
    'buzzer': Action(needs_device=True, runner=_action_buzzer),
    'rail': Action(needs_device=True, runner=_action_rail),
    'ocp_write': Action(needs_device=True, runner=_action_ocp_write),
    'ocp_load': Action(needs_device=True, runner=_action_ocp_load),
    'config': Action(needs_device=False, runner=_action_config),
    'serial': Action(needs_device=False, runner=_action_serial),
}
_DEVICE_ACTIONS = frozenset(name for name, action in ACTIONS.items() if action.needs_device)


def _footer_text():
    """Key legend; the digit-jump range covers the single-key numbers only."""
    jump = min(len(ITEMS), 9)
    return f'Up/Down move   Enter run   1-{jump} jump   q/Esc quit   ? keys'


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
    _write(_CLEAR)


def _write(text):
    """Best-effort terminal write: a closed stdout must not kill the menu."""
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (OSError, UnicodeError):
        pass


def _alt_screen():
    """Alternate-screen buffer on real terminals, except the VGA console."""
    if not _is_tty(sys.stdout):
        return False
    return os.environ.get('TERM', '').strip().lower() not in _ALT_UNSUPPORTED_TERMS


def _size(fd=None):
    try:
        if fd is None:
            fd = sys.stdout.fileno()
        size = os.get_terminal_size(fd)
        return max(1, size.columns), max(1, size.lines)
    except (AttributeError, OSError, ValueError):
        return 80, 24


_SGR_RE = re.compile(r'\x1b\[[0-9;]*m')


def _display_width(text):
    """Visible terminal columns, honouring SGR-free wide/full-width glyphs.

    A CJK label or a warning pasted into a prompt counts two columns on real
    terminals; ``len()`` counts one, which shifts every following field. SGR
    sequences are removed first so an already-painted string can be measured.
    """
    stripped = _SGR_RE.sub('', text)
    return sum(2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1 for char in stripped)


def _pad(text, width):
    """Pad ``text`` to ``width`` visible columns with spaces."""
    return text + ' ' * max(0, width - _display_width(text))


def _truncate(text, width):
    """Cut to ``width`` columns, marking the cut so it is not read as data."""
    if width <= 0:
        return ''
    if _display_width(text) <= width:
        return text
    if width <= 2:
        return text[:width]
    # Leave two columns for the marker; CJK characters count two columns, so a
    # character-width loop would otherwise overflow the line.
    out = []
    seen = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
        if seen + char_width > width - 2:
            break
        out.append(char)
        seen += char_width
    return ''.join(out) + '..'


def _paint(text, code, enabled):
    return f'{code}{text}{_RESET}' if enabled else text


_ASCII_GLYPHS = {
    'tl': '+',
    'tr': '+',
    'bl': '+',
    'br': '+',
    'h': '-',
    'v': '|',
    'dot': '*',
}
_UNICODE_GLYPHS = {
    'tl': '╭',
    'tr': '╮',
    'bl': '╰',
    'br': '╯',
    'h': '─',
    'v': '│',
    'dot': '·',
}


def _glyphs():
    """Box glyphs that the terminal can actually encode.

    The Linux VGA console (``TERM=linux``) and a non-UTF-8 locale get ASCII:
    a UnicodeEncodeError while drawing the menu would otherwise kill it. The
    caller can also inject a fixed set in tests.
    """
    term = os.environ.get('TERM', '').strip().lower()
    encoding = (getattr(sys.stdout, 'encoding', '') or '').lower()
    if term == 'linux' or 'utf' not in encoding:
        return _ASCII_GLYPHS
    return _UNICODE_GLYPHS


def _line_for(item, width, selected, color):
    """One menu row, padded to exactly ``width`` visible columns.

    The command is a separate dim column: the fixed prefix (marker, number,
    label) keeps the eyes on the action name, while the exact command stays
    available for anyone who wants to type it manually.
    """
    marker = '>' if selected else ' '
    prefix = f'{marker} {item.number})'
    prefix_field = f'{prefix:<5}'
    label_width = min(15, max(8, width - _display_width(prefix_field) - 6))
    label_field = _pad(item.label, label_width)
    base = f'{prefix_field} {label_field}'
    command = _truncate(item.command, max(0, width - _display_width(base) - 1))
    plain = _pad(_truncate(f'{base} {command}', width), width)
    padding = ' ' * max(0, width - _display_width(plain))
    if selected:
        # Reverse video paints a full-width selection bar, including the
        # padding, so the cursor line is unmistakable even without colour.
        return _paint(plain + padding, _REVERSE, color)
    if not color:
        return plain + padding
    return (
        f'{_COLOR_NUMBER}{prefix_field}{_RESET} '
        f'{_COLOR_LABEL}{label_field}{_RESET} '
        f'{_COLOR_COMMAND}{command}{_RESET}{padding}'
    )


def _group_line(group, count, width, color, glyphs):
    """A group heading with item count and a subtle rule to the right."""
    label = f' {group}'
    meta = f' {glyphs["dot"]} {count} '
    rule = glyphs['h'] * max(0, width - _display_width(label) - _display_width(meta))
    if not color:
        return label + meta + rule
    return f'{_COLOR_GROUP}{label}{_RESET}{_DIM}{meta}{_RESET}{_COLOR_BORDER}{rule}{_RESET}'


def _body_lines(items, selected, width, color, glyphs):
    """Return (lines, index of the selected line) with group headings."""
    counts = {group: 0 for group in GROUPS}
    for item in items:
        counts[item.group] = counts.get(item.group, 0) + 1
    lines = []
    selected_line = 0
    for group in GROUPS:
        lines.append(_group_line(group, counts[group], width, color, glyphs))
        for item in items:
            if item.group != group:
                continue
            if item is items[selected]:
                selected_line = len(lines)
            lines.append(_line_for(item, width, item is items[selected], color))
        lines.append(' ' * width)
    return lines, selected_line


def _border_top(inner, title, right, color, glyphs, right_color=None):
    """Top border with a title on the left and version/status on the right."""
    available = inner - 2
    title_text = f' {title} '
    right_text = f' {right} ' if right else ''
    max_right = max(0, available - 2 - _display_width(title_text))
    right_text = _truncate(right_text, max_right)
    fill = max(
        0,
        available - 2 - _display_width(title_text) - _display_width(right_text),
    )
    rule = glyphs['h'] * fill
    if not color:
        return (
            glyphs['tl'] + glyphs['h'] + title_text + rule + right_text + glyphs['h'] + glyphs['tr']
        )
    return (
        f'{_COLOR_BORDER}{glyphs["tl"]}{glyphs["h"]}{_RESET}'
        f'{_COLOR_TITLE}{title_text}{_RESET}'
        f'{_COLOR_BORDER}{rule}{_RESET}'
        f'{right_color or _COLOR_DETAIL}{right_text}{_RESET}'
        f'{_COLOR_BORDER}{glyphs["h"]}{glyphs["tr"]}{_RESET}'
    )


def _box_line(content, glyphs, color):
    if color:
        return (
            f'{_COLOR_BORDER}{glyphs["v"]}{_RESET} {content} {_COLOR_BORDER}{glyphs["v"]}{_RESET}'
        )
    return f'{glyphs["v"]} {content} {glyphs["v"]}'


def render_menu(
    items,
    selected,
    offset,
    width,
    height,
    *,
    color=True,
    help_mode=False,
    status=None,
    glyphs=None,
):
    """Pure renderer: returns (frame, new_offset) for tests and the loop."""
    inner = max(MIN_WIDTH, min(width, 100))
    glyphs = glyphs or _glyphs()
    content_width = max(1, inner - 4)
    body, selected_line = _body_lines(items, selected, content_width, color, glyphs)

    available = max(1, height - 4)  # top border, bottom border, detail, footer
    offset = max(0, min(offset, max(0, len(body) - available)))
    if selected_line < offset:
        offset = selected_line
    elif selected_line >= offset + available:
        offset = selected_line - available + 1
    window = body[offset : offset + available]
    item = items[selected]

    if status:
        right = f'last: {status}'
        if status.endswith(' ok'):
            right_color = _COLOR_OK
        elif ' exit ' in status:
            right_color = _COLOR_ERROR
        elif status.endswith(' stopped'):
            right_color = _COLOR_WARN
        else:
            right_color = _COLOR_DETAIL
    else:
        version = getattr(monitor, '__version__', '')
        right = f'v{version}' if version else ''
        right_color = _COLOR_DETAIL

    frame = [_border_top(inner, 'MSI PSU Monitor', right, color, glyphs, right_color)]
    frame.extend(_box_line(line, glyphs, color) for line in window)
    frame.append(
        _paint(
            glyphs['bl'] + glyphs['h'] * (inner - 2) + glyphs['br'],
            _COLOR_BORDER,
            color,
        )
    )

    if help_mode:
        # The detail slot is the most readable place for the key legend; the
        # footer keeps its usual shape so the frame height never changes.
        detail = ' ' + _truncate(_footer_text(), inner - 1)
        footer = ' ' + _truncate('Esc or ? returns to the list', inner - 1)
    else:
        detail = ' ' + _truncate(f'{item.label}: {item.purpose}', inner - 1)
        footer = ' ' + _truncate(_footer_text(), inner - 1)
    # Pad the two free-standing lines too, so every visual row has the same
    # width as the card even when the terminal has no background colour.
    frame.append(_paint(_pad(detail, inner), _COLOR_DETAIL, color))
    frame.append(_paint(_pad(footer, inner), _COLOR_FOOTER, color))
    return '\n'.join(frame), offset


#: Complete escape sequences; reading stops as soon as one matches so a key
#: pressed immediately after an arrow is not swallowed into the same read.
#: The ``ESC O`` forms arrive when a terminal is left in application cursor
#: mode (tmux/vim leftovers); both spellings are accepted instead of flipping
#: the terminal into smkx, which would also switch the numpad into
#: application mode and break the digit jump.
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
        b'\x1bOA',
        b'\x1bOB',
        b'\x1bOC',
        b'\x1bOD',
        b'\x1bOH',
        b'\x1bOF',
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
        b'\x1bOA': 'up',
        b'\x1bOB': 'down',
        b'\x1bOC': None,
        b'\x1bOD': None,
        b'\x1bOH': 'home',
        b'\x1bOF': 'end',
        b'\x1b': 'escape',
        b'\x1b\x1b': 'escape',
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
            # next key (e.g. the q that follows an arrow) and lost it.  A lone
            # ESC that sees no follow-up byte within the window is the Esc key.
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


def _ask(prompt):
    """Read one line for a parameter prompt; None on EOF / Ctrl-C."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _confirm(label):
    """Explicit yes/no before a PSU write; anything but 'y' cancels."""
    answer = _ask(f'{label}? [y/N] ')
    return bool(answer) and answer.lower() in ('y', 'yes')


def _cancelled():
    """EOF/Ctrl-C at a parameter prompt is a cancellation, not an error."""
    print('Cancelled.')
    return monitor.EXIT_OK


def _run(action, psu, args, cfg, monitor_state, engine):
    spec = ACTIONS.get(action)
    if spec is None:
        raise AssertionError(f'unknown menu action: {action}')
    return spec.runner(psu, args, cfg, monitor_state, engine)


def _line_show():
    """Fallback/piped menu: the same order and grouping as the card."""
    width = 62
    print()
    print(' MSI PSU Monitor - menu')
    print(' ' + '-' * width)
    counts = {}
    for item in ITEMS:
        counts[item.group] = counts.get(item.group, 0) + 1
    current = None
    for item in ITEMS:
        if item.group != current:
            current = item.group
            print(f' {current} ({counts[current]})')
        print(f'   {item.number:>2})  {item.label:<15} {item.command}')
        print(f'        -> {item.purpose}')
    print()
    print(' 0) quit   ?=menu   h/help=menu')
    print(' ' + '-' * width)


def _line_prompt():
    return f'[1-{len(ITEMS)}, ?=menu, 0=quit] choice: '


def _sanitize_input(text):
    """Make raw terminal input safe to echo in an error message.

    A control character or escape sequence typed into the numbered prompt must
    not be printed back as a terminal command; '?' keeps the message readable
    without inventing content.
    """
    return ''.join(
        char if ord(char) >= 0x20 and unicodedata.category(char) != 'Cc' else '?' for char in text
    )


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
            # The factory (device discovery) has already printed the precise
            # reason; repeating a generic error here only doubles the noise.
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
            safe = _sanitize_input(choice)
            print(f'invalid choice: {safe} (valid 1-{len(ITEMS)}, 0=quit, ?=menu)')
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


def _action_status(item, code):
    """One-line result for the header; 'stopped' marks a Ctrl-C exit."""
    if code == 'interrupted':
        return f'{item.label} stopped'
    if code in (None, monitor.EXIT_OK):
        return f'{item.label} ok'
    return f'{item.label} exit {code}'


def _interactive_menu(psu, args, cfg, monitor_state, engine, psu_factory=None):
    fd = sys.stdin.fileno()
    selected = 0
    offset = 0
    help_mode = False
    status: Optional[str] = None
    color = termdash.colour_enabled(sys.stdout)
    alt = _alt_screen()
    alt_active = False
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
        _write('\x1b[?25l')
        cursor_hidden = True
        if alt:
            _write(_ALT_ENTER)
            alt_active = True
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
                    ITEMS,
                    selected,
                    offset,
                    width,
                    height,
                    color=color,
                    help_mode=help_mode,
                    status=status,
                )
                _clear()
                _write(frame + '\n')
                dirty = False
            key = _read_key(fd)
            if key is None:
                # A select() timeout only exists to notice a resize; without a
                # state change there is nothing to redraw (redrawing on every
                # timeout made the screen flash several times a second).
                continue
            if key == 'quit':
                return monitor.EXIT_OK
            if key == 'escape':
                # Esc closes the help overlay first; on the list it quits, the
                # way dialog/whiptail treat Esc as cancel.
                if help_mode:
                    help_mode = False
                    dirty = True
                    continue
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
            old_tty = None
            try:
                # Action output lands on the normal screen and survives the
                # menu, so leave the alternate buffer for the duration.
                if alt_active:
                    _write(_ALT_EXIT)
                    alt_active = False
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
                    status = _action_status(item, 'interrupted')
                else:
                    status = _action_status(item, code)
                if code not in (None, monitor.EXIT_OK):
                    print(f'exit={code}')
                    _pause()
            finally:
                old_tty = _cbreak(fd)
                if alt:
                    _write(_ALT_ENTER)
                    alt_active = True
            dirty = True
            help_mode = False
    finally:
        if old_tty is not None:
            _restore_tty(fd, old_tty)
        monitor._watch_restore_signals(signals)
        if cursor_hidden:
            _write('\x1b[?25h')
        if alt_active:
            _write(_ALT_EXIT)


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
