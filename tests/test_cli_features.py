"""CLI tests for the new flags: export, fan write, serial select, status lines."""

import csv
import io
import json
import logging
import os
import pathlib
import subprocess
import sys
import time

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor import protocol
from msi_psu_monitor import state as stats
from msi_psu_monitor.monitor import EXIT_ALERT, EXIT_ERROR, EXIT_OK


class StubHID:
    def open(self):
        return self

    def close(self):
        pass


class StubPSU:
    """Minimal PSU surface: sensors, alerts, fan/Zero Fan/buzzer read-back."""

    def __init__(
        self,
        sensors=None,
        alerts=None,
        fan_mode=1,
        fan_duty=30,
        accept_write=True,
        zero_fan=True,
        accept_zero_fan=True,
        accept_buzzer=True,
        multirail=True,
        accept_rail=True,
        supports_multirail_ocp=False,
    ):
        self._sensors = sensors if sensors is not None else {}
        self._alerts = alerts
        self.serial = self._sensors.get('serial', 'SN1')
        self.product = self._sensors.get('product', 'MPG Ai1600TS')
        self.fan_mode = fan_mode
        self.fan_duty = fan_duty
        self.accept_write = accept_write
        self.zero_fan = zero_fan
        self.accept_zero_fan = accept_zero_fan
        self.accept_buzzer = accept_buzzer
        self.writes = []
        self.zero_fan_writes = []
        self.buzzer_requests = 0
        self.multirail = multirail
        self.accept_rail = accept_rail
        self.supports_multirail_ocp = supports_multirail_ocp
        self.rail_writes = []
        self.closed = False

    def open(self):
        return self

    def close(self):
        self.closed = True

    def init(self):
        return self.product

    def get_sensors(self):
        return dict(self._sensors)

    def read_alert_status(self):
        return self._alerts

    def read_fan_state(self):
        return {'mode': self.fan_mode, 'duty': self.fan_duty, 'zero_fan': self.zero_fan}

    def read_zero_fan(self):
        return self.zero_fan

    def set_zero_fan(self, enabled):
        self.zero_fan_writes.append(enabled)
        if not self.accept_write:
            return False
        if self.accept_zero_fan:
            self.zero_fan = enabled
        return True

    def silence_buzzer(self):
        self.buzzer_requests += 1
        return self.accept_write and self.accept_buzzer

    def read_multirail_ocp(self):
        return self.multirail if self.supports_multirail_ocp else None

    def set_multirail_ocp(self, enabled):
        self.rail_writes.append(enabled)
        if not (self.accept_write and self.supports_multirail_ocp):
            return False
        if self.accept_rail:
            self.multirail = enabled
        return True

    def read_fan_setting(self):
        return (self.fan_mode, self.fan_duty)

    def set_fan_mode(self, mode, duty=0):
        self.writes.append((mode, duty))
        if self.accept_write:
            self.fan_mode, self.fan_duty = mode, duty
        return True


def sensors(**extra):
    base = {
        'product': 'MPG Ai1600TS',
        'serial': 'SN1',
        'vendor': 'MSI',
        'fw_revision': '1.0',
        'vout_12v': (12.1, 'V'),
        'iout_12v_total': (50.0, 'A'),
        'iout_pins': ([8.0] * 12, 'A'),
        'power_total': (600.0, 'W'),
        'efficiency': (94.0, '%'),
        'temp': (56.0, 'C'),
        'fan_rpm': (2050, 'RPM'),
        'uptime': 2700,
        'uptime_total': 446400,
    }
    base.update(extra)
    return base


def run_main(monkeypatch, capsys, stub, argv):
    monkeypatch.setattr(monitor, 'detect_device', lambda: '/dev/hidraw9')
    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: StubHID())
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: stub)
    monkeypatch.setattr('sys.argv', ['prog'] + argv)
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    return exc.value.code, capsys.readouterr()


# The autouse ``isolated_state`` fixture that points ``MSI_PSU_STATE_DIR`` at a
# tmp dir now lives in ``tests/conftest.py`` so no module can forget it.

# ---- argument validation ------------------------------------------------


@pytest.mark.parametrize(
    'argv',
    [
        ['--watch', '1', '--export', '--from', '2h'],
        ['--from', '2h'],
        ['--columns', 'temp'],
        ['--port', '9000'],
        ['--watch', '1', '-f', 'json'],
        ['--watch', '1', '--once'],
        ['--fan-duty', '50', '--watch', '1'],
        ['--show-log', '-f', 'json'],
        ['--watch', '0'],
        ['--watch', '-1'],
        ['--watch', 'nan'],
        ['--watch', '1', '-i', '0'],
        ['--watch', '1', '-i', 'inf'],
        ['--dashboard', '--export', '--from', '2h'],
        ['--dashboard', '--watch', '1'],
        ['--dashboard', '--show-log'],
        ['--dashboard', '--fan-mode', 'auto'],
        ['--dashboard', '-f', 'json'],
        ['--dashboard', '--port', '99999'],
        ['--dashboard', '--port', '-1'],
        ['--port', '0'],  # valid, but only with --dashboard
        ['--fan-mode', 'auto', '--fan-duty', '50'],
        ['--dashboard', '-O', '/tmp/page.html'],
        ['--dashboard', '--once'],  # the page is a server: it never "reads once"
        ['--dashboard', '--serial', 'ABC123'],  # the page reads history, not a device
        ['-i', '5'],  # a bare --interval used to be accepted and then ignored
        ['--once', '-O', ''],  # an unset $OUT is not "no -O"
        ['--watch', '1', '-O', ''],
        ['--export', '--from', '2h', '-O', ''],
        ['--config', ''],  # an unset $CONF is not "no --config"
        ['--config', '', '--once'],
        ['--serial', ''],  # an unset $SERIAL is not a serial filter
        ['--zero-fan', 'on', '--watch', '1'],
        ['--zero-fan', 'on', '--ocp'],
        ['--zero-fan', 'on', '--show-log'],
        ['--buzzer-off', '--export', '--from', '2h'],
        ['--buzzer-off', '--dashboard'],
        ['--set-rail', 'multi', '--watch', '1'],
        ['--set-rail', 'multi', '--ocp'],
        ['--show-alert-log', '--export', '--from', '2h'],
        ['--show-alert-log', '--show-log'],
        ['--dump-config', '--once'],
        ['--dump-config', '--watch', '1'],
        ['--dump-config', '--serial', 'SN1'],
        ['--dump-config', '--port', '9000'],
        ['--dump-config', '-f', 'prometheus'],
        ['--dump-config', '--dump-thresholds'],
        ['--ocp-set', '13,6,10,12,60', '--watch', '1'],
        ['--ocp-set', '13,6,10,12,60', '--load-thresholds', 'x'],
        ['--dump-thresholds', '--ocp'],
        ['--dump-thresholds', '-f', 'prometheus'],
        ['--load-thresholds', ''],
    ],
)
def test_conflicting_flags_are_rejected(argv):
    parser = monitor.build_parser()
    args = parser.parse_args(argv)
    with pytest.raises(SystemExit) as exc:
        monitor._validate_args(parser, args)
    assert exc.value.code == 2


def test_invalid_ocp_set_values_are_usage_errors():
    parser = monitor.build_parser()
    for argv in (
        ['--ocp-set', '9,6,10,12,60'],
        ['--ocp-set', '13,6,10,12'],
        ['--ocp-set', '13,6,10,12,60,maybe'],
    ):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(argv)
        assert excinfo.value.code == 2


def test_fan_mode_and_export_are_not_rejected():
    parser = monitor.build_parser()
    for argv in (
        ['--fan-mode', 'auto'],
        ['--export', '--from', '2h'],
        ['--dashboard'],
        ['--dump-config'],
        ['--dump-config', '-f', 'json'],
        ['--dump-thresholds'],
        ['--dump-thresholds', '-f', 'json'],
        ['--ocp-set', '13,6,10,12,60'],
        ['--load-thresholds', '/tmp/x.json'],
    ):
        args = parser.parse_args(argv)
        monitor._validate_args(parser, args)  # must not raise


# ---- export -------------------------------------------------------------


def test_export_without_from_exits_one(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['prog', '--export'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == EXIT_ERROR
    assert '--export requires --from' in capsys.readouterr().err


def test_export_writes_history_csv(monkeypatch, capsys, tmp_path):
    stats.append_history(tmp_path, sensors(), ts=time.time())
    monkeypatch.setattr('sys.argv', ['prog', '--export', '--from', '2h', '--columns', 'temp,fan'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    out = capsys.readouterr().out
    assert exc.value.code == EXIT_OK
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ['time', 'temp', 'fan']
    assert rows[1][1:] == ['56.0', '2050']


def test_export_rejects_a_bad_window(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['prog', '--export', '--from', 'soon'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == EXIT_ERROR
    assert 'invalid --from value' in capsys.readouterr().err


def test_output_through_a_symlink_keeps_the_symlink(monkeypatch, capsys, tmp_path):
    """-O must write through a symlink instead of renaming the link away.

    os.replace() replaces the *name*: the previous atomic write turned the link
    into a regular file and left the real target untouched. For /dev/stdout (a
    symlink to /proc/self/fd/1) that is a system-level name when the tool runs as
    root, which the install docs tell users to do.
    """
    real = tmp_path / 'real.txt'
    real.write_text('old output\n', encoding='utf-8')
    link = tmp_path / 'link.txt'
    link.symlink_to(real)
    code, captured = run_main(monkeypatch, capsys, StubPSU(sensors()), ['--once', '-O', str(link)])
    assert code == EXIT_OK
    assert link.is_symlink(), 'the output path replaced the symlink'
    assert real.read_text(encoding='utf-8').startswith('MSI PSU:')
    assert captured.out == ''


def test_export_through_a_symlink_keeps_the_symlink(monkeypatch, capsys, tmp_path):
    stats.append_history(tmp_path, sensors(), ts=time.time())
    real = tmp_path / 'real.csv'
    real.write_text('old export\n', encoding='utf-8')
    link = tmp_path / 'link.csv'
    link.symlink_to(real)
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(sensors()), ['--export', '--from', '2h', '-O', str(link)]
    )
    assert code == EXIT_OK
    assert link.is_symlink(), 'the export replaced the symlink'
    assert real.read_text(encoding='utf-8').startswith('time,')
    assert captured.out == ''


# ---- fan control --------------------------------------------------------


def test_fan_write_sets_and_verifies(monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, out = run_main(
        monkeypatch, capsys, stub, ['--fan-mode', 'customized', '--fan-duty', '80']
    )
    assert code == EXIT_OK
    assert stub.writes == [(3, 80)]
    assert out.out.strip() == 'Fan mode: customized   Duty: 80%'
    assert stub.closed


def test_fan_duty_implies_customized_mode(monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, _ = run_main(monkeypatch, capsys, stub, ['--fan-duty', '55'])
    assert code == EXIT_OK
    assert stub.writes == [(3, 55)]


def test_fan_auto_ignores_duty_and_reports_mode(monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, out = run_main(monkeypatch, capsys, stub, ['--fan-mode', 'auto'])
    assert code == EXIT_OK
    assert stub.writes == [(1, 0)]
    assert out.out.strip() == 'Fan mode: auto'


def test_fan_write_reports_a_readback_mismatch(monkeypatch, capsys):
    stub = StubPSU(sensors(), accept_write=False)
    code, out = run_main(
        monkeypatch, capsys, stub, ['--fan-mode', 'customized', '--fan-duty', '80']
    )
    assert code == EXIT_ERROR
    assert 'read-back mismatch' in out.err
    assert len(stub.writes) == 3  # three attempts before giving up


# ---- device selection ---------------------------------------------------


def test_unknown_serial_lists_available_devices(monkeypatch, capsys):
    monkeypatch.setattr(protocol, 'detect_devices', lambda: ['/dev/hidraw9'])
    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: StubHID())
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: StubPSU(sensors()))
    monkeypatch.setattr('sys.argv', ['prog', '--serial', 'NOPE'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == EXIT_ERROR
    assert 'Available: SN1' in capsys.readouterr().err


def test_matching_serial_is_selected(monkeypatch, capsys):
    monkeypatch.setattr(protocol, 'detect_devices', lambda: ['/dev/hidraw9'])
    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: StubHID())
    stub = StubPSU(sensors(), alerts={'ocp_12v': False})
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: stub)
    monkeypatch.setattr('sys.argv', ['prog', '--serial', 'SN1', '--once'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == EXIT_OK
    assert 'MPG Ai1600TS' in capsys.readouterr().out


# ---- enriched output ----------------------------------------------------


def test_text_includes_status_avg_fan_and_energy(monkeypatch, capsys):
    stub = StubPSU(sensors(), alerts={'ocp_12v': False})
    code, out = run_main(monkeypatch, capsys, stub, ['--once'])
    assert code == EXIT_OK
    assert 'Serial: SN1' in out.out
    assert '12V-2x6 Status: Normal' in out.out
    assert '(AVG 600.00 W)' in out.out
    assert 'Zero Fan: on    Mode: auto' in out.out
    assert 'Uptime     : 0d 00:45:00' in out.out
    assert 'Total energy: 0.0 kWh' in out.out


def test_json_exposes_avg_and_status(monkeypatch, capsys):
    import json

    stub = StubPSU(sensors(), alerts={'ocp_12v': False})
    _, captured = run_main(monkeypatch, capsys, stub, ['--once', '-f', 'json'])
    payload = json.loads(captured.out)
    assert payload['status'] == 'Normal'
    assert payload['power_avg'] == {'value': 600.0, 'unit': 'W'}
    assert payload['zero_fan'] is True
    assert payload['total_energy']['unit'] == 'kWh'


def test_prometheus_exposes_the_new_metrics(monkeypatch, capsys):
    stub = StubPSU(sensors(), alerts={'ocp_12v': False})
    _, captured = run_main(monkeypatch, capsys, stub, ['--once', '-f', 'prometheus'])
    out = captured.out
    assert 'msi_psu_power_avg{} 600.0' in out
    assert 'msi_psu_efficiency_avg{} 94.0' in out
    assert 'msi_psu_energy_kwh_total{}' in out
    assert 'msi_psu_total_energy_kwh{}' in out
    assert 'msi_psu_status_12v_2x6{status="Normal"} 1' in out
    assert 'msi_psu_zero_fan{state="on"} 1' in out
    assert 'msi_psu_total_energy_kwh{}' in out
    assert 'serial="SN1"' in out
    assert 'msi_psu_alert{alert="ocp_12v"}' not in out  # inactive bit is not exported


def test_prometheus_exports_an_active_alert(monkeypatch, capsys):
    stub = StubPSU(sensors(), alerts={'fan': True})
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '-f', 'prometheus'])
    assert code == EXIT_ALERT
    assert 'msi_psu_alert{alert="fan"} 1' in out.out


def test_no_alerts_flag_skips_the_status_line(monkeypatch, capsys):
    stub = StubPSU(sensors(), alerts={'ocp_12v': True})
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '--no-alerts'])
    assert code == EXIT_OK
    assert '12V-2x6 Status' not in out.out


def test_show_log_dumps_blackbox_without_touching_stats(monkeypatch, capsys, tmp_path):
    records = [
        {
            'info_id': 3,
            'pin_set': 1,
            'status': 1,
            'run_time': 100,
            'total_time': 200000,
            'pins_1_6': [13.5] * 6,
            'total_count': 2,
        }
    ]
    stub = StubPSU(sensors(), alerts={'ocp_12v': False})
    stub.read_blackbox = lambda max_records=10: records
    code, out = run_main(monkeypatch, capsys, stub, ['--show-log'])
    assert code == EXIT_OK
    assert 'single-pin OCP (>12A)' in out.out
    assert '0d 00:01:40' in out.out
    assert not stats.state_path(tmp_path).exists()


def test_fan_duty_is_only_reported_in_customized_mode(monkeypatch, capsys):
    """MSI reports the customize duty only while that mode is active."""
    from msi_psu_monitor.monitor import read_fan_fields

    class Psu:
        def __init__(self, mode):
            self.mode = mode

        def read_fan_state(self):
            return {'mode': self.mode, 'duty': 30, 'zero_fan': True}

    assert read_fan_fields(Psu(3))['fan_duty'] == 30
    assert 'fan_duty' not in read_fan_fields(Psu(1))


def test_meg_fan_line_reports_an_unknown_zero_fan(monkeypatch, capsys):
    """A model that cannot be asked must not render as "off" (which reads as OK)."""
    stub = StubPSU(sensors())
    stub.read_fan_state = lambda: {'mode': 1, 'duty': None, 'zero_fan': None}
    _, captured = run_main(monkeypatch, capsys, stub, ['--once'])
    assert 'Zero Fan: unknown   Mode: auto' in captured.out


def test_an_unknown_format_in_the_config_falls_back_to_text(tmp_path, monkeypatch, capsys):
    """A free-text config value must not reach FORMATTERS[...] as a KeyError."""
    conf = tmp_path / 'psu.conf'
    conf.write_text('[monitor]\nformat = xml\n')
    stub = StubPSU(sensors())
    code, captured = run_main(monkeypatch, capsys, stub, ['--once', '--config', str(conf)])
    assert code == EXIT_OK
    assert 'MSI PSU: MPG Ai1600TS' in captured.out  # the text formatter ran
    assert "Ignoring unknown format 'xml'" in captured.err


def test_a_missing_config_file_exits_one(tmp_path, monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, captured = run_main(
        monkeypatch, capsys, stub, ['--once', '--config', str(tmp_path / 'nope.conf')]
    )
    assert code == EXIT_ERROR
    assert 'nope.conf' in captured.err


# ---- output honesty -----------------------------------------------------


def test_a_failed_sample_does_not_look_healthy_in_prometheus(monkeypatch, capsys):
    stub = StubPSU(sensors={'product': 'MPG Ai1600TS', 'payload_error': 'got 10 of 44 bytes'})
    code, captured = run_main(monkeypatch, capsys, stub, ['-f', 'prometheus'])
    assert code == EXIT_ERROR
    assert 'msi_psu_up 0' in captured.out
    assert 'msi_psu_error_info{reason="got 10 of 44 bytes"}' in captured.out


def test_ocp_unsupported_keeps_both_lines_in_one_output_file(monkeypatch, capsys, tmp_path):
    """Two emits truncated the same -O file, so the header line vanished."""
    target = tmp_path / 'ocp.txt'
    stub = StubPSU(sensors())  # no supports_ocp_config: the Ai1600T path
    code, captured = run_main(monkeypatch, capsys, stub, ['--ocp', '-O', str(target)])
    assert code == EXIT_OK
    assert captured.out == ''
    lines = target.read_text().splitlines()
    assert lines[0] == 'MSI PSU: MPG Ai1600TS'
    assert 'not available on this model' in lines[1]
    assert not (tmp_path / 'ocp.txt.tmp').exists()  # the write stayed atomic


def test_serial_scan_reports_devices_it_cannot_open(monkeypatch, capsys):
    """Permission/busy errors were swallowed into "Available: none"."""
    monkeypatch.setattr(protocol, 'detect_devices', lambda: ['/dev/hidraw3'])

    def refuse(path):
        raise PermissionError(13, 'Permission denied')

    monkeypatch.setattr(monitor, 'HIDDevice', refuse)
    monkeypatch.setattr('sys.argv', ['prog', '--serial', 'SN1'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == EXIT_ERROR
    err = capsys.readouterr().err
    assert 'Permission denied' in err
    assert 'could not open any MSI PSU device' in err
    assert 'Available: none' not in err


def test_show_log_writes_to_the_output_file(monkeypatch, capsys, tmp_path):
    """-O means "file instead of screen"; --show-log printed instead."""
    target = tmp_path / 'blackbox.txt'
    stub = StubPSU(sensors())
    stub.read_blackbox = lambda max_records=10: [
        {
            'info_id': 3,
            'pin_set': 1,
            'status': 1,
            'run_time': 100,
            'total_time': 200000,
            'pins_1_6': [13.5] * 6,
            'total_count': 2,
        }
    ]
    code, captured = run_main(monkeypatch, capsys, stub, ['--show-log', '-O', str(target)])
    assert code == EXIT_OK
    assert captured.out == ''
    assert 'GPU Safeguard+' in target.read_text()


def test_a_fan_write_writes_to_the_output_file(monkeypatch, capsys, tmp_path):
    target = tmp_path / 'fan.txt'
    stub = StubPSU(sensors())
    code, captured = run_main(
        monkeypatch,
        capsys,
        stub,
        ['--fan-mode', 'customized', '--fan-duty', '40', '-O', str(target)],
    )
    assert code == EXIT_OK
    assert captured.out == ''
    assert target.read_text().strip() == 'Fan mode: customized   Duty: 40%'


def test_the_watch_banner_is_silent_under_quiet(monkeypatch, capsys, tmp_path):
    """-q promises "errors only on stderr"; the banner is not an error."""
    stub = StubPSU(sensors())
    read = stub.get_sensors
    frames = []

    def counting():
        frames.append(1)
        if len(frames) > 1:
            raise KeyboardInterrupt
        return read()

    stub.get_sensors = counting
    target = tmp_path / 'frames.log'
    code, captured = run_main(
        monkeypatch,
        capsys,
        stub,
        ['--watch', '1', '-i', '0.01', '-O', str(target), '-q'],
    )
    assert code == EXIT_OK
    assert 'Appending frames to' not in captured.err
    assert 'MSI PSU:' in target.read_text()


@pytest.mark.parametrize(
    ('argv', 'expected'),
    [
        (['--watch'], 2.0),  # bare --watch: the documented default
        (['--watch', '5'], 5.0),
        (['--watch', '-i', '0.25'], 0.25),  # -i wins over the default
    ],
)
def test_the_watch_interval_resolution(monkeypatch, capsys, argv, expected):
    slept = []
    monkeypatch.setattr(time, 'sleep', slept.append)
    stub = StubPSU(sensors())
    read = stub.get_sensors
    frames = []

    def counting():
        frames.append(1)
        if len(frames) > 1:
            raise KeyboardInterrupt
        return read()

    stub.get_sensors = counting
    code, _ = run_main(monkeypatch, capsys, stub, argv)
    assert code == EXIT_OK
    assert slept == [expected]


def test_bare_watch_takes_the_interval_from_the_config(monkeypatch, capsys, tmp_path):
    """[monitor] interval used to be dead: the example config advertised it."""
    cfg = tmp_path / 'psu.conf'
    cfg.write_text('[monitor]\ninterval = 7\n')
    slept = []
    monkeypatch.setattr(time, 'sleep', slept.append)
    stub = StubPSU(sensors())
    read = stub.get_sensors
    frames = []

    def counting():
        frames.append(1)
        if len(frames) > 1:
            raise KeyboardInterrupt
        return read()

    stub.get_sensors = counting
    code, _ = run_main(monkeypatch, capsys, stub, ['--config', str(cfg), '--watch'])
    assert code == EXIT_OK
    assert slept == [7.0]


def test_a_config_format_is_not_silently_ignored_in_watch_mode(monkeypatch, capsys, tmp_path):
    """`-f json --watch` is a usage error; from the config it must not be silent."""
    cfg = tmp_path / 'psu.conf'
    cfg.write_text('[monitor]\nformat = json\n')
    stub = StubPSU(sensors())
    read = stub.get_sensors
    frames = []

    def counting():
        frames.append(1)
        if len(frames) > 1:
            raise KeyboardInterrupt
        return read()

    stub.get_sensors = counting
    code, captured = run_main(
        monkeypatch, capsys, stub, ['--config', str(cfg), '--watch', '1', '-i', '0.01']
    )
    assert code == EXIT_OK
    assert 'ignoring [monitor] format' in captured.err
    assert 'MSI PSU:' in captured.out


def test_a_failed_first_frame_leaves_a_self_explanatory_output_file(monkeypatch, capsys, tmp_path):
    """An empty -O artifact explains nothing; --once puts the reason in the file."""
    target = tmp_path / 'frames.log'
    stub = StubPSU({'product': 'MEG Ai1600T', 'error': 'unknown model'})
    code, _ = run_main(monkeypatch, capsys, stub, ['--watch', '1', '-O', str(target)])
    assert code == EXIT_ERROR
    assert 'ERROR' in target.read_text()


def test_watch_appends_frames_to_the_output_file(monkeypatch, capsys, tmp_path):
    """-O means "file instead of screen" everywhere; --watch printed instead.

    The flag was accepted and silently ignored: stdout got the frames and the
    requested file was never created.
    """
    target = tmp_path / 'watch.log'
    stub = StubPSU(sensors())
    read = stub.get_sensors
    frames = []

    def counting():
        frames.append(1)
        if len(frames) > 2:
            raise KeyboardInterrupt  # what Ctrl-C does to the loop
        return read()

    stub.get_sensors = counting
    code, captured = run_main(
        monkeypatch, capsys, stub, ['--watch', '1', '-i', '0.01', '-O', str(target)]
    )
    assert code == EXIT_OK
    assert captured.out == ''
    assert target.read_text().count('MSI PSU: MPG Ai1600TS') == 2
    assert 'Appending frames to' in captured.err


def test_watch_reports_an_unwritable_output(monkeypatch, capsys, tmp_path):
    stub = StubPSU(sensors())
    target = tmp_path / 'missing' / 'watch.log'
    code, captured = run_main(monkeypatch, capsys, stub, ['--watch', '1', '-O', str(target)])
    assert code == EXIT_ERROR
    assert 'cannot write' in captured.err


def test_an_empty_columns_spec_is_not_silently_every_column(monkeypatch, capsys):
    """`--columns "$COLS"` with COLS unset used to export all 11 columns."""
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(), ['--export', '--from', '2h', '--columns', '']
    )
    assert code == EXIT_ERROR
    assert 'at least one column' in captured.err


def test_an_empty_from_spec_names_the_value(monkeypatch, capsys):
    code, captured = run_main(monkeypatch, capsys, StubPSU(), ['--export', '--from', ''])
    assert code == EXIT_ERROR
    assert '--from requires a window' in captured.err


def test_export_reports_an_unwritable_output(monkeypatch, capsys, tmp_path):
    stub = StubPSU(sensors())
    target = tmp_path / 'missing' / 'out.csv'
    code, captured = run_main(
        monkeypatch, capsys, stub, ['--export', '--from', '2h', '-O', str(target)]
    )
    assert code == EXIT_ERROR
    assert 'cannot write' in captured.err


def test_an_empty_export_says_the_window_found_nothing(monkeypatch, capsys, tmp_path):
    """Header-only CSV used to be indistinguishable from a wrong state dir."""
    stub = StubPSU(sensors())
    code, captured = run_main(monkeypatch, capsys, stub, ['--export', '--from', '2h'])
    assert code == EXIT_OK
    assert captured.out.strip() == 'time,cpu,gpu,12v,5v,3v3,temp,fan,eff'
    assert 'No history rows' in captured.err


def test_once_prunes_with_the_configured_retention(monkeypatch, capsys, tmp_path):
    """[daemon] retention_days = 60 must not be cut to 30 by a --once run."""
    from msi_psu_monitor import state as stats

    cfg = tmp_path / 'psu.conf'
    cfg.write_text('[daemon]\nretention_days = 60\n')
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    old = time.time() - 40 * 86400
    monitor_state = stats.MonitorState()
    monitor_state.update(600.0, 94.0, ts=old)
    monitor_state.update(600.0, 94.0, ts=old + 10)
    assert monitor_state.daily  # a bucket dated 40 days ago
    monitor_state.save(stats.state_path(state_dir))
    monkeypatch.setenv('MSI_PSU_STATE_DIR', str(state_dir))

    stub = StubPSU(sensors())
    code, _ = run_main(monkeypatch, capsys, stub, ['--config', str(cfg), '--once'])
    assert code == EXIT_OK
    kept = stats.MonitorState.load(stats.state_path(state_dir))
    assert kept.daily, 'the 40-day-old bucket must survive with retention_days = 60'


@pytest.mark.parametrize('argv', (['--once'], ['--help'], ['--version']))
def test_a_closed_stdout_pipe_is_not_a_traceback(tmp_path, argv):
    """A shell pipeline that stops reading is normal usage, not a CLI fault.

    Unhandled, BrokenPipeError escapes as exit 120 plus "Exception ignored on
    flushing sys.stdout", which looks like a crash in scripts and cron mail.
    --help/--version leave through argparse's SystemExit before the main handler,
    so they exercise the final-flush path separately.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    env = dict(os.environ, MSI_PSU_DEMO='1', MSI_PSU_STATE_DIR=str(tmp_path))
    read_fd, write_fd = os.pipe()
    os.close(read_fd)  # no reader: the first write gets EPIPE
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'msi_psu_monitor', *argv],
            cwd=root,
            stdout=write_fd,
            stderr=subprocess.PIPE,
            env=env,
            timeout=30,
        )
    finally:
        os.close(write_fd)
    assert proc.returncode == 0, proc.stderr.decode()
    assert b'BrokenPipeError' not in proc.stderr
    assert b'Traceback' not in proc.stderr


def test_zero_fan_write_sets_and_verifies(monkeypatch, capsys):
    stub = StubPSU(sensors(), zero_fan=True)
    code, out = run_main(monkeypatch, capsys, stub, ['--zero-fan', 'off'])
    assert code == EXIT_OK
    assert stub.zero_fan_writes == [False]
    assert out.out.strip() == 'Zero Fan: off'


def test_zero_fan_readback_mismatch_exits_one(monkeypatch, capsys):
    stub = StubPSU(sensors(), zero_fan=True, accept_zero_fan=False)
    code, out = run_main(monkeypatch, capsys, stub, ['--zero-fan', 'off'])
    assert code == EXIT_ERROR
    assert len(stub.zero_fan_writes) == 3  # three attempts, like the fan write
    assert 'Zero Fan' in out.err


def test_zero_fan_and_fan_mode_write_together(monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, out = run_main(monkeypatch, capsys, stub, ['--zero-fan', 'on', '--fan-duty', '70'])
    assert code == EXIT_OK
    assert stub.zero_fan_writes == [True]
    assert stub.writes == [(3, 70)]
    assert out.out.strip().splitlines() == [
        'Zero Fan: on',
        'Fan mode: customized   Duty: 70%',
    ]


def test_buzzer_off_writes_and_reports_the_switch(monkeypatch, capsys):
    """C2h is MSI's BUZZER_SWITCH: write-only and a toggle, so no "silenced" claim."""
    stub = StubPSU(sensors())
    code, out = run_main(monkeypatch, capsys, stub, ['--buzzer-off'])
    assert code == EXIT_OK
    assert stub.buzzer_requests == 1
    assert out.out.strip() == 'Buzzer: switch toggled (no read-back)'


def test_buzzer_off_refused_exits_one(monkeypatch, capsys):
    stub = StubPSU(sensors(), accept_buzzer=False)
    code, out = run_main(monkeypatch, capsys, stub, ['--buzzer-off'])
    assert code == EXIT_ERROR
    assert 'buzzer-off' in out.err


def test_set_rail_writes_and_verifies(monkeypatch, capsys):
    stub = StubPSU(sensors(), multirail=False, supports_multirail_ocp=True)
    code, out = run_main(monkeypatch, capsys, stub, ['--set-rail', 'multi'])
    assert code == EXIT_OK
    assert stub.rail_writes == [True]
    assert stub.multirail is True
    assert out.out.strip() == 'Rail mode: multi'


def test_set_rail_is_a_noop_when_already_in_the_requested_mode(monkeypatch, capsys):
    """The hardware rejects writing the value it already holds (REQ-11).

    Reading first also avoids burning an F1h flash save on every idempotent run.
    """
    stub = StubPSU(sensors(), multirail=True, supports_multirail_ocp=True)
    code, out = run_main(monkeypatch, capsys, stub, ['--set-rail', 'multi'])
    assert code == EXIT_OK
    assert stub.rail_writes == [], 'a same-value write must not be sent'
    assert out.out.strip() == 'Rail mode: multi (already set)'


def test_set_rail_readback_mismatch_exits_one(monkeypatch, capsys):
    stub = StubPSU(sensors(), multirail=False, accept_rail=False, supports_multirail_ocp=True)
    code, out = run_main(monkeypatch, capsys, stub, ['--set-rail', 'multi'])
    assert code == EXIT_ERROR
    assert len(stub.rail_writes) == 3
    assert 'rail mode' in out.err


def test_set_rail_is_refused_on_a_ts_model(monkeypatch, capsys):
    stub = StubPSU(sensors(), supports_multirail_ocp=False)
    code, out = run_main(monkeypatch, capsys, stub, ['--set-rail', 'single'])
    assert code == EXIT_ERROR
    assert 'rail mode' in out.err


def test_fan_performance_is_an_alias_for_the_psu_curve(monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, out = run_main(monkeypatch, capsys, stub, ['--fan-mode', 'performance'])
    assert code == EXIT_OK
    assert stub.writes == [(1, 0)]
    assert out.out.strip() == 'Fan mode: performance'


def test_show_alert_log_prints_the_local_file(monkeypatch, capsys, tmp_path):
    stats.append_alert_log(tmp_path, 'ALERT [warning] ocp_pin1: over-current', ts=1000.0)
    code, out = run_main(monkeypatch, capsys, StubPSU(sensors()), ['--show-alert-log'])
    assert code == EXIT_OK
    assert 'ALERT [warning] ocp_pin1: over-current' in out.out


def test_show_alert_log_reports_an_empty_log(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, StubPSU(sensors()), ['--show-alert-log'])
    assert code == EXIT_OK
    assert out.out.strip() == 'No alert log records stored.'


def test_successful_writes_leave_an_audit_line(monkeypatch, capsys, caplog):
    stub = StubPSU(sensors())
    with caplog.at_level('INFO', logger='msi_psu_monitor.monitor'):
        code, _ = run_main(
            monkeypatch,
            capsys,
            stub,
            ['--fan-mode', 'customized', '--fan-duty', '60', '--buzzer-off'],
        )
    assert code == EXIT_OK
    assert 'write fan mode=customized duty=60 verified=true' in caplog.text
    assert 'write buzzer=toggled verified=false' in caplog.text
    assert 'SN1' not in caplog.text


def test_once_reports_an_unwritable_output_as_an_output_error(monkeypatch, capsys, tmp_path):
    """A bad -O path must not be reported as "Permission denied. Run as root."

    The output error used to be raised as PermissionError and swallowed by the
    handler that is meant for the PSU device, which sent the user to sudo for a
    path typo.
    """
    stub = StubPSU(sensors())
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory')
    target = blocker / 'once.out'
    code, captured = run_main(monkeypatch, capsys, stub, ['--once', '-O', str(target)])
    assert code == EXIT_ERROR
    assert 'cannot write' in captured.err
    assert 'Run as root' not in captured.err


def test_show_alert_log_reports_an_unwritable_output(monkeypatch, capsys, tmp_path):
    """--show-alert-log ran before the PSU try/except and used to traceback on -O."""
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory')
    target = blocker / 'alerts.log'
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(), ['--show-alert-log', '-O', str(target)]
    )
    assert code == EXIT_ERROR
    assert 'cannot write' in captured.err
    assert 'Traceback' not in captured.err


def test_show_log_reports_an_unwritable_output(monkeypatch, capsys, tmp_path):
    stub = StubPSU(sensors())
    stub.read_blackbox = lambda: []
    blocker = tmp_path / 'blocker'
    blocker.write_text('not a directory')
    target = blocker / 'log.out'
    code, captured = run_main(monkeypatch, capsys, stub, ['--show-log', '-O', str(target)])
    assert code == EXIT_ERROR
    assert 'cannot write' in captured.err


def test_export_preserves_an_existing_file_when_the_write_fails(monkeypatch, capsys, tmp_path):
    """A failed export must not leave a truncated file where the old one was."""
    target = tmp_path / 'out.csv'
    target.write_text('old export\n', encoding='utf-8')

    def explode(stream, header, rows):
        stream.write('partial\n')
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(monitor, '_write_csv', explode)
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(), ['--export', '--from', '2h', '-O', str(target)]
    )
    assert code == EXIT_ERROR
    assert 'cannot write' in captured.err
    assert target.read_text(encoding='utf-8') == 'old export\n'
    assert not (tmp_path / 'out.csv.tmp').exists()


@pytest.mark.parametrize(
    'argv',
    [
        ['--export', '--from', '2h', '-f', 'json'],
        ['--export', '--from', '2h', '--serial', 'SN1'],
        ['--fan-mode', 'auto', '-f', 'json'],
        ['--buzzer-off', '-f', 'prometheus'],
    ],
)
def test_flags_that_would_be_silently_ignored_are_rejected(monkeypatch, capsys, argv):
    """--format/--serial must not be accepted by modes that cannot honour them."""
    code, captured = run_main(monkeypatch, capsys, StubPSU(sensors()), list(argv))
    assert code == 2
    assert 'does not apply' in captured.err


def test_a_config_format_is_ignored_with_a_warning_in_fixed_format_modes(
    monkeypatch, capsys, tmp_path
):
    """CLI rejects -f json with writes; a config-file format must not be silent."""
    conf = tmp_path / 'psu.conf'
    conf.write_text('[monitor]\nformat = json\n', encoding='utf-8')
    stub = StubPSU(sensors())
    code, captured = run_main(
        monkeypatch, capsys, stub, ['--fan-mode', 'auto', '--config', str(conf)]
    )
    assert code == EXIT_OK
    assert captured.out.strip() == 'Fan mode: auto'
    assert 'fixed output format' in captured.err


def test_serial_discovery_skips_an_unexpected_parser_error(monkeypatch, caplog):
    """A malformed device must be reported blocked, not crash --serial discovery."""

    class BadPSU:
        serial = ''

        def open(self):
            return self

        def init(self):
            raise ValueError('bad identification payload')

        def close(self):
            pass

    monkeypatch.setattr(protocol, 'detect_devices', lambda: ['/dev/hidraw9'])
    monkeypatch.setattr(monitor, 'HIDDevice', lambda _path: StubHID())
    monkeypatch.setattr(monitor, 'MSIPSU', lambda _hid: BadPSU())
    with caplog.at_level(logging.WARNING, logger='msi_psu.monitor'):
        path, available, blocked = monitor.resolve_device('SN123')
    assert path is None
    assert available == []
    assert blocked == ['/dev/hidraw9']
    assert 'unexpected error' in caplog.text


# ---- local early-warning thresholds -------------------------------------


def test_a_configured_threshold_trips_exit_two(monkeypatch, capsys):
    stub = StubPSU(sensors(power_total=(1500.0, 'W'), temp=(80.0, 'C')))
    code, out = run_main(monkeypatch, capsys, stub, ['--once'])
    assert code == EXIT_ALERT
    assert 'ALERT [warning] power_high' in out.err
    assert 'ALERT [warning] temp_high' in out.err
    assert 'measured 1500, limit 1200' in out.err
    assert 'measured 80, limit 70' in out.err
    assert 'Thresholds    : power_high, temp_high' in out.out


def test_a_config_threshold_override_can_keep_the_same_sample_normal(monkeypatch, capsys, tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[alerts]\npower_w = 2000\ntemp_c = 90\n', encoding='utf-8')
    stub = StubPSU(sensors(power_total=(1500.0, 'W'), temp=(80.0, 'C')))
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '--config', str(conf)])
    assert code == EXIT_OK
    assert 'Thresholds' not in out.out
    assert 'ALERT' not in out.err


def test_thresholds_appear_in_json(monkeypatch, capsys):
    stub = StubPSU(sensors(power_total=(1500.0, 'W')))
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '-f', 'json'])
    assert code == EXIT_ALERT
    payload = json.loads(out.out)
    assert payload['threshold_alerts'] == ['power_high']
    assert payload['threshold_limits']['power_w'] == 1200.0
    assert payload['threshold_limits']['temp_c'] == 70.0


def test_thresholds_appear_in_prometheus(monkeypatch, capsys):
    stub = StubPSU(sensors())
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '-f', 'prometheus'])
    assert code == EXIT_OK
    assert 'msi_psu_threshold_limit{name="power_w"} 1200.0' in out.out
    assert 'msi_psu_threshold_limit{name="pin_max_a"} 12.0' in out.out
    assert 'msi_psu_threshold_alert' not in out.out

    stub = StubPSU(sensors(power_total=(1500.0, 'W')))
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '-f', 'prometheus'])
    assert code == EXIT_ALERT
    assert 'msi_psu_threshold_alert{alert="power_high"} 1' in out.out


def test_no_alerts_skips_the_local_thresholds_too(monkeypatch, capsys):
    stub = StubPSU(sensors(power_total=(1500.0, 'W'), temp=(80.0, 'C')))
    code, out = run_main(monkeypatch, capsys, stub, ['--once', '--no-alerts', '-f', 'json'])
    assert code == EXIT_OK
    payload = json.loads(out.out)
    assert 'threshold_alerts' not in payload
    assert 'threshold_limits' not in payload


# ---- --dump-config ------------------------------------------------------


def test_dump_config_prints_effective_thresholds_without_a_psu(monkeypatch, capsys):
    code, out = run_main(monkeypatch, capsys, StubPSU(), ['--dump-config'])
    assert code == EXIT_OK
    assert '[alerts]' in out.out
    assert 'power_w = 1200.0' in out.out
    assert 'rail_12v_a = 108.33' in out.out
    assert out.err == ''


def test_dump_config_json_reflects_a_config_override(monkeypatch, capsys, tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[alerts]\npower_w = 900\ntemp_c = 65\n', encoding='utf-8')
    code, out = run_main(
        monkeypatch, capsys, StubPSU(), ['--dump-config', '-f', 'json', '--config', str(conf)]
    )
    assert code == EXIT_OK
    payload = json.loads(out.out)
    assert payload['power_w'] == 900.0
    assert payload['temp_c'] == 65.0
    assert payload['pin_max_a'] == 12.0


def test_dump_config_can_write_to_a_file(monkeypatch, capsys, tmp_path):
    target = tmp_path / 'effective.ini'
    code, out = run_main(monkeypatch, capsys, StubPSU(), ['--dump-config', '-O', str(target)])
    assert code == EXIT_OK
    assert out.out == ''
    body = target.read_text(encoding='utf-8')
    assert '[alerts]' in body and 'power_w = 1200.0' in body


# ---- hardware OCP threshold write / dump / load (MPG TS) -----------------


class ThresholdPSU:
    """Read/write OCP thresholds the way protocol.MSIPSU does (no hardware)."""

    supports_ocp_config = True

    def __init__(self, config=None, accept=True, readback_updates=True):
        self.config = dict(
            config
            or {
                'enabled': True,
                'point_a': 12.0,
                'diff_a': 5.0,
                'trigger_s': 20,
                'diff_trigger_s': 20,
                'warning_s': 180,
            }
        )
        self.accept = accept
        self.readback_updates = readback_updates
        self.writes = []
        self.product = 'MPG Ai1600TS'
        self.fw_revision = '1.0'

    def open(self):
        return self

    def init(self):
        return self.product

    def close(self):
        pass

    def read_ocp_thresholds(self):
        return dict(self.config)

    def set_ocp_thresholds(self, config):
        self.writes.append(dict(config))
        if not self.accept:
            return False
        if self.readback_updates:
            self.config = dict(config)
        return True


def test_dump_thresholds_prints_text_and_json(monkeypatch, capsys):
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--dump-thresholds'])
    assert code == EXIT_OK
    assert 'Pin OCP point' in out.out
    assert '12.0 A' in out.out

    code, out = run_main(monkeypatch, capsys, stub, ['--dump-thresholds', '-f', 'json'])
    assert code == EXIT_OK
    payload = json.loads(out.out)
    assert payload['ocp_config']['point_a'] == 12.0
    assert payload['ocp_config']['warning_s'] == 180


def test_ocp_set_writes_and_verifies(monkeypatch, capsys):
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--ocp-set', '13,6,10,12,60'])
    assert code == EXIT_OK
    assert len(stub.writes) == 1
    assert stub.writes[0]['point_a'] == 13
    assert stub.config['diff_a'] == 6
    assert 'OCP thresholds: point 13.0 A' in out.out
    assert 'trigger 10 s' in out.out


def test_ocp_set_is_idempotent(monkeypatch, capsys):
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--ocp-set', '12,5,20,20,180'])
    assert code == EXIT_OK
    assert stub.writes == []
    assert '(already set)' in out.out


def test_ocp_set_readback_mismatch_exits_one(monkeypatch, capsys):
    stub = ThresholdPSU(readback_updates=False)
    code, out = run_main(monkeypatch, capsys, stub, ['--ocp-set', '13,6,10,12,60'])
    assert code == EXIT_ERROR
    assert len(stub.writes) == 3
    assert 'read-back mismatch' in out.err


def test_ocp_set_is_refused_on_a_model_without_the_8_byte_view(monkeypatch, capsys):
    stub = ThresholdPSU()
    stub.supports_ocp_config = False
    code, out = run_main(monkeypatch, capsys, stub, ['--ocp-set', '13,6,10,12,60'])
    assert code == EXIT_ERROR
    assert stub.writes == []
    assert 'not available on this model' in out.err


def test_load_thresholds_reads_a_dump_and_writes(monkeypatch, capsys, tmp_path):
    path = tmp_path / 'thresholds.json'
    path.write_text(
        json.dumps(
            {
                'ocp_config': {
                    'enabled': False,
                    'point_a': 11.0,
                    'diff_a': 6.0,
                    'trigger_s': 9,
                    'diff_trigger_s': 10,
                    'warning_s': 45,
                }
            }
        ),
        encoding='utf-8',
    )
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--load-thresholds', str(path)])
    assert code == EXIT_OK
    assert stub.config['point_a'] == 11.0
    assert stub.config['enabled'] is False
    assert 'enabled no' in out.out


def test_dump_thresholds_is_refused_on_an_unsupported_model(monkeypatch, capsys):
    stub = ThresholdPSU()
    stub.supports_ocp_config = False
    code, out = run_main(monkeypatch, capsys, stub, ['--dump-thresholds'])
    assert code == EXIT_ERROR
    assert 'not available on this model' in out.err


def test_ocp_set_explains_a_failed_configuration_read(monkeypatch, capsys):
    stub = ThresholdPSU()
    stub.read_ocp_thresholds = lambda: None
    code, out = run_main(monkeypatch, capsys, stub, ['--ocp-set', '13,6,10,12,60'])
    assert code == EXIT_ERROR
    assert 'did not answer the 0xC0 OCP configuration read' in out.err
    assert stub.writes == []


def test_ocp_set_can_disable_ocp_with_the_optional_flag(monkeypatch, capsys):
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--ocp-set', '13,6,10,12,60,off'])
    assert code == EXIT_OK
    assert stub.config['enabled'] is False
    assert 'enabled no' in out.out


def test_load_thresholds_rejects_unknown_keys(monkeypatch, capsys, tmp_path):
    path = tmp_path / 'thresholds.json'
    path.write_text(json.dumps({'point_a': 12, 'point_a_typo': 5}), encoding='utf-8')
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--load-thresholds', str(path)])
    assert code == EXIT_ERROR
    assert 'unknown threshold key(s): point_a_typo' in out.err
    assert stub.writes == []


def test_load_thresholds_reports_malformed_json(monkeypatch, capsys, tmp_path):
    path = tmp_path / 'thresholds.json'
    path.write_text('{not json', encoding='utf-8')
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--load-thresholds', str(path)])
    assert code == EXIT_ERROR
    assert 'cannot load OCP thresholds' in out.err


def test_load_thresholds_rejects_out_of_range_values(monkeypatch, capsys, tmp_path):
    path = tmp_path / 'thresholds.json'
    path.write_text(json.dumps({'point_a': 99}), encoding='utf-8')
    stub = ThresholdPSU()
    code, out = run_main(monkeypatch, capsys, stub, ['--load-thresholds', str(path)])
    assert code == EXIT_ERROR
    assert 'point_a must be 10-14' in out.err
    assert stub.writes == []


def test_a_config_json_format_is_ignored_for_threshold_modes(monkeypatch, capsys, tmp_path):
    conf = tmp_path / 'psu.conf'
    conf.write_text('[monitor]\nformat = json\n', encoding='utf-8')
    stub = ThresholdPSU()
    code, captured = run_main(
        monkeypatch, capsys, stub, ['--ocp-set', '13,6,10,12,60', '--config', str(conf)]
    )
    assert code == EXIT_OK
    assert 'fixed output format' in captured.err
    assert 'OCP thresholds:' in captured.out

    code, captured = run_main(
        monkeypatch, capsys, stub, ['--dump-thresholds', '--config', str(conf)]
    )
    assert code == EXIT_OK
    assert 'fixed output format' not in captured.err
    payload = json.loads(captured.out)
    assert payload['ocp_config']['point_a'] == 13.0


def test_watch_survives_an_unwritable_state_directory(monkeypatch, capsys):
    """A read-only state dir must not end the sample stream or Ctrl-C with exit 1."""
    stub = StubPSU(sensors())
    read = stub.get_sensors
    frames = []

    def counting():
        frames.append(1)
        if len(frames) > 1:
            raise KeyboardInterrupt
        return read()

    stub.get_sensors = counting

    def refuse(_self, _path):
        raise OSError(13, 'Permission denied')

    monkeypatch.setattr(stats.MonitorState, 'save', refuse)
    code, captured = run_main(monkeypatch, capsys, stub, ['--watch', '1', '-i', '0.01', '-q'])
    assert code == EXIT_OK
    assert 'Cannot persist state' in captured.err
    assert 'MSI PSU:' in captured.out


def test_once_still_prints_the_frame_when_state_cannot_be_saved(monkeypatch, capsys):
    """The reading is the output; an unwritable state dir must not hide it."""
    stub = StubPSU(sensors())

    def refuse(_self, _path):
        raise OSError(13, 'Permission denied')

    monkeypatch.setattr(stats.MonitorState, 'save', refuse)
    code, captured = run_main(monkeypatch, capsys, stub, ['--once'])
    assert code == EXIT_OK
    assert 'MSI PSU:' in captured.out
    assert 'Cannot persist state' in captured.err


def test_show_alert_log_reports_a_read_error_instead_of_no_records(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise OSError(5, 'Input/output error')

    monkeypatch.setattr(stats, 'iter_alert_log', boom)
    code, captured = run_main(monkeypatch, capsys, StubPSU(), ['--show-alert-log'])
    assert code == EXIT_ERROR
    assert 'cannot read the alert log' in captured.err
    assert 'No alert log records stored' not in captured.out


def test_export_reports_a_history_read_error(monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise OSError(5, 'Input/output error')

    monkeypatch.setattr(stats, 'build_export', boom)
    code, captured = run_main(monkeypatch, capsys, StubPSU(), ['--export', '--from', '2h'])
    assert code == EXIT_ERROR
    assert 'cannot read the history' in captured.err


def test_export_keeps_the_existing_output_mode(monkeypatch, capsys, tmp_path):
    """Replacing a 0600 CSV must not widen it to the umask default."""
    import os
    import stat

    target = tmp_path / 'out.csv'
    target.write_text('old\n', encoding='utf-8')
    os.chmod(target, 0o600)
    code, _ = run_main(
        monkeypatch, capsys, StubPSU(sensors()), ['--export', '--from', '2h', '-O', str(target)]
    )
    assert code == EXIT_OK
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_config_serial_is_not_silently_ignored_by_export(monkeypatch, capsys, tmp_path):
    conf = tmp_path / 'serial.conf'
    conf.write_text('[monitor]\nserial = ABC\n', encoding='utf-8')
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(sensors()), ['--export', '--from', '2h', '--config', str(conf)]
    )
    assert code == EXIT_OK
    assert 'ignoring [monitor] serial' in captured.err


def test_config_serial_is_not_silently_ignored_by_show_alert_log(monkeypatch, capsys, tmp_path):
    conf = tmp_path / 'serial.conf'
    conf.write_text('[monitor]\nserial = ABC\n', encoding='utf-8')
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(sensors()), ['--show-alert-log', '--config', str(conf)]
    )
    assert code == EXIT_OK
    assert 'ignoring [monitor] serial' in captured.err


def test_config_output_and_serial_are_not_silently_ignored_by_dashboard(
    monkeypatch, capsys, tmp_path
):
    conf = tmp_path / 'dash.conf'
    conf.write_text('[monitor]\nserial = ABC\noutput = /tmp/never-written\n', encoding='utf-8')
    started = []
    monkeypatch.setattr(monitor, 'run_dashboard', lambda args, cfg: started.append(True) or 0)
    code, captured = run_main(
        monkeypatch, capsys, StubPSU(sensors()), ['--dashboard', '--config', str(conf)]
    )
    assert code == EXIT_OK
    assert started == [True]
    assert 'ignoring [monitor] output' in captured.err
    assert 'ignoring [monitor] serial' in captured.err
