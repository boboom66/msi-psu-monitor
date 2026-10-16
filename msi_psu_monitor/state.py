"""Persistent cumulative statistics for msi-psu-monitor (stdlib only).

Whoever currently holds the PSU (a one-shot CLI read, ``--watch`` or the
daemon) feeds every valid sample into the running totals. Totals are written
to disk so a restart does not reset the averages or the energy counter
(REQ-7/REQ-8).

State directory: ``/var/lib/msi-psu-monitor`` when writable, otherwise
``$XDG_STATE_HOME/msi-psu-monitor`` (or ``~/.local/state/msi-psu-monitor``).
``MSI_PSU_STATE_DIR`` overrides both (used by the tests).

Files:
    state.json          cumulative counters, atomically replaced
    daily-YYYYMMDD.log  one CSV sample per minute, append-only, 30-day retention
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path

STATE_VERSION = 1
DEFAULT_STATE_DIR = Path('/var/lib/msi-psu-monitor')
RETENTION_DAYS = 30
# Longer gaps mean the machine slept or the service was down; integrating them
# would invent energy that was never drawn, so they only advance the clock.
MAX_SAMPLE_GAP_S = 300.0

STATE_FILENAME = 'state.json'
HISTORY_PREFIX = 'daily-'
HISTORY_SUFFIX = '.log'

# CSV columns of a history line (the --export view renames some of them).
# ``cpu_w``/``gpu_w`` are empty on single-rail models, which is what makes the
# export render them as N/A.
HISTORY_COLUMNS = (
    'time',
    '12v',
    '5v',
    '3v3',
    'total_a',
    'temp',
    'fan',
    'power',
    'eff',
    'cpu_w',
    'gpu_w',
)

# --columns tokens, in canonical (report) order. ``all`` expands to all of them.
COLUMN_CPU = 'cpu'
COLUMN_GPU = 'gpu'
EXPORT_COLUMNS = ('cpu', 'gpu', '12v', '5v', '3v3', 'temp', 'fan', 'eff')
# CPU/GPU wattage needs the discrete 12V rails that only the multi-rail MEG
# models report, so single-rail models record them as N/A (REQ-9).
NOT_AVAILABLE = 'N/A'
# Rail selection behind CPU/GPU wattage, straight from the MSI Center dashboard:
# CPU = 12V2, GPU = 12V3+12V4+12V5 (UC_Dashboard_Page.xaml.cs:203-204).
CPU_RAIL_INDEX = 1
GPU_RAIL_INDEXES = (2, 3, 4)
REQUIRED_RAILS = max(GPU_RAIL_INDEXES) + 1

_UNIT_SECONDS = {'m': 60.0, 'h': 3600.0, 'd': 86400.0}
_FROM_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*([mhd])$', re.IGNORECASE)


def default_state_dir():
    """Return the directory used for state.json and daily-*.log."""
    override = os.environ.get('MSI_PSU_STATE_DIR')
    if override:
        return Path(override)
    if os.access(DEFAULT_STATE_DIR, os.W_OK) or (
        not DEFAULT_STATE_DIR.exists() and os.access(DEFAULT_STATE_DIR.parent, os.W_OK)
    ):
        return DEFAULT_STATE_DIR
    xdg = os.environ.get('XDG_STATE_HOME') or os.path.join(
        os.path.expanduser('~'), '.local', 'state'
    )
    return Path(xdg) / 'msi-psu-monitor'


def state_path(state_dir):
    return Path(state_dir) / STATE_FILENAME


def history_path(state_dir, day=None):
    day = day or date.today()
    return Path(state_dir) / f'{HISTORY_PREFIX}{day.strftime("%Y%m%d")}{HISTORY_SUFFIX}'


class MonitorState:
    """Cumulative averages and energy totals, with atomic persistence."""

    def __init__(
        self,
        count=0,
        watt_sum=0.0,
        efficiency_sum=0.0,
        energy_wh=0.0,
        last_ts=None,
        daily=None,
        product='',
        serial='',
    ):
        self.count = int(count)
        self.watt_sum = float(watt_sum)
        self.efficiency_sum = float(efficiency_sum)
        self.energy_wh = float(energy_wh)
        self.last_ts = None if last_ts is None else float(last_ts)
        self.daily = dict(daily or {})
        self.product = str(product or '')
        self.serial = str(serial or '')

    # ---- derived values -------------------------------------------------

    @property
    def power_avg(self):
        """Cumulative mean output power in watts (0.0 before the first sample)."""
        return self.watt_sum / self.count if self.count else 0.0

    @property
    def efficiency_avg(self):
        """Cumulative mean efficiency in percent (0.0 before the first sample)."""
        return self.efficiency_sum / self.count if self.count else 0.0

    @property
    def total_energy_kwh(self):
        return self.energy_wh / 1000.0

    # ---- accumulation ---------------------------------------------------

    def update(self, watts, efficiency, ts=None, max_gap_s=MAX_SAMPLE_GAP_S):
        """Fold one valid sample into the totals; return the energy delta in Wh.

        Energy uses the frozen integral ``wh += watts * dt / 3600``. The first
        sample after load only starts the clock; gaps longer than
        ``max_gap_s`` are not integrated (see MAX_SAMPLE_GAP_S).
        """
        ts = time.time() if ts is None else float(ts)
        watts = float(watts)
        delta_wh = 0.0
        if self.last_ts is not None:
            dt = ts - self.last_ts
            if 0.0 < dt <= max_gap_s:
                delta_wh = watts * dt / 3600.0
                self.energy_wh += delta_wh
                key = date.fromtimestamp(ts).isoformat()
                self.daily[key] = self.daily.get(key, 0.0) + delta_wh / 1000.0
        self.last_ts = ts
        self.count += 1
        self.watt_sum += watts
        self.efficiency_sum += float(efficiency)
        return delta_wh

    def note_identity(self, sensors):
        """Remember the model/serial so exports and the dashboard can show them."""
        product = sensors.get('product')
        serial = sensors.get('serial')
        if product:
            self.product = str(product)
        if serial:
            self.serial = str(serial)

    def prune(self, today=None, days=RETENTION_DAYS):
        """Drop daily buckets older than ``days`` (default 30, REQ-8)."""
        today = today or date.today()
        cutoff = today.toordinal() - days
        dropped = []
        for key in list(self.daily):
            try:
                ordinal = date.fromisoformat(key).toordinal()
            except ValueError:
                dropped.append(key)
                continue
            if ordinal < cutoff:
                dropped.append(key)
        for key in dropped:
            del self.daily[key]
        return dropped

    # ---- serialisation --------------------------------------------------

    def to_dict(self):
        return {
            'version': STATE_VERSION,
            'count': self.count,
            'watt_sum': self.watt_sum,
            'efficiency_sum': self.efficiency_sum,
            'energy_wh': self.energy_wh,
            'last_ts': self.last_ts,
            'daily': dict(sorted(self.daily.items())),
            'product': self.product,
            'serial': self.serial,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get('version') != STATE_VERSION:
            return cls()
        daily = data.get('daily')
        return cls(
            count=data.get('count', 0) or 0,
            watt_sum=data.get('watt_sum', 0.0) or 0.0,
            efficiency_sum=data.get('efficiency_sum', 0.0) or 0.0,
            energy_wh=data.get('energy_wh', 0.0) or 0.0,
            last_ts=data.get('last_ts'),
            daily=daily if isinstance(daily, dict) else {},
            product=data.get('product', '') or '',
            serial=data.get('serial', '') or '',
        )

    @classmethod
    def load(cls, path):
        """Load state from ``path``; a missing/corrupt file yields empty state."""
        try:
            raw = Path(path).read_text()
        except OSError:
            return cls()
        try:
            data = json.loads(raw)
        except ValueError:
            return cls()
        return cls.from_dict(data)

    def save(self, path):
        """Atomically replace ``path`` (``.tmp`` + ``os.replace``)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + '\n')
        os.replace(tmp, path)


# ---- history (daily-*.log) ---------------------------------------------


def append_history(state_dir, sensors, ts=None):
    """Append one CSV sample line to today's history file; return its path."""
    ts = time.time() if ts is None else float(ts)
    path = history_path(state_dir, date.fromtimestamp(ts))
    path.parent.mkdir(parents=True, exist_ok=True)
    row = _history_row(sensors, ts)
    is_new = not path.exists()
    with path.open('a', newline='') as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(HISTORY_COLUMNS)
        writer.writerow(row)
    return path


def rail_watts(sensors):
    """Return ``(cpu_watts, gpu_watts)`` for a multi-rail PSU, else ``None``.

    MSI Center derives both figures from the discrete 12V rails of the
    Ai1000P/Ai1300P (CPU = 12V2, GPU = 12V3+12V4+12V5). Single-rail models
    report no per-rail data at all, which the export shows as N/A.
    """
    voltages = reading(sensors, 'vout_12v_rails')
    currents = reading(sensors, 'iout_12v_rails')
    if not isinstance(voltages, list) or not isinstance(currents, list):
        return None
    if len(voltages) < REQUIRED_RAILS or len(currents) < REQUIRED_RAILS:
        return None
    cpu = voltages[CPU_RAIL_INDEX] * currents[CPU_RAIL_INDEX]
    gpu = sum(voltages[i] * currents[i] for i in GPU_RAIL_INDEXES)
    return round(cpu, 1), round(gpu, 1)


def reading(sensors, key):
    """Return the value of a sensors entry, unwrapping ``(value, unit)``."""
    value = sensors.get(key)
    if isinstance(value, tuple):
        return value[0]
    return value


def _history_row(sensors, ts):
    def fmt(key, digits, default=''):
        value = reading(sensors, key)
        return default if value is None else f'{float(value):.{digits}f}'

    watts = rail_watts(sensors)
    cpu_w = '' if watts is None else f'{watts[0]:.1f}'
    gpu_w = '' if watts is None else f'{watts[1]:.1f}'

    return (
        datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S'),
        fmt('vout_12v', 3),
        fmt('vout_5v', 3),
        fmt('vout_3v3', 3),
        fmt('iout_12v_total', 3),
        fmt('temp', 1),
        fmt('fan_rpm', 0),
        fmt('power_total', 1),
        fmt('efficiency', 2),
        cpu_w,
        gpu_w,
    )


def iter_history(state_dir, since_ts=None):
    """Yield history rows as dicts, newest files last, honouring ``since_ts``."""
    for path in sorted(Path(state_dir).glob(f'{HISTORY_PREFIX}*{HISTORY_SUFFIX}')):
        try:
            with path.open(newline='') as handle:
                for row in csv.DictReader(handle):
                    if since_ts is not None:
                        stamp = _parse_timestamp(row.get('time'))
                        if stamp is None or stamp < since_ts:
                            continue
                    yield row
        except OSError:
            continue


def _parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def prune_history(state_dir, today=None, days=RETENTION_DAYS):
    """Delete daily-*.log files older than ``days``; return the removed paths."""
    today = today or date.today()
    cutoff = today.toordinal() - days
    removed = []
    for path in sorted(Path(state_dir).glob(f'{HISTORY_PREFIX}*{HISTORY_SUFFIX}')):
        stamp = path.stem[len(HISTORY_PREFIX) :]
        try:
            ordinal = datetime.strptime(stamp, '%Y%m%d').date().toordinal()
        except ValueError:
            continue
        if ordinal < cutoff:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                continue
    return removed


# ---- --from / --columns parsing ----------------------------------------


def parse_from(spec):
    """Parse a ``--from`` window such as ``30m``/``2h``/``7d`` into seconds."""
    if not spec:
        raise ValueError('--from requires a window such as 30m, 2h or 7d')
    match = _FROM_RE.match(spec.strip())
    if not match:
        raise ValueError(f'invalid --from value {spec!r}: expected e.g. 30m, 2h, 7d')
    return float(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]


def parse_columns(spec):
    """Parse ``--columns`` into canonical order; ``all``/None selects everything."""
    if spec is None or not spec.strip():
        return list(EXPORT_COLUMNS)
    selected = []
    for token in spec.split(','):
        token = token.strip().lower()
        if not token:
            continue
        if token == 'all':
            return list(EXPORT_COLUMNS)
        if token not in EXPORT_COLUMNS:
            raise ValueError(
                f'invalid --columns value {token!r}: choose from '
                f'{", ".join(("all",) + EXPORT_COLUMNS)}'
            )
        if token not in selected:
            selected.append(token)
    if not selected:
        raise ValueError('--columns needs at least one column name')
    return [name for name in EXPORT_COLUMNS if name in selected]


def build_export(state_dir, since_ts, columns):
    """Return ``(header, rows)`` for ``--export`` over the history files."""
    columns = list(columns)
    header = ['time'] + columns
    rows = []
    for row in iter_history(state_dir, since_ts=since_ts):
        out = [row.get('time', '')]
        for name in columns:
            if name == COLUMN_CPU:
                out.append(row.get('cpu_w') or NOT_AVAILABLE)
            elif name == COLUMN_GPU:
                out.append(row.get('gpu_w') or NOT_AVAILABLE)
            else:
                out.append(row.get(name, ''))
        rows.append(out)
    return header, rows
