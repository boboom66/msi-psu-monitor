#!/usr/bin/env python3
"""MSI PSU Monitor - CLI tool for reading sensors from MSI PSUs via USB HID.

Supports MSI MPG Ai1600TS (with GPU Safeguard+ per-pin current monitoring),
MEG Ai1600(T), MEG Ai1300P, and MEG Ai1000P power supplies.

Usage:
    msi-psu-monitor --once          # One-shot sensor read
    msi-psu-monitor --watch         # Continuous monitoring
    msi-psu-monitor --format json   # JSON output
    msi-psu-monitor --format prometheus --output /path/file.prom  # Prometheus output
"""

import argparse
import json
import logging
import os
import sys
import time

from msi_psu_monitor import __version__
from msi_psu_monitor.alerts import AlertEngine, format_alert_line
from msi_psu_monitor.config import load_config
from msi_psu_monitor.protocol import MSIPSU, HIDDevice, detect_device

EXIT_OK = 0
EXIT_ALERT = 2
EXIT_ERROR = 1

logger = logging.getLogger('msi_psu')


def setup_logging(verbose=False, quiet=False):
    """Route diagnostics to stderr; stdout stays clean for machine output."""
    level = logging.DEBUG if verbose else (logging.ERROR if quiet else logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)


def format_text(sensors):
    """Format sensor data as human-readable text."""
    lines = []
    lines.append(f'MSI PSU: {sensors.get("product", "unknown")}')
    lines.append(f'  Vendor: {sensors.get("vendor", "")}')
    lines.append(f'  FW: {sensors.get("fw_revision", "")}  Serial: {sensors.get("serial", "")}')
    lines.append('')

    if 'error' in sensors:
        lines.append(f'  ERROR   : {sensors["error"]}')
        return '\n'.join(lines)

    for key in ['vout_12v', 'vout_5v', 'vout_3v3']:
        if key in sensors:
            v, unit = sensors[key]
            label = key.replace('vout_', '+').replace('_', '.').upper()
            lines.append(f'  {label:8s}: {v:8.3f} {unit}')

    for key in ['iout_12v_total', 'iout_5v', 'iout_3v3']:
        if key in sensors:
            v, unit = sensors[key]
            label = key.replace('iout_', '').replace('_', ' ').upper()
            lines.append(f'  {label:8s}: {v:8.3f} {unit}')

    if 'iout_pins' in sensors:
        pins, unit = sensors['iout_pins']
        lines.append('  Per-pin currents (12V-2x6 GPU Safeguard+):')
        for i, pin_val in enumerate(pins):
            conn = 1 if i < 6 else 2
            pin = i % 6 + 1
            lines.append(f'    Conn{conn} Pin{pin}: {pin_val:8.3f} {unit}')

    if 'power_total' in sensors:
        v, unit = sensors['power_total']
        lines.append(f'  POWER   : {v:8.1f} {unit}')
    if 'efficiency' in sensors:
        v, unit = sensors['efficiency']
        lines.append(f'  EFF     : {v:8.2f} {unit}')
    if 'temp' in sensors:
        v, unit = sensors['temp']
        lines.append(f'  TEMP    : {v:8.1f} {unit}')
    if 'fan_rpm' in sensors:
        v, unit = sensors['fan_rpm']
        lines.append(f'  FAN     : {v:8.0f} {unit}')

    for key in ['uptime', 'uptime_total']:
        if key in sensors:
            secs = sensors[key]
            days = secs // 86400
            hours = (secs % 86400) // 3600
            mins = (secs % 3600) // 60
            label = 'Uptime' if key == 'uptime' else 'Total uptime'
            lines.append(f'  {label:11s}: {days}d {hours:02d}:{mins:02d}:{secs % 60:02d}')

    return '\n'.join(lines)


def format_json(sensors):
    """Format sensor data as JSON."""
    out = {}
    for k, v in sensors.items():
        if isinstance(v, tuple):
            out[k] = {'value': v[0], 'unit': v[1]}
        else:
            out[k] = v
    return json.dumps(out, indent=2)


def format_prometheus(sensors):
    """Format sensor data for Prometheus node_exporter textfile collector."""
    lines = []
    lines.append('# HELP msi_psu_info MSI PSU information')
    lines.append('# TYPE msi_psu_info gauge')
    lines.append(
        f'msi_psu_info{{product="{sensors.get("product", "")}",'
        f'vendor="{sensors.get("vendor", "")}",'
        f'fw="{sensors.get("fw_revision", "")}"}} 1'
    )

    prefix = 'msi_psu'
    for key in ['vout_12v', 'vout_5v', 'vout_3v3']:
        if key in sensors:
            v, unit = sensors[key]
            name = key.replace('vout_', 'voltage_')
            lines.append(f'# HELP {prefix}_{name} {name} in volts')
            lines.append(f'# TYPE {prefix}_{name} gauge')
            lines.append(f'{prefix}_{name}{{rail="{key}"}} {v}')

    for key in ['iout_12v_total', 'iout_5v', 'iout_3v3']:
        if key in sensors:
            v, unit = sensors[key]
            name = key.replace('iout_', 'current_')
            lines.append(f'# HELP {prefix}_{name} {name} in amps')
            lines.append(f'# TYPE {prefix}_{name} gauge')
            lines.append(f'{prefix}_{name}{{rail="{key}"}} {v}')

    if 'iout_pins' in sensors:
        pins, unit = sensors['iout_pins']
        for i, pin_val in enumerate(pins):
            conn = 1 if i < 6 else 2
            pin = i % 6 + 1
            lines.append('# HELP msi_psu_pin_current Per-pin current on 12V-2x6 connector in amps')
            lines.append('# TYPE msi_psu_pin_current gauge')
            lines.append(f'msi_psu_pin_current{{connector="{conn}",pin="{pin}"}} {pin_val}')

    if 'power_total' in sensors:
        v, unit = sensors['power_total']
        lines.append('# HELP msi_psu_power_total Total output power in watts')
        lines.append('# TYPE msi_psu_power_total gauge')
        lines.append(f'msi_psu_power_total {{}} {v}')

    if 'efficiency' in sensors:
        v, unit = sensors['efficiency']
        lines.append('# HELP msi_psu_efficiency Efficiency in percent')
        lines.append('# TYPE msi_psu_efficiency gauge')
        lines.append(f'msi_psu_efficiency {{}} {v}')

    if 'temp' in sensors:
        v, unit = sensors['temp']
        lines.append('# HELP msi_psu_temperature Temperature in celsius')
        lines.append('# TYPE msi_psu_temperature gauge')
        lines.append(f'msi_psu_temperature {{}} {v}')

    if 'fan_rpm' in sensors:
        v, unit = sensors['fan_rpm']
        lines.append('# HELP msi_psu_fan_speed Fan speed in RPM')
        lines.append('# TYPE msi_psu_fan_speed gauge')
        lines.append(f'msi_psu_fan_speed {{}} {v}')

    for alert_name in sensors.get('alerts', []):
        lines.append('# HELP msi_psu_alert Active PSU alert (E1h bit set)')
        lines.append('# TYPE msi_psu_alert gauge')
        lines.append(f'msi_psu_alert{{alert="{alert_name}"}} 1')

    for key in ['uptime', 'uptime_total']:
        if key in sensors:
            lines.append(f'# HELP {prefix}_{key} {key} in seconds')
            lines.append(f'# TYPE {prefix}_{key} counter')
            lines.append(f'{prefix}_{key}{{}} {sensors[key]}')

    return '\n'.join(lines)


def format_blackbox(records):
    """Format C1h black-box records as human-readable text."""
    if not records:
        return 'No black-box alert records stored.'
    lines = ['Black-box alert records (newest first):']
    for rec in records:
        lines.append(
            f'  #{rec["info_id"]} set={rec["pin_set"]} status={rec["status"]} '
            f'run_time={rec["run_time"]}s total={rec["total_time"]}s '
            f'count={rec["total_count"]} pins={rec["pins_1_6"]}'
        )
    return '\n'.join(lines)


def check_alerts(psu, engine):
    """Poll E1h once, feed the engine, print newly fired alerts.

    Returns the list of newly fired Alert objects (possibly empty).
    A PSU that does not answer E1h is treated as no-data, never as OK.
    """
    status = psu.read_alert_status()
    if status is None:
        return []
    fired = engine.update(status)
    for alert in fired:
        logger.warning(format_alert_line(alert))
    return fired


def main():
    parser = argparse.ArgumentParser(
        description='MSI PSU Monitor - read sensors from MSI PSUs via USB HID',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--format',
        '-f',
        choices=['text', 'json', 'prometheus'],
        default=None,
        help='Output format (default: text)',
    )
    parser.add_argument(
        '--watch',
        '-w',
        action='store_true',
        help='Watch mode: continuously read and display sensors',
    )
    parser.add_argument(
        '--interval',
        '-i',
        type=float,
        default=None,
        help='Polling interval in seconds (default: 2.0)',
    )
    parser.add_argument('--once', '-o', action='store_true', help='Read sensors once and exit')
    parser.add_argument(
        '--output', '-O', type=str, default=None, help='Write output to file instead of stdout'
    )
    parser.add_argument(
        '--no-alerts',
        action='store_true',
        help='Skip the E1h alert poll (default: alerts are checked)',
    )
    parser.add_argument(
        '--show-log',
        action='store_true',
        help='Dump PSU black-box alert records (C1h) and exit',
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
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.interval is None:
        args.interval = cfg['interval']
    if args.format is None:
        args.format = cfg['format']
    if args.output is None:
        args.output = cfg['output']
    if not args.no_alerts:
        args.no_alerts = cfg['no_alerts']
    verbose = args.verbose or (cfg['verbose'] and not args.quiet)
    quiet = args.quiet or (cfg['quiet'] and not args.verbose)
    setup_logging(verbose=verbose, quiet=quiet)
    if args.once or not args.watch:
        debounce = 1
    else:
        debounce = cfg['consecutive_required']

    dev_path = detect_device()
    if dev_path is None:
        logger.error('Error: MSI PSU not found. Is it connected via USB?')
        sys.exit(EXIT_ERROR)

    psu = None
    try:
        psu = MSIPSU(HIDDevice(dev_path))
        psu.open()
        psu.init()

        if args.show_log:
            print(format_blackbox(psu.read_blackbox()))
            sys.exit(EXIT_OK)

        if args.once or not args.watch:
            sensors = psu.get_sensors()
            exit_code = EXIT_OK
            if 'error' in sensors:
                logger.error(f'Error: {sensors["error"]}')
                exit_code = EXIT_ERROR
            elif not args.no_alerts:
                fired = check_alerts(psu, AlertEngine(consecutive_required=debounce))
                if fired:
                    sensors['alerts'] = [alert.name for alert in fired]
                    exit_code = EXIT_ALERT
            if args.format == 'text':
                output = format_text(sensors)
            elif args.format == 'json':
                output = format_json(sensors)
            else:
                output = format_prometheus(sensors)

            if args.output:
                with open(args.output, 'w') as f:
                    f.write(output + '\n')
            else:
                print(output)
            sys.exit(exit_code)

        # Watch mode: edge-triggered engine, alerts print once when raised.
        engine = AlertEngine(consecutive_required=debounce)
        try:
            while True:
                sensors = psu.get_sensors()
                if 'error' in sensors:
                    logger.error(f'Error: {sensors["error"]}')
                    sys.exit(EXIT_ERROR)
                if not args.no_alerts:
                    check_alerts(psu, engine)
                os.system('clear' if sys.platform == 'linux' else 'cls')
                print(format_text(sensors))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            pass

    except PermissionError:
        logger.error('Error: Permission denied. Run as root.')
        sys.exit(EXIT_ERROR)
    except Exception as e:
        logger.error(f'Error: {e}')
        import traceback

        traceback.print_exc()
        sys.exit(EXIT_ERROR)
    finally:
        if psu is not None:
            psu.close()


if __name__ == '__main__':
    main()


