"""Colour text dashboard for a terminal without a browser.

The Linux text console cannot render the HTML dashboard: it has no browser and
no JavaScript engine.  This module draws the same information directly with
ANSI colours and block characters, so ``msi-psu-monitor --dashboard-text`` works
on a headless server with nothing installed beyond Python.

Only width-based bars are used, never height-graded block elements: the VGA
console font maps every "lower block" glyph to a full block, so a sparkline made
of ``▁▂▃`` collapses into one solid line there.  Wide bars and colours survive
any font.

No third-party imports; colours are plain SGR sequences and disappear when
``NO_COLOR`` is set or stdout is not a terminal.
"""

import os
import time

RESET = '\x1b[0m'
BOLD = '\x1b[1m'
DIM = '\x1b[2m'
RED = '\x1b[31m'
GREEN = '\x1b[32m'
YELLOW = '\x1b[33m'
CYAN = '\x1b[36m'
REVERSE = '\x1b[7m'

#: (low, high) used to scale a bar when the row has no useful history yet.
_SCALES = {
    'vout_12v': (11.4, 12.6),
    'vout_5v': (4.75, 5.25),
    'vout_3v3': (3.14, 3.47),
    'power_total': (0.0, 1600.0),
    'efficiency': (80.0, 96.0),
    'temp': (20.0, 90.0),
    'fan_rpm': (0.0, 2500.0),
}

#: row order for the value block: (sensors key, label, unit, digits)
_ROWS = (
    ('vout_12v', '+12V', 'V', 3),
    ('vout_5v', '+5V', 'V', 3),
    ('vout_3v3', '+3.3V', 'V', 3),
    ('power_total', 'POWER', 'W', 1),
    ('efficiency', 'EFF', '%', 2),
    ('temp', 'TEMP', 'C', 1),
    ('fan_rpm', 'FAN', 'RPM', 0),
)

_HISTORY_KEYS = {
    'vout_12v': '12v',
    'vout_5v': '5v',
    'vout_3v3': '3v3',
    'power_total': 'power',
    'efficiency': 'eff',
    'temp': 'temp',
    'fan_rpm': 'fan',
}


def colour_enabled(stream, env=None):
    """Respect NO_COLOR and only colourise a real terminal."""
    env = os.environ if env is None else env
    if env.get('NO_COLOR'):
        return False
    if env.get('TERM', '').strip().lower() == 'dumb':
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _paint(text, code, enabled):
    return f'{code}{text}{RESET}' if enabled else text


def _reading(sensors, key):
    value = sensors.get(key)
    if isinstance(value, tuple) and len(value) == 2:
        try:
            return float(value[0]), str(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _history_values(history, key):
    column = _HISTORY_KEYS.get(key)
    if column is None:
        return []
    values = []
    for row in history:
        raw = row.get(column, '')
        if raw in ('', 'N/A'):
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def _bar(value, low, high, width, code, enabled, ascii_only=False):
    if width <= 0:
        return ''
    if high <= low:
        high = low + 1.0
    ratio = max(0.0, min(1.0, (value - low) / (high - low)))
    filled = int(round(ratio * width))
    filled = max(0, min(width, filled))
    if ascii_only:
        return _paint('#' * filled, code, enabled) + '-' * (width - filled)
    return _paint('█' * filled, code, enabled) + '░' * (width - filled)


def _voltage_colour(value):
    nominal = {12.0: 12.0, 5.0: 5.0, 3.3: 3.3}
    # The nominal is the closest standard rail; the tolerance gates mirror a
    # PSU's own ATX window rather than pretending to be a lab instrument.
    closest = min(nominal, key=lambda rail: abs(value - rail))
    deviation = abs(value - closest) / closest
    if deviation <= 0.03:
        return GREEN
    if deviation <= 0.05:
        return YELLOW
    return RED


def _row_colour(key, value):
    if key.startswith('vout_'):
        return _voltage_colour(value)
    if key == 'temp':
        return GREEN if value < 70 else (YELLOW if value < 85 else RED)
    if key == 'efficiency':
        return GREEN if value >= 90 else (YELLOW if value >= 85 else RED)
    return GREEN


def _pin_colour(value):
    if value >= 10.0:
        return RED
    if value >= 8.0:
        return YELLOW
    return GREEN


def _range_text(values, unit, digits):
    if not values:
        return ''
    return f'min {min(values):.{digits}f} max {max(values):.{digits}f}'


def _status_colour(status):
    normal = (status or '').strip().lower()
    if normal == 'normal':
        return GREEN
    if normal in ('', 'unknown'):
        return YELLOW
    return RED


def _box(lines, width, enabled, ascii_only):
    """Frame ``lines`` with a box; every line is padded to the same width."""
    inner = max(20, width - 2)
    if ascii_only:
        top = '+' + '-' * inner + '+'
        bottom = top
        side = '|'
    else:
        top = '┌' + '─' * inner + '┐'
        bottom = '└' + '─' * inner + '┘'
        side = '│'
    out = [_paint(top, DIM, enabled)]
    for line in lines:
        visible = line
        pad = inner - len(visible)
        out.append(
            _paint(side, DIM, enabled) + visible + ' ' * max(0, pad) + _paint(side, DIM, enabled)
        )
    out.append(_paint(bottom, DIM, enabled))
    return out


def render(
    sensors,
    history=(),
    *,
    width=80,
    height=24,
    interval=1.0,
    color=True,
    ascii_only=False,
    now=None,
):
    """Return the dashboard frame as a string (no screen control sequences)."""
    now = time.time() if now is None else now
    stamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
    product = str(sensors.get('product', 'unknown'))
    serial = str(sensors.get('serial', ''))
    inner = max(20, min(width, 100) - 2)

    header = f' {_paint("MSI PSU Monitor", BOLD, color)}  {product}  {serial}'
    header = header[:inner]
    sub = f' {stamp}   refresh {interval:g}s   Ctrl-C to stop'

    lines = [header, sub, '']

    bar_width = max(0, min(24, inner - 46))
    for key, label, unit, digits in _ROWS:
        reading = _reading(sensors, key)
        if reading is None:
            continue
        value, _ = reading
        code = _row_colour(key, value)
        value_text = f'{value:9.{digits}f} {unit}'
        colour_value = _paint(value_text, code, color)
        low, high = _SCALES[key]
        history_values = _history_values(history, key)
        if history_values:
            # Let observed values drive the bar; keep a minimum span so a
            # perfectly flat rail still shows a sensible half-full bar.
            low = min(low, min(history_values))
            high = max(high, max(history_values))
        bar = _bar(value, low, high, bar_width, code, color, ascii_only)
        range_text = _range_text(history_values, unit, digits)
        lines.append(f' {label:7s}{colour_value}  {bar}  {range_text}'.rstrip())

    if 'iout_pins' in sensors:
        pins, _unit = sensors['iout_pins']
        lines.append('')
        for offset, label in ((0, 'Conn1'), (6, 'Conn2')):
            chunk = pins[offset : offset + 6]
            cells = []
            for index, current in enumerate(chunk, start=1):
                cell = f'P{index} {current:5.2f}'
                cells.append(_paint(cell, _pin_colour(current), color))
            lines.append(f' {label:6s} ' + '  '.join(cells))

    status = sensors.get('status')
    if status:
        lines.append('')
        lines.append(f' 12V-2x6 Status: {_paint(str(status), _status_colour(status), color)}')
    alerts = sensors.get('threshold_alerts') or []
    if alerts:
        lines.append(f' Alerts        : {_paint(", ".join(str(a) for a in alerts), RED, color)}')

    # Fit the window: drop the least important blocks first instead of letting
    # the terminal scroll a header away on every refresh.
    budget = max(6, height - 2)
    while len(lines) > budget:
        for index in range(len(lines) - 1, 2, -1):
            if lines[index] == '':
                del lines[index]
                break
        else:
            lines.pop()

    return '\n'.join(_box(lines, min(width, 100), color, ascii_only))


def ascii_only_default(env=None):
    """The VGA console has no height-graded blocks; prefer ASCII there."""
    env = os.environ if env is None else env
    return env.get('TERM', '').strip().lower() == 'linux'
