"""Unit tests for INI configuration loading (config.load_config)."""

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
