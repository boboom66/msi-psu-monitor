"""Ai1300TS (PID 0xAA6F) full-feature regression.

The Ai1300TS uses the same 7ZPU 44-byte 0xE0 layout and C0h 8-byte OCP
configuration as the Ai1600TS, but it is a different PID and must not be
dispatched as the generic Ai1300P. These tests exercise every user-facing
feature against the synthetic Ai1300TS so a refactor cannot silently drop one.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from msi_psu_monitor import demo
from msi_psu_monitor import monitor
from msi_psu_monitor.protocol import MSIPSU, PSU_PRODUCT_IDS

ROOT = Path(__file__).resolve().parents[1]
VARIANT = 'mpg_ai1300ts'


def test_ai1300ts_pid_and_variant_are_wired():
    assert MSIPSU.VARIANTS[VARIANT]['pid'] == 0xAA6F
    assert 0xAA6F in PSU_PRODUCT_IDS
    psu = demo.DemoPSU(variant=VARIANT)
    assert psu.product == 'MPG Ai1300TS (demo)'
    assert psu.variant == VARIANT


def test_ai1300ts_readings_cover_all_formats_and_per_pin_data():
    sensors = demo.DemoPSU(variant=VARIANT).get_sensors()
    sensors['status'] = 'Normal'  # collect_alerts() adds this on the CLI path
    assert len(sensors['iout_pins'][0]) == 12
    assert 'vin' not in sensors
    assert 'iout_12v_rails' not in sensors

    text = monitor.format_text(sensors)
    assert 'MSI PSU: MPG Ai1300TS (demo)' in text
    assert 'Conn1 Pin1' in text and 'Conn2 Pin6' in text
    assert '12V-2x6 Status: Normal' in text

    payload = json.loads(monitor.format_json(sensors))
    assert payload['product'] == 'MPG Ai1300TS (demo)'
    assert len(payload['iout_pins']['value']) == 12

    prom = monitor.format_prometheus(sensors)
    assert 'msi_psu_pin_current{connector="1",pin="1"}' in prom
    assert 'msi_psu_pin_current{connector="2",pin="6"}' in prom
    assert 'msi_psu_up 1' in prom


def test_ai1300ts_ocp_thresholds_roundtrip():
    psu = demo.DemoPSU(variant=VARIANT)
    assert psu.supports_ocp_config is True
    original = psu.read_ocp_thresholds()
    assert original['point_a'] == 12.0

    result, changed = monitor.apply_ocp_thresholds(
        psu,
        {
            'point_a': 13,
            'diff_a': 6,
            'trigger_s': 10,
            'diff_trigger_s': 12,
            'warning_s': 60,
        },
    )
    assert changed is True
    assert result['point_a'] == 13.0
    readback = psu.read_ocp_thresholds()
    assert readback['point_a'] == 13.0
    assert readback['warning_s'] == 60

    # The same 0xC0 address is the multirail switch on MEG P models; a TS model
    # must refuse that path rather than writing an unrelated byte.
    assert psu.supports_multirail_ocp is False
    assert psu.set_multirail_ocp(True) is False


def test_ai1300ts_write_controls_are_supported():
    psu = demo.DemoPSU(variant=VARIANT)
    assert psu.set_fan_mode(3, 55) is True
    assert psu.read_fan_setting() == (3, 55)
    assert psu.set_zero_fan(False) is True
    assert psu.read_zero_fan() is False
    assert psu.silence_buzzer() is True
    assert len(psu.read_blackbox()) > 0


def _run(*args, env=None, timeout=30):
    full_env = os.environ.copy()
    full_env.update(
        {
            'MSI_PSU_DEMO': '1',
            'MSI_PSU_DEMO_MODEL': VARIANT,
            'MSI_PSU_STATE_DIR': os.environ.get('_AI1300TS_TEST_STATE', '/tmp'),
        }
    )
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, '-m', 'msi_psu_monitor', *args],
        cwd=ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _run_daemon(*args, env=None, timeout=30):
    full_env = os.environ.copy()
    full_env.update(
        {
            'MSI_PSU_DEMO': '1',
            'MSI_PSU_DEMO_MODEL': VARIANT,
            'MSI_PSU_STATE_DIR': os.environ.get('_AI1300TS_TEST_STATE', '/tmp'),
        }
    )
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, '-m', 'msi_psu_monitor.daemon', *args],
        cwd=ROOT,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_ai1300ts_cli_covers_every_feature(tmp_path, monkeypatch):
    monkeypatch.setenv('_AI1300TS_TEST_STATE', str(tmp_path))
    config = tmp_path / 'threshold.conf'
    config.write_text('[alerts]\npower_w = 50\n', encoding='utf-8')

    cases = [
        (('--once',), 0),
        (('--once', '-f', 'json'), 0),
        (('--once', '-f', 'prometheus'), 0),
        (('--ocp',), 0),
        (('--ocp', '-f', 'json'), 0),
        (('--ocp', '-f', 'prometheus'), 0),
        (('--dump-thresholds',), 0),
        (('--dump-thresholds', '-f', 'json'), 0),
        (('--ocp-set', '13,6,10,12,60'), 0),
        (('--fan-duty', '60'), 0),
        (('--fan-mode', 'auto'), 0),
        (('--zero-fan', 'off'), 0),
        (('--buzzer-off',), 0),
        (('--show-log',), 0),
        (('--dump-config',), 0),
        (('--no-alerts', '--once', '--config', str(config)), 0),
    ]
    for args, expected in cases:
        result = _run(*args)
        assert result.returncode == expected, (args, result.stdout, result.stderr)

    # Local thresholds and E1h alerts both exit 2.
    result = _run('--once', '--config', str(config))
    assert result.returncode == 2
    assert 'thresholds    : power_high' in result.stdout.lower()
    assert 'ALERT [warning] power_high' in result.stderr

    result = _run('--once', env={'MSI_PSU_DEMO_ALERT': 'ocp_pin1'})
    assert result.returncode == 2
    assert 'ALERT [warning] ocp_pin1' in result.stderr

    # Dump -> load roundtrip, optional OCP on/off, daemon state and export.
    ocp_json = tmp_path / 'ocp.json'
    result = _run('--dump-thresholds', '-f', 'json', '-O', str(ocp_json))
    assert result.returncode == 0
    assert json.loads(ocp_json.read_text(encoding='utf-8'))['ocp_config']['point_a'] == 12.0
    result = _run('--load-thresholds', str(ocp_json))
    assert result.returncode == 0
    result = _run('--ocp-set', '13,6,10,12,60,off')
    assert result.returncode == 0

    state = tmp_path / 'daemon-state'
    daemon_config = tmp_path / 'daemon.conf'
    daemon_config.write_text(
        '[daemon]\nsample_interval = 0.1\nhistory_interval = 0.1\nprom_interval = 0.2\n',
        encoding='utf-8',
    )
    result = _run_daemon(
        '--config',
        str(daemon_config),
        '--state-dir',
        str(state),
        '--prom-path',
        str(state / 'psu.prom'),
        '--iterations',
        '3',
    )
    assert result.returncode == 0, result.stderr
    assert (state / 'state.json').is_file()
    assert (state / 'latest.json').is_file()
    prom = (state / 'psu.prom').read_text(encoding='utf-8')
    assert 'msi_psu_pin_current' in prom
    assert 'msi_psu_ocp_available 1' in prom
    assert 'msi_psu_up 1' in prom

    result = _run('--export', '--from', '1d', env={'MSI_PSU_STATE_DIR': str(state)})
    assert result.returncode == 0
    assert result.stdout.startswith('time,cpu,gpu,12v,5v,3v3,temp,fan,eff')

    alert_state = tmp_path / 'alert-state'
    result = _run_daemon(
        '--state-dir',
        str(alert_state),
        '--iterations',
        '3',
        env={'MSI_PSU_DEMO_ALERT': 'ocp_pin1'},
    )
    assert result.returncode == 0
    result = _run('--show-alert-log', env={'MSI_PSU_STATE_DIR': str(alert_state)})
    assert result.returncode == 0
    assert 'ALERT [warning] ocp_pin1' in result.stdout

    # The MEG-P multirail switch is not an Ai1300TS feature.
    result = _run('--set-rail', 'multi')
    assert result.returncode == 1
    assert 'MEG Ai1000P/Ai1300P' in result.stderr
