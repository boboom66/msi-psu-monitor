"""Hardware-kit invariants: shell syntax, shipped files, release wiring."""

import subprocess

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hardware_scripts_pass_bash_syntax():
    for name in ('setup.sh', 'acceptance.sh', 'uninstall.sh'):
        path = ROOT / 'scripts' / 'hardware' / name
        assert path.is_file(), name
        result = subprocess.run(['bash', '-n', str(path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_the_kit_builder_ships_binary_source_and_docs():
    text = (ROOT / 'scripts' / 'build_hardware_kit.sh').read_text(encoding='utf-8')
    for needle in (
        'bin/msi-psu-monitor',
        'source',
        'setup.sh',
        'acceptance.sh',
        'hardware-acceptance.md',
    ):
        assert needle in text, needle


def test_the_hardware_guide_explains_the_install_and_evidence_flow():
    text = (ROOT / 'docs' / 'hardware-acceptance.md').read_text(encoding='utf-8')
    for needle in ('setup.sh', 'acceptance.sh', '--demo', '--writes', 'msi-psu-acceptance', 'udev'):
        assert needle in text, needle


def test_the_release_workflow_publishes_the_hardware_kit():
    text = (ROOT / '.github' / 'workflows' / 'release.yml').read_text(encoding='utf-8')
    assert 'build_hardware_kit.sh' in text
    assert 'hardware-kit' in text
    # A broad dist/*.tar.gz also matches the hardware kit and then the explicit
    # kit glob passes the same asset twice to gh release create.
    assert 'dist/*.tar.gz' not in text
    assert 'dist/msi-psu-monitor_*.tar.gz' in text
