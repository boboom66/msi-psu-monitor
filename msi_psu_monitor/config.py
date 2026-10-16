"""INI configuration for msi-psu-monitor (stdlib only, Python 3.10+).

Precedence: CLI flags > config file > built-in defaults.
Files: /etc/msi-psu-monitor.conf, then ~/.config/msi-psu-monitor/config.ini.
"""

import configparser
import os

CONFIG_FILES = (
    '/etc/msi-psu-monitor.conf',
    os.path.expanduser('~/.config/msi-psu-monitor/config.ini'),
)

DEFAULTS = {
    'interval': 2.0,
    'format': 'text',
    'output': None,
    'verbose': False,
    'quiet': False,
    'no_alerts': False,
    'serial': None,
    'consecutive_required': 2,
    'state_dir': None,
    'prom_path': None,
    'port': 8899,
    'sample_interval': 1.0,
    'prom_interval': 30.0,
    'history_interval': 60.0,
    'retention_days': 30,
}


def load_config(path=None):
    """Load configuration, returning a dict of effective values.

    Args:
        path: Explicit config file (--config), or None to search defaults.
    """
    cfg = dict(DEFAULTS)
    files = [path] if path else [f for f in CONFIG_FILES if os.path.exists(f)]
    parser = configparser.ConfigParser()
    parser.read(files)
    monitor = parser['monitor'] if parser.has_section('monitor') else {}
    alerts = parser['alerts'] if parser.has_section('alerts') else {}
    cfg['interval'] = _as_float(monitor.get('interval'), cfg['interval'])
    cfg['format'] = monitor.get('format', cfg['format'])
    cfg['output'] = monitor.get('output', cfg['output'])
    cfg['verbose'] = _as_bool(monitor.get('verbose'), cfg['verbose'])
    cfg['quiet'] = _as_bool(monitor.get('quiet'), cfg['quiet'])
    cfg['no_alerts'] = _as_bool(monitor.get('no_alerts'), cfg['no_alerts'])
    cfg['serial'] = monitor.get('serial', cfg['serial']) or None
    cfg['consecutive_required'] = _as_int(
        alerts.get('consecutive_required'), cfg['consecutive_required']
    )
    if cfg['consecutive_required'] < 1:
        cfg['consecutive_required'] = 1

    daemon = parser['daemon'] if parser.has_section('daemon') else {}
    cfg['state_dir'] = daemon.get('state_dir', cfg['state_dir']) or None
    cfg['prom_path'] = daemon.get('prom_path', cfg['prom_path']) or None
    cfg['port'] = _as_int(daemon.get('port'), cfg['port'])
    cfg['sample_interval'] = _as_float(daemon.get('sample_interval'), cfg['sample_interval'])
    cfg['prom_interval'] = _as_float(daemon.get('prom_interval'), cfg['prom_interval'])
    cfg['history_interval'] = _as_float(daemon.get('history_interval'), cfg['history_interval'])
    cfg['retention_days'] = _as_int(daemon.get('retention_days'), cfg['retention_days'])
    if cfg['sample_interval'] <= 0:
        cfg['sample_interval'] = DEFAULTS['sample_interval']
    if cfg['prom_interval'] <= 0:
        cfg['prom_interval'] = DEFAULTS['prom_interval']
    if cfg['history_interval'] <= 0:
        cfg['history_interval'] = DEFAULTS['history_interval']
    if cfg['retention_days'] < 1:
        cfg['retention_days'] = DEFAULTS['retention_days']
    return cfg


def _as_float(raw, fallback):
    try:
        return float(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _as_int(raw, fallback):
    try:
        return int(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _as_bool(raw, fallback):
    if raw is None:
        return fallback
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
