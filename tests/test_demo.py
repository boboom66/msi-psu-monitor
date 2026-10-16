"""Tests for the MSI_PSU_DEMO synthetic device (no hardware, fully deterministic)."""

import time

import pytest

from msi_psu_monitor import demo
from msi_psu_monitor import monitor
from msi_psu_monitor import state as stats
from msi_psu_monitor.daemon import MonitorDaemon
from msi_psu_monitor.config import DEFAULTS


class Clock:
    def __init__(self, now=None):
        self.now = time.time() if now is None else now

    def __call__(self):
        return self.now


@pytest.mark.parametrize('value', ['1', 'true', 'YES', 'on', ' On '])
def test_enabled_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv('MSI_PSU_DEMO', value)
    assert demo.enabled()


@pytest.mark.parametrize('value', ['', '0', 'false', 'no', 'off'])
def test_enabled_rejects_everything_else(monkeypatch, value):
    monkeypatch.setenv('MSI_PSU_DEMO', value)
    assert not demo.enabled()


def test_enabled_defaults_to_off(monkeypatch):
    monkeypatch.delenv('MSI_PSU_DEMO', raising=False)
    assert not demo.enabled()


def test_sensors_are_plausible_and_complete():
    psu = demo.DemoPSU(clock=Clock())
    sensors = psu.get_sensors()
    for key in (
        'vendor',
        'product',
        'fw_revision',
        'serial',
        'vout_12v',
        'vout_5v',
        'vout_3v3',
        'iout_12v_total',
        'iout_pins',
        'power_total',
        'efficiency',
        'temp',
        'fan_rpm',
        'uptime',
    ):
        assert key in sensors, key

    assert sensors['serial'] == demo.DEMO_SERIAL
    assert 11.9 <= sensors['vout_12v'][0] <= 12.15
    assert 4.9 <= sensors['vout_5v'][0] <= 5.15
    assert 3.2 <= sensors['vout_3v3'][0] <= 3.4
    assert 50.0 <= sensors['power_total'][0] <= 740.0
    assert 87.0 <= sensors['efficiency'][0] <= 95.0
    assert len(sensors['iout_pins'][0]) == 12


def test_pin_currents_track_the_12v_total():
    psu = demo.DemoPSU(clock=Clock())
    sensors = psu.get_sensors()
    pins = sensors['iout_pins'][0]
    total = sensors['iout_12v_total'][0]
    assert sum(pins) == pytest.approx(total, rel=0.15)


def test_zero_fan_follows_the_load_cycle():
    clock = Clock()
    psu = demo.DemoPSU(clock=clock)
    idle = psu.get_sensors()
    assert idle['zero_fan'] is True
    assert idle['fan_rpm'][0] == 0

    clock.now += demo.CYCLE_S / 4  # peak of the sine
    loaded = psu.get_sensors()
    assert loaded['zero_fan'] is False
    assert loaded['fan_rpm'][0] > 700


def test_two_instances_with_the_same_clock_agree():
    left = demo.DemoPSU(clock=Clock())
    right = demo.DemoPSU(clock=Clock())
    assert left.get_sensors() == right.get_sensors()


def test_fan_write_round_trips(monkeypatch):
    monkeypatch.delenv('MSI_PSU_DEMO_ALERT', raising=False)
    psu = demo.DemoPSU(clock=Clock())
    assert psu.read_fan_setting() == (1, 30)
    assert psu.set_fan_mode(3, 80) is True
    assert psu.read_fan_setting() == (3, 80)
    assert psu.read_fan_state()['duty'] == 80


def test_alerts_are_all_clear_by_default(monkeypatch):
    monkeypatch.delenv('MSI_PSU_DEMO_ALERT', raising=False)
    alerts = demo.DemoPSU(clock=Clock()).read_alert_status()
    assert alerts
    assert not any(alerts.values())


def test_demo_alert_env_sticks_exactly_one_bit(monkeypatch):
    monkeypatch.setenv('MSI_PSU_DEMO_ALERT', 'fan')
    alerts = demo.DemoPSU(clock=Clock()).read_alert_status()
    assert alerts['fan'] is True
    assert sum(alerts.values()) == 1

    monkeypatch.setenv('MSI_PSU_DEMO_ALERT', 'not_an_alert')
    assert not any(demo.DemoPSU(clock=Clock()).read_alert_status().values())


def test_blackbox_demo_records_are_limited():
    psu = demo.DemoPSU(clock=Clock())
    assert len(psu.read_blackbox()) == 2
    assert len(psu.read_blackbox(max_records=1)) == 1


# ---- wiring -------------------------------------------------------------


def test_open_psu_uses_the_demo_device_only_when_enabled(monkeypatch):
    monkeypatch.delenv('MSI_PSU_DEMO', raising=False)
    monkeypatch.setattr(monitor, 'MSIPSU', lambda hid: 'real')
    monkeypatch.setattr(monitor, 'HIDDevice', lambda path: ('hid', path))
    assert monitor.open_psu('/dev/hidraw9') == 'real'

    monkeypatch.setenv('MSI_PSU_DEMO', '1')
    assert isinstance(monitor.open_psu('/dev/hidraw9'), demo.DemoPSU)


def test_resolve_device_honours_the_demo_serial(monkeypatch):
    monkeypatch.setenv('MSI_PSU_DEMO', '1')
    path, available = monitor.resolve_device(None)
    assert path == demo.DEVICE_PATH
    assert available == [demo.DEMO_SERIAL]

    path, available = monitor.resolve_device(demo.DEMO_SERIAL)
    assert path == demo.DEVICE_PATH

    path, available = monitor.resolve_device('SOMETHING-ELSE')
    assert path is None
    assert available == [demo.DEMO_SERIAL]


def test_daemon_history_and_prometheus_work_in_demo_mode(tmp_path, monkeypatch):
    """End-to-end daemon pass over the synthetic device: history + textfile."""
    monkeypatch.setenv('MSI_PSU_DEMO', '1')
    clock = Clock()
    cfg = dict(DEFAULTS)
    cfg.update(
        {
            'state_dir': str(tmp_path),
            'prom_path': str(tmp_path / 'psu.prom'),
            'consecutive_required': 1,
        }
    )

    daemon = MonitorDaemon(cfg, clock=clock, wall_clock=clock)
    assert daemon.tick()
    clock.now += 60
    assert daemon.tick()

    history = next(tmp_path.glob('daily-*.log')).read_text().splitlines()
    assert len(history) == 3
    assert history[0] == ','.join(stats.HISTORY_COLUMNS)
    assert history[1].split(',')[0] != history[2].split(',')[0]
    prom = (tmp_path / 'psu.prom').read_text()
    assert 'msi_psu_info{product="MPG Ai1600TS (demo)"' in prom
    assert 'msi_psu_status_12v_2x6{status="Normal"} 1' in prom
    assert stats.MonitorState.load(stats.state_path(tmp_path)).serial == demo.DEMO_SERIAL
