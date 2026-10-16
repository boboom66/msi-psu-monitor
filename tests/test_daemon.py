"""Tests for the resident daemon sample loop (device and clock fully faked)."""

import logging
import time

from msi_psu_monitor import state as stats
from msi_psu_monitor.config import DEFAULTS
from msi_psu_monitor.daemon import RESCAN_AFTER_FAILURES, MonitorDaemon
from msi_psu_monitor.protocol import DeviceBusyError


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


# ---- fan profile restore ([fan] mode) -----------------------------------


class FanPSU(StubPSU):
    """StubPSU that records fan writes and can refuse them."""

    MODE_BYTES = {1: 3, 3: 3}  # auto=1, customized=3; matches protocol.py

    def __init__(self, accept=True, **kwargs):
        super().__init__(**kwargs)
        self.accept = accept
        self.writes = []
        self.saved = 0
        self.mode = 1
        self.duty = 0

    def set_fan_mode(self, mode, duty=0):
        self.writes.append((mode, duty))
        if not self.accept:
            return False
        self.mode, self.duty = mode, duty
        self.saved += 1
        return True

    def read_fan_setting(self):
        return (self.mode, self.duty)


def test_no_fan_section_means_the_daemon_never_writes(tmp_path):
    """Opt-in only: a stock install must not touch the PSU's own curve."""
    psu = FanPSU(sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu)
    daemon.sample()
    assert psu.writes == []
    assert psu.saved == 0


def test_fan_profile_is_restored_when_the_psu_is_opened(tmp_path):
    psu = FanPSU(sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu, fan_mode='customized', fan_duty=60)
    daemon.sample()
    assert psu.writes == [(3, 60)]
    assert psu.saved == 1  # F1h rode along with the 41h write


def test_fan_auto_profile_is_restored_without_a_duty(tmp_path):
    psu = FanPSU(sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu, fan_mode='auto')
    daemon.sample()
    assert psu.writes == [(1, 0)]


def test_fan_profile_is_restored_again_after_a_rescan(tmp_path, caplog):
    """Reconnect is the case that matters: AC loss drops the saved setting."""
    psu = FanPSU(sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu, fan_mode='customized', fan_duty=30)
    daemon.sample()
    daemon._rediscover()
    daemon.sample()
    assert psu.writes == [(3, 30), (3, 30)]


def test_a_refused_fan_profile_is_logged_but_not_fatal(tmp_path, caplog):
    psu = FanPSU(accept=False, sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu, fan_mode='customized', fan_duty=60)
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        sample = daemon.sample()
    assert sample is not None  # monitoring keeps running
    assert len(psu.writes) == 3  # three attempts, like MSI Center
    assert psu.saved == 0
    assert 'refused the configured fan profile' in caplog.text


def test_a_failing_fan_write_does_not_break_the_open(tmp_path):
    class Exploding(FanPSU):
        def set_fan_mode(self, mode, duty=0):
            raise OSError('device vanished')

    daemon = make_daemon(
        tmp_path, Exploding(sensors=clean_sensors()), fan_mode='customized', fan_duty=60
    )
    assert daemon.sample() is not None
    assert daemon.psu is not None


def test_restore_fan_profile_is_a_noop_before_the_psu_is_open(tmp_path):
    daemon = make_daemon(tmp_path, FanPSU(sensors=clean_sensors()), fan_mode='customized')
    assert daemon.restore_fan_profile() is False


class UnpluggedPSU:
    """A PSU whose cable was pulled: every read raises ENODEV."""

    def __init__(self, sensors=None):
        self.opened = []
        self.closed = False

    def open(self):
        self.opened.append(True)
        return self

    def close(self):
        self.closed = True

    def init(self):
        return 'MPG Ai1600TS'

    def get_sensors(self):
        raise OSError(19, 'No such device')

    def read_alert_status(self):
        return None

    def read_fan_state(self):
        return {'mode': None, 'duty': None, 'zero_fan': None}


def test_an_unplugged_psu_counts_towards_the_rescan(tmp_path, caplog):
    """ENODEV must be a counted failure; a crash loop never reaches the rescan."""
    daemon = make_daemon(tmp_path, UnpluggedPSU())
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        for expected in range(1, RESCAN_AFTER_FAILURES + 1):
            assert daemon.tick() is True
            assert daemon.failures == expected % RESCAN_AFTER_FAILURES
    assert any('No such device' in record.message for record in caplog.records)
    assert any('rescanning' in record.message for record in caplog.records)


def test_a_psu_that_answers_its_ident_only_is_a_read_failure(tmp_path, caplog):
    """No payload at all is not a healthy sample with an empty chart."""
    daemon = make_daemon(tmp_path, StubPSU({'product': 'MPG Ai1600TS'}))
    with caplog.at_level(logging.ERROR, logger='msi_psu.daemon'):
        assert daemon.sample() is None
    assert daemon.failures == 1
    assert any('0xE0 read failed' in record.message for record in caplog.records)
    assert daemon.samples == 0


def test_an_unopenable_device_is_retried_on_the_discovery_throttle(tmp_path, caplog):
    """Keeping device_path made every tick reopen (and re-warn) once a second."""

    class Locked:
        def open(self):
            raise DeviceBusyError('PSU is already in use by another process')

    daemon = make_daemon(tmp_path, Locked())
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        for _ in range(6):
            assert daemon.tick() is True
    assert len(daemon.created) == 1  # the other ticks waited for the throttle
    warnings = [r.message for r in caplog.records if 'Cannot open' in r.message]
    assert len(warnings) == 1
