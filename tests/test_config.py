"""Unit tests for INI configuration loading (config.load_config)."""

import logging

from msi_psu_monitor.config import DEFAULTS, load_config


def test_defaults_without_files(tmp_path):
    cfg = load_config(str(tmp_path / 'missing.conf'))
    assert cfg == DEFAULTS


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


def _fan_conf(tmp_path, body):
    conf = tmp_path / 'fan.conf'
    conf.write_text('[fan]\n' + body)
    return load_config(str(conf))


def test_fan_is_opt_in(tmp_path):
    """No [fan] section: the daemon must never write to the PSU."""
    assert load_config(str(tmp_path / 'missing.conf'))['fan_mode'] is None
    assert load_config(str(tmp_path / 'missing.conf'))['fan_duty'] is None


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
