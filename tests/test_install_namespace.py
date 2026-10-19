"""Root install/uninstall test inside a disposable user+mount namespace."""

import os
import shutil
import subprocess

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _probe_namespace() -> bool:
    unshare = shutil.which('unshare')
    if unshare is None:
        return False
    target = '/tmp/msi-psu-ns-probe'
    script = 'mkdir -p %s && mount -t tmpfs tmpfs %s && touch %s/ok && umount %s' % (
        target,
        target,
        target,
        target,
    )
    result = subprocess.run(
        [unshare, '-r', '-m', 'bash', '-c', script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.returncode == 0


@pytest.mark.skipif(not _probe_namespace(), reason='user/mount namespace unavailable')
def test_root_install_keeps_config_and_uninstall_purges_it(tmp_path):
    source = tmp_path / 'src'
    fake = tmp_path / 'fake'
    source.mkdir()
    fake.mkdir()
    # The installer only checks -x and runs --version; stubs are enough here.
    for name in ('msi-psu-monitor', 'msi-psu-monitor-daemon'):
        stub = source / name
        stub.write_text('#!/bin/sh\necho msi-psu-monitor 1.0.0\n', encoding='utf-8')
        stub.chmod(0o755)
    shutil.copy(ROOT / 'systemd/99-msi-psu.rules', source)
    shutil.copy(ROOT / 'systemd/msi-psu-monitor.service', source)
    shutil.copy(ROOT / 'docs/msi-psu-monitor.conf.example', source)
    shutil.copy(ROOT / 'scripts/install_binary.sh', source / 'install.sh')
    shutil.copy(ROOT / 'scripts/uninstall_binary.sh', source / 'uninstall.sh')
    log = tmp_path / 'calls.log'
    for name in ('systemctl', 'udevadm'):
        tool = fake / name
        tool.write_text(
            f'#!/bin/sh\necho {name} "$@" >> "{log}"\nexit 0\n',
            encoding='utf-8',
        )
        tool.chmod(0o755)
    prefix = tmp_path / 'prefix'
    script = r"""
        set -e
        mount -t tmpfs tmpfs /etc
        mkdir -p /etc/systemd/system /etc/udev/rules.d /var/lib "$PREFIX"
        mount -t tmpfs tmpfs /var/lib
        export PATH="$FAKE:$PATH" PREFIX FAKE_LOG
        bash "$STAGE/install.sh" >/dev/null
        test -x "$PREFIX/bin/msi-psu-monitor"
        test -x "$PREFIX/bin/msi-psu-monitor-daemon"
        test -f /etc/msi-psu-monitor.conf
        test -f /etc/systemd/system/msi-psu-monitor.service
        test -f /etc/udev/rules.d/99-msi-psu.rules
        test -d /var/lib/node_exporter
        echo custom > /etc/msi-psu-monitor.conf
        bash "$STAGE/install.sh" >/dev/null
        test "$(cat /etc/msi-psu-monitor.conf)" = custom
        bash "$STAGE/uninstall.sh" >/dev/null
        test ! -e "$PREFIX/bin/msi-psu-monitor"
        test ! -e /etc/systemd/system/msi-psu-monitor.service
        test -f /etc/msi-psu-monitor.conf
        bash "$STAGE/uninstall.sh" --purge >/dev/null
        test ! -e /etc/msi-psu-monitor.conf
    """
    env = os.environ.copy()
    env.update(STAGE=str(source), FAKE=str(fake), FAKE_LOG=str(log), PREFIX=str(prefix))
    result = subprocess.run(
        [shutil.which('unshare'), '-r', '-m', 'bash', '-c', script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = log.read_text(encoding='utf-8')
    assert 'systemctl enable --now msi-psu-monitor.service' in calls
    assert 'systemctl disable msi-psu-monitor.service' in calls
    assert 'udevadm trigger --subsystem-match=hidraw' in calls
