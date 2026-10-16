"""Tests for the resident daemon sample loop (device and clock fully faked)."""

import logging
import time

from msi_psu_monitor import state as stats
from msi_psu_monitor.config import DEFAULTS
from msi_psu_monitor.daemon import RESCAN_AFTER_FAILURES, MonitorDaemon


class Clock:
    """Deterministic stand-in for time.monotonic/time.time."""

    def __init__(self, start=None):
        self.now = time.time() if start is None else start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StubPSU:
    def __init__(self, sensors=None, alerts=None, fan=None, error=None):
        self._sensors = sensors if sensors is not None else {}
        self._alerts = alerts
        self._fan = fan or {}
        self.error = error
        self.reads = 0
        self.closed = False

    def open(self):
        return self

    def init(self):
        return self._sensors.get('product', 'MPG Ai1600TS')

    def close(self):
        self.closed = True

    def get_sensors(self):
        self.reads += 1
        if self.error is not None:
            return {'product': 'MPG Ai1600TS', 'error': self.error}
        return dict(self._sensors)

    def read_alert_status(self):
        return self._alerts

    def read_fan_state(self):
        return dict(self._fan)


def clean_sensors():
    return {
        'product': 'MPG Ai1600TS',
        'serial': 'SN1234',
        'vout_12v': (12.1, 'V'),
        'iout_pins': ([8.0] * 12, 'A'),
        'power_total': (600.0, 'W'),
        'efficiency': (94.0, '%'),
        'temp': (56.0, 'C'),
        'fan_rpm': (2050, 'RPM'),
    }


def make_daemon(tmp_path, psu, clock=None, **overrides):
    cfg = dict(DEFAULTS)
    cfg.update({'state_dir': str(tmp_path), 'consecutive_required': 1})
    cfg.update(overrides)
    clock = clock or Clock()
    created = []

    def factory(path):
        created.append(path)
        return psu

    daemon = MonitorDaemon(
        cfg,
        psu_factory=factory,
        select_device=lambda: '/dev/hidraw9',
        clock=clock,
        wall_clock=clock,
    )
    daemon.created = created
    return daemon


def test_sample_enriches_and_accumulates(tmp_path):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': False}))
    sample = daemon.sample()
    assert sample['status'] == 'Normal'
    assert sample['alerts'] == []
    assert sample['power_avg'] == (600.0, 'W')
    assert daemon.state.count == 1
    assert daemon.state.serial == 'SN1234'


def test_sample_reports_unknown_status_when_no_alert_source(tmp_path):
    bare = clean_sensors()
    del bare['iout_pins']
    daemon = make_daemon(tmp_path, StubPSU(bare, alerts=None))
    assert daemon.sample()['status'] == 'Unknown'


def test_tick_cadence_prom_30s_history_60s(tmp_path):
    clock = Clock()
    daemon = make_daemon(
        tmp_path,
        StubPSU(clean_sensors(), alerts={'ocp_12v': False}),
        clock=clock,
        prom_path=str(tmp_path / 'psu.prom'),
    )
    assert daemon.tick()
    prom = tmp_path / 'psu.prom'
    assert 'msi_psu_power_total {} 600.0' in prom.read_text()
    assert not prom.with_name('psu.prom.tmp').exists()
    assert len(list(tmp_path.glob('daily-*.log'))) == 1

    clock.advance(1)
    assert daemon.tick()
    assert daemon.samples == 2  # sampled, but below both write intervals

    clock.advance(30)
    assert daemon.tick()
    assert daemon.state.count == 3


def test_prometheus_is_written_atomically_and_replaced(tmp_path):
    clock = Clock()
    daemon = make_daemon(
        tmp_path,
        StubPSU(clean_sensors(), alerts={'ocp_12v': False}),
        clock=clock,
        prom_path=str(tmp_path / 'run' / 'psu.prom'),
    )
    daemon.tick()
    target = tmp_path / 'run' / 'psu.prom'
    assert target.exists()
    clock.advance(1)
    daemon.sample()
    daemon.write_prometheus(daemon.sample())
    assert target.read_text().count('msi_psu_power_total {}') == 1


def test_alert_is_logged_only_after_the_debounce(tmp_path, caplog):
    daemon = make_daemon(
        tmp_path,
        StubPSU(clean_sensors(), alerts={'ocp_pin3': True}),
        consecutive_required=2,
    )
    daemon.engine.consecutive_required = 2
    with caplog.at_level(logging.WARNING, logger='msi_psu'):
        daemon.sample()
        assert not [r for r in caplog.records if 'ALERT' in r.message]
        daemon.sample()
    assert any('ALERT [warning] ocp_pin3' in r.message for r in caplog.records)


def test_five_read_failures_trigger_a_rescan(tmp_path):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors(), error='short read'))
    for _ in range(RESCAN_AFTER_FAILURES):
        assert daemon.sample() is None
    assert daemon.psu is None
    assert daemon.device_path is None
    assert daemon.created == ['/dev/hidraw9']

    daemon.sample()  # rediscovers and reopens
    assert daemon.created == ['/dev/hidraw9', '/dev/hidraw9']


def test_history_is_written_once_per_interval(tmp_path):
    clock = Clock()
    daemon = make_daemon(
        tmp_path,
        StubPSU(clean_sensors(), alerts={'ocp_12v': False}),
        clock=clock,
    )
    daemon.tick()
    clock.advance(1)
    daemon.tick()
    lines = next(tmp_path.glob('daily-*.log')).read_text().splitlines()
    assert len(lines) == 2  # header + one sample
    clock.advance(60)
    daemon.tick()
    assert len(next(tmp_path.glob('daily-*.log')).read_text().splitlines()) == 3


def test_run_stops_after_the_requested_iterations(tmp_path, monkeypatch):
    monkeypatch.setattr('time.sleep', lambda _s: None)
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': False}))
    assert daemon.run(iterations=3) == 0
    assert daemon.samples == 3
    assert daemon.psu is None  # the device is released on shutdown
    assert stats.MonitorState.load(stats.state_path(tmp_path)).count == 3


def test_state_survives_a_restart(tmp_path):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': False}))
    daemon.tick()
    first = daemon.state.count

    reborn = make_daemon(tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': False}))
    assert reborn.state.count == first
