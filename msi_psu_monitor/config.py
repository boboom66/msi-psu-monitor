"""INI configuration for msi-psu-monitor (stdlib only, Python 3.10+).

Precedence: CLI flags > config file > built-in defaults.
Files: /etc/msi-psu-monitor.conf, then ~/.config/msi-psu-monitor/config.ini.
"""

import configparser
import logging
import math
import os

logger = logging.getLogger('msi_psu.config')


class ConfigError(ValueError):
    """A config file the user asked for cannot be used (missing or malformed)."""


# Kept as literal strings so config.py stays importable on its own; monitor.py
# owns the byte mapping (1 = auto, 3 = customized).
FAN_MODES = ('auto', 'performance', 'customized')

CONFIG_FILES = (
    '/etc/msi-psu-monitor.conf',
    os.path.expanduser('~/.config/msi-psu-monitor/config.ini'),
)

#: Options each section understands. Anything else is a typo the loader would
#: otherwise ignore silently -- a misspelled ``intervall`` just keeps the default,
#: which is exactly the kind of failure an operator cannot see.
KNOWN_OPTIONS = {
    'monitor': {'interval', 'format', 'output', 'verbose', 'quiet', 'no_alerts', 'serial'},
    'alerts': {
        'consecutive_required',
        'power_w',
        'temp_c',
        'pin_max_a',
        'pin_imbalance_a',
        'connector_a',
        'rail_12v_a',
        'rail_5v_a',
        'rail_3v3_a',
    },
    'daemon': {
        'state_dir',
        'prom_path',
        'port',
        'sample_interval',
        'prom_interval',
        'history_interval',
        'retention_days',
        'alert_log',
        'live_snapshot',
    },
    'fan': {'mode', 'duty', 'zero_fan'},
}

DEFAULTS = {
    'interval': 2.0,
    'format': 'text',
    'output': None,
    'verbose': False,
    'quiet': False,
    'no_alerts': False,
    'serial': None,
    'consecutive_required': 2,
    # Local early-warning limits (software, not PSU protection). Initial values
    # are the REQ-14 draft: 1200 W total, 70 C internal, 12 A per pin, 5 A pin
    # spread, 50 A per 12V-2x6 connector (600 W at 12 V), and the product-spec
    # rail currents. 0 disables a limit. Tune after real-hardware acceptance.
    'power_w': 1200.0,
    'temp_c': 70.0,
    'pin_max_a': 12.0,
    'pin_imbalance_a': 5.0,
    'connector_a': 50.0,
    'rail_12v_a': 108.33,
    'rail_5v_a': 22.0,
    'rail_3v3_a': 22.0,
    'state_dir': None,
    'prom_path': None,
    'port': 8899,
    'sample_interval': 1.0,
    'prom_interval': 30.0,
    'history_interval': 60.0,
    'retention_days': 30,
    'alert_log': True,
    'live_snapshot': True,
    'fan_mode': None,
    'fan_duty': None,
    'fan_zero_fan': None,
}


def load_config(path=None):
    """Load configuration, returning a dict of effective values.

    Args:
        path: Explicit config file (--config), or None to search defaults.
    """
    cfg = dict(DEFAULTS)
    if path is not None and not str(path).strip():
        # `--config ""` (a $CONF that was never set) used to mean "search the
        # default paths", i.e. silently run on defaults instead of on the file
        # the user named -- the same silent no-op as `-O ""` and `--from ""`.
        raise ConfigError('config file path is empty')
    files = [path] if path else [f for f in CONFIG_FILES if os.path.exists(f)]
    # No interpolation: these are plain values, and the default BasicInterpolation
    # turns a stray '%' (a path, a duty comment) into InterpolationSyntaxError at
    # .get() time -- outside the except below, so it escaped as a traceback.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        # utf-8-sig: UTF-8 regardless of the service manager's locale, and a
        # BOM saved by a Windows editor is tolerated instead of becoming an
        # "unknown section" warning on the first line.
        read = parser.read(files, encoding='utf-8-sig')
    except (configparser.Error, UnicodeDecodeError) as exc:
        # A malformed file would otherwise escape as a traceback from main().
        # UnicodeDecodeError (a Latin-1 or UTF-16 file a Windows editor saved,
        # or one bad byte) is not a configparser.Error and comes out of
        # ConfigParser.read(), which only catches OSError around the open().
        raise ConfigError(f'invalid config file: {exc}') from exc
    if path and not read:
        # Silently falling back to the defaults would leave the user staring at
        # settings that are not the ones they wrote.
        raise ConfigError(f'config file not found or unreadable: {path}')
    for section in parser.sections():
        known = KNOWN_OPTIONS.get(section)
        if known is None:
            logger.warning(f'Ignoring unknown config section [{section}].')
            continue
        for option in parser[section]:
            if option not in known:
                logger.warning(f'Ignoring unknown option [{section}] {option}.')
    monitor = parser['monitor'] if parser.has_section('monitor') else {}
    alerts = parser['alerts'] if parser.has_section('alerts') else {}
    cfg['interval'] = _as_float(monitor.get('interval'), cfg['interval'])
    if cfg['interval'] <= 0:
        # A bare --watch uses this value; 0 is a busy loop and a negative value
        # raises in time.sleep instead of running the text stream.
        cfg['interval'] = DEFAULTS['interval']
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
    for key in THRESHOLD_KEYS:
        raw = alerts.get(key)
        value = _as_float(raw, cfg[key])
        if value < 0:
            logger.warning(f'[alerts] {key} is negative ({raw!r}); using 0 (disabled).')
            value = 0.0
        cfg[key] = value

    daemon = parser['daemon'] if parser.has_section('daemon') else {}
    cfg['state_dir'] = daemon.get('state_dir', cfg['state_dir']) or None
    cfg['prom_path'] = daemon.get('prom_path', cfg['prom_path']) or None
    cfg['port'] = _as_int(daemon.get('port'), cfg['port'])
    if not 1 <= cfg['port'] <= 65535:
        cfg['port'] = DEFAULTS['port']
    cfg['sample_interval'] = _as_float(daemon.get('sample_interval'), cfg['sample_interval'])
    cfg['prom_interval'] = _as_float(daemon.get('prom_interval'), cfg['prom_interval'])
    cfg['history_interval'] = _as_float(daemon.get('history_interval'), cfg['history_interval'])
    cfg['retention_days'] = _as_int(daemon.get('retention_days'), cfg['retention_days'])
    cfg['alert_log'] = _as_bool(daemon.get('alert_log'), cfg['alert_log'])
    cfg['live_snapshot'] = _as_bool(daemon.get('live_snapshot'), cfg['live_snapshot'])
    if cfg['sample_interval'] <= 0:
        cfg['sample_interval'] = DEFAULTS['sample_interval']
    if cfg['prom_interval'] <= 0:
        cfg['prom_interval'] = DEFAULTS['prom_interval']
    if cfg['history_interval'] <= 0:
        cfg['history_interval'] = DEFAULTS['history_interval']
    if cfg['retention_days'] < 1:
        cfg['retention_days'] = DEFAULTS['retention_days']

    # [fan] is opt-in: an absent mode means "never touch the fan", so a stock
    # install cannot surprise the user by overriding the PSU's own curve.
    fan = parser['fan'] if parser.has_section('fan') else {}
    mode = (fan.get('mode') or '').strip().lower()
    if mode in FAN_MODES:
        cfg['fan_mode'] = mode
        cfg['fan_duty'] = _as_int(fan.get('duty'), DEFAULTS['fan_duty'])
        if cfg['fan_mode'] in ('auto', 'performance') or cfg['fan_duty'] is None:
            cfg['fan_duty'] = None  # auto is a mode, not a duty
        else:
            cfg['fan_duty'] = min(100, max(0, cfg['fan_duty']))
    elif mode:
        logger.warning(f'Ignoring unknown [fan] mode {mode!r} (use auto or customized).')
    raw_zero = (fan.get('zero_fan') or '').strip().lower()
    if raw_zero:
        if raw_zero in ('1', 'true', 'yes', 'on'):
            cfg['fan_zero_fan'] = True
        elif raw_zero in ('0', 'false', 'no', 'off'):
            cfg['fan_zero_fan'] = False
        else:
            logger.warning(f'Ignoring unknown [fan] zero_fan value {raw_zero!r} (use on or off).')
    return cfg


#: Config keys that form the local early-warning thresholds, in report order.
THRESHOLD_KEYS = (
    'power_w',
    'temp_c',
    'pin_max_a',
    'pin_imbalance_a',
    'connector_a',
    'rail_12v_a',
    'rail_5v_a',
    'rail_3v3_a',
)


def threshold_limits(cfg):
    """Return the enabled local thresholds as {config_key: float} (0 = disabled)."""
    return {key: float(cfg.get(key) or 0.0) for key in THRESHOLD_KEYS}


def _as_float(raw, fallback):
    try:
        value = float(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        return fallback
    # nan/inf pass the "<= 0" range checks below and then break the daemon
    # (time.sleep(nan) raises, and now >= now + nan is never true, so the
    # prometheus file and the history are never written again).
    return value if math.isfinite(value) else fallback


def _as_int(raw, fallback):
    try:
        return int(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        return fallback


def _as_bool(raw, fallback):
    if raw is None:
        return fallback
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
