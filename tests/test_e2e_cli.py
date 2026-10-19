"""End-to-end tests through the real console entry point (subprocess, demo mode)."""

import glob
import json
import os
import subprocess
import sys

from pathlib import Path

import pytest

from msi_psu_monitor import state as stats

ROOT = Path(__file__).resolve().parents[1]


def _run(args, tmp_path, demo=True, extra_env=None, timeout=20):
    env = os.environ.copy()
    env['MSI_PSU_STATE_DIR'] = str(tmp_path)
    env.pop('MSI_PSU_DEMO', None)
    env.pop('MSI_PSU_DEMO_MODEL', None)
    env.pop('MSI_PSU_DEMO_ALERT', None)
    if demo:
        env['MSI_PSU_DEMO'] = '1'
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, '-m', 'msi_psu_monitor', *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_the_real_entry_point_reports_its_version(tmp_path):
    result = _run(['--version'], tmp_path, demo=False)
    assert result.returncode == 0
    assert result.stdout.strip() == 'msi-psu-monitor 1.0.0'
    assert result.stderr == ''


def test_help_exits_zero_and_documents_control_flags(tmp_path):
    result = _run(['--help'], tmp_path, demo=False)
    assert result.returncode == 0
    for flag in ('--once', '--watch', '--serial', '--set-rail', '--show-alert-log'):
        assert flag in result.stdout


def test_demo_text_and_json_via_subprocess(tmp_path):
    text = _run(['--once'], tmp_path)
    assert text.returncode == 0
    assert 'MSI PSU: MPG Ai1600TS (demo)' in text.stdout
    parsed = _run(['-f', 'json'], tmp_path)
    assert parsed.returncode == 0
    payload = json.loads(parsed.stdout)
    assert payload['product'] == 'MPG Ai1600TS (demo)'


def test_demo_alert_exit_code_and_stderr_via_subprocess(tmp_path):
    result = _run(['--once'], tmp_path, extra_env={'MSI_PSU_DEMO_ALERT': 'ocp_pin1'})
    assert result.returncode == 2
    assert 'ALERT [warning] ocp_pin1:' in result.stderr
    assert '12V-2x6 Status: ocp_pin1' in result.stdout


def test_output_file_and_show_alert_log_via_subprocess(tmp_path):
    target = tmp_path / 'out.json'
    result = _run(['-f', 'json', '-O', str(target)], tmp_path)
    assert result.returncode == 0
    assert json.loads(target.read_text(encoding='utf-8'))['product'].startswith('MPG')
    empty = _run(['--show-alert-log'], tmp_path)
    assert empty.returncode == 0
    assert empty.stdout.strip() == 'No alert log records stored.'


def test_show_alert_log_can_write_to_a_file(tmp_path):
    stats.append_alert_log(tmp_path, 'ALERT [warning] ocp_pin1: test', ts=1000.0)
    target = tmp_path / 'alerts.txt'
    result = _run(['--show-alert-log', '-O', str(target)], tmp_path)
    assert result.returncode == 0
    assert 'ALERT [warning] ocp_pin1: test' in target.read_text(encoding='utf-8')


def test_no_demo_no_hardware_is_a_clean_error(tmp_path):
    if glob.glob('/dev/hidraw*'):
        pytest.skip('a real hidraw device is attached to this machine')
    result = _run(['--once'], tmp_path, demo=False)
    assert result.returncode == 1
    assert 'MSI PSU not found' in result.stderr
    assert 'Traceback' not in result.stderr


@pytest.mark.skipif(not Path('/dev/full').exists(), reason='/dev/full not available')
@pytest.mark.parametrize('args', [['--show-alert-log'], ['--export', '--from', '2h'], ['--once']])
def test_a_full_stdout_is_a_clean_exit_one(args, tmp_path):
    """ENOSPC on stdout must not produce a traceback / exit 120."""
    env = os.environ.copy()
    env['MSI_PSU_STATE_DIR'] = str(tmp_path)
    env['MSI_PSU_DEMO'] = '1'
    with open('/dev/full', 'w', encoding='utf-8') as sink:
        result = subprocess.run(
            [sys.executable, '-m', 'msi_psu_monitor', *args],
            cwd=ROOT,
            env=env,
            stdout=sink,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )
    assert result.returncode == 1, result.stderr
    assert 'Traceback' not in result.stderr
    assert 'Exception ignored' not in result.stderr
    assert 'cannot write output' in result.stderr
