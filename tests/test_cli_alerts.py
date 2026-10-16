"""CLI exit-code tests for alert/error paths (hardware fully stubbed)."""

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor.monitor import EXIT_ALERT, EXIT_ERROR, EXIT_OK, format_blackbox


class StubHID:
    def open(self):
        return self

    def close(self):
        pass


# A real sample always carries decoded sensor values; only the ident-only dict of
# a failed 0xE0 read has none, which the CLI reports as an error.
READINGS = {
    'vout_12v': (12.1, 'V'),
    'iout_12v_total': (40.0, 'A'),
    'power_total': (600.0, 'W'),
    'efficiency': (94.0, '%'),
}


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
    stub = StubPSU({'product': 'MPG Ai1600TS', **READINGS}, alerts={'ocp_12v': False})
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_OK
    assert 'MPG Ai1600TS' in out.out
    assert stub.closed


def test_once_alert_exits_two_and_prints_line(monkeypatch, capsys):
    stub = StubPSU({'product': 'MPG Ai1600TS', **READINGS}, alerts={'ocp_pin3': True})
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


def test_format_blackbox_orders_newest_first_from_the_records_own_counters():
    """The header says "newest first"; the slot number cannot be trusted for it.

    Nothing documents which InfoID holds the newest trip, so the order comes from
    the cumulative uptime/trip count each record carries: the numbers printed on
    the lines are the order they appear in, which makes it checkable by eye.
    """
    older = {
        'info_id': 1,
        'pin_set': 2,
        'status': 1,
        'run_time': 120,
        'total_time': 442800,
        'pins_1_6': [1.0] * 6,
        'total_count': 1,
    }
    newer = {
        'info_id': 2,
        'pin_set': 1,
        'status': 2,
        'run_time': 3600,
        'total_time': 446400,
        'pins_1_6': [1.0] * 6,
        'total_count': 3,
    }
    out = format_blackbox([older, newer])
    assert out.index('#2') < out.index('#1')
    assert out.index('total 5d 04:00') < out.index('total 5d 03:00')
    # Same counters -> the device's slot order wins (sorted() is stable).
    tie_a = dict(older, info_id=1)
    tie_b = dict(older, info_id=2)
    assert format_blackbox([tie_a, tie_b]).index('#1') < format_blackbox([tie_a, tie_b]).index('#2')


def test_prometheus_carries_alert_metric():
    from msi_psu_monitor.monitor import format_prometheus

    out = format_prometheus({'product': 'P', 'alerts': ['opp', 'fan']})
    assert 'msi_psu_alert{alert="opp"} 1' in out
    assert 'msi_psu_alert{alert="fan"} 1' in out


def test_once_without_a_sensor_payload_is_an_error(monkeypatch, capsys):
    """An ident-only answer is a failed read, not a healthy PSU with no data."""
    stub = StubPSU({'product': 'MPG Ai1600TS'}, alerts={'ocp_12v': False})
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_ERROR
    assert '0xE0 read failed' in out.err
    assert 'MPG Ai1600TS' in out.out  # the ident we did get is still shown


def test_once_reports_an_alert_even_without_a_sensor_payload(monkeypatch, capsys):
    """E1h is a separate register: a missing payload must not swallow the alarm."""
    stub = StubPSU({'product': 'MPG Ai1600TS'}, alerts={'ocp_pin3': True})
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_ALERT
    assert 'ALERT [warning] ocp_pin3' in out.err
    assert '0xE0 read failed' in out.err


def test_once_says_unknown_when_only_the_pin_mirror_answered(monkeypatch, capsys):
    """`Normal` is a claim about every alert bit, and the mirror cannot see them all.

    With the E1h read NAKed, only the software pin mirror has data; ``opp``,
    ``otp`` and the critical ``fan`` bit are invisible, so the status must not
    read as an all-clear. The exit code stays 0: nothing fired.
    """
    sensors = {
        'product': 'MPG Ai1600TS',
        'vout_12v': (12.1, 'V'),
        'power_total': (600.0, 'W'),
        'iout_pins': ([8.0] * 12, 'A'),
    }
    stub = StubPSU(sensors, alerts=None)
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_OK
    assert '12V-2x6 Status: Unknown' in out.out


def test_once_reports_a_wrong_length_payload_with_the_actual_numbers(monkeypatch, capsys):
    """A mis-sized device should name the mismatch, not claim the read failed."""
    stub = StubPSU(
        {
            'product': 'MPG Ai1600TS',
            'payload_error': '0xE0 payload too short for mpg_ai1600ts: got 20 of 44 bytes',
        },
        alerts={'ocp_12v': False},
    )
    code, out = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_ERROR
    assert 'got 20 of 44 bytes' in out.err
    assert '0xE0 read failed' not in out.err
    # The text output carries the same reason, so a saved artifact explains itself.
    assert 'got 20 of 44 bytes' in out.out


def test_the_cli_writes_only_into_the_isolated_state_dir(monkeypatch, capsys, isolated_state):
    """Regression: these tests used to run ``monitor.main()`` against the real one.

    The module drove full CLI runs with the *default* state directory, so a plain
    ``pytest`` overwrote ``~/.local/state/msi-psu-monitor/state.json`` with stub
    data and pruned the user's own daily buckets with the default retention. The
    suite could not notice because nothing asserted on that directory. The
    isolation now lives in ``tests/conftest.py`` (autouse); this test fails if it
    is ever removed, and it spies on the write itself so it cannot pass vacuously.
    """
    from pathlib import Path

    from msi_psu_monitor import state as stats

    # Guard 1: the override is in place *and* it is not the real default (deleting
    # the override must change the answer, otherwise the check is a tautology).
    real_default = stats.default_state_dir()
    monkeypatch.delenv('MSI_PSU_STATE_DIR')
    monkeypatch.delenv('STATE_DIRECTORY', raising=False)
    assert stats.default_state_dir() != real_default
    monkeypatch.setenv('MSI_PSU_STATE_DIR', str(isolated_state))

    # Guard 2: every path the run actually writes to is inside the throwaway dir.
    written = []
    real_save = stats.MonitorState.save

    def spy_save(self, path):
        written.append(Path(path))
        return real_save(self, path)

    monkeypatch.setattr(stats.MonitorState, 'save', spy_save)

    stub = StubPSU({'product': 'MPG Ai1600TS', **READINGS}, alerts={'ocp_12v': False})
    code, _ = _run_main(monkeypatch, capsys, stub, ['prog', '--once'])
    assert code == EXIT_OK
    assert written, 'the run did not save anything, so this test proves nothing'
    assert all(path.is_relative_to(isolated_state) for path in written)
    assert stats.state_path(isolated_state).exists()
