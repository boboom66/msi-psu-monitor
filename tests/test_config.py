"""Unit tests for INI configuration loading (config.load_config)."""

import logging
import pathlib
import subprocess
import sys

import pytest

from msi_psu_monitor.config import DEFAULTS, ConfigError, load_config


def test_defaults_without_files():
    """No config anywhere (the default search) is fine and yields the defaults."""
    assert load_config() == DEFAULTS


def test_explicit_file_values(tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text(
        '[monitor]\ninterval = 5\nformat = json\nverbose = yes\nno_alerts = true\n'
        '[alerts]\nconsecutive_required = 3\n'
    )
    cfg = load_config(str(conf))
    assert cfg['interval'] == 5.0
    assert cfg['format'] == 'json'
    assert cfg['verbose'] is True
    assert cfg['no_alerts'] is True
    assert cfg['consecutive_required'] == 3


def test_invalid_values_fall_back(tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[monitor]\ninterval = soon\n[alerts]\nconsecutive_required = 0\n')
    cfg = load_config(str(conf))
    assert cfg['interval'] == DEFAULTS['interval']
    assert cfg['consecutive_required'] == 1


def test_bool_spellings(tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[monitor]\nverbose = ON\nquiet = off\n')
    cfg = load_config(str(conf))
    assert cfg['verbose'] is True
    assert cfg['quiet'] is False


# ---- [fan] profile restore ----------------------------------------------


def _write(tmp_path, body, name='psu.conf'):
    conf = tmp_path / name
    conf.write_text(body)
    return conf


def _fan_conf(tmp_path, body):
    conf = tmp_path / 'fan.conf'
    conf.write_text('[fan]\n' + body)
    return load_config(str(conf))


def test_fan_is_opt_in(tmp_path):
    """No [fan] section: the daemon must never write to the PSU."""
    conf = tmp_path / 'nofan.conf'
    conf.write_text('[monitor]\ninterval = 3\n')
    cfg = load_config(str(conf))
    assert cfg['fan_mode'] is None
    assert cfg['fan_duty'] is None


def test_fan_customized_with_duty(tmp_path):
    cfg = _fan_conf(tmp_path, 'mode = customized\nduty = 65\n')
    assert cfg['fan_mode'] == 'customized'
    assert cfg['fan_duty'] == 65


def test_fan_mode_is_case_insensitive(tmp_path):
    assert _fan_conf(tmp_path, 'MODE = Customized\nDUTY = 40\n')['fan_mode'] == 'customized'


def test_fan_auto_drops_the_duty(tmp_path):
    """auto is a mode, not a duty: 41h ignores the byte in auto mode."""
    cfg = _fan_conf(tmp_path, 'mode = auto\nduty = 70\n')
    assert cfg['fan_mode'] == 'auto'
    assert cfg['fan_duty'] is None


def test_fan_customized_without_a_duty_keeps_the_current_one(tmp_path):
    cfg = _fan_conf(tmp_path, 'mode = customized\n')
    assert cfg['fan_mode'] == 'customized'
    assert cfg['fan_duty'] is None


def test_fan_duty_is_clamped(tmp_path):
    assert _fan_conf(tmp_path, 'mode = customized\nduty = 250\n')['fan_duty'] == 100
    assert _fan_conf(tmp_path, 'mode = customized\nduty = -5\n')['fan_duty'] == 0


def test_fan_unknown_mode_is_ignored(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger='msi_psu.config')
    """A typo must not silently pin the fan to something the user did not ask."""
    cfg = _fan_conf(tmp_path, 'mode = turbo\nduty = 90\n')
    assert cfg['fan_mode'] is None
    assert cfg['fan_duty'] is None
    assert 'Ignoring unknown [fan] mode' in caplog.text


def test_an_explicit_config_file_must_exist(tmp_path):
    """Silently using the defaults would hide every setting the user wrote."""
    with pytest.raises(ConfigError) as exc:
        load_config(str(tmp_path / 'missing.conf'))
    assert 'missing.conf' in str(exc.value)


def test_a_malformed_config_file_is_reported_not_raised(tmp_path):
    """configparser's own error must surface as ConfigError, not a traceback."""
    conf = tmp_path / 'broken.conf'
    conf.write_text('interval = 5\n')  # no section header
    with pytest.raises(ConfigError):
        load_config(str(conf))


def test_a_config_file_that_is_not_utf8_is_reported_not_raised(tmp_path):
    """ConfigParser.read only catches OSError around the open().

    A Latin-1/UTF-16 file (or one bad byte) makes the decode raise
    UnicodeDecodeError, which is not a configparser.Error: it used to escape as a
    20-line traceback from every CLI run and from the daemon's systemd start.
    """
    conf = tmp_path / 'latin1.conf'
    conf.write_bytes(b'[monitor]\noutput = /tmp/\xff\n')
    with pytest.raises(ConfigError):
        load_config(str(conf))


@pytest.mark.parametrize('value', ['', '   '])
def test_an_empty_config_path_is_reported(tmp_path, value):
    """`--config "$CONF"` with CONF unset must not silently use the defaults."""
    with pytest.raises(ConfigError):
        load_config(value)


def test_an_out_of_range_port_falls_back(tmp_path):
    conf = _write(tmp_path, '[daemon]\nport = 99999\n')
    assert load_config(str(conf))['port'] == DEFAULTS['port']
    conf = _write(tmp_path, '[daemon]\nport = -1\n', name='neg.conf')
    assert load_config(str(conf))['port'] == DEFAULTS['port']
    conf = _write(tmp_path, '[daemon]\nport = 9000\n', name='ok.conf')
    assert load_config(str(conf))['port'] == 9000


def test_a_percent_sign_in_a_value_is_literal(tmp_path):
    """BasicInterpolation turned a stray '%' into a traceback at .get() time."""
    conf = _write(tmp_path, '[monitor]\noutput = /tmp/100%.prom\n')
    assert load_config(str(conf))['output'] == '/tmp/100%.prom'


@pytest.mark.parametrize('token', ['nan', 'inf', '-inf'])
def test_a_non_finite_interval_falls_back_to_the_default(tmp_path, token):
    """nan slips past the "<= 0" guards, then time.sleep(nan) kills the daemon."""
    conf = _write(
        tmp_path,
        f'[monitor]\ninterval = {token}\n'
        f'[daemon]\nsample_interval = {token}\nprom_interval = {token}\n'
        f'history_interval = {token}\n',
    )
    cfg = load_config(str(conf))
    assert cfg['interval'] == DEFAULTS['interval']
    assert cfg['sample_interval'] == DEFAULTS['sample_interval']
    assert cfg['prom_interval'] == DEFAULTS['prom_interval']
    assert cfg['history_interval'] == DEFAULTS['history_interval']


def test_unknown_sections_and_options_are_reported(tmp_path, caplog):
    """A misspelled option used to keep the default without a word."""
    conf = tmp_path / 'psu.conf'
    conf.write_text(
        """[monitor]
intervall = 5
[typo]
foo = 1
""",
        encoding='utf-8',
    )
    with caplog.at_level(logging.WARNING):
        cfg = load_config(str(conf))
    assert cfg['interval'] == DEFAULTS['interval']
    text = caplog.text.lower()
    assert 'unknown config section [typo]' in text
    assert 'unknown option [monitor] intervall' in text


def test_a_utf8_config_is_read_under_an_ascii_locale(tmp_path):
    """The service manager may run with LC_ALL=C; a Chinese comment is still valid."""
    conf = tmp_path / 'psu.conf'
    conf.write_text(
        """# 中文注释
[monitor]
interval = 5
""",
        encoding='utf-8',
    )
    root = pathlib.Path(__file__).resolve().parents[1]
    code = (
        'from msi_psu_monitor.config import load_config; '
        f'print(load_config({str(conf)!r})["interval"])'
    )
    env = {
        'PATH': '/usr/bin:/bin',
        'LC_ALL': 'C',
        'LANG': 'C',
        'PYTHONUTF8': '0',
        'PYTHONCOERCECLOCALE': '0',
    }
    result = subprocess.run(
        [sys.executable, '-c', code], cwd=root, capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '5.0'


def test_a_utf8_bom_is_tolerated(tmp_path):
    """Notepad saves UTF-8 with a BOM; that must not become a missing section."""
    conf = tmp_path / 'psu.conf'
    body = '[monitor]' + chr(10) + 'interval = 4' + chr(10)
    conf.write_bytes(bytes([0xEF, 0xBB, 0xBF]) + body.encode('utf-8'))
    assert load_config(str(conf))['interval'] == 4.0


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [('on', True), ('off', False), ('yes', True), ('0', False), ('true', True)],
)
def test_fan_zero_fan_is_parsed(tmp_path, raw, expected):
    conf = tmp_path / 'psu.conf'
    body = '[fan]' + chr(10) + 'zero_fan = ' + raw + chr(10)
    conf.write_text(body, encoding='utf-8')
    assert load_config(str(conf))['fan_zero_fan'] is expected


def test_an_unknown_fan_zero_fan_value_is_reported_and_ignored(tmp_path, caplog):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[fan]' + chr(10) + 'zero_fan = maybe' + chr(10), encoding='utf-8')
    with caplog.at_level(logging.WARNING):
        cfg = load_config(str(conf))
    assert cfg['fan_zero_fan'] is None
    assert 'zero_fan' in caplog.text


def test_daemon_alert_log_defaults_on_and_can_be_disabled(tmp_path):
    empty = tmp_path / 'empty.conf'
    empty.write_text('[daemon]' + chr(10), encoding='utf-8')
    assert load_config(str(empty))['alert_log'] is True
    disabled = tmp_path / 'disabled.conf'
    disabled.write_text('[daemon]' + chr(10) + 'alert_log = no' + chr(10), encoding='utf-8')
    assert load_config(str(disabled))['alert_log'] is False


def test_live_snapshot_defaults_on_and_can_be_disabled(tmp_path):
    empty = tmp_path / 'live-empty.conf'
    empty.write_text('[daemon]' + chr(10), encoding='utf-8')
    assert load_config(str(empty))['live_snapshot'] is True
    disabled = tmp_path / 'live-disabled.conf'
    disabled.write_text('[daemon]' + chr(10) + 'live_snapshot = no' + chr(10), encoding='utf-8')
    assert load_config(str(disabled))['live_snapshot'] is False


@pytest.mark.parametrize('value', ['0', '-2', '-0.5'])
def test_a_non_positive_monitor_interval_falls_back(tmp_path, value):
    """A bare --watch uses [monitor] interval; 0 busy-loops and <0 raises in sleep."""
    conf = _write(tmp_path, f'[monitor]\ninterval = {value}\n')
    assert load_config(str(conf))['interval'] == DEFAULTS['interval']


def test_performance_mode_drops_a_configured_duty(tmp_path):
    """performance is the PSU curve; a duty does not apply."""
    cfg = _fan_conf(tmp_path, 'mode = performance\nduty = 60\n')
    assert cfg['fan_mode'] == 'performance'
    assert cfg['fan_duty'] is None


# ---- local early-warning thresholds -------------------------------------


def test_threshold_defaults_match_the_req14_initial_set():
    cfg = load_config()
    assert cfg['power_w'] == 1200.0
    assert cfg['temp_c'] == 70.0
    assert cfg['pin_max_a'] == 12.0
    assert cfg['pin_imbalance_a'] == 5.0
    assert cfg['connector_a'] == 50.0
    assert cfg['rail_12v_a'] == 108.33
    assert cfg['rail_5v_a'] == 22.0
    assert cfg['rail_3v3_a'] == 22.0


def test_thresholds_can_be_overridden_and_disabled(tmp_path):
    from msi_psu_monitor.config import threshold_limits

    conf = tmp_path / 'psu.conf'
    conf.write_text(
        '[alerts]\n'
        'power_w = 900\n'
        'temp_c = 60\n'
        'pin_max_a = 10\n'
        'pin_imbalance_a = 4\n'
        'connector_a = 40\n'
        'rail_12v_a = 90\n'
        'rail_5v_a = 20\n'
        'rail_3v3_a = 0\n',
        encoding='utf-8',
    )
    cfg = load_config(str(conf))
    limits = threshold_limits(cfg)
    assert limits['power_w'] == 900.0
    assert limits['pin_max_a'] == 10.0
    assert limits['rail_3v3_a'] == 0.0, '0 disables that limit'


def test_a_negative_threshold_disables_it_with_a_warning(tmp_path, caplog):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[alerts]\npower_w = -5\n', encoding='utf-8')
    with caplog.at_level(logging.WARNING, logger='msi_psu.config'):
        cfg = load_config(str(conf))
    assert cfg['power_w'] == 0.0
    assert 'negative' in caplog.text


def test_unparsable_threshold_keeps_the_safe_default(tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[alerts]\ntemp_c = soon\n', encoding='utf-8')
    cfg = load_config(str(conf))
    assert cfg['temp_c'] == 70.0


def _base_conf(tmp_path):
    conf = tmp_path / 'base.conf'
    conf.write_text(
        '[monitor]\n'
        'interval = 3.5\n'
        'output = /tmp/from-config\n'
        'verbose = yes\n'
        'serial = SN-1\n'
        '[alerts]\n'
        'consecutive_required = 3\n'
        'power_w = 900\n'
        'rail_12v_a = 100\n'
        '[daemon]\n'
        'state_dir = /tmp/st\n'
        'prom_path = /tmp/p.prom\n'
        'port = 9001\n'
        'retention_days = 14\n'
        'alert_log = no\n'
        '[fan]\n'
        'mode = customized\n'
        'duty = 60\n'
        'zero_fan = off\n',
        encoding='utf-8',
    )
    return conf


def test_dump_config_ini_round_trips_every_section(tmp_path):
    """--dump-config text output must be a usable config file.

    It is the documented way to snapshot an installation's effective settings;
    a value that did not survive a reload would make that snapshot a lie.
    """
    import configparser

    from msi_psu_monitor import monitor

    cfg = load_config(str(_base_conf(tmp_path)))
    dumped = monitor._dump_effective_config(cfg, 'text')
    # The dump must also stay INI-parseable with the strict default parser.
    configparser.ConfigParser().read_string(dumped)
    round_trip = tmp_path / 'round.conf'
    round_trip.write_text(dumped + '\n', encoding='utf-8')
    reloaded = load_config(str(round_trip))
    checked = (
        'interval',
        'output',
        'verbose',
        'serial',
        'consecutive_required',
        'power_w',
        'rail_12v_a',
        'state_dir',
        'prom_path',
        'port',
        'retention_days',
        'alert_log',
        'fan_mode',
        'fan_duty',
        'fan_zero_fan',
    )
    for key in checked:
        assert reloaded[key] == cfg[key], key


def test_dump_config_json_round_trips(tmp_path):
    import json

    from msi_psu_monitor import monitor

    cfg = load_config(str(_base_conf(tmp_path)))
    dumped = json.loads(monitor._dump_effective_config(cfg, 'json'))
    assert dumped['interval'] == 3.5
    assert dumped['output'] == '/tmp/from-config'
    assert dumped['consecutive_required'] == 3
    assert dumped['power_w'] == 900.0
    assert dumped['port'] == 9001
    assert dumped['retention_days'] == 14
    assert dumped['alert_log'] is False
    assert dumped['fan_mode'] == 'customized'
    assert dumped['fan_duty'] == 60
    assert dumped['fan_zero_fan'] is False
