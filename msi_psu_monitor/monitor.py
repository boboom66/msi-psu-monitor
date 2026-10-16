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
from msi_psu_monitor.alerts import AlertEngine, evaluate_pin_alerts, format_alert_line
from msi_psu_monitor.config import ConfigError, load_config
from msi_psu_monitor.protocol import MSIPSU, DeviceBusyError, HIDDevice, detect_device

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ALERT = 2

FAN_MODE_AUTO = 'auto'
FAN_MODE_CUSTOMIZED = 'customized'
#: `--watch` without a number: take [monitor] interval from the config file.
WATCH_FROM_CONFIG = 'config'
_FAN_MODE_TO_BYTE = {FAN_MODE_AUTO: 1, FAN_MODE_CUSTOMIZED: 3}
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
    """Escape a Prometheus label value."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')


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
        lines.append(f'msi_psu_cpu_watts {{}} {watts[0]}')
        lines.append(
            '# HELP msi_psu_gpu_watts Wattage drawn by the GPU rails (12V3+12V4+12V5) in watts'
        )
        lines.append('# TYPE msi_psu_gpu_watts gauge')
        lines.append(f'msi_psu_gpu_watts {{}} {watts[1]}')
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
        lines.append(f'msi_psu_power_total {{}} {value}')
    if 'power_avg' in sensors:
        lines.append('# HELP msi_psu_power_avg Cumulative mean output power in watts')
        lines.append('# TYPE msi_psu_power_avg gauge')
        lines.append(f'msi_psu_power_avg {{}} {_value(sensors["power_avg"])}')
    if 'efficiency' in sensors:
        value, _ = sensors['efficiency']
        lines.append('# HELP msi_psu_efficiency Efficiency in percent')
        lines.append('# TYPE msi_psu_efficiency gauge')
        lines.append(f'msi_psu_efficiency {{}} {value}')
    if 'efficiency_avg' in sensors:
        lines.append('# HELP msi_psu_efficiency_avg Cumulative mean efficiency in percent')
        lines.append('# TYPE msi_psu_efficiency_avg gauge')
        lines.append(f'msi_psu_efficiency_avg {{}} {_value(sensors["efficiency_avg"])}')
    if 'temp' in sensors:
        value, _ = sensors['temp']
        lines.append('# HELP msi_psu_temperature Temperature in celsius')
        lines.append('# TYPE msi_psu_temperature gauge')
        lines.append(f'msi_psu_temperature {{}} {value}')
    if 'fan_rpm' in sensors:
        value, _ = sensors['fan_rpm']
        lines.append('# HELP msi_psu_fan_speed Fan speed in RPM')
        lines.append('# TYPE msi_psu_fan_speed gauge')
        lines.append(f'msi_psu_fan_speed {{}} {value}')
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
        lines.append('# HELP msi_psu_total_energy_kwh Cumulative energy drawn in kWh')
        lines.append('# TYPE msi_psu_total_energy_kwh counter')
        lines.append(f'msi_psu_total_energy_kwh {{}} {_value(sensors["total_energy"])}')

    alerts = sensors.get('alerts')
    if alerts:
        lines.append('# HELP msi_psu_alert Active PSU alert (E1h bit or per-pin mirror)')
        lines.append('# TYPE msi_psu_alert gauge')
        for alert_name in alerts:
            lines.append(f'msi_psu_alert{{alert="{_label(alert_name)}"}} 1')

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
    """Format C1h black-box records as human-readable text (newest first)."""
    if not records:
        return 'No black-box alert records stored.'
    lines = ['GPU Safeguard+ alert log (black box, last 10, newest first)', '']
    for record in records:
        status = _BLACKBOX_STATUS.get(record.get('status'), f'status {record.get("status")}')
        lines.append(
            f'#{record["info_id"]}  Conn{record.get("pin_set")}   {status}   '
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


def collect_alerts(psu, engine, sensors):
    """Merge E1h hardware bits with the software per-pin mirror.

    Returns ``(fired, active_names, have_e1h)``. It is True only when
    the PSU answered the E1h status read. The software mirror is a second,
    independent measurement, but it only sees the OCP pins and their imbalance:
    it cannot see the E1h-only bits (``opp``, ``otp``, and ``fan`` -- the one
    critical bit, "shutdown imminent"), so a mirror-only poll must not be
    rendered as "Normal". A PSU that answers neither source is not complete
    either, so callers never read a silent read failure as "all OK".

    Names the caller leaves out keep the state the engine already has: a failed
    E1h read never clears an alert that is already firing.
    """
    active = {}
    have_e1h = False
    hardware = psu.read_alert_status()
    if hardware:
        active.update({name: bool(value) for name, value in hardware.items()})
        have_e1h = True

    pins = sensors.get('iout_pins')
    software = evaluate_pin_alerts(pins[0] if isinstance(pins, tuple) else pins)
    if software:
        for name, value in software.items():
            active[name] = active.get(name, False) or value

    if not active and not have_e1h:
        return [], [], False

    fired = engine.update(active)
    for alert in fired:
        logger.warning(format_alert_line(alert))
    return fired, engine.active_alerts, have_e1h


def status_from(active_names, have_e1h):
    """Render the ``12V-2x6 Status`` label.

    ``have_e1h`` says whether the E1h bitmap answered; without it the honest
    answer is ``Unknown`` even when the pin mirror found nothing wrong.
    """
    if active_names:
        return ', '.join(active_names)
    return STATUS_NORMAL if have_e1h else STATUS_UNKNOWN


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
    if not power or not efficiency:
        return None
    return float(power), float(efficiency)


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


def emit(output, output_path):
    """Write ``output`` to stdout, or replace ``output_path`` atomically."""
    if not output_path:
        print(output)
        return
    if os.path.exists(output_path) and not os.path.isfile(output_path):
        # A fifo or /dev/stdout cannot be replaced, only written into.
        with open(output_path, 'w') as handle:
            handle.write(output + '\n')
        return
    stats.atomic_write_text(output_path, output + '\n')


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
        _, active, have_e1h = collect_alerts(psu, engine, sensors)
        sensors['alerts'] = active
        sensors['status'] = status_from(active, have_e1h)
    apply_stats(sensors, monitor_state)
    if monitor_state is not None:
        monitor_state.prune()
        monitor_state.save(stats.state_path(_state_dir(cfg)))

    emit(FORMATTERS[args.format](sensors), args.output)
    # An active alert outranks a failed payload read: the E1h bit is a separate
    # register and is the safety-critical signal, so it must reach exit 2 even
    # when the sensor payload is missing.
    if sensors.get('alerts'):
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
                _, active, have_e1h = collect_alerts(psu, engine, sensors)
                sensors['alerts'] = active
                sensors['status'] = status_from(active, have_e1h)
            apply_stats(sensors, monitor_state)

            now = time.time()
            if monitor_state is not None and now - last_save >= 30.0:
                monitor_state.prune()
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
        mode: 'auto'/'customized', or None to infer 'customized' from a duty.
        duty: 0-100 for 'customized'; None keeps whatever the PSU reports.

    Returns:
        ``(mode, duty)`` as actually applied, or None when the PSU refused
        (write NAK or a read-back that disagrees with what was sent).
    """
    mode = mode or (FAN_MODE_CUSTOMIZED if duty is not None else FAN_MODE_AUTO)
    if mode == FAN_MODE_AUTO:
        duty = 0
    elif duty is None:
        current = psu.read_fan_setting()
        duty = current[1] if current else 0

    target_mode = _FAN_MODE_TO_BYTE[mode]
    for _ in range(3):
        if not psu.set_fan_mode(target_mode, duty):
            continue
        setting = psu.read_fan_setting()
        if setting and setting[0] == target_mode and (mode == FAN_MODE_AUTO or setting[1] == duty):
            return (mode, duty)
    return None


def run_fan_write(psu, mode, duty, output=None):
    """Apply the fan setting and describe the result (stdout or ``-O`` file)."""
    applied = apply_fan_setting(psu, mode, duty)
    if applied is None:
        logger.error('Error: the PSU did not accept the fan setting (read-back mismatch).')
        return EXIT_ERROR
    mode, duty = applied
    duty_text = '' if mode == FAN_MODE_AUTO else f'   Duty: {duty}%'
    emit(f'Fan mode: {mode}{duty_text}', output)
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

    header, rows = stats.build_export(_state_dir(cfg), time.time() - window, columns)
    if not args.output:
        _write_csv(sys.stdout, header, rows)
        return EXIT_OK
    # The CSV is streamed, so it is written in place; a failed write is reported
    # rather than left behind as a silently truncated file (or a traceback).
    try:
        with open(args.output, 'w', newline='') as handle:
            _write_csv(handle, header, rows)
    except OSError as exc:
        logger.error(f'Error: cannot write {args.output}: {exc}')
        return EXIT_ERROR
    return EXIT_OK


def _write_csv(stream, header, rows):
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)


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
        epilog=__doc__,
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
        choices=[FAN_MODE_AUTO, FAN_MODE_CUSTOMIZED],
        default=None,
        help='Write the fan control mode (41h) and save it (F1h)',
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
        '--ocp',
        action='store_true',
        help='Show the OCP view (C0h/C1h): the 12V-2x6 thresholds and state on the '
        'MPG TS models, the multirail mode flag on the MEG P models',
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
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    return parser


def _validate_args(parser, args):
    """Reject conflicting flag combinations before touching the device."""
    if args.show_log and (
        args.watch is not None or args.export or args.format not in (None, 'text')
    ):
        parser.error('--show-log cannot be combined with --watch, --export or --format')
    if args.ocp and (
        args.watch is not None
        or args.export
        or args.show_log
        or args.dashboard
        or args.fan_mode
        or args.fan_duty is not None
    ):
        parser.error(
            '--ocp cannot be combined with --watch, --export, --show-log, '
            '--dashboard or a fan write'
        )
    if args.export and args.watch is not None:
        parser.error('--export cannot be combined with --watch')
    if args.output is not None and not args.output:
        # `--columns "$COLS"` with COLS unset was the same silent no-op: the flag
        # was accepted and the output went to stdout instead of the named file.
        parser.error('--output requires a path')
    if args.config is not None and not args.config:
        # Same class: `--config "$CONF"` with CONF unset silently searched the
        # default paths and ran on the built-in defaults.
        parser.error('--config requires a path')
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
        or args.fan_mode
        or args.fan_duty is not None
        or args.once
        or args.serial is not None
    ):
        # The page reads the history files, not the device: --once never gets to
        # "read once and exit", and --serial cannot pick a PSU for it (the page
        # labels whichever serial the daemon last sampled).
        parser.error(
            '--dashboard serves the local page only: it cannot be combined with '
            '--export, --show-log, --watch, --once, --serial or a fan write'
        )
    if args.dashboard and args.format not in (None, 'text'):
        parser.error('--dashboard serves the HTML page; --format does not apply')
    if args.dashboard and args.output is not None:
        parser.error('--dashboard serves the HTML page; --output does not apply')
    if args.watch is not None and args.once:
        parser.error('--watch and --once are mutually exclusive')
    if args.watch is not None and args.format not in (None, 'text'):
        parser.error('--watch only supports the text format')
    if (args.fan_mode or args.fan_duty is not None) and (
        args.show_log or args.export or args.watch is not None
    ):
        parser.error(
            '--fan-mode/--fan-duty cannot be combined with --watch, --export or --show-log'
        )
    if args.fan_mode == FAN_MODE_AUTO and args.fan_duty is not None:
        parser.error('--fan-duty does not apply to --fan-mode auto (the PSU uses its own curve)')
    if args.port is not None and not 0 <= args.port <= 65535:
        # bind() raises OverflowError, which is not an OSError: it used to escape
        # serve() as a traceback instead of a usage message.
        parser.error('--port must be between 0 and 65535')
    if args.port is not None and not args.dashboard:
        parser.error('--port is only valid together with --dashboard')


def main():
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

    if args.dashboard:
        sys.exit(run_dashboard(args, cfg))
    if args.export:
        sys.exit(run_export(args, cfg))

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

        if args.fan_mode or args.fan_duty is not None:
            sys.exit(run_fan_write(psu, args.fan_mode, args.fan_duty, args.output))
        if args.show_log:
            emit(format_blackbox(psu.read_blackbox()), args.output)
            sys.exit(EXIT_OK)
        if args.ocp:
            sys.exit(run_ocp(psu, args))
        if args.watch is not None:
            sys.exit(run_watch(psu, args, cfg, monitor_state, engine))
        sys.exit(run_once(psu, args, cfg, monitor_state, engine))
    except DeviceBusyError:
        logger.error('Error: the PSU is busy (the daemon or another run holds it).')
        sys.exit(EXIT_ERROR)
    except PermissionError:
        logger.error('Error: Permission denied. Run as root.')
        sys.exit(EXIT_ERROR)
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
