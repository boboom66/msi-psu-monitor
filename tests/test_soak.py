"""The repeatable demo soak gate (scripts/soak.sh).

The 50k-sample soak was originally a hand-typed command; a shell script makes it
a CI gate and keeps the RSS/fd ceilings in one place.
"""

import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOAK = ROOT / 'scripts' / 'soak.sh'
DAEMON = ROOT / '.venv' / 'bin' / 'msi-psu-monitor-daemon'
WORKFLOW = ROOT / '.github' / 'workflows' / 'ci.yml'


def test_the_soak_script_is_executable_and_in_the_ci_gate():
    assert SOAK.is_file()
    assert SOAK.stat().st_mode & 0o111, 'scripts/soak.sh must be executable'
    script = SOAK.read_text(encoding='utf-8')
    assert 'SOAK PASS' in script and 'SOAK FAIL' in script
    assert 'scripts/soak.sh 5000' in WORKFLOW.read_text(encoding='utf-8')


def test_the_soak_script_rejects_bad_sample_counts():
    for value in ('abc', '10', '0'):
        result = subprocess.run(
            ['bash', str(SOAK), value],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 2, (value, result.stdout, result.stderr)


def test_the_soak_script_passes_a_short_run():
    if not DAEMON.exists():
        pytest.skip('no .venv daemon to soak; run uv sync --group dev')
    env = os.environ.copy()
    env['MSI_PSU_DAEMON'] = str(DAEMON)
    result = subprocess.run(
        ['bash', str(SOAK), '1000'],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert 'SOAK PASS' in result.stdout
    assert 'peak RSS' in result.stdout
