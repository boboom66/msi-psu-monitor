"""CLI tests for the new flags: export, fan write, serial select, status lines."""

import csv
import io
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
    """Minimal PSU surface: sensors, alerts, fan read-back."""

    def __init__(self, sensors=None, alerts=None, fan_mode=1, fan_duty=30, accept_write=True):
        self._sensors = sensors if sensors is not None else {}
        self._alerts = alerts
        self.serial = self._sensors.get('serial', 'SN1')
        self.product = self._sensors.get('product', 'MPG Ai1600TS')
        self.fan_mode = fan_mode
        self.fan_duty = fan_duty
        self.accept_write = accept_write
        self.writes = []
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
        return {'mode': self.fan_mode, 'duty': self.fan_duty, 'zero_fan': True}

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


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv('MSI_PSU_STATE_DIR', str(tmp_path))
    return tmp_path


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
    ],
)
def test_conflicting_flags_are_rejected(argv):
    parser = monitor.build_parser()
    args = parser.parse_args(argv)
    with pytest.raises(SystemExit) as exc:
        monitor._validate_args(parser, args)
    assert exc.value.code == 2


def test_fan_mode_and_export_are_not_rejected():
    parser = monitor.build_parser()
    for argv in (['--fan-mode', 'auto'], ['--export', '--from', '2h'], ['--dashboard']):
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
    assert 'msi_psu_power_avg {} 600.0' in out
    assert 'msi_psu_efficiency_avg {} 94.0' in out
    assert 'msi_psu_status_12v_2x6{status="Normal"} 1' in out
    assert 'msi_psu_zero_fan{state="on"} 1' in out
    assert 'msi_psu_total_energy_kwh {}' in out
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
