"""Regression tests for the full-project audit (Oct 2026).

Each test reproduces a confirmed defect found by code review before the fix:
it failed (raised, poisoned state, or performed a wrong write) on the old code
and passes after the fix. All are stdlib-only and hardware-free.
"""

import pytest


# ---- protocol.detect_devices: non-UTF-8 uevent must not kill the scan ----


def test_detect_devices_skips_non_utf8_uevent(monkeypatch, tmp_path):
    from msi_psu_monitor import protocol

    good = tmp_path / 'hidraw9' / 'device' / 'uevent'
    good.parent.mkdir(parents=True)
    good.write_bytes(b'HID_ID=0003:00000DB0:0000808C\n')
    bad_name = str(tmp_path / 'bad_uevent')

    def fake_glob(_pattern):
        return [str(good), bad_name]

    real_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == bad_name:
            raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'bad byte')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(protocol.glob, 'glob', fake_glob)
    monkeypatch.setattr('builtins.open', fake_open)
    # Must not raise; the bad file is skipped like an unreadable one.
    assert protocol.detect_devices() == ['/dev/hidraw9']


# ---- protocol.HIDDevice.send_command: empty/oversize rejected ----


def test_send_command_rejects_empty_and_oversize():
    from msi_psu_monitor.protocol import CMD_BUFFER_SIZE, HIDDevice

    device = HIDDevice.__new__(HIDDevice)
    device.fd = 12345  # non-None so validation runs before any os.* call
    assert device.send_command([]) is None
    assert device.send_command(list(range(CMD_BUFFER_SIZE + 1))) is None
    assert device.send_command(list(range(CMD_BUFFER_SIZE + 100))) is None
    # Malformed byte values are a framing failure, not a ValueError traceback.
    assert device.send_command([0x51, 0xE0, 999]) is None
    assert device.send_command([0x51, 'x']) is None


def test_close_is_idempotent_on_bad_fd():
    from msi_psu_monitor.protocol import HIDDevice

    device = HIDDevice.__new__(HIDDevice)
    device.fd = -9999  # invalid fd: os.close raises EBADF
    device.close()  # must not raise
    assert device.fd is None
    device.close()  # second close is a no-op
    assert device.fd is None


def test_write_command_requires_non_empty_reply(monkeypatch):
    from msi_psu_monitor.protocol import HIDDevice

    device = HIDDevice.__new__(HIDDevice)
    device.fd = 1
    # A 2-byte non-NAK frame comes back as b""; that is a protocol
    # violation, not an ACK.
    monkeypatch.setattr(device, 'send_command', lambda data, timeout_ms=250: b'')
    assert device.write_command([0x41, 0x01]) is False
    monkeypatch.setattr(device, 'send_command', lambda data, timeout_ms=250: b'\xfc')
    assert device.write_command([0x41, 0x01]) is True
    monkeypatch.setattr(device, 'send_command', lambda data, timeout_ms=250: None)
    assert device.write_command([0x41, 0x01]) is False


# ---- daemon._ensure_psu: discovery exception throttles, never kills ----


def test_daemon_discovery_exception_is_a_throttled_miss(tmp_path):
    from msi_psu_monitor.daemon import MonitorDaemon

    cfg = {
        'state_dir': str(tmp_path),
        'prom_path': None,
        'sample_interval': 1.0,
        'prom_interval': 30.0,
        'history_interval': 60.0,
        'retention_days': 30,
        'alert_log': False,
        'live_snapshot': False,
        'fan_mode': None,
        'fan_duty': None,
        'fan_zero_fan': None,
        'consecutive_required': 2,
    }
    now = [100.0]

    def boom():
        raise RuntimeError('sysfs exploded')

    daemon = MonitorDaemon(
        cfg,
        psu_factory=lambda _p: (_ for _ in ()).throw(AssertionError('must not open')),
        select_device=boom,
        clock=lambda: now[0],
        wall_clock=lambda: 1000.0,
    )
    assert daemon._ensure_psu() is None
    # Throttled: a second call before +5 s does not retry discovery.
    calls = []
    daemon.select_device = lambda: (
        calls.append(1) or (_ for _ in ()).throw(AssertionError('throttle broken'))
    )
    assert daemon._ensure_psu() is None
    assert calls == []


# ---- NaN/inf must not poison averages or the energy counter ----


def test_valid_sample_rejects_non_finite():
    from msi_psu_monitor import monitor

    assert (
        monitor._valid_sample({'power_total': (float('nan'), 'W'), 'efficiency': (90.0, '%')})
        is None
    )
    assert (
        monitor._valid_sample({'power_total': (100.0, 'W'), 'efficiency': (float('inf'), '%')})
        is None
    )
    assert monitor._valid_sample({'power_total': (0.0, 'W'), 'efficiency': (0.0, '%')}) == (
        0.0,
        0.0,
    )


def test_state_update_ignores_non_finite():
    from msi_psu_monitor.state import MonitorState

    st = MonitorState()
    st.update(100.0, 90.0, ts=1000.0)
    before = (st.energy_wh, st.watt_sum, st.efficiency_sum, st.count)
    assert st.update(float('nan'), 90.0, ts=1001.0) == 0.0
    assert st.update(100.0, float('inf'), ts=1002.0) == 0.0
    assert st.update(100.0, 90.0, ts=float('nan')) == 0.0
    assert (st.energy_wh, st.watt_sum, st.efficiency_sum, st.count) == before
    # The clock was not moved by the bad samples: the next good one integrates.
    delta = st.update(100.0, 90.0, ts=1001.0)
    assert delta > 0.0
    assert st.count == before[3] + 1


def test_state_prune_drops_non_string_keys():
    from msi_psu_monitor.state import MonitorState

    st = MonitorState(daily={123: 1.0, 'not-a-date': 2.0})
    dropped = st.prune()
    assert st.daily == {}
    assert set(dropped) == {123, 'not-a-date'}


# ---- format_blackbox: missing info_id / pin_set must not crash ----


def test_format_blackbox_missing_info_id_and_pin():
    from msi_psu_monitor import monitor

    out = monitor.format_blackbox(
        [{'pin_set': 1, 'status': 1, 'run_time': 0, 'total_time': 0, 'total_count': 1}]
    )
    assert '#0' in out  # missing info_id falls back to 0 for sort + display
    out2 = monitor.format_blackbox(
        [{'info_id': 1, 'status': 1, 'run_time': 0, 'total_time': 0, 'total_count': 1}]
    )
    assert 'pin unknown' in out2
    assert 'pin None' not in out2


# ---- OCP threshold file: enabled must be bool/0/1; BOM must load ----


def test_normalize_ocp_thresholds_rejects_enabled_2():
    from msi_psu_monitor import monitor

    with pytest.raises(ValueError):
        monitor._normalize_ocp_thresholds({'enabled': 2, 'point_a': 12})
    assert monitor._normalize_ocp_thresholds({'enabled': 1, 'point_a': 12}) == {
        'enabled': True,
        'point_a': 12,
    }
    assert monitor._normalize_ocp_thresholds({'enabled': 0, 'point_a': 12}) == {
        'enabled': False,
        'point_a': 12,
    }
    assert monitor._normalize_ocp_thresholds({'enabled': True, 'point_a': 12}) == {
        'enabled': True,
        'point_a': 12,
    }


def test_read_ocp_thresholds_file_accepts_bom(tmp_path):
    from msi_psu_monitor import monitor

    path = tmp_path / 'thresholds.json'
    path.write_bytes(
        b'\xef\xbb\xbf{"point_a": 12, "diff_a": 5, "trigger_s": 20, '
        b'"diff_trigger_s": 20, "warning_s": 180}'
    )
    assert monitor._read_ocp_thresholds_file(str(path))['point_a'] == 12


# ---- apply_fan_setting: unknown duty must not invent (customized, 0) ----


def test_apply_fan_setting_refuses_unknown_duty_without_writing():
    from msi_psu_monitor import monitor

    writes = []

    class FakePSU:
        def read_fan_setting(self):
            return None  # NAK / unsupported model

        def set_fan_mode(self, mode, duty):
            writes.append((mode, duty))
            return True

    assert monitor.apply_fan_setting(FakePSU(), 'customized', None) is None
    assert writes == []


# ---- threshold helpers: bad strings disable the limit, never raise ----


def test_threshold_helpers_tolerate_bad_strings():
    from msi_psu_monitor import alerts
    from msi_psu_monitor.config import threshold_limits

    sensors = {'power_total': (1300.0, 'W')}
    assert alerts.evaluate_threshold_alerts(sensors, {'power_w': 'abc'}) == {}
    assert alerts.evaluate_threshold_alerts(sensors, {'power_w': float('inf')}) == {}
    assert alerts.configured_threshold_names({'power_w': 'abc'}, True) == set()
    assert threshold_limits({'power_w': 'abc'})['power_w'] == 0.0
    assert threshold_limits({'power_w': float('nan')})['power_w'] == 0.0


def test_threshold_detail_tolerates_bad_limit_string():
    from msi_psu_monitor import monitor

    sensors = {'power_total': (1300.0, 'W')}
    out = monitor._threshold_detail('power_high', sensors, {'power_w': 'abc'})
    assert out == monitor.describe('power_high')
    out2 = monitor._threshold_detail(
        'connector1_high',
        {'iout_pins': ([1.0] * 12, 'A')},
        {'connector_a': 'abc'},
    )
    assert out2 == monitor.describe('connector1_high')


def test_install_sh_tolerates_missing_udev_and_systemd():
    import pathlib

    text = pathlib.Path('scripts/install.sh').read_text(encoding='utf-8')
    assert 'udevadm control --reload-rules || true' in text
    assert 'udevadm trigger --subsystem-match=hidraw || true' in text
    assert 'systemctl daemon-reload || true' in text
    assert 'systemctl enable --now msi-psu-monitor.service || true' in text


def test_send_command_drain_is_bounded(monkeypatch):
    from msi_psu_monitor.protocol import HIDDevice

    reads = []

    def endless_read(fd, size):
        reads.append(1)
        return b'\x00' * size  # device always has bytes ready

    writes = []

    def fake_write(fd, data):
        writes.append(bytes(data))
        return len(data)

    monkeypatch.setattr('os.read', endless_read)
    monkeypatch.setattr('os.write', fake_write)
    monkeypatch.setattr('select.select', lambda r, w, x, t: ([], [], []))

    device = HIDDevice.__new__(HIDDevice)
    device.fd = 7
    assert device.send_command([0x51, 0xE0], timeout_ms=10) is None
    assert len(reads) == 16  # bounded, then the write still went out
    assert len(writes) == 1
    assert len(writes[0]) == 64


def test_live_snapshot_never_writes_non_finite_json(tmp_path):
    """NaN/Infinity in latest.json breaks the browser's JSON.parse.

    That froze every live chart while the one-minute history kept working, so
    it looked like a UI bug: response.json() rejects the whole document.
    """
    import json

    from msi_psu_monitor import state

    path = state.write_live_snapshot(
        tmp_path,
        {
            'product': 'X',
            'vout_12v': (float('nan'), 'V'),
            'power_total': (float('inf'), 'W'),
            'temp': (31.5, 'C'),
        },
        ts=1000.0,
    )
    assert path is not None
    text = path.read_text(encoding='utf-8')
    parsed = json.loads(
        text,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    assert parsed['temp'] == 31.5
    assert 'vout_12v' not in parsed
    assert 'power_total' not in parsed


def test_live_snapshot_rejects_non_finite_timestamp(tmp_path):
    from msi_psu_monitor import state

    assert state.write_live_snapshot(tmp_path, {'product': 'X'}, ts=float('nan')) is None
    assert not (tmp_path / state.LIVE_FILENAME).exists()


def test_text_frame_shows_the_customize_duty():
    """JSON carried fan_duty but the text frame omitted it in customized mode."""
    from msi_psu_monitor import monitor

    text = monitor.format_text(
        {
            'product': 'MPG Ai1600TS',
            'zero_fan': False,
            'fan_mode': 'customized',
            'fan_duty': 55,
        }
    )
    assert 'Mode: customized   Duty: 55%' in text
    # auto mode never reports a stale customized duty, so the suffix stays out
    auto = monitor.format_text({'product': 'MPG Ai1600TS', 'zero_fan': True, 'fan_mode': 'auto'})
    assert 'Duty:' not in auto


def test_dump_config_writes_the_fan_section(tmp_path):
    """--dump-config printed an empty [fan] header for a configured profile.

    The INI options are mode/duty/zero_fan but the loaded cfg keys are
    fan_mode/fan_duty/fan_zero_fan, so the generic "key in cfg" loop skipped
    every one of them even though load_config had parsed the file.
    """
    from msi_psu_monitor import config, monitor

    conf = tmp_path / 'fan.conf'
    conf.write_text('[fan]\nmode = customized\nduty = 55\nzero_fan = on\n', encoding='utf-8')
    cfg = config.load_config(str(conf))
    dumped = monitor._dump_effective_config(cfg, 'text')
    assert '[fan]' in dumped
    assert 'mode = customized' in dumped
    assert 'duty = 55' in dumped
    assert 'zero_fan = yes' in dumped

    # The dump must be a usable config file: reloading it keeps the profile.
    again = tmp_path / 'again.conf'
    again.write_text(dumped + '\n', encoding='utf-8')
    reloaded = config.load_config(str(again))
    assert reloaded['fan_mode'] == 'customized'
    assert reloaded['fan_duty'] == 55
    assert reloaded['fan_zero_fan'] is True


def test_release_publishes_the_checksum_sidecars_the_docs_reference():
    """README/docs tell users to run sha256sum -c <tarball>.sha256.

    The build scripts produce those sidecars and upload them as workflow
    artifacts, but gh release create did not attach them, so the documented
    check fetched a 404 from the release page.
    """
    import pathlib

    root = pathlib.Path('.')
    workflow = (root / '.github/workflows/release.yml').read_text(encoding='utf-8')
    publish = workflow.split('gh release create', 1)[1]
    assert 'dist/msi-psu-monitor_*.tar.gz.sha256' in publish
    assert 'dist/msi-psu-monitor_*_amd64.deb.sha256' in publish
    assert 'dist/msi-psu-monitor_*_arm64.deb.sha256' in publish
    assert 'dist/*hardware-kit*.tar.gz.sha256' in publish

    # The documented hardware-kit name must be the one the builder writes.
    doc = (root / 'docs/release.md').read_text(encoding='utf-8')
    builder = (root / 'scripts/build_hardware_kit.sh').read_text(encoding='utf-8')
    assert 'msi-psu-monitor-hardware-kit-$VERSION-linux-$ARCH.tar.gz' in builder
    assert 'msi-psu-monitor-hardware-kit-<version>-linux-<arch>.tar.gz' in doc


def test_read_fan_fields_tolerates_a_non_dict_result():
    """A read_fan_state() that returns None must not break the whole sample."""
    from msi_psu_monitor import monitor

    class NoneFan:
        def read_fan_state(self):
            return None

    assert monitor.read_fan_fields(NoneFan()) == {}

    class ListFan:
        def read_fan_state(self):
            return [1, 2]

    assert monitor.read_fan_fields(ListFan()) == {}


HOST_CASES = [
    # (Host header, accepted)
    ('127.0.0.1', True),
    ('127.0.0.1:8899', True),
    ('LOCALHOST', True),
    ('localhost:1', True),
    ('[::1]', True),
    ('[::1]:8899', True),
    (' 127.0.0.1 ', True),
    ('', False),
    (None, False),
    ('evil.example', False),
    ('localhost.', False),
    ('127.0.0.1.evil', False),
    ('[::1', False),  # unbalanced bracket
    ('[::1]x', False),  # junk after the bracket
    ('[::1]:80:90', False),
    ('[::1]:', False),
    ('localhost:', False),
    ('localhost:abc', False),
    ('127.0.0.1:0', True),
    ('::1', False),  # unbracketed IPv6
    ('127.0.0.1:80:90', False),
    ('user@127.0.0.1', False),
]


def test_host_header_parser_rejects_every_non_loopback_shape():
    from msi_psu_monitor.dashboard import _host_is_loopback

    for header, accepted in HOST_CASES:
        assert _host_is_loopback(header) is accepted, header


def test_hid_open_takes_an_exclusive_lock_and_close_is_reusable(tmp_path):
    """Two CLI/daemon runs must not interleave writes on one hidraw node."""
    import pytest

    from msi_psu_monitor.protocol import DeviceBusyError, HIDDevice

    node = tmp_path / 'hidraw0'
    node.write_bytes(b'')

    first = HIDDevice(str(node)).open()
    try:
        second = HIDDevice(str(node))
        with pytest.raises(DeviceBusyError):
            second.open()
        assert second.fd is None
    finally:
        first.close()
    assert first.fd is None

    # The lock is released by close(), so a later run can open the node.
    again = HIDDevice(str(node)).open()
    again.close()
    assert again.fd is None


def test_soak_fails_when_it_could_not_measure_anything():
    """A zero-poll soak used to print PASS with 'peak RSS 0 KB, fd=0'.

    Nothing was measured, so the RSS/fd ceilings proved nothing; a gate that
    cannot observe the process must fail instead of passing silently.
    """
    import pathlib

    script = pathlib.Path('scripts/soak.sh').read_text(encoding='utf-8')
    block = script.split('if [ "$POLLS" -eq 0 ]', 1)[1].split('\nfi\n', 1)[0]
    assert 'FAILED=1' in block
    # FAILED must be initialised before the block, or the assignment is reset.
    assert script.index('FAILED=0') < script.index('if [ "$POLLS" -eq 0 ]')


def test_the_sbom_is_generated_after_every_artifact_it_hashes():
    """SBOM claims a SHA-256 for every shipped artifact.

    The workflow built the hardware kit after generating the SBOM, so the kit
    tarball was never named or hashed in it.
    """
    import pathlib

    text = pathlib.Path('.github/workflows/release.yml').read_text(encoding='utf-8')
    assert text.index('Build the hardware acceptance kit') < text.index('Generate the SBOM')
    sbom = pathlib.Path('scripts/build_sbom.py').read_text(encoding='utf-8')
    assert "endswith(('.tar.gz', '.deb'))" in sbom


def test_hardware_uninstall_removes_the_unit_without_systemd():
    """setup.sh installs the unit on non-systemd hosts; uninstall must still remove it."""
    import pathlib

    text = pathlib.Path('scripts/hardware/uninstall.sh').read_text(encoding='utf-8')
    marker = 'rm -f "$UNIT"'
    assert marker in text
    # It must sit outside the /run/systemd/system guard.
    guard = text.split('if [ -d /run/systemd/system ]; then', 1)[1].split('\nfi', 1)[0]
    assert marker not in guard


def test_negative_state_counters_do_not_produce_negative_totals(tmp_path, caplog):
    """A hand-edited/corrupt state must not show a negative average or kWh total."""
    import json
    import logging

    from msi_psu_monitor import state

    path = tmp_path / 'state.json'
    path.write_text(
        json.dumps(
            {
                'version': 1,
                'count': -5,
                'watt_sum': -100.0,
                'efficiency_sum': -90.0,
                'energy_wh': -250.0,
                'last_ts': 1000.0,
                'daily': {},
            }
        ),
        encoding='utf-8',
    )
    with caplog.at_level(logging.WARNING):
        loaded = state.MonitorState.load(path)
    assert loaded.count == 0
    assert loaded.watt_sum == 0.0
    assert loaded.efficiency_sum == 0.0
    assert loaded.energy_wh == 0.0
    assert loaded.power_avg == 0.0
    assert loaded.total_energy_kwh == 0.0
    assert 'negative' in caplog.text


def test_demo_blackbox_negative_limit_matches_the_real_reader():
    """records[:-1] returned one record for a negative limit; MSIPSU returns none."""
    from msi_psu_monitor import demo
    from msi_psu_monitor.protocol import MSIPSU

    assert demo.DemoPSU().read_blackbox(-1) == []
    assert demo.DemoPSU().read_blackbox(0) == []
    assert len(demo.DemoPSU().read_blackbox(1)) == 1
    # The real reader builds range(1, max+1): a negative limit is empty.
    real = MSIPSU.__new__(MSIPSU)
    real.hid = None
    assert real.read_blackbox(-1) == []


def test_live_reader_rejects_a_non_finite_reading(tmp_path):
    """An old/hand-written latest.json with NaN must not break the live chart."""
    import json

    from msi_psu_monitor import state

    state.live_path(tmp_path).write_text(
        json.dumps({'ts': 1000.0, 'temp': float('nan'), 'product': 'X'}),
        encoding='utf-8',
    )
    assert state.read_live_snapshot(tmp_path, now=1001.0) is None
    # Nested non-finite values (a pin list) are rejected too.
    state.live_path(tmp_path).write_text(
        json.dumps({'ts': 1000.0, 'iout_pins': [1.0, float('inf')]}),
        encoding='utf-8',
    )
    assert state.read_live_snapshot(tmp_path, now=1001.0) is None
    # A finite file still reads.
    state.live_path(tmp_path).write_text(
        json.dumps({'ts': 1000.0, 'temp': 31.5, 'product': 'X'}),
        encoding='utf-8',
    )
    assert state.read_live_snapshot(tmp_path, now=1001.0)['temp'] == 31.5


def test_hid_open_is_idempotent_and_does_not_leak_a_fd(tmp_path):
    """A second open() overwrote self.fd and leaked the first descriptor."""
    import os

    from msi_psu_monitor.protocol import HIDDevice

    node = tmp_path / 'hidraw1'
    node.write_bytes(b'')
    device = HIDDevice(str(node)).open()
    first_fd = device.fd
    assert first_fd is not None

    device.open()
    assert device.fd == first_fd
    before = len(os.listdir('/proc/self/fd'))
    for _ in range(5):
        device.open()
    assert len(os.listdir('/proc/self/fd')) == before

    device.close()
    assert device.fd is None


def test_parse_from_rejects_a_window_that_overflows_to_infinity():
    """time.time() - inf silently selected every row instead of a 400."""
    import pytest

    from msi_psu_monitor import state

    with pytest.raises(ValueError):
        state.parse_from('9' * 400 + 'h')
    assert state.parse_from('2h') == 7200.0


def test_linear11_fixed_vectors_for_the_nak_comment():
    """Independent vectors: 0xCDFE is 11.984 V, 0xCEFE would be 13.984 V.

    The comments cited 0xCEFE for 11.984 V; the code was right, the hex was not.
    """
    from msi_psu_monitor.protocol import lin11_to_int

    assert lin11_to_int(0xCDFE, 1000) == 11984  # 1534 * 2**-7 V
    assert lin11_to_int(0xCEFE, 1000) == 13984  # 1790 * 2**-7 V


def test_pin_alerts_ignore_phantom_pins_and_non_finite_values():
    from msi_psu_monitor.alerts import evaluate_pin_alerts

    long_list = evaluate_pin_alerts([1.0] * 14, pin_max_a=0.5, imbalance_a=5.0)
    assert {name for name in long_list if name.startswith('ocp_pin')} == {
        f'ocp_pin{index}' for index in range(1, 13)
    }
    assert 'ocp_pin13' not in long_list and 'ocp_pin14' not in long_list

    # NaN must not silently look "below the limit" and disable the mirror.
    assert evaluate_pin_alerts([float('nan')] + [1.0] * 11) == {}
    assert evaluate_pin_alerts([float('inf')] + [1.0] * 11) == {}


def test_threshold_alerts_treat_non_finite_readings_as_missing():
    """NaN is not 'below the limit': it must keep a latched alert, not clear it."""
    from msi_psu_monitor.alerts import evaluate_threshold_alerts

    sensors = {
        'power_total': (float('nan'), 'W'),
        'temp': (float('inf'), 'C'),
        'iout_12v_total': (50.0, 'A'),
    }
    active = evaluate_threshold_alerts(
        sensors, {'power_w': 1200.0, 'temp_c': 70.0, 'rail_12v_a': 108.0}
    )
    assert 'power_high' not in active
    assert 'temp_high' not in active
    assert active['rail_12v_high'] is False


def test_history_writes_blank_for_non_finite_readings(tmp_path):
    """'nan' in a CSV cell is not a measurement any exporter can use."""
    from msi_psu_monitor import state

    path = state.append_history(
        tmp_path,
        {
            'vout_12v': (float('nan'), 'V'),
            'power_total': (float('inf'), 'W'),
            'temp': (31.5, 'C'),
        },
        ts=1000.0,
    )
    rows = list(state.iter_history(tmp_path))
    assert rows[0]['temp'] == '31.5'
    assert rows[0]['12v'] == ''
    assert rows[0]['power'] == ''
    assert path.exists()


def test_rail_watts_refuses_non_finite_or_malformed_rails():
    from msi_psu_monitor import state

    good = {
        'vout_12v_rails': ([12.0] * 5, 'V'),
        'iout_12v_rails': ([1.0, 2.0, 3.0, 4.0, 5.0], 'A'),
    }
    assert state.rail_watts(good) == (24.0, 144.0)
    bad = {
        'vout_12v_rails': ([12.0, float('nan')] + [12.0] * 3, 'V'),
        'iout_12v_rails': ([1.0, 2.0, 3.0, 4.0, 5.0], 'A'),
    }
    assert state.rail_watts(bad) is None
    malformed = {
        'vout_12v_rails': (['x', 12, 12, 12, 12], 'V'),
        'iout_12v_rails': ([1.0, 2.0, 3.0, 4.0, 5.0], 'A'),
    }
    assert state.rail_watts(malformed) is None


def test_quiet_suppresses_config_load_warnings(tmp_path):
    """Config warnings were emitted before setup_logging and bypassed --quiet."""
    import subprocess
    import sys

    conf = tmp_path / 'warn.conf'
    conf.write_text('[bogus]\nx = 1\n', encoding='utf-8')
    base = [sys.executable, '-m', 'msi_psu_monitor', '--config', str(conf), '--dump-config']

    quiet = subprocess.run(base + ['--quiet'], capture_output=True, text=True, timeout=60)
    assert quiet.returncode == 0
    assert quiet.stderr == ''

    loud = subprocess.run(base, capture_output=True, text=True, timeout=60)
    assert loud.returncode == 0
    assert 'unknown config section' in loud.stderr.lower()


def test_deeply_nested_json_is_damaged_state_not_a_recursion_crash(tmp_path):
    """100k nested arrays raise RecursionError from json.loads, not ValueError.

    That escaped state.load's ValueError handler: a hand-edited state.json
    became a daemon startup crash-loop (and /api/live dropped the connection).
    """
    import pytest

    from msi_psu_monitor import monitor, state

    deep = '[' * 100_000 + ']' * 100_000
    path = tmp_path / 'state.json'
    path.write_text('{"version": 1, "daily": ' + deep + '}', encoding='utf-8')
    assert state.MonitorState.load(path).count == 0
    with pytest.raises(state.StateError):
        state.MonitorState.load(path, strict=True)

    (tmp_path / state.LIVE_FILENAME).write_text(
        '{"ts": 1000.0, "x": ' + deep + '}', encoding='utf-8'
    )
    assert state.read_live_snapshot(tmp_path, now=1001.0) is None

    thresholds = tmp_path / 'thresholds.json'
    thresholds.write_text(deep, encoding='utf-8')
    with pytest.raises(ValueError):
        monitor._read_ocp_thresholds_file(str(thresholds))


def test_dump_config_output_error_is_a_clean_exit_not_a_traceback(tmp_path):
    """--dump-config is dispatched before the PSU try/except; an unwritable -O
    escaped as an uncaught OutputError traceback."""
    import os
    import subprocess
    import sys

    if not os.path.exists('/dev/full'):
        import pytest

        pytest.skip('/dev/full is not available')

    result = subprocess.run(
        [sys.executable, '-m', 'msi_psu_monitor', '--dump-config', '-O', '/dev/full'],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert 'Traceback' not in result.stderr
    assert 'cannot write /dev/full' in result.stderr


def test_the_down_rule_does_not_reference_a_label_the_metric_lacks():
    """msi_psu_error_info carries reason; msi_psu_up does not."""
    import pathlib

    rules = pathlib.Path('docs/prometheus-rules.yml').read_text(encoding='utf-8')
    down = rules.split('alert: MsiPsuDown', 1)[1].split('alert:', 1)[0]
    assert 'msi_psu_up' in down
    assert '$labels.reason' not in down
    assert 'msi_psu_error_info' in down


def test_ocp_threshold_file_rejects_non_finite_numbers():
    """JSON 1e999 parses as inf; int(inf) raises OverflowError, not ValueError."""
    import pytest

    from msi_psu_monitor import monitor

    with pytest.raises(ValueError):
        monitor._normalize_ocp_thresholds({'point_a': float('inf')})
    with pytest.raises(ValueError):
        monitor._normalize_ocp_thresholds({'point_a': float('nan')})
    # Comparison must not explode on an inf from a malformed current config.
    assert (
        monitor._ocp_thresholds_equal(
            {
                'enabled': True,
                'point_a': float('inf'),
                'diff_a': 5,
                'trigger_s': 20,
                'diff_trigger_s': 20,
                'warning_s': 180,
            },
            {
                'enabled': True,
                'point_a': 12,
                'diff_a': 5,
                'trigger_s': 20,
                'diff_trigger_s': 20,
                'warning_s': 180,
            },
        )
        is False
    )


def test_every_register_reader_survives_random_short_payloads():
    """Deterministic fuzz (seed 1): 0..64 random bytes × all variants × readers.

    The readers guard lengths, but a new offset must not turn a malformed frame
    into a struct.error/IndexError out of the daemon loop.
    """
    import random

    from msi_psu_monitor.protocol import MSIPSU

    class FakeHID:
        def __init__(self, payload):
            self.payload = payload

        def read_register(self, _reg):
            return self.payload

        def send_command(self, _data, timeout_ms=250):
            return self.payload

        def read_all(self):
            return self.payload

    rng = random.Random(1)
    readers = (
        'read_fan_setting',
        'read_fan_duty',
        'read_fan_state',
        'read_vin',
        'read_ocp_thresholds',
        'read_ocp_state',
        'read_blackbox',
        'read_alert_status',
        'read_multirail_ocp',
    )
    for variant in ('mpg_ai1600ts', 'mpg_ai1300ts', 'meg_ai1600', 'ai1300p', 'ai1000p', None):
        for length in range(0, 65):
            for _ in range(5):
                payload = bytes(rng.randrange(256) for _ in range(length))
                psu = MSIPSU(FakeHID(payload))
                psu.variant = variant
                psu.product = 'x'
                psu.vendor = 'v'
                psu.serial = 's'
                psu.fw_revision = '1.0'
                for reader in readers:
                    getattr(psu, reader)()


def test_negative_daily_energy_buckets_are_dropped(tmp_path):
    """A negative daily kWh would render a negative bar/total."""
    import json

    from msi_psu_monitor import state

    path = tmp_path / 'state.json'
    path.write_text(
        json.dumps({'version': 1, 'daily': {'2026-10-01': -1.5, '2026-10-02': 2.5}}),
        encoding='utf-8',
    )
    loaded = state.MonitorState.load(path)
    assert loaded.daily == {'2026-10-02': 2.5}


def test_atomic_writes_keep_the_existing_file_mode(tmp_path):
    """os.replace gives the target the scratch mode; a 0600 file became 0644."""
    import os
    import stat

    from msi_psu_monitor import state

    path = tmp_path / 'state.json'
    path.write_text('old', encoding='utf-8')
    os.chmod(path, 0o600)
    state.atomic_write_text(path, 'new\n')
    assert path.read_text(encoding='utf-8') == 'new\n'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # New files keep the normal umask-derived mode rather than being forced 600.
    fresh = tmp_path / 'fresh.json'
    state.atomic_write_text(fresh, 'x\n')
    assert stat.S_IMODE(fresh.stat().st_mode) & 0o400


def test_verify_doc_uses_a_version_agnostic_artifact_name():
    """A literal 1.0.0 name sent the checklist to a file the 1.0.1 build never makes."""
    import pathlib
    import re

    text = pathlib.Path('docs/verify.md').read_text(encoding='utf-8')
    literals = re.findall(r'msi-psu-monitor_\d+\.\d+\.\d+_', text)
    assert not literals, literals


def test_live_snapshot_reader_does_not_block_on_a_fifo(tmp_path):
    """A FIFO named latest.json would hang the dashboard's read forever."""
    import os

    import pytest

    from msi_psu_monitor import state

    fifo = state.live_path(tmp_path)
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError):  # pragma: no cover - non-POSIX
        pytest.skip('mkfifo is unavailable')
    assert state.read_live_snapshot(tmp_path, now=1000.0) is None


def test_history_and_alert_appenders_refuse_a_fifo(tmp_path):
    """open('a') on a FIFO blocks forever; the daemon must get an error instead."""
    import os

    import pytest

    import time

    from msi_psu_monitor import state

    now = time.time()
    day = state.date.fromtimestamp(now)
    history = state.history_path(tmp_path, day)
    alert = state.alert_log_path(tmp_path, day)
    try:
        os.mkfifo(history)
        os.mkfifo(alert)
    except (AttributeError, OSError):  # pragma: no cover - non-POSIX
        pytest.skip('mkfifo is unavailable')
    with pytest.raises(OSError):
        state.append_history(tmp_path, {'temp': (30.0, 'C')}, ts=now)
    assert state.append_alert_log(tmp_path, 'ALERT x', ts=now) is None
    assert not history.is_file() and not alert.is_file()


def test_daemon_survives_a_sensor_reader_that_returns_none(tmp_path):
    """'error' in None is a TypeError; the resident loop must count a failed read."""
    from msi_psu_monitor.daemon import MonitorDaemon

    class NoneSensors:
        def open(self):
            return self

        def init(self):
            return 'X'

        def get_sensors(self):
            return None

        def close(self):
            pass

    cfg = {
        'state_dir': str(tmp_path),
        'prom_path': None,
        'sample_interval': 1.0,
        'prom_interval': 30.0,
        'history_interval': 60.0,
        'retention_days': 30,
        'alert_log': False,
        'live_snapshot': False,
        'fan_mode': None,
        'fan_duty': None,
        'fan_zero_fan': None,
        'consecutive_required': 2,
    }
    daemon = MonitorDaemon(
        cfg,
        psu_factory=lambda _p: NoneSensors(),
        select_device=lambda: '/dev/fake',
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    assert daemon.sample() is None
    assert daemon.failures == 1
    assert 'not a dict' in daemon.last_failure


def test_demo_non_ts_models_do_not_report_zero_fan():
    """Real non-TS read_fan_duty returns None for the Zero Fan field."""
    from msi_psu_monitor import demo

    for variant in ('meg_ai1600', 'ai1300p', 'ai1000p'):
        psu = demo.DemoPSU(variant=variant)
        assert 'zero_fan' not in psu.get_sensors(), variant
        assert psu.read_zero_fan() is None, variant
        assert psu.read_fan_state()['zero_fan'] is None, variant
    ts = demo.DemoPSU(variant='mpg_ai1600ts')
    assert 'zero_fan' in ts.get_sensors()
    assert ts.read_zero_fan() is not None


def test_huge_integer_thresholds_do_not_raise_overflow():
    from msi_psu_monitor import alerts
    from msi_psu_monitor.config import threshold_limits

    huge = 10**400
    assert alerts.evaluate_threshold_alerts({'power_total': (1.0, 'W')}, {'power_w': huge}) == {}
    assert alerts.configured_threshold_names({'power_w': huge}, True) == set()
    assert threshold_limits({'power_w': huge})['power_w'] == 0.0


def test_overflowing_sensor_values_are_treated_as_unreadable():
    from msi_psu_monitor.alerts import evaluate_pin_alerts, evaluate_threshold_alerts
    from msi_psu_monitor.state import rail_watts

    huge = 10**400
    assert evaluate_pin_alerts([huge] * 12) == {}
    assert evaluate_threshold_alerts({'power_total': (huge, 'W')}, {'power_w': 1.0}) == {}
    assert (
        rail_watts(
            {
                'vout_12v_rails': ([huge] * 5, 'V'),
                'iout_12v_rails': ([1.0] * 5, 'A'),
            }
        )
        is None
    )


@pytest.mark.parametrize(
    'argv',
    [
        ['--once', '--export', '--from', '2h'],
        ['--once', '--show-log'],
        ['--once', '--show-alert-log'],
        ['--once', '--ocp'],
        ['--once', '--dump-thresholds'],
    ],
)
def test_once_is_rejected_with_a_mode_that_would_ignore_it(argv):
    """--once used to be accepted and then silently discarded by these modes."""
    from msi_psu_monitor import monitor

    parser = monitor.build_parser()
    args = parser.parse_args(argv)
    with pytest.raises(SystemExit) as exc:
        monitor._validate_args(parser, args)
    assert exc.value.code == 2
