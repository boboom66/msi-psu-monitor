"""Tests for the resident daemon sample loop (device and clock fully faked)."""

import logging
import os
import time

import pytest

from msi_psu_monitor import monitor
from msi_psu_monitor import state as stats
from msi_psu_monitor.config import DEFAULTS
from msi_psu_monitor.daemon import EXIT_ERROR, RESCAN_AFTER_FAILURES, MonitorDaemon
from msi_psu_monitor.daemon import build_parser
from msi_psu_monitor.daemon import main as daemon_main
from msi_psu_monitor.protocol import ALERT_NAMES, DeviceBusyError


class Clock:
    """Deterministic stand-in for time.monotonic/time.time."""

    def __init__(self, start=None):
        self.now = time.time() if start is None else start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def ocp_config():
    """C0h thresholds as an MPG TS model reports them."""
    return {
        'enabled': True,
        'point_a': 12.0,
        'diff_a': 5.0,
        'trigger_s': 20,
        'diff_trigger_s': 20,
        'warning_s': 180,
    }


def ocp_state():
    """C1h realtime state: both 12V-2x6 connectors, all pins normal."""
    return {
        'status_12v5': 0,
        'run_time': 0,
        'total_time': 446400,
        'pins_1_6': [7.0] * 6,
        'status_12v3': 0,
        'run_time_2': 0,
        'total_time_2': 446400,
        'pins_7_12': [7.0] * 6,
    }


class StubPSU:
    # Default to a MEG model: there 0xC1 is the 26-byte black box, not OCP state.
    supports_ocp_config = False
    supports_multirail_ocp = False

    def __init__(self, sensors=None, alerts=None, fan=None, error=None, ocp=None):
        self._sensors = sensors if sensors is not None else {}
        self._alerts = alerts
        self._fan = fan or {}
        self.error = error
        self.ocp = ocp
        self.multirail = None
        self.ocp_reads = 0
        self.reads = 0
        #: Distinct from ocp_reads: proves whether 0xE1 was polled at all.
        self.alert_reads = 0
        self.closed = False

    def read_ocp_thresholds(self):
        self.ocp_reads += 1
        return self.ocp

    def read_ocp_state(self):
        self.ocp_reads += 1
        return ocp_state()

    def read_multirail_ocp(self):
        self.ocp_reads += 1
        return self.multirail

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
        self.alert_reads += 1
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


def test_a_silent_e1h_read_is_not_reported_as_normal(tmp_path):
    """The pin mirror cannot see the E1h-only bits -- ``fan`` is a critical one.

    ``opp``/``otp``/``fan`` exist only in the E1h bitmap, so when that read is
    NAKed or times out, the mirror's per-pin readings are not enough to declare
    the PSU healthy: the honest answer is Unknown.
    """
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors(), alerts=None))
    assert daemon.sample()['status'] == 'Unknown'


def test_a_silent_e1h_read_still_reports_the_mirror_alerts(tmp_path):
    """Unknown is not "say nothing": a pin the mirror does see over the limit counts."""
    sensors = clean_sensors()
    sensors['iout_pins'] = ([20.0] + [8.0] * 11, 'A')
    daemon = make_daemon(tmp_path, StubPSU(sensors, alerts=None))
    sample = daemon.sample()
    assert sample['status'] == 'ocp_pin1, pin_imbalance'
    assert sample['alerts'] == ['ocp_pin1', 'pin_imbalance']


def test_a_silent_e1h_read_does_not_clear_a_fired_alert(tmp_path):
    """A failed read leaves names out of the poll; the engine keeps its state."""
    sensors = clean_sensors()
    stub = StubPSU(sensors, alerts={'fan': True})
    daemon = make_daemon(tmp_path, stub)
    assert daemon.sample()['status'] == 'fan'
    stub._alerts = None  # the E1h read now fails: it must not look recovered
    sample = daemon.sample()
    assert sample['status'] == 'fan'
    assert sample['alerts'] == ['fan']


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
    assert 'msi_psu_power_total{} 600.0' in prom.read_text()
    assert not prom.with_name('psu.prom.tmp').exists()
    assert len(list(tmp_path.glob('daily-*.log'))) == 1

    clock.advance(1)
    assert daemon.tick()
    assert daemon.samples == 2  # sampled, but below both write intervals

    clock.advance(30)
    assert daemon.tick()
    assert daemon.state.count == 3


def test_the_daemon_exports_the_ocp_block_for_ts_models(tmp_path):
    """The textfile collector carries the C0h thresholds and the C1h state."""
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': False}, ocp=ocp_config())
    psu.supports_ocp_config = True
    # A TS model answers the 8-byte 12V-2x6 read, never the 1-byte multirail one.
    psu.supports_multirail_ocp = True
    psu.multirail = True
    daemon = make_daemon(tmp_path, psu, prom_path=str(tmp_path / 'psu.prom'))
    assert daemon.tick()

    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_up 1' in prom
    assert 'msi_psu_multirail_ocp' not in prom
    assert 'msi_psu_ocp_available 1' in prom
    assert 'msi_psu_ocp_enabled{} 1' in prom
    assert 'msi_psu_ocp_pin_point_a{} 12.0' in prom
    assert 'msi_psu_ocp_pin_diff_a{} 5.0' in prom
    assert 'msi_psu_ocp_status{connector="1"} 0' in prom
    assert 'msi_psu_ocp_status{connector="2"} 0' in prom


def test_the_ocp_state_is_refreshed_on_every_prometheus_write(tmp_path):
    """C1h is a rolling 5 s average, so one read per session would go stale."""
    clock = Clock()
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': False}, ocp=ocp_config())
    psu.supports_ocp_config = True
    daemon = make_daemon(tmp_path, psu, clock=clock, prom_path=str(tmp_path / 'psu.prom'))
    daemon.tick()
    reads = psu.ocp_reads

    clock.advance(30)
    daemon.tick()
    assert psu.ocp_reads > reads


def test_the_daemon_never_reads_ocp_on_a_meg_model(tmp_path):
    """0xC1 on MEG units is the black box; exporting it as OCP state would lie."""
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': False}, ocp=ocp_config())
    daemon = make_daemon(tmp_path, psu, prom_path=str(tmp_path / 'psu.prom'))
    assert daemon.tick()

    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_ocp_available 0' in prom
    assert 'msi_psu_ocp_enabled' not in prom
    assert psu.ocp_reads == 0


def test_a_meg_p_model_exports_the_multirail_flag_instead(tmp_path):
    """0xC0's other meaning: per-rail vs combined protection on the MEG P models."""
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': False})
    psu.supports_multirail_ocp = True
    psu.multirail = True
    daemon = make_daemon(tmp_path, psu, prom_path=str(tmp_path / 'psu.prom'))
    assert daemon.tick()

    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_ocp_available 0' in prom
    assert 'msi_psu_multirail_ocp{} 1' in prom
    assert 'msi_psu_ocp_enabled' not in prom


def test_a_model_with_neither_ocp_view_exports_no_ocp_lines(tmp_path):
    """MEG Ai1600T: 0xC0/0xC1 give no OCP data at all, so claim none."""
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': False})
    daemon = make_daemon(tmp_path, psu, prom_path=str(tmp_path / 'psu.prom'))
    assert daemon.tick()

    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_ocp_available 0' in prom
    assert 'msi_psu_multirail_ocp' not in prom
    assert psu.ocp_reads == 0


def test_a_replacement_psu_does_not_inherit_the_old_ocp_block(tmp_path):
    clock = Clock()
    ts = StubPSU(clean_sensors(), alerts={'ocp_12v': False}, ocp=ocp_config())
    ts.supports_ocp_config = True
    meg = StubPSU(clean_sensors(), alerts={'ocp_12v': False})
    daemon = make_daemon(tmp_path, ts, clock=clock, prom_path=str(tmp_path / 'psu.prom'))
    daemon.tick()
    assert 'msi_psu_ocp_enabled{} 1' in (tmp_path / 'psu.prom').read_text()

    daemon._rediscover()  # the PSU dropped off the bus
    daemon.psu_factory = lambda path: meg
    clock.advance(30)
    daemon.tick()

    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_ocp_available 0' in prom
    assert 'msi_psu_ocp_enabled' not in prom


def test_a_failed_ocp_read_clears_the_exported_block(tmp_path):
    clock = Clock()
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': False}, ocp=ocp_config())
    psu.supports_ocp_config = True
    daemon = make_daemon(tmp_path, psu, clock=clock, prom_path=str(tmp_path / 'psu.prom'))
    daemon.tick()
    assert 'msi_psu_ocp_enabled{} 1' in (tmp_path / 'psu.prom').read_text()

    psu.ocp = None  # the C0h read now NAKs
    clock.advance(30)
    daemon.tick()

    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_ocp_available 1' in prom  # the model still supports it
    assert 'msi_psu_ocp_enabled' not in prom  # but no thresholds may be claimed


def test_prometheus_is_replaced_not_appended(tmp_path):
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
    assert target.read_text().count('msi_psu_power_total{}') == 1


def test_a_failed_prometheus_replace_keeps_the_previous_textfile(tmp_path, monkeypatch):
    """node_exporter reads this file; a torn rewrite would export half a sample.

    The write goes through ``state.atomic_write_text``, so when the final
    os.replace fails the last complete document -- ``msi_psu_up 1`` included --
    must still be what the next scrape sees.
    """
    clock = Clock()
    daemon = make_daemon(
        tmp_path,
        StubPSU(clean_sensors(), alerts={'ocp_12v': False}),
        clock=clock,
        prom_path=str(tmp_path / 'psu.prom'),
    )
    daemon.tick()
    target = tmp_path / 'psu.prom'
    before = target.read_bytes()
    assert b'msi_psu_up' in before

    def no_space(src, dst):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(stats.os, 'replace', no_space)
    clock.advance(30)
    with pytest.raises(OSError):
        daemon.write_prometheus(daemon.sample())

    assert target.read_bytes() == before
    assert target.with_name(target.name + '.tmp').exists()


def test_a_failed_read_stops_the_textfile_from_claiming_health(tmp_path):
    """node_exporter re-exports the last file on every scrape.

    Without this, an unplugged PSU keeps showing ``msi_psu_up 1`` and its last
    wattage for as long as nobody looks -- indistinguishable from a live PSU.
    """
    clock = Clock()
    stub = StubPSU(clean_sensors(), alerts={'ocp_12v': False})
    daemon = make_daemon(tmp_path, stub, clock=clock, prom_path=str(tmp_path / 'psu.prom'))
    target = tmp_path / 'psu.prom'
    daemon.tick()
    assert 'msi_psu_up 1' in target.read_text()

    stub.error = 'ENODEV: the PSU went away'
    clock.advance(1)
    daemon.tick()
    text = target.read_text()
    assert 'msi_psu_up 0' in text
    assert 'msi_psu_error_info{reason="ENODEV: the PSU went away"} 1' in text
    assert 'msi_psu_power_total' not in text  # no stale readings are kept
    assert 'msi_psu_ocp' not in text  # nor a stale OCP block


def test_the_failure_is_written_once_per_reason(tmp_path, monkeypatch):
    """A PSU that stays away must not rewrite the file every second."""
    from msi_psu_monitor import state as stats

    clock = Clock()
    stub = StubPSU(clean_sensors(), alerts={'ocp_12v': False})
    daemon = make_daemon(tmp_path, stub, clock=clock, prom_path=str(tmp_path / 'psu.prom'))
    daemon.tick()
    stub.error = 'ENODEV'
    writes = []
    real = stats.atomic_write_text
    monkeypatch.setattr(
        stats, 'atomic_write_text', lambda path, text: (writes.append(path), real(path, text))[1]
    )
    clock.advance(1)
    daemon.tick()
    clock.advance(1)
    daemon.tick()
    assert len(writes) == 1

    # ... and a recovery puts the readings back.
    stub.error = None
    clock.advance(31)
    daemon.tick()
    assert 'msi_psu_up 1' in (tmp_path / 'psu.prom').read_text()


def test_a_failed_read_without_prometheus_configured_writes_nothing(tmp_path):
    stub = StubPSU(clean_sensors(), alerts=None)
    daemon = make_daemon(tmp_path, stub)
    stub.error = 'ENODEV'
    daemon.tick()  # must not raise: there is no textfile to keep honest
    assert list(tmp_path.glob('*.prom')) == []


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
    assert RESCAN_AFTER_FAILURES == 5
    for _ in range(4):
        assert daemon.sample() is None
    assert daemon.psu is not None
    # The fifth consecutive failure, not the configured loop bound, triggers it.
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
        self.zero_fan = True
        self.zero_writes = []
        self.buzzer_requests = 0

    def set_fan_mode(self, mode, duty=0):
        self.writes.append((mode, duty))
        if not self.accept:
            return False
        self.mode, self.duty = mode, duty
        self.saved += 1
        return True

    def read_fan_setting(self):
        return (self.mode, self.duty)

    def set_zero_fan(self, enabled):
        self.zero_writes.append(enabled)
        if not self.accept:
            return False
        self.zero_fan = enabled
        self.saved += 1
        return True

    def read_zero_fan(self):
        return self.zero_fan

    def silence_buzzer(self):
        self.buzzer_requests += 1
        return self.accept


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


def test_a_swapped_model_does_not_inherit_the_old_latched_alert(tmp_path, caplog):
    """A TS alert is not in the MEG's index array, so nothing would ever clear it.

    Only a poll reporting the name ``False`` clears the latch, so after a model
    swap ``ocp_pin1`` stayed fired forever: the daemon exported
    ``msi_psu_alert{alert="ocp_pin1"} 1`` and a status line naming it on a PSU that
    has no per-pin sensing, while its own E1h register said Normal.
    """
    clock = Clock()
    # A TS model reports ocp_pin1 (and the software mirror adds pin_imbalance);
    # the MEG index array has neither, but both report otp.
    ts_pins = [8.0] * 12
    ts = StubPSU(
        {**clean_sensors(), 'iout_pins': (ts_pins, 'A')},
        alerts={'ocp_pin1': True, 'pin_imbalance': True, 'otp': True, 'fan': False},
    )
    meg = StubPSU(
        {'product': 'MEG Ai1300P', 'vout_12v': (12.0, 'V'), 'power_total': (500.0, 'W')},
        alerts={'otp': True, 'fan': False},
    )
    daemon = make_daemon(tmp_path, ts, clock=clock, prom_path=str(tmp_path / 'psu.prom'))
    assert daemon.sample()['status'] == 'ocp_pin1, otp, pin_imbalance'
    daemon.tick()

    daemon._rediscover()  # the PSU dropped off the bus
    daemon.psu_factory = lambda path: meg

    # otp is reported active by both models and stays; the TS-only names are gone.
    assert daemon.sample()['status'] == 'otp'
    clock.advance(30)  # the textfile is rewritten on the 30 s cadence
    daemon.tick()
    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_alert{alert="otp"} 1' in prom
    assert 'msi_psu_alert{alert="ocp_pin1"}' not in prom
    # pin_imbalance also names a configured threshold limit, so match the alert
    # metric exactly instead of the bare substring.
    assert 'msi_psu_alert{alert="pin_imbalance"}' not in prom


def test_an_unanswered_e1h_read_never_prunes_the_latch(tmp_path):
    """retain() must only run on a real E1h answer.

    Otherwise a single failed poll would drop the fan bit -- the one critical
    alert -- and the next successful poll would re-announce it as a new edge.
    """
    sensors = clean_sensors()
    stub = StubPSU(sensors, alerts={'fan': True, 'otp': False})
    daemon = make_daemon(tmp_path, stub)
    assert daemon.sample()['status'] == 'fan'

    stub._alerts = None  # E1h now fails: the mirror-only poll must not prune
    assert daemon.sample()['status'] == 'fan'
    stub._alerts = {'fan': False, 'otp': False}  # and a real answer still clears it
    assert daemon.sample()['status'] == 'Normal'


def test_a_failed_payload_read_does_not_clear_a_mirror_alert(tmp_path):
    """A missing 0xE0 frame is not a recovery the per-pin mirror measured.

    The E1h bitmap still answers, but its False bits only say that the PSU's own
    protection did not trip -- not that the software mirror's earlier per-pin
    threshold recovered. Treating them as a recovery logged a RECOVERED line and
    dropped a live alert for a condition nothing had re-measured.
    """
    sensors = clean_sensors()
    sensors['iout_pins'] = ([20.0] + [8.0] * 11, 'A')
    stub = StubPSU(sensors, alerts={name: False for name in ALERT_NAMES['mpg_ai1600ts']})
    daemon = make_daemon(tmp_path, stub)
    assert daemon.sample()['status'] == 'ocp_pin1, pin_imbalance'

    del stub._sensors['iout_pins']  # the 0xE0 payload read now fails
    sample = daemon.sample()
    assert sample['status'] == 'ocp_pin1, pin_imbalance'
    assert daemon.engine.take_cleared() == [], 'a failed payload read logged a recovery'


def test_a_bad_config_is_one_line_not_a_traceback(tmp_path, capsys):
    """`--config` pointing at nothing used to escape as an interpreter dump.

    That is what the shipped unit did on every start (ExecStart named a file no
    installer created): systemd logged a traceback per RestartSec forever while
    apt had reported success.
    """
    missing = tmp_path / 'nope.conf'
    assert daemon_main(['--config', str(missing)]) == EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.err.count('\n') == 1
    assert captured.err.startswith('Error: ')
    assert 'Traceback' not in captured.err
    assert str(missing) in captured.err


def test_a_failing_prune_does_not_kill_the_daemon(tmp_path, monkeypatch, caplog):
    """Hourly housekeeping ran unguarded inside tick(); an OSError crashed it.

    A state directory whose permissions changed under the daemon (or a filesystem
    that refuses readdir) raised straight out of tick() into systemd, which
    restarted the unit into the same wall every hour.
    """
    clock = Clock()
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()), clock=clock)
    assert daemon.tick() is True
    clock.advance(3601)

    def broken(*_args, **_kwargs):
        raise PermissionError(13, 'Permission denied', str(tmp_path))

    monkeypatch.setattr(stats, 'prune_history', broken)
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        assert daemon.tick() is True
    assert 'Cannot prune old files' in caplog.text


@pytest.mark.parametrize('argv', [['--state-dir', ''], ['--prom-path', ''], ['--config', '']])
def test_empty_path_arguments_are_usage_errors(argv):
    """An unset $DIR must not silently fall back to the packaged default."""
    with pytest.raises(SystemExit) as excinfo:
        daemon_main(argv)
    assert excinfo.value.code == 2


def test_no_alerts_from_the_config_switches_the_poll_off(tmp_path):
    """`[monitor] no_alerts` is documented as "skip the E1h poll entirely".

    The daemon never read the key, so the switch a user set in
    /etc/msi-psu-monitor.conf -- the file the packaged unit loads -- did nothing
    in the tool's normal mode: the E1h register was still polled and the alert
    metrics were still exported.
    """
    stub = StubPSU(clean_sensors(), alerts={'fan': True})
    daemon = make_daemon(tmp_path, stub, no_alerts=True)
    sample = daemon.sample()
    assert 'status' not in sample
    assert 'alerts' not in sample
    assert stub.alert_reads == 0


def test_alerts_are_still_polled_when_the_config_does_not_disable_them(tmp_path):
    """The guard above must not disable the poll for everyone."""
    stub = StubPSU(clean_sensors(), alerts={'fan': True})
    daemon = make_daemon(tmp_path, stub, no_alerts=False)
    assert daemon.sample()['status'] == 'fan'
    assert stub.alert_reads == 1


def test_zero_fan_only_profile_is_restored(tmp_path):
    psu = FanPSU(sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu, fan_zero_fan=True)
    daemon.sample()
    assert psu.zero_writes == [True]
    assert psu.writes == []


def test_zero_fan_is_restored_with_the_fan_profile(tmp_path):
    psu = FanPSU(sensors=clean_sensors())
    daemon = make_daemon(tmp_path, psu, fan_zero_fan=False, fan_mode='customized', fan_duty=60)
    daemon.sample()
    assert psu.zero_writes == [False]
    assert psu.writes == [(3, 60)]
    assert psu.saved == 2  # one F1h for Zero Fan, one for the fan setting


def test_alert_edges_and_recoveries_are_written_to_the_alert_log(tmp_path):
    psu = StubPSU(clean_sensors(), alerts={'ocp_12v': True})
    daemon = make_daemon(tmp_path, psu)
    daemon.sample()
    lines = stats.iter_alert_log(tmp_path)
    assert len(lines) == 1
    assert '| ALERT [warning] ocp_12v:' in lines[0]
    daemon.sample()
    assert len(stats.iter_alert_log(tmp_path)) == 1  # sustained alert is not re-logged
    psu._alerts = {'ocp_12v': False}
    daemon.sample()
    lines = stats.iter_alert_log(tmp_path)
    assert len(lines) == 2
    assert lines[1].endswith(
        '| RECOVERED ALERT [warning] ocp_12v: 12V rail over-current (≥105% rated)'
    )


def test_the_alert_log_can_be_disabled(tmp_path):
    daemon = make_daemon(
        tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': True}), alert_log=False
    )
    daemon.sample()
    assert stats.iter_alert_log(tmp_path) == []


def test_no_alerts_never_writes_the_alert_log(tmp_path):
    daemon = make_daemon(
        tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': True}), no_alerts=True
    )
    daemon.sample()
    assert stats.iter_alert_log(tmp_path) == []


def test_a_broken_alert_log_cannot_break_sampling(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(stats, 'append_alert_log', broken)
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors(), alerts={'ocp_12v': True}))
    assert daemon.sample() is not None


def test_sample_writes_the_live_snapshot(tmp_path):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()))
    daemon.sample()
    live = stats.read_live_snapshot(tmp_path, now=daemon.wall_clock())
    assert live['ts'] == daemon.wall_clock()
    assert live['vout_12v'] == clean_sensors()['vout_12v'][0]


def test_the_live_snapshot_can_be_disabled(tmp_path):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()), live_snapshot=False)
    daemon.sample()
    assert stats.read_live_snapshot(tmp_path, now=daemon.wall_clock()) is None


def test_many_iterations_do_not_leak_file_descriptors(tmp_path, monkeypatch):
    clock = Clock()
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()), clock=clock)
    monkeypatch.setattr('time.sleep', lambda _s: clock.advance(1))
    before = len(os.listdir('/proc/self/fd'))
    daemon.run(iterations=300)
    after = len(os.listdir('/proc/self/fd'))
    assert after <= before + 3, f'fd count grew from {before} to {after}'


def test_daemon_rejects_zero_or_negative_iterations():
    parser = build_parser()
    for value in ('0', '-1'):
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(['--iterations', value])
        assert excinfo.value.code == 2


def test_a_failed_init_closes_the_already_open_device(tmp_path):
    """open() then init() failing must not leak the hidraw descriptor."""

    class FailingInit(StubPSU):
        def init(self):
            raise OSError('init handshake failed')

    psu = FailingInit(clean_sensors())
    daemon = make_daemon(tmp_path, psu)
    assert daemon._ensure_psu() is None
    assert psu.closed is True
    assert daemon.device_path is None


def test_an_unexpected_parser_exception_is_a_counted_read_failure(tmp_path, caplog):
    """A malformed payload bug must not kill the resident daemon."""

    class BrokenPSU(StubPSU):
        def get_sensors(self):
            raise ValueError('malformed bulk payload')

    daemon = make_daemon(tmp_path, BrokenPSU(clean_sensors()))
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        assert daemon.tick() is True
    assert daemon.failures == 1
    assert daemon.samples == 0
    assert any('Unexpected error while reading' in record.message for record in caplog.records)


def test_an_unexpected_enrichment_error_is_a_counted_failure(tmp_path, monkeypatch, caplog):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()))

    def explode(_sensors, _state):
        raise ValueError('enrichment bug')

    monkeypatch.setattr(monitor, 'apply_stats', explode)
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        assert daemon.tick() is True
    assert daemon.failures == 1
    assert daemon.samples == 0
    assert any('Unexpected error while enriching' in record.message for record in caplog.records)


def test_an_unexpected_history_error_does_not_stop_the_daemon(tmp_path, caplog):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()))

    def explode(_sensors):
        raise ValueError('history bug')

    daemon.record_history = explode
    with caplog.at_level(logging.ERROR, logger='msi_psu.daemon'):
        assert daemon.tick() is True
    assert 'Unexpected error while writing history' in caplog.text


def test_an_unexpected_prometheus_error_does_not_stop_the_daemon(tmp_path, caplog):
    daemon = make_daemon(tmp_path, StubPSU(clean_sensors()))

    def explode(_sensors):
        raise ValueError('prom bug')

    daemon.write_prometheus = explode
    with caplog.at_level(logging.ERROR, logger='msi_psu.daemon'):
        assert daemon.tick() is True
    assert 'Unexpected error while writing' in caplog.text


def test_an_unexpected_open_error_is_retried_not_fatal(tmp_path, caplog):
    class BrokenOpen(StubPSU):
        def open(self):
            raise ValueError('broken device object')

    psu = BrokenOpen(clean_sensors())
    daemon = make_daemon(tmp_path, psu)
    with caplog.at_level(logging.WARNING, logger='msi_psu.daemon'):
        assert daemon.tick() is True
    assert daemon.psu is None
    assert any('Unexpected error while opening' in record.message for record in caplog.records)


def test_a_zero_watt_sample_still_counts_in_the_average(tmp_path):
    """0 W idle is a real sample; skipping it biased count/average."""
    sensors = clean_sensors()
    sensors['power_total'] = (0.0, 'W')
    sensors['efficiency'] = (0.0, '%')
    daemon = make_daemon(tmp_path, StubPSU(sensors))
    sample = daemon.sample()
    assert sample is not None
    assert daemon.state.count == 1
    assert sample['power_avg'] == (0.0, 'W')
    assert sample['efficiency_avg'] == (0.0, '%')


# ---- local early-warning thresholds -------------------------------------


def test_a_threshold_alert_is_logged_exported_and_file_logged(tmp_path, caplog):
    sensors = clean_sensors()
    sensors['power_total'] = (1500.0, 'W')
    stub = StubPSU(sensors, alerts={'ocp_12v': False})
    daemon = make_daemon(tmp_path, stub, prom_path=str(tmp_path / 'psu.prom'))
    with caplog.at_level(logging.WARNING, logger='msi_psu'):
        sample = daemon.sample()
    assert sample['threshold_alerts'] == ['power_high']
    assert sample['threshold_limits']['power_w'] == 1200.0
    assert any('ALERT [warning] power_high' in record.message for record in caplog.records)

    assert daemon.tick() is True
    prom = (tmp_path / 'psu.prom').read_text(encoding='utf-8')
    assert 'msi_psu_threshold_alert{alert="power_high"} 1' in prom
    assert 'msi_psu_threshold_limit{name="power_w"} 1200.0' in prom

    alert_files = list(tmp_path.glob('alerts-*.log'))
    assert len(alert_files) == 1
    assert 'power_high' in alert_files[0].read_text(encoding='utf-8')


def test_a_failed_payload_read_does_not_clear_a_threshold_alert(tmp_path):
    sensors = clean_sensors()
    sensors['power_total'] = (1500.0, 'W')
    stub = StubPSU(sensors, alerts={'ocp_12v': False})
    daemon = make_daemon(tmp_path, stub)
    assert 'power_high' in daemon.sample()['threshold_alerts']

    # 0xE0 unreadable but E1h still answers: no measurement, no recovery.
    monitor.attach_alerts(stub, daemon.engine, {'product': 'MPG Ai1600TS'}, daemon.cfg)
    assert 'power_high' in daemon.engine.active_alerts
    assert daemon.engine.take_cleared() == []

    # A healthy sample below the limit is a real recovery.
    monitor.attach_alerts(stub, daemon.engine, clean_sensors(), daemon.cfg)
    assert 'power_high' in [alert.name for alert in daemon.engine.take_cleared()]


def test_no_alerts_also_skips_the_local_thresholds(tmp_path):
    sensors = clean_sensors()
    sensors['power_total'] = (1500.0, 'W')
    daemon = make_daemon(tmp_path, StubPSU(sensors), no_alerts=True)
    sample = daemon.sample()
    assert 'threshold_alerts' not in sample
    assert 'threshold_limits' not in sample
