#!/usr/bin/env python3
"""MSI PSU Monitor - CLI tool for reading sensors from MSI PSUs via USB HID.

Supports MSI MPG Ai1600TS / MPG Ai1300TS (GPU Safeguard+ per-pin current
monitoring), MEG Ai1600(T), MEG Ai1300P and MEG Ai1000P power supplies.

Usage:
    msi-psu-monitor --once                    # one-shot sensor read (default)
    msi-psu-monitor --watch 1                 # refresh every second
    msi-psu-monitor --format json             # machine-readable output
    msi-psu-monitor -f prometheus -O /var/lib/node_exporter/msi-psu.prom
    msi-psu-monitor --show-log                # GPU Safeguard+ black box
    msi-psu-monitor --ocp                      # 12V-2x6 OCP thresholds + state
    msi-psu-monitor --fan-mode customized --fan-duty 80
    msi-psu-monitor --export --from 2h --columns temp,fan,eff -O psu.csv
    msi-psu-monitor --dashboard               # local charts in a browser
"""

import argparse
import csv
import json
import logging
import math
import os
import sys
import time

from msi_psu_monitor import __version__
from msi_psu_monitor import demo
from msi_psu_monitor import state as stats
from msi_psu_monitor.alerts import (
    CONNECTOR_ALERTS,
    CONNECTOR_LIMIT_KEY,
    IMBALANCE_ALERT,
    PIN_IMBALANCE_THRESHOLD_A,
    PIN_OCP_THRESHOLD_A,
    THRESHOLD_ALERT_NAMES,
    THRESHOLD_SOURCES,
    AlertEngine,
    configured_threshold_names,
    describe,
    evaluate_pin_alerts,
    evaluate_threshold_alerts,
    format_alert_line,
)
from msi_psu_monitor.config import (
    KNOWN_OPTIONS,
    ConfigError,
    load_config,
    threshold_limits,
)
from msi_psu_monitor.protocol import MSIPSU, DeviceBusyError, HIDDevice, detect_device

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALERT = 2

FAN_MODE_AUTO = 'auto'
# MSI Center's PCIE5 Cooling Wizard calls the PSU's own curve "Performance";
# accept that spelling as an alias for the same byte (1), never a second mode.
FAN_MODE_PERFORMANCE = 'performance'
FAN_MODE_CUSTOMIZED = 'customized'
RAIL_MODE_MULTI = 'multi'
RAIL_MODE_SINGLE = 'single'
#: `--watch` without a number: take [monitor] interval from the config file.
WATCH_FROM_CONFIG = 'config'
_FAN_MODE_TO_BYTE = {
    FAN_MODE_AUTO: 1,
    FAN_MODE_PERFORMANCE: 1,
    FAN_MODE_CUSTOMIZED: 3,
}
_FAN_BYTE_TO_MODE = {1: FAN_MODE_AUTO, 3: FAN_MODE_CUSTOMIZED}

STATUS_NORMAL = 'Normal'
STATUS_UNKNOWN = 'Unknown'

STREAM_FORMATS = ('text', 'json', 'prometheus')

logger = logging.getLogger('msi_psu')


def setup_logging(verbose=False, quiet=False):
    """Route diagnostics to stderr; stdout stays clean for machine output."""
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)


# ---- output formatters --------------------------------------------------


def _format_duration(total_seconds):
    total_seconds = int(total_seconds)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return f'{days}d {hours:02d}:{minutes:02d}:{seconds:02d}'


def _value(reading):
    """Unwrap a ``(value, unit)`` reading (or pass a scalar through)."""
    if isinstance(reading, tuple):
        return reading[0]
    return reading


def _reading_line(label, value, unit, digits, avg_reading=None, avg_digits=None):
    line = f'  {label:8s}: {value:8.{digits}f} {unit}'
    avg = _value(avg_reading)
    if avg is not None:
        avg_digits = digits if avg_digits is None else avg_digits
        line += f'   (AVG {avg:.{avg_digits}f} {unit})'
    return line


def format_text(sensors):
    """Format sensor data as human-readable text."""
    lines = []
    lines.append(f'MSI PSU: {sensors.get("product", "unknown")}')
    lines.append(f'  Vendor: {sensors.get("vendor", "")}')
    lines.append(f'  FW: {sensors.get("fw_revision", "")}  Serial: {sensors.get("serial", "")}')
    lines.append('')

    reason = sensors.get('error') or sensors.get('payload_error')
    if reason:
        lines.append(f'  ERROR   : {reason}')
        return '\n'.join(lines)

    for key, label in _VOLTAGE_LABELS.items():
        if key in sensors:
            value, unit = sensors[key]
            lines.append(f'  {label:8s}: {value:8.3f} {unit}')

    for key, label in _CURRENT_LABELS.items():
        if key in sensors:
            value, unit = sensors[key]
            lines.append(f'  {label:8s}: {value:8.3f} {unit}')

    if 'iout_12v_rails' in sensors:
        rails, unit = sensors['iout_12v_rails']
        voltages = stats.reading(sensors, 'vout_12v_rails') or []
        lines.append('  Per-rail 12V:')
        for index, rail_value in enumerate(rails):
            volts = voltages[index] if index < len(voltages) else None
            prefix = f'    12V{index + 1}'
            if volts is None:
                lines.append(f'{prefix}: {rail_value:8.3f} {unit}')
            else:
                lines.append(f'{prefix}: {volts:8.3f} V {rail_value:8.3f} {unit}')
        watts = stats.rail_watts(sensors)
        if watts is not None:
            for label, value in zip(('CPU', 'GPU'), watts):
                lines.append(f'  {label:8s}: {value:8.1f} W')

    if 'iout_pins' in sensors:
        pins, unit = sensors['iout_pins']
        lines.append('  Per-pin currents (12V-2x6 GPU Safeguard+):')
        for index, pin_value in enumerate(pins):
            conn = 1 if index < 6 else 2
            pin = index % 6 + 1
            lines.append(f'    Conn{conn} Pin{pin}: {pin_value:8.3f} {unit}')

    if 'status' in sensors:
        lines.append(f'  12V-2x6 Status: {sensors["status"]}')
    if sensors.get('threshold_alerts'):
        lines.append(f'  Thresholds    : {", ".join(sensors["threshold_alerts"])}')

    if 'vin' in sensors:
        value, unit = sensors['vin']
        lines.append(f'  AC Input: {value:8.1f} {unit}')

    if 'power_total' in sensors:
        value, unit = sensors['power_total']
        lines.append(_reading_line('POWER', value, unit, 1, sensors.get('power_avg'), 2))
    if 'efficiency' in sensors:
        value, unit = sensors['efficiency']
        lines.append(_reading_line('EFF', value, unit, 2, sensors.get('efficiency_avg'), 2))
    if 'temp' in sensors:
        value, unit = sensors['temp']
        lines.append(f'  TEMP    : {value:8.1f} {unit}')
    if 'fan_rpm' in sensors:
        value, unit = sensors['fan_rpm']
        lines.append(f'  FAN     : {value:8.0f} {unit}')

    if 'zero_fan' in sensors or 'fan_mode' in sensors:
        zero_fan = sensors.get('zero_fan')
        zero = 'unknown' if zero_fan is None else ('on' if zero_fan else 'off')
        mode = sensors.get('fan_mode') or 'unknown'
        lines.append(f'  Zero Fan: {zero:3s}   Mode: {mode}')

    for key in ['uptime', 'uptime_total']:
        if key in sensors:
            label = 'Uptime' if key == 'uptime' else 'Total uptime'
            lines.append(f'  {label:11s}: {_format_duration(sensors[key])}')

    if 'total_energy' in sensors:
        lines.append(f'  Total energy: {_value(sensors["total_energy"]):.1f} kWh')

    return '\n'.join(lines)


def format_json(sensors):
    """Format sensor data as JSON."""
    out = {}
    for key, value in sensors.items():
        if isinstance(value, tuple):
            out[key] = {'value': value[0], 'unit': value[1]}
        else:
            out[key] = value
    return json.dumps(out, indent=2)


def _label(value):
    """Escape a Prometheus label value and strip every C0 control character.

    A device-supplied serial or product string is untrusted input (CRA ST-008):
    an embedded CR/LF would otherwise start a new exposition line, and a bare
    backslash/quote would make the scrape invalid.
    """
    text = str(value).replace('\\', '\\\\').replace('"', '\\"')
    return ''.join(' ' if ord(ch) < 0x20 or ord(ch) == 0x7F else ch for ch in text)


def format_prometheus(sensors):
    """Format sensor data for the node_exporter textfile collector."""
    lines = []
    # "up" answers the first question a scraper asks: did this sample carry any
    # reading at all? An ident-only reply used to export a file that looked
    # healthy -- msi_psu_info 1 and no sensor metrics -- while stdout said failure.
    readable = has_readings(sensors)
    lines.append('# HELP msi_psu_up 1 when the last sample carried sensor readings')
    lines.append('# TYPE msi_psu_up gauge')
    lines.append(f'msi_psu_up {1 if readable else 0}')
    if not readable:
        lines.append('# HELP msi_psu_error_info Why the last sample carried no readings')
        lines.append('# TYPE msi_psu_error_info gauge')
        lines.append(f'msi_psu_error_info{{reason="{_label(_missing_payload(sensors))}"}} 1')
    lines.append('# HELP msi_psu_info MSI PSU information')
    lines.append('# TYPE msi_psu_info gauge')
    lines.append(
        f'msi_psu_info{{product="{_label(sensors.get("product", ""))}",'
        f'vendor="{_label(sensors.get("vendor", ""))}",'
        f'fw="{_label(sensors.get("fw_revision", ""))}",'
        f'serial="{_label(sensors.get("serial", ""))}"}} 1'
    )

    prefix = 'msi_psu'
    for key in ['vout_12v', 'vout_5v', 'vout_3v3']:
        if key in sensors:
            value, _ = sensors[key]
            name = key.replace('vout_', 'voltage_')
            lines.append(f'# HELP {prefix}_{name} {name} in volts')
            lines.append(f'# TYPE {prefix}_{name} gauge')
            lines.append(f'{prefix}_{name}{{rail="{key}"}} {value}')

    for key in ['iout_12v_total', 'iout_5v', 'iout_3v3']:
        if key in sensors:
            value, _ = sensors[key]
            name = key.replace('iout_', 'current_')
            lines.append(f'# HELP {prefix}_{name} {name} in amps')
            lines.append(f'# TYPE {prefix}_{name} gauge')
            lines.append(f'{prefix}_{name}{{rail="{key}"}} {value}')

    if 'vin' in sensors:
        value, _ = sensors['vin']
        lines.append('# HELP msi_psu_input_voltage AC input voltage in volts')
        lines.append('# TYPE msi_psu_input_voltage gauge')
        lines.append(f'msi_psu_input_voltage {value}')

    rails = stats.reading(sensors, 'iout_12v_rails')
    if rails:
        voltages = stats.reading(sensors, 'vout_12v_rails') or []
        lines.append('# HELP msi_psu_rail_voltage Voltage of a discrete 12V rail in volts')
        lines.append('# TYPE msi_psu_rail_voltage gauge')
        for index, rail_value in enumerate(rails):
            if index < len(voltages):
                lines.append(f'msi_psu_rail_voltage{{rail="12V{index + 1}"}} {voltages[index]}')
        lines.append('# HELP msi_psu_rail_current Current of a discrete 12V rail in amps')
        lines.append('# TYPE msi_psu_rail_current gauge')
        for index, rail_value in enumerate(rails):
            lines.append(f'msi_psu_rail_current{{rail="12V{index + 1}"}} {rail_value}')

    watts = stats.rail_watts(sensors)
    if watts is not None:
        lines.append('# HELP msi_psu_cpu_watts Wattage drawn by the CPU rail (12V2) in watts')
        lines.append('# TYPE msi_psu_cpu_watts gauge')
        lines.append(f'msi_psu_cpu_watts{{}} {watts[0]}')
        lines.append(
            '# HELP msi_psu_gpu_watts Wattage drawn by the GPU rails (12V3+12V4+12V5) in watts'
        )
        lines.append('# TYPE msi_psu_gpu_watts gauge')
        lines.append(f'msi_psu_gpu_watts{{}} {watts[1]}')
    if 'iout_pins' in sensors:
        pins, _ = sensors['iout_pins']
        lines.append('# HELP msi_psu_pin_current Per-pin current on 12V-2x6 connector in amps')
        lines.append('# TYPE msi_psu_pin_current gauge')
        for index, pin_value in enumerate(pins):
            conn = 1 if index < 6 else 2
            pin = index % 6 + 1
            lines.append(f'msi_psu_pin_current{{connector="{conn}",pin="{pin}"}} {pin_value}')

    if 'power_total' in sensors:
        value, _ = sensors['power_total']
        lines.append('# HELP msi_psu_power_total Total output power in watts')
        lines.append('# TYPE msi_psu_power_total gauge')
        lines.append(f'msi_psu_power_total{{}} {value}')
    if 'power_avg' in sensors:
        lines.append('# HELP msi_psu_power_avg Cumulative mean output power in watts')
        lines.append('# TYPE msi_psu_power_avg gauge')
        lines.append(f'msi_psu_power_avg{{}} {_value(sensors["power_avg"])}')
    if 'efficiency' in sensors:
        value, _ = sensors['efficiency']
        lines.append('# HELP msi_psu_efficiency Efficiency in percent')
        lines.append('# TYPE msi_psu_efficiency gauge')
        lines.append(f'msi_psu_efficiency{{}} {value}')
    if 'efficiency_avg' in sensors:
        lines.append('# HELP msi_psu_efficiency_avg Cumulative mean efficiency in percent')
        lines.append('# TYPE msi_psu_efficiency_avg gauge')
        lines.append(f'msi_psu_efficiency_avg{{}} {_value(sensors["efficiency_avg"])}')
    if 'temp' in sensors:
        value, _ = sensors['temp']
        lines.append('# HELP msi_psu_temperature Temperature in celsius')
        lines.append('# TYPE msi_psu_temperature gauge')
        lines.append(f'msi_psu_temperature{{}} {value}')
    if 'fan_rpm' in sensors:
        value, _ = sensors['fan_rpm']
        lines.append('# HELP msi_psu_fan_speed Fan speed in RPM')
        lines.append('# TYPE msi_psu_fan_speed gauge')
        lines.append(f'msi_psu_fan_speed{{}} {value}')
    if 'zero_fan' in sensors:
        state = 'on' if sensors['zero_fan'] else 'off'
        lines.append('# HELP msi_psu_zero_fan Zero Fan mode state (1 for the active state)')
        lines.append('# TYPE msi_psu_zero_fan gauge')
        lines.append(f'msi_psu_zero_fan{{state="{state}"}} 1')
    if 'status' in sensors:
        lines.append('# HELP msi_psu_status_12v_2x6 12V-2x6 status label (1 for the active label)')
        lines.append('# TYPE msi_psu_status_12v_2x6 gauge')
        lines.append(f'msi_psu_status_12v_2x6{{status="{_label(sensors["status"])}"}} 1')
    if 'total_energy' in sensors:
        energy = _value(sensors['total_energy'])
        lines.append('# HELP msi_psu_total_energy_kwh Cumulative energy drawn in kWh')
        lines.append('# TYPE msi_psu_total_energy_kwh counter')
        lines.append(f'msi_psu_total_energy_kwh{{}} {energy}')
        # REQ-8 draft names the counter msi_psu_energy_kwh_total. Keep both so
        # recording rules written against either name work; they carry the same
        # counter value in the same scrape.
        lines.append('# HELP msi_psu_energy_kwh_total Cumulative energy drawn in kWh (REQ-8 name)')
        lines.append('# TYPE msi_psu_energy_kwh_total counter')
        lines.append(f'msi_psu_energy_kwh_total{{}} {energy}')

    alerts = sensors.get('alerts')
    if alerts:
        lines.append('# HELP msi_psu_alert Active PSU alert (E1h bit or per-pin mirror)')
        lines.append('# TYPE msi_psu_alert gauge')
        for alert_name in alerts:
            lines.append(f'msi_psu_alert{{alert="{_label(alert_name)}"}} 1')

    limits = sensors.get('threshold_limits')
    if limits:
        lines.append('# HELP msi_psu_threshold_limit Configured local early-warning limit')
        lines.append('# TYPE msi_psu_threshold_limit gauge')
        for name in sorted(limits):
            lines.append(f'msi_psu_threshold_limit{{name="{_label(name)}"}} {limits[name]}')
    threshold_alerts = sensors.get('threshold_alerts')
    if threshold_alerts:
        lines.append('# HELP msi_psu_threshold_alert Local limit reached (software early warning)')
        lines.append('# TYPE msi_psu_threshold_alert gauge')
        for alert_name in threshold_alerts:
            lines.append(f'msi_psu_threshold_alert{{alert="{_label(alert_name)}"}} 1')

    for key in ['uptime', 'uptime_total']:
        if key in sensors:
            lines.append(f'# HELP {prefix}_{key} {key} in seconds')
            lines.append(f'# TYPE {prefix}_{key} counter')
            lines.append(f'{prefix}_{key}{{}} {sensors[key]}')

    return '\n'.join(lines)


FORMATTERS = {'text': format_text, 'json': format_json, 'prometheus': format_prometheus}

# Display labels, in report order (the 7ZPU layout omits the 5V/3.3V rails).
_VOLTAGE_LABELS = {'vout_12v': '+12V', 'vout_5v': '+5V', 'vout_3v3': '+3.3V'}
_CURRENT_LABELS = {'iout_12v_total': '12V TOTAL', 'iout_5v': '5V', 'iout_3v3': '3.3V'}
_BLACKBOX_STATUS = {
    0: 'normal',
    1: 'single-pin OCP (>12A)',
    2: 'pin difference (>5A)',
    3: 'instant OCP (>18A)',
}


def format_blackbox(records):
    """Format C1h black-box records as human-readable text (newest first).

    REV6 p.13 defines InfoID 1 as the latest record. Sorting by InfoID keeps the
    display correct even when a caller hands the records over in another order,
    and unlike the cumulative counters it cannot be reordered by a wrap, a reset
    or a device that counts differently -- it is the field the firmware itself
    uses to define recency.
    """
    if not records:
        return 'No black-box alert records stored.'
    ordered = sorted(records, key=lambda rec: rec.get('info_id') or 0)
    lines = ['GPU Safeguard+ alert log (black box, last 10, newest first)', '']
    for record in ordered:
        status = _BLACKBOX_STATUS.get(record.get('status'), f'status {record.get("status")}')
        # REV6 p.13 byte 1 is "12+4 pin ID / pin set"; MSI never reads this
        # record, so a 1/2 value is most likely the connector and 3..12 can only
        # be a pin number. Claiming "Conn3" for a pin would be worse than naming
        # the raw id, so the ambiguous 1/2 values keep the connector label and a
        # larger value is shown as the pin it must be (needs a real capture).
        id_or_set = record.get('pin_set')
        location = f'Conn{id_or_set}' if id_or_set in (1, 2) else f'pin {id_or_set}'
        lines.append(
            f'#{record["info_id"]}  {location}   {status}   '
            f'uptime {_format_duration(record.get("run_time", 0))} / '
            f'total {_format_duration(record.get("total_time", 0))}   '
            f'total count: {record.get("total_count")}'
        )
        pins = record.get('pins_1_6') or []
        if pins:
            rendered = '  '.join(f'{pin:.1f}' for pin in pins)
            lines.append(f'    Pin currents (A): {rendered}')
        lines.append('')
    while lines and lines[-1] == '':
        lines.pop()
    return '\n'.join(lines)


# ---- 12V-2x6 OCP inspection (read-only, phase 1 scope) ------------------

# C1h status codes, per CPSU.cs OCP_12V2x6_Status.
_OCP_STATUS = {
    0: 'Normal',
    1: 'OCP point',
    2: 'Current difference',
    3: 'Instant OC (>18A)',
}

# Settable windows from CPSU.cs; out-of-range writes are clamped by the PSU.
_OCP_RANGES = {
    'point_a': (10, 14),
    'diff_a': (4, 8),
    'trigger_s': (5, 30),
    'diff_trigger_s': (5, 30),
    'warning_s': (30, 240),
}

# C0h is an overloaded address with complementary model gates: CPSU.cs sends the
# 8-byte 12V-2x6 read only for the MPG TS models and the 1-byte multirail read
# only for the MEG P models. An unsupported model is therefore a fact, not a
# failure, and the message says which of the two views is missing.
OCP_UNSUPPORTED = (
    'OCP configuration is not available on this model '
    '(0xC0/0xC1 exist only on the MPG Ai1600TS / MPG Ai1300TS / MEG Ai1300P / MEG Ai1000P).'
)
MULTIRAIL_UNSUPPORTED = (
    'Multirail OCP status is not available on this model '
    '(the 1-byte 0xC0 flag exists only on the MEG Ai1300P / MEG Ai1000P).'
)


_OCP_AMP_KEYS = ('point_a', 'diff_a')
_OCP_TIME_KEYS = ('trigger_s', 'diff_trigger_s', 'warning_s')
_OCP_ALL_KEYS = _OCP_AMP_KEYS + _OCP_TIME_KEYS


def _ocp_setting(text):
    """argparse type for --ocp-set: POINT,DIFF,TRIGGER,DIFF_TRIGGER,WARNING[,on|off].

    Values are validated here rather than clamped later: a protection limit is
    not a place where a typo should be silently rounded into something else.
    """
    parts = [part.strip() for part in str(text).split(',')]
    if len(parts) not in (5, 6):
        raise argparse.ArgumentTypeError(
            '--ocp-set needs 5 comma-separated values: '
            'POINT_A,DIFF_A,TRIGGER_S,DIFF_TRIGGER_S,WARNING_S[,on|off]'
        )
    values = {}
    for key, raw in zip(_OCP_ALL_KEYS, parts[:5]):
        try:
            value = int(raw)
        except ValueError:
            raise argparse.ArgumentTypeError(f'{key} must be an integer: {raw!r}') from None
        low, high = _OCP_RANGES[key]
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f'{key} must be {low}-{high}, got {value}')
        values[key] = value
    if len(parts) == 6:
        flag = parts[5].lower()
        if flag in ('on', 'enable', 'enabled', 'yes'):
            values['enabled'] = True
        elif flag in ('off', 'disable', 'disabled', 'no'):
            values['enabled'] = False
        else:
            raise argparse.ArgumentTypeError(f'enabled must be on or off: {parts[5]!r}')
    return values


def _normalize_ocp_thresholds(values):
    """Validate a partial OCP threshold mapping from --load-thresholds."""
    if not isinstance(values, dict):
        raise ValueError('threshold file must contain a JSON object')
    normalized = {}
    if 'enabled' in values:
        if not isinstance(values['enabled'], (bool, int)):
            raise ValueError('enabled must be true/false')
        normalized['enabled'] = bool(values['enabled'])
    for key in _OCP_ALL_KEYS:
        if key not in values:
            continue
        raw = values[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f'{key} must be a number')
        value = int(raw)
        if value != raw:
            raise ValueError(f'{key} must be an integer, got {raw!r}')
        low, high = _OCP_RANGES[key]
        if not low <= value <= high:
            raise ValueError(f'{key} must be {low}-{high}, got {value}')
        normalized[key] = value
    if not normalized:
        raise ValueError('threshold file carries none of ' + ', '.join(_OCP_ALL_KEYS))
    return normalized


def _read_ocp_thresholds_file(path):
    """Load a --ocp/--dump-thresholds JSON payload or a flat threshold object."""
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if isinstance(data, dict) and isinstance(data.get('ocp_config'), dict):
        data = data['ocp_config']
    if isinstance(data, dict):
        allowed = set(_OCP_ALL_KEYS) | {'enabled'}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError('unknown threshold key(s): ' + ', '.join(unknown))
    return _normalize_ocp_thresholds(data)


def _ocp_thresholds_equal(left, right):
    """Compare two OCP config dicts at the precision the hardware stores."""
    try:
        if bool(left['enabled']) != bool(right['enabled']):
            return False
        for key in _OCP_AMP_KEYS:
            if int(round(float(left[key]))) != int(round(float(right[key]))):
                return False
        for key in _OCP_TIME_KEYS:
            if int(left[key]) != int(right[key]):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def apply_ocp_thresholds(psu, requested):
    """Write + F1h + verified read-back.

    Returns (config, changed), or (None, reason) where reason is unsupported,
    read or verify. Keeping the reason separate lets the CLI explain which step
    failed instead of collapsing all failures into one read-back mismatch line.

    The current configuration is read first, so re-applying the values the PSU
    already holds is a no-op instead of another flash save.
    """
    if not getattr(psu, 'supports_ocp_config', False):
        return None, 'unsupported'
    current = psu.read_ocp_thresholds()
    if current is None:
        return None, 'read'
    target = dict(current)
    target.update(requested)
    if _ocp_thresholds_equal(current, target):
        return target, False
    for _ in range(3):
        if not psu.set_ocp_thresholds(target):
            continue
        readback = psu.read_ocp_thresholds()
        if readback is not None and _ocp_thresholds_equal(readback, target):
            return target, True
    return None, 'verify'


def run_ocp_thresholds(psu, args):
    """--dump-thresholds / --ocp-set / --load-thresholds (C0h, MPG TS only)."""
    product = getattr(psu, 'product', '')
    if args.dump_thresholds:
        if not getattr(psu, 'supports_ocp_config', False):
            logger.error(f'Error: {OCP_UNSUPPORTED}')
            return EXIT_ERROR
        config = psu.read_ocp_thresholds()
        if config is None:
            logger.error('Error: the PSU did not answer the 0xC0 OCP configuration read.')
            return EXIT_ERROR
        emit(OCP_FORMATTERS[args.format](config, None, product), args.output)
        return EXIT_OK

    requested = {}
    if args.ocp_set is not None:
        requested = dict(args.ocp_set)
    else:
        try:
            requested = _read_ocp_thresholds_file(args.load_thresholds)
        except (OSError, ValueError) as exc:
            logger.error(f'Error: cannot load OCP thresholds from {args.load_thresholds}: {exc}')
            return EXIT_ERROR

    config, changed = apply_ocp_thresholds(psu, requested)
    if config is None:
        if changed == 'unsupported':
            logger.error(f'Error: {OCP_UNSUPPORTED}')
        elif changed == 'read':
            logger.error('Error: the PSU did not answer the 0xC0 OCP configuration read.')
        else:
            logger.error(
                'Error: the PSU did not accept the OCP threshold write '
                '(read-back mismatch after 3 attempts).'
            )
        return EXIT_ERROR
    logger.info(
        f'write ocp_thresholds point={config["point_a"]:.1f} diff={config["diff_a"]:.1f} '
        f'trigger={config["trigger_s"]} diff_trigger={config["diff_trigger_s"]} '
        f'warning={config["warning_s"]} enabled={int(bool(config["enabled"]))} '
        f'verified=true changed={changed} '
        f'product={getattr(psu, "product", "")!r} fw={getattr(psu, "fw_revision", "")!r}'
    )
    line = (
        f'OCP thresholds: point {config["point_a"]:.1f} A, '
        f'diff {config["diff_a"]:.1f} A, trigger {config["trigger_s"]} s, '
        f'diff trigger {config["diff_trigger_s"]} s, warning {config["warning_s"]} s, '
        f'enabled {"yes" if config["enabled"] else "no"}'
    )
    if not changed:
        line += ' (already set)'
    emit(line, args.output)
    return EXIT_OK


def _ocp_state_rows(state):
    """Yield (status, run_time, total_time, pins) for both 12V-2x6 connectors."""
    yield (state['status_12v5'], state['run_time'], state['total_time'], state['pins_1_6'])
    yield (
        state['status_12v3'],
        state['run_time_2'],
        state['total_time_2'],
        state['pins_7_12'],
    )


def _ocp_status_name(code):
    return _OCP_STATUS.get(code, f'status {code}')


def format_ocp_text(config, state, product):
    """Format the C0h threshold configuration (+ C1h state) as text."""
    lines = [f'MSI PSU: {product}' if product else 'MSI PSU']
    lines.append('12V-2x6 OCP configuration (0xC0):')
    lines.append(f'  {"Enabled":<16}: {"yes" if config["enabled"] else "no"}')
    for label, key, digits, unit in (
        ('Pin OCP point', 'point_a', 1, 'A'),
        ('Pin difference', 'diff_a', 1, 'A'),
        ('OCP trigger', 'trigger_s', 0, 's'),
        ('Diff trigger', 'diff_trigger_s', 0, 's'),
        ('Warning time', 'warning_s', 0, 's'),
    ):
        low, high = _OCP_RANGES[key]
        value = f'{config[key]:.{digits}f}'
        lines.append(f'  {label:<16}: {value} {unit}   (range {low}-{high})')

    if state:
        lines.append('')
        lines.append('12V-2x6 state (0xC1, 5 s averages):')
        for index, (status, run_time, total_time, pins) in enumerate(
            _ocp_state_rows(state), start=1
        ):
            lines.append(
                f'  Conn{index}: {_ocp_status_name(status):<20} '
                f'uptime {_format_duration(run_time)} / total {_format_duration(total_time)}'
            )
            lines.append(f'    Pin currents (A): {"  ".join(f"{pin:.1f}" for pin in pins)}')
    return '\n'.join(lines)


def format_ocp_json(config, state, product):
    """Format the C0h threshold configuration (+ C1h state) as JSON."""
    payload = {
        'product': product,
        'ocp_config': {
            'enabled': config['enabled'],
            'point_a': config['point_a'],
            'diff_a': config['diff_a'],
            'trigger_s': config['trigger_s'],
            'diff_trigger_s': config['diff_trigger_s'],
            'warning_s': config['warning_s'],
        },
    }
    if state:
        payload['ocp_state'] = {
            'connectors': [
                {
                    'status': status,
                    'status_name': _ocp_status_name(status),
                    'run_time': run_time,
                    'total_time': total_time,
                    'pins': pins,
                }
                for status, run_time, total_time, pins in _ocp_state_rows(state)
            ]
        }
    return json.dumps(payload, indent=2)


#: HELP line of the OCP availability gauge (see below).
OCP_AVAILABLE_HELP = (
    '# HELP msi_psu_ocp_available 12V-2x6 OCP registers exposed by this model (1) or not (0)'
)


def format_ocp_availability_prometheus(available):
    """The honest stand-in for a model without the C0h/C1h OCP registers.

    Every prometheus write the daemon makes (and those are only the writes it
    makes after a successful sample) carries this gauge: an absent
    ``msi_psu_ocp_*`` block is indistinguishable from a broken exporter on a
    dashboard.
    """
    return '\n'.join(
        [
            OCP_AVAILABLE_HELP,
            '# TYPE msi_psu_ocp_available gauge',
            f'msi_psu_ocp_available {1 if available else 0}',
        ]
    )


def format_ocp_prometheus(config, state, product):
    """Format the C0h threshold configuration (+ C1h state) as prometheus text."""
    lines = [
        OCP_AVAILABLE_HELP,
        '# TYPE msi_psu_ocp_available gauge',
        'msi_psu_ocp_available 1',
        '# HELP msi_psu_ocp_enabled 12V-2x6 OCP enabled (1) or disabled (0)',
        '# TYPE msi_psu_ocp_enabled gauge',
        f'msi_psu_ocp_enabled{{}} {1 if config["enabled"] else 0}',
        '# HELP msi_psu_ocp_pin_point_a Configured single-pin OCP trip point in amps',
        '# TYPE msi_psu_ocp_pin_point_a gauge',
        f'msi_psu_ocp_pin_point_a{{}} {config["point_a"]}',
        '# HELP msi_psu_ocp_pin_diff_a Configured pin-to-pin tolerance in amps',
        '# TYPE msi_psu_ocp_pin_diff_a gauge',
        f'msi_psu_ocp_pin_diff_a{{}} {config["diff_a"]}',
        '# HELP msi_psu_ocp_trigger_s OCP trip trigger time in seconds',
        '# TYPE msi_psu_ocp_trigger_s gauge',
        f'msi_psu_ocp_trigger_s{{}} {config["trigger_s"]}',
        '# HELP msi_psu_ocp_diff_trigger_s Pin-difference trigger time in seconds',
        '# TYPE msi_psu_ocp_diff_trigger_s gauge',
        f'msi_psu_ocp_diff_trigger_s{{}} {config["diff_trigger_s"]}',
        '# HELP msi_psu_ocp_warning_s Abnormal warning time in seconds',
        '# TYPE msi_psu_ocp_warning_s gauge',
        f'msi_psu_ocp_warning_s{{}} {config["warning_s"]}',
    ]
    if state:
        lines.append(
            '# HELP msi_psu_ocp_status 12V-2x6 OCP state per connector '
            '(0 normal, 1 OCP point, 2 difference, 3 instant OC)'
        )
        lines.append('# TYPE msi_psu_ocp_status gauge')
        for index, (status, run_time, total_time, _pins) in enumerate(
            _ocp_state_rows(state), start=1
        ):
            lines.append(f'msi_psu_ocp_status{{connector="{index}"}} {status}')
        lines.append('# HELP msi_psu_ocp_run_time Seconds the connector spent in an alert state')
        lines.append('# TYPE msi_psu_ocp_run_time gauge')
        for index, (_status, run_time, _total, _pins) in enumerate(_ocp_state_rows(state), start=1):
            lines.append(f'msi_psu_ocp_run_time{{connector="{index}"}} {run_time}')
        lines.append('# HELP msi_psu_ocp_total_time Seconds the connector has been powered')
        lines.append('# TYPE msi_psu_ocp_total_time counter')
        for index, (_status, _run, total_time, _pins) in enumerate(_ocp_state_rows(state), start=1):
            lines.append(f'msi_psu_ocp_total_time{{connector="{index}"}} {total_time}')
    return '\n'.join(lines)


def format_multirail_text(multirail, product):
    """Format the 1-byte multirail OCP flag (0xC0) as text."""
    state = 'enabled' if multirail else 'disabled'
    detail = 'per-rail protection' if multirail else 'single combined-rail protection'
    lines = [f'MSI PSU: {product}' if product else 'MSI PSU']
    lines.append('Multirail OCP (0xC0):')
    lines.append(f'  {"Enabled":<16}: {state}   ({detail})')
    return '\n'.join(lines)


def format_multirail_json(multirail, product):
    """Format the 1-byte multirail OCP flag (0xC0) as JSON."""
    return json.dumps(
        {'product': product, 'multirail_ocp': {'enabled': bool(multirail)}},
        indent=2,
    )


def format_multirail_prometheus(multirail, product):
    """Format the 1-byte multirail OCP flag (0xC0) as prometheus text."""
    return '\n'.join(
        [
            '# HELP msi_psu_multirail_ocp Per-rail OCP enabled (1) or combined-rail (0)',
            '# TYPE msi_psu_multirail_ocp gauge',
            f'msi_psu_multirail_ocp{{}} {1 if multirail else 0}',
        ]
    )


MULTIRAIL_FORMATTERS = {
    'text': format_multirail_text,
    'json': format_multirail_json,
    'prometheus': format_multirail_prometheus,
}

OCP_FORMATTERS = {
    'text': format_ocp_text,
    'json': format_ocp_json,
    'prometheus': format_ocp_prometheus,
}


# ---- sensor enrichment --------------------------------------------------


def read_fan_fields(psu):
    """Return fan_mode/zero_fan (and duty) fields, or {} when unsupported."""
    reader = getattr(psu, 'read_fan_state', None)
    if reader is None:
        return {}
    try:
        fan = reader()
    except Exception:  # pragma: no cover - defensive against odd devices
        return {}
    fields = {}
    if fan.get('mode') is not None:
        fields['fan_mode'] = _FAN_BYTE_TO_MODE.get(fan['mode'], f'mode{fan["mode"]}')
    if fan.get('zero_fan') is not None:
        fields['zero_fan'] = bool(fan['zero_fan'])
    # MSI only reports the customize duty while the customize mode is active
    # (``Mode == 3 ? RxData[5] : 0``, ``CPSU.cs:772``); a duty left over from an
    # earlier session is not what the fan is running at, so it stays out.
    if fan.get('duty') is not None and fan.get('mode') == _FAN_MODE_TO_BYTE[FAN_MODE_CUSTOMIZED]:
        fields['fan_duty'] = fan['duty']
    return fields


def _threshold_detail(name, sensors, thresholds):
    """Alert description with the measured value and configured limit.

    Static names alone make the journal line useless for tuning: an operator
    needs "measured 1512 W, limit 1200 W" to decide whether the threshold is
    wrong or the load is. Falls back to the generic description when the reading
    is not available.
    """
    if name in THRESHOLD_SOURCES:
        sensor_key, limit_key = THRESHOLD_SOURCES[name]
        value = sensors.get(sensor_key)
        if isinstance(value, tuple):
            value = value[0]
        try:
            measured = float(value)
        except (TypeError, ValueError):
            return describe(name)
        limit = float(thresholds.get(limit_key) or 0.0)
        return f'{describe(name)}: measured {measured:g}, limit {limit:g}'
    if name in CONNECTOR_ALERTS:
        pins = sensors.get('iout_pins')
        if isinstance(pins, tuple):
            pins = pins[0]
        try:
            index = CONNECTOR_ALERTS.index(name)
            measured = sum(float(pin) for pin in pins[index * 6 : (index + 1) * 6])
        except (TypeError, ValueError):
            return describe(name)
        limit = float(thresholds.get(CONNECTOR_LIMIT_KEY) or 0.0)
        return f'{describe(name)}: measured {measured:.3g} A, limit {limit:g} A'
    return describe(name)


def collect_alerts(psu, engine, sensors, thresholds=None):
    """Merge E1h bits, the per-pin mirror and the configured local thresholds.

    Returns (fired, active_security, have_e1h, threshold_active). have_e1h is
    True only when the PSU answered the E1h status read. The software mirror is
    a second, independent measurement, but it only sees the OCP pins and their
    imbalance: it cannot see the E1h-only bits (opp, otp, and fan -- the one
    critical bit, "shutdown imminent"), so a mirror-only poll must not be
    rendered as "Normal". A PSU that answers neither source is not complete
    either, so callers never read a silent read failure as "all OK".

    Local thresholds (power/temperature/rail current/connector current) are
    software-only early warnings. They use the same engine and the same
    consecutive-poll debounce, but are returned separately so the "12V-2x6
    Status" line keeps its hardware meaning.

    Names the caller leaves out keep the state the engine already has: a failed
    E1h read never clears an alert that is already firing. The same holds for a
    failed 0xE0 read: no sensor was measured, so a missing name must not be read
    as a recovery.
    """
    thresholds = thresholds or {}
    active = {}
    have_e1h = False
    hardware = psu.read_alert_status()
    if hardware:
        active.update({name: bool(value) for name, value in hardware.items()})
        have_e1h = True

    pins = sensors.get('iout_pins')
    pin_values = pins[0] if isinstance(pins, tuple) else pins
    pin_max = thresholds.get('pin_max_a', PIN_OCP_THRESHOLD_A)
    imbalance = thresholds.get('pin_imbalance_a', PIN_IMBALANCE_THRESHOLD_A)
    mirror_enabled = pin_max > 0 or imbalance > 0
    software = evaluate_pin_alerts(pin_values, pin_max, imbalance)
    if software:
        for name, value in software.items():
            active[name] = active.get(name, False) or value
    local = evaluate_threshold_alerts(sensors, thresholds)
    for name, value in local.items():
        active[name] = active.get(name, False) or value

    if not active and not have_e1h:
        return [], [], False, []

    if have_e1h:
        if mirror_enabled and not software:
            # The 0xE0 payload was missing (or unusable), so the per-pin mirror
            # did not run. A False bit in the E1h bitmap is not a recovery the
            # mirror measured: drop it from this poll so the engine keeps the
            # latched alert until a real pin reading clears it. A True bit still
            # reports a trip. Without this, one failed payload read silently
            # turned a live pin alert into a logged RECOVERED edge.
            for name in [
                name
                for name, is_active in active.items()
                if not is_active and name.startswith('ocp_pin')
            ]:
                del active[name]
        # The E1h answer defines the names this device has (its index array),
        # plus the mirror's and local thresholds' names when they applied. Drop
        # anything else the engine latched while a different model was attached:
        # a name this device never reports can never be cleared by a False.
        # Only on a successful E1h read -- an unanswered poll must not clear an
        # alert that is firing.
        known = set(hardware) | set(software)
        has_per_pin_data = isinstance(pin_values, list) and len(pin_values) >= 12
        if not has_per_pin_data and any(name.startswith('ocp_pin') for name in hardware):
            # A TS model with the payload missing still reports ocp_pin* bits,
            # which is how retain() knows the mirror's imbalance alert belongs
            # to this device (it has no E1h bit of its own).
            has_per_pin_data = True
        if mirror_enabled and not software and imbalance > 0 and has_per_pin_data:
            known.add(IMBALANCE_ALERT)
        known |= configured_threshold_names(thresholds, has_per_pin_data)
        engine.retain(known)

    fired = engine.update(active)
    for alert in fired:
        if alert.name in THRESHOLD_ALERT_NAMES:
            alert.description = _threshold_detail(alert.name, sensors, thresholds)
        logger.warning(format_alert_line(alert))
    active_all = engine.active_alerts
    security = [name for name in active_all if name not in THRESHOLD_ALERT_NAMES]
    threshold_active = [name for name in active_all if name in THRESHOLD_ALERT_NAMES]
    return fired, security, have_e1h, threshold_active


def status_from(active_names, have_e1h):
    """Render the ``12V-2x6 Status`` label.

    ``have_e1h`` says whether the E1h bitmap answered; without it the honest
    answer is ``Unknown`` even when the pin mirror found nothing wrong.
    """
    if active_names:
        return ', '.join(active_names)
    return STATUS_NORMAL if have_e1h else STATUS_UNKNOWN


def attach_alerts(psu, engine, sensors, cfg):
    """Poll alerts and publish the alert/status/threshold fields on sensors.

    One place for the CLI and the daemon, so the three output formats always
    see the same field set. Returns the alerts fired by this poll (threshold
    alerts included) for the daemon's audit log.
    """
    thresholds = threshold_limits(cfg)
    fired, active, have_e1h, threshold_active = collect_alerts(psu, engine, sensors, thresholds)
    sensors['alerts'] = active
    sensors['status'] = status_from(active, have_e1h)
    sensors['threshold_alerts'] = threshold_active
    sensors['threshold_limits'] = {key: value for key, value in thresholds.items() if value > 0}
    return fired


# Any of these proves the bulk payload was decoded; ident-only keys (vendor,
# product, fw_revision, serial, uptime) survive a failed 0xE0 read.
CORE_READING_KEYS = ('vout_12v', 'vout_5v', 'vout_3v3', 'power_total')


def has_readings(sensors):
    """True when the sample carries at least one decoded sensor value.

    A PSU that answers its ident but not the 0xE0 payload yields an ident-only
    dict. Rendering that as a successful read would report health we never
    measured, so callers treat it as a read failure (exit 1 for one-shot, a
    counted failure for the daemon).
    """
    return any(key in sensors for key in CORE_READING_KEYS)


def _missing_payload(sensors):
    """Explain a payload-less sample, keeping the specific reason when there is one."""
    return (
        sensors.get('payload_error')
        or sensors.get('error')
        or 'no sensor payload in this sample (0xE0 read failed)'
    )


def _valid_sample(sensors):
    """Return (watts, efficiency) when both readings are usable, else None."""
    power = _value(sensors.get('power_total'))
    efficiency = _value(sensors.get('efficiency'))
    # Zero is a valid reading: at idle a PSU can report 0 W and must still count
    # as a sample (skipping it biases the average and the sample count). Only
    # missing/malformed values are not usable.
    if power is None or efficiency is None:
        return None
    try:
        return float(power), float(efficiency)
    except (TypeError, ValueError):
        return None


def apply_stats(sensors, monitor_state):
    """Fold the sample into the cumulative stats and expose the derived values."""
    if monitor_state is None:
        return
    monitor_state.note_identity(sensors)
    sample = _valid_sample(sensors)
    if sample is not None:
        monitor_state.update(*sample)
    sensors['power_avg'] = (round(monitor_state.power_avg, 2), 'W')
    sensors['efficiency_avg'] = (round(monitor_state.efficiency_avg, 2), '%')
    sensors['total_energy'] = (round(monitor_state.total_energy_kwh, 3), 'kWh')


# ---- device selection ---------------------------------------------------


def open_psu(path):
    """Open the PSU on ``path`` (the synthetic demo device in MSI_PSU_DEMO mode)."""
    if demo.enabled():
        return demo.DemoPSU()
    return MSIPSU(HIDDevice(path))


def resolve_device(serial):
    """Pick the hidraw path to use; returns ``(path, available_serials, blocked)``.

    ``blocked`` lists the devices that could not be opened at all (permission, or
    held by the daemon). Reporting those as "no PSU with that serial" sends the
    user looking for a device that is sitting right there.
    """
    if demo.enabled():
        available = [demo.DEMO_SERIAL]
        if serial in (None, demo.DEMO_SERIAL):
            return demo.DEVICE_PATH, available, []
        return None, available, []
    if serial is None:
        return detect_device(), [], []
    from msi_psu_monitor.protocol import detect_devices

    available = []
    blocked = []
    for path in detect_devices():
        psu = None
        try:
            psu = MSIPSU(HIDDevice(path))
            psu.open()
            psu.init()
        except (OSError, DeviceBusyError) as exc:
            blocked.append(path)
            logger.warning(f'Skipping {path}: {exc}')
            continue
        except Exception as exc:
            # A malformed/parser-bug device must not crash serial discovery.
            blocked.append(path)
            logger.warning(f'Skipping {path}: unexpected error: {exc}')
            continue
        finally:
            if psu is not None:
                psu.close()
        available.append(psu.serial)
        if psu.serial == serial:
            return path, available, blocked
    return None, available, blocked


def _state_dir(cfg):
    return str(cfg.get('state_dir') or stats.default_state_dir())


# ---- modes --------------------------------------------------------------


class OutputError(Exception):
    """The requested output path could not be written (not a PSU failure)."""


def _must_write_through(path):
    """True when 'path' has to be opened, not renamed over.

    os.replace() replaces the *name*, so a symlink would be swapped for a plain
    file and the real target left untouched. That is merely surprising for a user
    symlink, and destructive for the system names: with stdout redirected to a
    regular file, -O /dev/stdout looks like a regular file, and running as root
    would replace /dev/stdout itself. A FIFO or a device node cannot be renamed
    over either, so all three are written through instead of atomically.
    """
    return os.path.islink(path) or (os.path.exists(path) and not os.path.isfile(path))


def emit(output, output_path):
    """Write ``output`` to stdout, or replace ``output_path`` atomically."""
    if not output_path:
        # flush: a closed pipe must fail here, inside main()'s handler, not during
        # the interpreter's shutdown flush (which would exit 120).
        try:
            print(output, flush=True)
        except BrokenPipeError:
            raise
        except OSError as exc:
            # ENOSPC/EIO on stdout: one normal fault, not the interpreter's 120.
            _redirect_stdout_to_devnull()
            raise OutputError(f'cannot write output: {exc}') from exc
        return
    try:
        if _must_write_through(output_path):
            # A fifo, a device node or a symlink cannot be replaced, only written
            # into (see _must_write_through for why a symlink counts).
            with open(output_path, 'w', encoding='utf-8') as handle:
                handle.write(output + '\n')
            return
        stats.atomic_write_text(output_path, output + '\n')
    except OSError as exc:
        # A failed output path used to escape as PermissionError and be reported
        # as "Run as root" (the catch for the PSU device), or as a raw traceback
        # from --show-alert-log. Name the output path and keep it a normal fault.
        raise OutputError(f'cannot write {output_path}: {exc}') from exc


def run_once(psu, args, cfg, monitor_state, engine):
    """One-shot read; returns the process exit code."""
    sensors = psu.get_sensors()
    if 'error' in sensors:
        logger.error(f'Error: {sensors["error"]}')
        emit(FORMATTERS[args.format](sensors), args.output)
        return EXIT_ERROR
    complete = has_readings(sensors)

    sensors.update(read_fan_fields(psu))
    if not args.no_alerts:
        attach_alerts(psu, engine, sensors, cfg)
    apply_stats(sensors, monitor_state)
    if monitor_state is not None:
        # Same retention the daemon uses: pruning with the built-in default
        # would drop buckets a user asked to keep for 60 days.
        monitor_state.prune(days=cfg['retention_days'])
        monitor_state.save(stats.state_path(_state_dir(cfg)))

    emit(FORMATTERS[args.format](sensors), args.output)
    # An active alert outranks a failed payload read: the E1h bit is a separate
    # register and is the safety-critical signal, so it must reach exit 2 even
    # when the sensor payload is missing.
    if sensors.get('alerts') or sensors.get('threshold_alerts'):
        if not complete:
            logger.error(f'Warning: {_missing_payload(sensors)}')
        return EXIT_ALERT
    if not complete:
        logger.error(f'Error: {_missing_payload(sensors)}.')
        return EXIT_ERROR
    return EXIT_OK


def run_watch(psu, args, cfg, monitor_state, engine):
    """Continuous text refresh; returns the process exit code.

    With ``-O`` the frames are appended to that file and the screen stays empty
    instead ("file instead of screen", like every other mode): printing to stdout
    and never touching the file was the silent half of that promise.
    """
    interval = args.interval
    if interval is None:
        interval = cfg['interval'] if args.watch == WATCH_FROM_CONFIG else args.watch
    stream = None
    if args.output:
        try:
            stream = open(args.output, 'a', encoding='utf-8', buffering=1)
        except OSError as exc:
            logger.error(f'Error: cannot write {args.output}: {exc}')
            return EXIT_ERROR
        if not args.quiet:
            print(
                f'Appending frames to {args.output} (Ctrl-C to stop)',
                file=sys.stderr,
                flush=True,
            )
    last_save = 0.0
    try:
        while True:
            sensors = psu.get_sensors()
            if 'error' in sensors:
                logger.error(f'Error: {sensors["error"]}')
                if stream is not None:
                    # Keep the file self-explanatory, the way --once -O does: an
                    # empty artifact says nothing about why the run stopped.
                    stream.write(format_text(sensors) + '\n')
                return EXIT_ERROR
            if not has_readings(sensors):
                # A stream survives one missed frame; the next one may land.
                logger.error(f'Warning: {_missing_payload(sensors)} (frame skipped).')
                time.sleep(interval)
                continue
            sensors.update(read_fan_fields(psu))
            if not args.no_alerts:
                attach_alerts(psu, engine, sensors, cfg)
            apply_stats(sensors, monitor_state)

            now = time.time()
            if monitor_state is not None and now - last_save >= 30.0:
                monitor_state.prune(days=cfg['retention_days'])
                monitor_state.save(stats.state_path(_state_dir(cfg)))
                last_save = now

            line = format_text(sensors)
            if stream is not None:
                stream.write(line + '\n')  # line-buffered: a tail -f sees each frame
            else:
                # Clear only on a terminal: pipes keep a complete, parseable stream.
                if sys.stdout.isatty():
                    os.system('clear' if sys.platform == 'linux' else 'cls')
                # flush so `msi-psu-monitor --watch | tee` still sees each frame.
                print(line, flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        return EXIT_OK
    finally:
        if stream is not None:
            stream.close()
        if monitor_state is not None:
            monitor_state.save(stats.state_path(_state_dir(cfg)))


def apply_fan_setting(psu, mode, duty=None):
    """Write the fan setting (41h) + save (F1h) and verify it by read-back.

    Shared by ``--fan-mode``/``--fan-duty`` and by the daemon's profile restore,
    so both paths send byte-for-byte the same sequence. Retries three times,
    matching the patience MSI Center shows before it reports a failure.

    Args:
        psu: An opened PSU.
        mode: 'auto'/'performance'/'customized', or None to infer 'customized'
            from a duty. 'performance' is MSI Center's name for the PSU's own
            curve and maps to the same byte as 'auto'.
        duty: 0-100 for 'customized'; None keeps whatever the PSU reports.

    Returns:
        ``(mode, duty)`` as actually applied (the requested spelling is kept so
        ``--fan-mode performance`` reports what the user asked for), or None when
        the PSU refused (write NAK or a read-back that disagrees).
    """
    mode = mode or (FAN_MODE_CUSTOMIZED if duty is not None else FAN_MODE_AUTO)
    effective = FAN_MODE_AUTO if mode == FAN_MODE_PERFORMANCE else mode
    if effective == FAN_MODE_AUTO:
        duty = 0
    elif duty is None:
        current = psu.read_fan_setting()
        duty = current[1] if current else 0

    target_mode = _FAN_MODE_TO_BYTE[effective]
    for _ in range(3):
        if not psu.set_fan_mode(target_mode, duty):
            continue
        setting = psu.read_fan_setting()
        if (
            setting
            and setting[0] == target_mode
            and (effective == FAN_MODE_AUTO or setting[1] == duty)
        ):
            return (mode, duty)
    return None


def apply_zero_fan_setting(psu, enabled):
    """Write Zero Fan (43h) + save (F1h) and verify it by read-back (42h byte 4).

    Three attempts, matching the patience apply_fan_setting shows. Returns the
    applied state, or None when the PSU refused the write or the read-back
    disagrees (including a model that does not report the field at all).
    """
    for _ in range(3):
        if not psu.set_zero_fan(enabled):
            continue
        current = psu.read_zero_fan()
        if current is not None and bool(current) == enabled:
            return enabled
    return None


def apply_rail_mode(psu, mode):
    """Switch the MEG P rail protection mode and verify it by read-back.

    MSI Center's DC Output page exposes this as Multi Rail / Single Rail and
    sends SET_MULTIRAIL_OCP + SAVE_SETTING without a read-back (C_PSU.cs:1392);
    we verify the single-byte register, which answers immediately. Three
    attempts, like the other control writes.

    The current mode is read before the write: re-writing the value the PSU
    already holds is not a no-op on the real hardware (REQ-11: read first and
    return when the value already matches; the hardware errors on a same-value
    write) and it also burns a flash save every time.

    Returns (mode, changed), where changed is False when the PSU was already in
    the requested mode, or None when the model does not support it or the
    read-back disagrees.
    """
    enabled = mode == RAIL_MODE_MULTI
    current = psu.read_multirail_ocp()
    if current is not None and bool(current) == enabled:
        return mode, False
    for _ in range(3):
        if not psu.set_multirail_ocp(enabled):
            continue
        current = psu.read_multirail_ocp()
        if current is not None and bool(current) == enabled:
            return mode, True
    return None


def _write_requested(args):
    """True when any flag asks for a device write (not a read/export/dashboard)."""
    return bool(
        args.fan_mode
        or args.fan_duty is not None
        or args.zero_fan is not None
        or args.buzzer_off
        or args.set_rail is not None
    )


def run_write_controls(psu, args):
    """Apply every requested control write, then describe the result once.

    Zero Fan goes first: that is the order MSI Center's Cooling Wizard uses
    (zero fan, then fan mode) and both are persisted by the F1h the protocol
    methods send. The buzzer command is a one-shot C2h switch with no read-back
    (MSI calls it BUZZER_SWITCH and it toggles), so success only means the PSU
    acknowledged it. One emit() at the end keeps -O from being overwritten by
    each line.
    """
    lines = []
    if args.set_rail is not None:
        applied = apply_rail_mode(psu, args.set_rail)
        if applied is None:
            logger.error(
                'Error: the PSU did not accept the rail mode '
                '(read-back mismatch, or only the MEG Ai1000P/Ai1300P support it).'
            )
            return EXIT_ERROR
        rail_mode, changed = applied
        logger.info(
            f'write rail mode={rail_mode} verified=true changed={changed} '
            f'product={getattr(psu, "product", "")!r} fw={getattr(psu, "fw_revision", "")!r}'
        )
        lines.append(f'Rail mode: {rail_mode}' + ('' if changed else ' (already set)'))
    if args.zero_fan is not None:
        enabled = args.zero_fan == 'on'
        applied = apply_zero_fan_setting(psu, enabled)
        if applied is None:
            logger.error(
                'Error: the PSU did not accept the Zero Fan setting '
                '(read-back mismatch, or the model does not support it).'
            )
            return EXIT_ERROR
        logger.info(
            f'write zero_fan={"on" if applied else "off"} verified=true '
            f'product={getattr(psu, "product", "")!r} fw={getattr(psu, "fw_revision", "")!r}'
        )
        lines.append(f'Zero Fan: {"on" if applied else "off"}')
    if args.fan_mode or args.fan_duty is not None:
        applied = apply_fan_setting(psu, args.fan_mode, args.fan_duty)
        if applied is None:
            logger.error('Error: the PSU did not accept the fan setting (read-back mismatch).')
            return EXIT_ERROR
        mode, duty = applied
        logger.info(
            f'write fan mode={mode} duty={duty} verified=true '
            f'product={getattr(psu, "product", "")!r} fw={getattr(psu, "fw_revision", "")!r}'
        )
        duty_text = '' if mode in (FAN_MODE_AUTO, FAN_MODE_PERFORMANCE) else f'   Duty: {duty}%'
        lines.append(f'Fan mode: {mode}{duty_text}')
    if args.buzzer_off:
        # C2h carries no value and has no read-back: MSI Center calls it
        # BUZZER_SWITCH (CPSU.cs:1148-1159), so it toggles. Saying "silenced"
        # claimed a state the tool cannot observe -- and a second run re-arms the
        # alarm while the user believes it is off.
        if not psu.silence_buzzer():
            logger.error(
                'Error: the PSU did not accept --buzzer-off '
                '(the C2h buzzer switch; or the model does not support it).'
            )
            return EXIT_ERROR
        logger.info(
            f'write buzzer=toggled verified=false '
            f'product={getattr(psu, "product", "")!r} fw={getattr(psu, "fw_revision", "")!r}'
        )
        lines.append('Buzzer: switch toggled (no read-back)')
    emit('\n'.join(lines), args.output)
    return EXIT_OK


def run_ocp(psu, args):
    """Show the OCP view for this model.

    0xC0 is one address with two complementary meanings: the MPG TS models answer
    the 8-byte 12V-2x6 configuration (plus the 42-byte state on 0xC1), while the
    MEG P models answer a single multirail flag. The Ai1600T answers neither and
    gets an explanation instead of an error.

    Read-only: phase 1 only inspects these registers, the write path stays
    frozen (CPSU.cs ``SET_OCP12V2x6_CONFIG`` is a later, separately approved
    batch). Returns the process exit code.
    """
    product = getattr(psu, 'product', '') or ''
    if not getattr(psu, 'supports_ocp_config', False):
        return _emit_ocp_unsupported(psu, product, args)

    return _run_ocp_12v2x6(psu, product, args)


def _emit_ocp_unsupported(psu, product, args):
    """Explain which OCP view is missing without treating it as an error.

    The MEG P models still have the multirail flag, so they get that instead of
    the 12V-2x6 report; the MEG Ai1600T answers neither register.
    """
    if getattr(psu, 'supports_multirail_ocp', False):
        multirail = psu.read_multirail_ocp()
        if multirail is None:
            logger.error('Error: the PSU did not answer the 0xC0 multirail OCP read.')
            return EXIT_ERROR
        emit(MULTIRAIL_FORMATTERS[args.format](multirail, product), args.output)
        return EXIT_OK

    if args.format == 'json':
        emit(json.dumps({'product': product, 'supported': False}, indent=2), args.output)
    elif args.format == 'prometheus':
        emit(f'# {OCP_UNSUPPORTED}', args.output)
    else:
        header = f'MSI PSU: {product}' if product else 'MSI PSU'
        # One emit: two calls truncated the same -O file, so the file kept only
        # the second line while stdout showed both.
        emit(f'{header}\n{OCP_UNSUPPORTED}', args.output)
    return EXIT_OK


def _run_ocp_12v2x6(psu, product, args):
    """Report the 8-byte 12V-2x6 OCP configuration and its realtime state."""
    config = psu.read_ocp_thresholds()
    if config is None:
        logger.error('Error: the PSU did not answer the 0xC0 OCP configuration read.')
        return EXIT_ERROR

    # The C1h state block is a bonus: an NAK there must not fail the report.
    state = None
    reader = getattr(psu, 'read_ocp_state', None)
    if reader is not None:
        try:
            state = reader()
        except Exception:  # pragma: no cover - defensive against odd devices
            state = None

    emit(OCP_FORMATTERS[args.format](config, state, product), args.output)
    return EXIT_OK


def run_show_alert_log(args, cfg):
    """Print the local alert log (MSI Center's ViewLog equivalent, text only)."""
    lines = stats.iter_alert_log(_state_dir(cfg), limit=200)
    try:
        if not lines:
            emit('No alert log records stored.', args.output)
            return EXIT_OK
        emit('\n'.join(lines), args.output)
        return EXIT_OK
    except OutputError as exc:
        logger.error(f'Error: {exc}')
        return EXIT_ERROR


def run_export(args, cfg):
    """Export a slice of the daemon history; returns the process exit code."""
    if args.from_spec is None:
        # An explicitly empty --from is reported by parse_from() below, so the
        # message names the offending value instead of claiming it is missing.
        logger.error('Error: --export requires --from (e.g. --from 2h).')
        return EXIT_ERROR
    try:
        window = stats.parse_from(args.from_spec)
        columns = stats.parse_columns(args.columns)
    except ValueError as exc:
        logger.error(f'Error: {exc}')
        return EXIT_ERROR

    state_dir = _state_dir(cfg)
    header, rows = stats.build_export(state_dir, time.time() - window, columns)
    if not rows:
        # A header-only CSV is exactly what a wrong state dir, a daemon that
        # never ran and a window wider than the retention all look like.
        logger.warning(
            f'No history rows in {state_dir} for the last {args.from_spec}; '
            'only the header is written.'
        )
    if not args.output:
        _write_csv(sys.stdout, header, rows)
        return EXIT_OK
    # A regular file is replaced atomically: a failed write must not destroy the
    # previous export. A fifo/device/symlink cannot be renamed over (see
    # _must_write_through), so it keeps the direct stream path.
    target = args.output
    try:
        if _must_write_through(target):
            with open(target, 'w', newline='', encoding='utf-8') as handle:
                _write_csv(handle, header, rows)
        else:
            scratch = target + '.tmp'
            try:
                with open(scratch, 'w', newline='', encoding='utf-8') as handle:
                    _write_csv(handle, header, rows)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(scratch, target)
            except OSError:
                try:
                    os.unlink(scratch)
                except OSError:
                    pass
                raise
    except OSError as exc:
        logger.error(f'Error: cannot write {args.output}: {exc}')
        return EXIT_ERROR
    return EXIT_OK


def _write_csv(stream, header, rows):
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
    # Same reason as emit(): surface a broken pipe at the write, not at exit.
    stream.flush()


def resolve_format(configured):
    """Return the output format, falling back to text for an unknown name.

    ``--format`` is argparse-validated, but the config file is free text: an
    unknown value must not reach ``FORMATTERS[...]`` as a KeyError mid-run.
    """
    name = str(configured or 'text').strip().lower()
    if name in STREAM_FORMATS:
        return name
    logger.warning(f'Ignoring unknown format {configured!r}; using text.')
    return 'text'


def run_dashboard(args, cfg):
    """Start the local chart server (blocks until interrupted)."""
    from msi_psu_monitor import dashboard

    return dashboard.serve(host='127.0.0.1', port=args.port, state_dir=_state_dir(cfg))


# ---- argument parsing ---------------------------------------------------


def _watch_interval(value):
    """``--watch`` value converter that lets the config sentinel through.

    argparse applies ``type`` to ``const`` as well, so ``float`` would blow up on
    a bare ``--watch`` (the sentinel) instead of leaving it for main() to resolve
    against ``[monitor] interval``.
    """
    if value == WATCH_FROM_CONFIG:
        return WATCH_FROM_CONFIG
    try:
        return float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f'invalid watch interval: {value!r}') from None


def build_parser():
    parser = argparse.ArgumentParser(
        prog='msi-psu-monitor',
        description='MSI PSU Monitor - read sensors from MSI PSUs via USB HID',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
        + """

Notes:
  - 12V-2x6 per-pin currents and the total 12V current are 5-second rolling averages.
  - Efficiency comes from the 0xE0 bulk payload (offset 32), not a separate register.
  - Pin order is Conn1 pins 1-6, then Conn2 pins 1-6.
  - Local early-warning limits live in [alerts] (power_w, temp_c, pin_max_a,
    pin_imbalance_a, connector_a, rail_12v_a, rail_5v_a, rail_3v3_a; 0 disables one).
    Use --dump-config to print the effective values.
""",
    )
    parser.add_argument(
        '-f',
        '--format',
        choices=list(STREAM_FORMATS),
        default=None,
        help='Output format (default: text)',
    )
    parser.add_argument(
        '-w',
        '--watch',
        nargs='?',
        # No number means "use [monitor] interval" (the config example has always
        # documented that); a string sentinel keeps `--watch 2` distinguishable
        # from bare `--watch`, which a numeric const cannot do.
        const=WATCH_FROM_CONFIG,
        default=None,
        type=_watch_interval,
        help='Watch mode; optional refresh seconds (default: [monitor] interval, 2.0)',
    )
    parser.add_argument(
        '-i',
        '--interval',
        type=float,
        default=None,
        help='Polling interval in seconds (only valid together with --watch)',
    )
    parser.add_argument('-o', '--once', action='store_true', help='Read sensors once and exit')
    parser.add_argument(
        '-O',
        '--output',
        type=str,
        default=None,
        help='Write output to file instead of stdout',
    )
    parser.add_argument(
        '--serial',
        type=str,
        default=None,
        help='Select one of several PSUs by serial number (default: first)',
    )
    parser.add_argument(
        '--fan-mode',
        choices=[FAN_MODE_AUTO, FAN_MODE_PERFORMANCE, FAN_MODE_CUSTOMIZED],
        default=None,
        help='Write the fan control mode (41h) and save it (F1h); '
        'performance is an alias for the PSU curve (auto)',
    )
    parser.add_argument(
        '--fan-duty',
        type=int,
        choices=range(0, 101),
        default=None,
        metavar='0-100',
        help='Custom fan duty in percent (implies --fan-mode customized)',
    )
    parser.add_argument(
        '--zero-fan',
        choices=['on', 'off'],
        default=None,
        help='Enable or disable Zero Fan (43h + F1h; 12+4 models only)',
    )
    parser.add_argument(
        '--buzzer-off',
        action='store_true',
        help='Toggle the 12+4 OCP buzzer switch (C2h; write-only, no read-back; 12+4 models only)',
    )
    parser.add_argument(
        '--set-rail',
        choices=[RAIL_MODE_MULTI, RAIL_MODE_SINGLE],
        default=None,
        help='Switch 12V rail protection mode (C0h + F1h; MEG Ai1000P/Ai1300P only)',
    )
    parser.add_argument(
        '--export',
        action='store_true',
        help='Export the daemon history as CSV',
    )
    parser.add_argument(
        '--from',
        dest='from_spec',
        type=str,
        default=None,
        help='Export window, e.g. 30m, 2h, 7d (required with --export)',
    )
    parser.add_argument(
        '--columns',
        type=str,
        default=None,
        help='Export columns: all,cpu,gpu,12v,5v,3v3,temp,fan,eff (default: all)',
    )
    parser.add_argument(
        '--dashboard',
        action='store_true',
        help='Serve local charts on 127.0.0.1',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=None,
        help='Dashboard port (default: 8899)',
    )
    parser.add_argument(
        '--show-log',
        action='store_true',
        help='Dump PSU black-box alert records (C1h)',
    )
    parser.add_argument(
        '--show-alert-log',
        action='store_true',
        help='Print the local alert log (alerts-*.log in the state directory)',
    )
    parser.add_argument(
        '--ocp',
        action='store_true',
        help='Show the OCP view (C0h/C1h): the 12V-2x6 thresholds and state on the '
        'MPG TS models, the multirail mode flag on the MEG P models',
    )
    parser.add_argument(
        '--dump-thresholds',
        '--ocp-dump',
        dest='dump_thresholds',
        action='store_true',
        help='Print the hardware OCP thresholds (C0h 8 bytes) as text or JSON',
    )
    parser.add_argument(
        '--ocp-set',
        type=_ocp_setting,
        default=None,
        metavar='POINT,DIFF,TRIGGER,DIFF_TRIGGER,WARNING[,on|off]',
        help='Write the 12V-2x6 OCP thresholds (C0h + F1h) and verify by read-back; '
        'MPG TS models only. Protection limits: 10-14 A / 4-8 A / 5-30 s / 5-30 s / '
        '30-240 s',
    )
    parser.add_argument(
        '--load-thresholds',
        '--ocp-load',
        dest='load_thresholds',
        type=str,
        default=None,
        metavar='FILE',
        help='Load OCP thresholds from a JSON file (--dump-thresholds -f json or '
        '--ocp -f json output) and write them with read-back verification',
    )
    parser.add_argument(
        '--no-alerts',
        action='store_true',
        help='Skip the E1h alert poll (default: alerts are checked)',
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Explicit config file (default: /etc/msi-psu-monitor.conf, ~/.config/...)',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true', help='Verbose diagnostics on stderr'
    )
    parser.add_argument('--quiet', '-q', action='store_true', help='Errors only on stderr')
    parser.add_argument(
        '--dump-config',
        action='store_true',
        help='Print the effective configuration (including [alerts] limits) and exit; '
        'no PSU access; text or json',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    return parser


def _validate_args(parser, args):
    """Reject conflicting flag combinations before touching the device."""
    if args.dump_config:
        # The dump reads the config files only. Anything that would touch the
        # device/history/page must be rejected instead of silently ignored.
        if (
            args.once
            or args.watch is not None
            or args.interval is not None
            or args.export
            or args.show_log
            or args.show_alert_log
            or args.ocp
            or args.dashboard
            or args.serial is not None
            or args.port is not None
            or args.from_spec is not None
            or args.columns is not None
            or args.dump_thresholds
            or args.ocp_set is not None
            or args.load_thresholds is not None
            or _write_requested(args)
            or args.format not in (None, 'text', 'json')
        ):
            parser.error(
                '--dump-config prints the effective configuration only: it cannot be '
                'combined with device/history/dashboard/threshold flags or a control '
                'write, and only supports text or json'
            )
        if args.output is not None and not args.output:
            parser.error('--output requires a path')
        if args.config is not None and not args.config:
            parser.error('--config requires a path')
        return
    threshold_dump = args.dump_thresholds
    threshold_write = args.ocp_set is not None or args.load_thresholds is not None
    if threshold_dump and (
        args.ocp
        or args.watch is not None
        or args.export
        or args.show_log
        or args.show_alert_log
        or args.dashboard
        or _write_requested(args)
        or threshold_write
        or args.interval is not None
        or args.port is not None
        or args.from_spec is not None
        or args.columns is not None
    ):
        parser.error(
            '--dump-thresholds reads the hardware OCP configuration only: it cannot be '
            'combined with --ocp, --watch, --export, --show-log, --show-alert-log, '
            '--dashboard, a control write or a threshold write'
        )
    if threshold_dump and args.format not in (None, 'text', 'json'):
        parser.error('--dump-thresholds supports only the text and json formats')
    if threshold_write and (
        args.ocp
        or args.watch is not None
        or args.export
        or args.show_log
        or args.show_alert_log
        or args.dashboard
        or _write_requested(args)
        or args.interval is not None
        or args.port is not None
        or args.from_spec is not None
        or args.columns is not None
    ):
        parser.error(
            'threshold writes (--ocp-set/--load-thresholds) cannot be combined with '
            '--ocp, --watch, --export, --show-log, --show-alert-log, --dashboard or '
            'another control write'
        )
    if threshold_write and args.format not in (None, 'text'):
        parser.error('threshold writes report text; --format does not apply')
    if args.ocp_set is not None and args.load_thresholds is not None:
        parser.error('--ocp-set and --load-thresholds are mutually exclusive')
    if args.load_thresholds is not None and not args.load_thresholds:
        parser.error('--load-thresholds requires a path')
    if args.output is not None and not args.output:
        parser.error('--output requires a path')
    if args.config is not None and not args.config:
        parser.error('--config requires a path')
    if threshold_dump or threshold_write:
        return
    if args.show_log and (
        args.watch is not None or args.export or args.format not in (None, 'text')
    ):
        parser.error('--show-log cannot be combined with --watch, --export or --format')
    if args.show_alert_log and (
        args.watch is not None
        or args.export
        or args.dashboard
        or args.show_log
        or args.ocp
        or args.serial is not None
        or _write_requested(args)
        or args.format not in (None, 'text')
    ):
        parser.error(
            '--show-alert-log reads local files only: it cannot be combined with '
            '--watch, --export, --dashboard, --show-log, --ocp, --serial, --format '
            'or a control write'
        )
    if args.ocp and (
        args.watch is not None
        or args.export
        or args.show_log
        or args.dashboard
        or _write_requested(args)
    ):
        parser.error(
            '--ocp cannot be combined with --watch, --export, --show-log, '
            '--dashboard or a control write'
        )
    if args.export and args.watch is not None:
        parser.error('--export cannot be combined with --watch')
    if args.export and args.format not in (None, 'text'):
        # --export always writes CSV; accepting -f json silently ignored it.
        parser.error('--export writes CSV; --format does not apply')
    if args.export and args.serial is not None:
        # --export reads the local history, not a device; a serial filter would
        # be silently ignored.
        parser.error('--export reads local history; --serial does not apply')
    if _write_requested(args) and args.format not in (None, 'text'):
        # Control-write results are plain text; silently ignoring -f json would
        # hand the caller machine-readable output it did not get.
        parser.error('control writes report text; --format does not apply')
    if args.output is not None and not args.output:
        # `--columns "$COLS"` with COLS unset was the same silent no-op: the flag
        # was accepted and the output went to stdout instead of the named file.
        parser.error('--output requires a path')
    if args.config is not None and not args.config:
        # Same class: `--config "$CONF"` with CONF unset silently searched the
        # default paths and ran on the built-in defaults.
        parser.error('--config requires a path')
    if args.serial is not None and not args.serial:
        # `--serial "$SERIAL"` with SERIAL unset must not become a search for
        # the literal empty serial; the other path-like flags reject this too.
        parser.error('--serial requires a value')
    if (args.from_spec is not None or args.columns is not None) and not args.export:
        parser.error('--from and --columns are only valid together with --export')
    # A non-positive or non-finite interval would busy-loop or raise inside
    # time.sleep() instead of failing here with a usage message.
    if (
        args.watch is not None
        and args.watch != WATCH_FROM_CONFIG
        and not (math.isfinite(args.watch) and args.watch > 0)
    ):
        parser.error('--watch must be a positive number of seconds')
    if args.interval is not None and not (math.isfinite(args.interval) and args.interval > 0):
        parser.error('--interval must be a positive number of seconds')
    if args.interval is not None and args.watch is None:
        # The manual says `-i` is only valid together with `-w`; accepting it made
        # `-i 5` look like it changed the cadence of a single read.
        parser.error('--interval only applies together with --watch')
    if args.dashboard and (
        args.export
        or args.show_log
        or args.watch is not None
        or _write_requested(args)
        or args.once
        or args.serial is not None
    ):
        # The page reads the history files, not the device: --once never gets to
        # "read once and exit", and --serial cannot pick a PSU for it (the page
        # labels whichever serial the daemon last sampled).
        parser.error(
            '--dashboard serves the local page only: it cannot be combined with '
            '--export, --show-log, --watch, --once, --serial or a control write'
        )
    if args.dashboard and args.format not in (None, 'text'):
        parser.error('--dashboard serves the HTML page; --format does not apply')
    if args.dashboard and args.output is not None:
        parser.error('--dashboard serves the HTML page; --output does not apply')
    if args.watch is not None and args.once:
        parser.error('--watch and --once are mutually exclusive')
    if args.watch is not None and args.format not in (None, 'text'):
        parser.error('--watch only supports the text format')
    if _write_requested(args) and (args.show_log or args.export or args.watch is not None):
        parser.error(
            'control writes (--fan-mode/--fan-duty/--zero-fan/--buzzer-off) cannot '
            'be combined with --watch, --export or --show-log'
        )
    if args.fan_mode in (FAN_MODE_AUTO, FAN_MODE_PERFORMANCE) and args.fan_duty is not None:
        parser.error(
            '--fan-duty does not apply to --fan-mode auto/performance (the PSU uses its own curve)'
        )
    if args.port is not None and not 0 <= args.port <= 65535:
        # bind() raises OverflowError, which is not an OSError: it used to escape
        # serve() as a traceback instead of a usage message.
        parser.error('--port must be between 0 and 65535')
    if args.port is not None and not args.dashboard:
        parser.error('--port is only valid together with --dashboard')


def _ini_value(value):
    """Render a config value so --dump-config output stays INI-parseable."""
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if value is None:
        return ''
    return str(value)


def _dump_effective_config(cfg, fmt):
    """Effective config as INI text or JSON, including every known section key."""
    if fmt == 'json':
        return json.dumps({key: cfg[key] for key in sorted(cfg)}, indent=2, sort_keys=True)
    lines = []
    for section in ('monitor', 'alerts', 'daemon', 'fan'):
        options = KNOWN_OPTIONS.get(section)
        if not options:
            continue
        lines.append(f'[{section}]')
        for key in sorted(options):
            if key in cfg:
                lines.append(f'{key} = {_ini_value(cfg[key])}')
        lines.append('')
    return '\n'.join(lines).rstrip()


def _redirect_stdout_to_devnull():
    """Point stdout at /dev/null after a broken pipe, so shutdown cannot re-raise."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
    except (OSError, ValueError):  # pragma: no cover - stdout already replaced
        pass


def main():
    """CLI entry point: a closed stdout pipe is normal shell usage, not a fault.

    ``msi-psu-monitor --once | head -1`` closes the pipe before the frame is
    written. Python turns that into BrokenPipeError; unhandled, the interpreter's
    shutdown flush prints "Exception ignored" and exits 120. Line-buffer stdout
    so the failing write raises (not the flush at exit), and answer 0.
    """
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except (OSError, ValueError):  # pragma: no cover - detached stdout
            pass

    def report_output_error(exc):
        # stderr can be a full disk too; never let the report itself traceback.
        try:
            print(f'Error: cannot write output: {exc}', file=sys.stderr, flush=True)
        except OSError:
            pass
        _redirect_stdout_to_devnull()

    try:
        _main()
    except BrokenPipeError:
        _redirect_stdout_to_devnull()
    except OSError as exc:
        # ENOSPC/EIO on stdout (e.g. > /dev/full): report one line and use the
        # documented exit code 1 instead of the interpreter's 120/traceback.
        report_output_error(exc)
        sys.exit(EXIT_ERROR)
    finally:
        # --help/--version exit through argparse's SystemExit before _main()'s
        # own handler, so a closed pipe can only surface at this final flush.
        try:
            sys.stdout.flush()
        except BrokenPipeError:
            _redirect_stdout_to_devnull()
        except OSError as exc:
            report_output_error(exc)
            sys.exit(EXIT_ERROR)


def _main():
    parser = build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        logger.error(f'Error: {exc}')
        sys.exit(EXIT_ERROR)
    if args.output is None:
        args.output = cfg['output']
    if args.port is None:
        args.port = cfg['port']
    if args.serial is None:
        args.serial = cfg['serial']
    if not args.no_alerts:
        args.no_alerts = cfg['no_alerts']

    verbose = args.verbose or (cfg['verbose'] and not args.quiet)
    quiet = args.quiet or (cfg['quiet'] and not args.verbose)
    setup_logging(verbose=verbose, quiet=quiet)
    # Publish the *effective* levels: downstream code (the --watch banner) has to
    # honour a quiet setting that came from the config file too.
    args.verbose = verbose
    args.quiet = quiet

    # Resolved after logging is configured, so the warning is actually shown.
    if args.format is None:
        args.format = resolve_format(cfg['format'])
    if args.watch is not None and args.format != 'text':
        # The same combination on the command line is a usage error
        # (_validate_args), but a config file arrives after that check; printing
        # text frames without a word was the silent half of it.
        logger.warning(
            f'--watch prints the text format only; ignoring [monitor] format = {cfg["format"]!r}'
        )
        args.format = 'text'
    threshold_write = args.ocp_set is not None or args.load_thresholds is not None
    if (
        args.format != 'text'
        and (
            args.dashboard
            or args.export
            or args.show_log
            or args.show_alert_log
            or threshold_write
            or _write_requested(args)
        )
    ) or ((args.dump_config or args.dump_thresholds) and args.format not in ('text', 'json')):
        # These modes have a fixed output shape; accepting [monitor] format from
        # the config file and silently printing text/CSV anyway is the same
        # silent no-op the CLI-level checks reject.
        logger.warning(
            f'this mode has a fixed output format; ignoring [monitor] format = {cfg["format"]!r}'
        )
        args.format = 'text'

    if args.dump_config:
        emit(_dump_effective_config(cfg, args.format), args.output)
        sys.exit(EXIT_OK)
    if args.dashboard:
        sys.exit(run_dashboard(args, cfg))
    if args.export:
        sys.exit(run_export(args, cfg))
    if args.show_alert_log:
        sys.exit(run_show_alert_log(args, cfg))

    if args.once or args.watch is None:
        debounce = 1
    else:
        debounce = cfg['consecutive_required']

    dev_path, available, blocked = resolve_device(args.serial)
    if dev_path is None:
        if args.serial is not None:
            if available:
                logger.error(
                    f'Error: no PSU with serial {args.serial!r}. Available: {", ".join(available)}'
                )
            elif blocked:
                # Every candidate device refused to open; "Available: none" would
                # send the user hunting for a PSU that is plugged in right there.
                logger.error(
                    f'Error: could not open any MSI PSU device while looking for '
                    f'serial {args.serial!r}. Run as root, or install the udev rule.'
                )
            else:
                logger.error(f'Error: no PSU with serial {args.serial!r}. Available: none')
        else:
            logger.error('Error: MSI PSU not found. Is it connected via USB?')
        sys.exit(EXIT_ERROR)

    state_dir = _state_dir(cfg)
    monitor_state = stats.MonitorState.load(stats.state_path(state_dir))
    engine = AlertEngine(consecutive_required=debounce)

    psu = None
    try:
        psu = open_psu(dev_path)
        psu.open()
        psu.init()

        if args.dump_thresholds or args.ocp_set is not None or args.load_thresholds is not None:
            sys.exit(run_ocp_thresholds(psu, args))
        if _write_requested(args):
            sys.exit(run_write_controls(psu, args))
        if args.show_log:
            emit(format_blackbox(psu.read_blackbox()), args.output)
            sys.exit(EXIT_OK)
        if args.ocp:
            sys.exit(run_ocp(psu, args))
        if args.watch is not None:
            sys.exit(run_watch(psu, args, cfg, monitor_state, engine))
        sys.exit(run_once(psu, args, cfg, monitor_state, engine))
    except OutputError as exc:
        logger.error(f'Error: {exc}')
        sys.exit(EXIT_ERROR)
    except DeviceBusyError:
        logger.error('Error: the PSU is busy (the daemon or another run holds it).')
        sys.exit(EXIT_ERROR)
    except PermissionError:
        logger.error('Error: Permission denied. Run as root.')
        sys.exit(EXIT_ERROR)
    except BrokenPipeError:
        # Handled by main(): redirect stdout and answer 0. Re-raise so the
        # generic handler below cannot turn normal `| head` usage into exit 1.
        raise
    except Exception as exc:
        logger.error(f'Error: {exc}')
        if verbose:
            import traceback

            traceback.print_exc()
        sys.exit(EXIT_ERROR)
    finally:
        if psu is not None:
            psu.close()


if __name__ == '__main__':
    main()
