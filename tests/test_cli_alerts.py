"""CLI exit-code tests for alert/error paths (hardware fully stubbed)."""

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor.monitor import EXIT_ALERT, EXIT_ERROR, EXIT_OK, format_blackbox


class StubHID:
    def open(self):
        return self

    def close(self):
        pass


class StubPSU:
    def __init__(self, sensors, alerts=None, blackbox=None):
        self._sensors = sensors
        self._alerts = alerts
        self._blackbox = blackbox if blackbox is not None else []
        self.opened = False
        self.closed = False

    def open(self):
        self.opened = True
        return self

    def close(self):
        self.closed = True

    def init(self):
        return self._sensors.get('product', '')

    def get_sensors(self):
        return dict(self._sensors)

    def read_alert_status(self):
        return self._alerts

    def read_blackbox(self, max_records=10):
        return self._blackbox[:max_records]


def _run_main(monkeypatch, capsys, stub, argv):
    monkeypatch.setattr(monitor, 'detect_device', lambda: '/dev/hidraw9')
    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: StubHID())
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: stub)
    monkeypatch.setattr('sys.argv', argv)
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    return exc.value.code, capsys.readouterr()


def test_once_clean_exits_zero(monkeypatch, capsys):
    stub = StubPSU({'product': 'MPG Ai1600TS'}, alerts={'ocp_12v': False})
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_OK
    assert 'MPG Ai1600TS' in out.out
    assert stub.closed


def test_once_alert_exits_two_and_prints_line(monkeypatch, capsys):
    stub = StubPSU({'product': 'MPG Ai1600TS'}, alerts={'ocp_pin3': True})
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_ALERT
    assert 'ALERT [warning] ocp_pin3' in out.err


def test_once_unsupported_variant_exits_one(monkeypatch, capsys):
    stub = StubPSU({'product': 'Mystery', 'error': 'unsupported PSU variant'})
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_ERROR
    assert 'unsupported PSU variant' in out.err
    assert 'ERROR' in out.out


def test_no_device_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(monitor, 'detect_device', lambda: None)
    monkeypatch.setattr('sys.argv', ['prog', '--once'])
    with pytest.raises(SystemExit) as exc:
        monitor.main()
    assert exc.value.code == EXIT_ERROR
    assert 'not found' in capsys.readouterr().err


def test_show_log_dumps_blackbox(monkeypatch, capsys):
    records = [
        {
            'info_id': 1,
            'pin_set': 1,
            'status': 2,
            'run_time': 100,
            'total_time': 200,
            'pins_1_6': [1.0] * 6,
            'total_count': 7,
        }
    ]
    stub = StubPSU({'product': 'MPG Ai1600TS'}, blackbox=records)
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once', '--show-log'])
    assert code == EXIT_OK
    assert '#1' in out.out


def test_format_blackbox_empty():
    assert format_blackbox([]) == 'No black-box alert records stored.'


def test_prometheus_carries_alert_metric():
    from msi_psu_monitor.monitor import format_prometheus

    out = format_prometheus({'product': 'P', 'alerts': ['opp', 'fan']})
    assert 'msi_psu_alert{alert="opp"} 1' in out
    assert 'msi_psu_alert{alert="fan"} 1' in out
