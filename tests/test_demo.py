"""Tests for the MSI_PSU_DEMO synthetic device (no hardware, fully deterministic)."""

import logging
import time

import pytest

from msi_psu_monitor import demo
from msi_psu_monitor import monitor
from msi_psu_monitor import state as stats
from msi_psu_monitor.daemon import MonitorDaemon
from msi_psu_monitor.config import DEFAULTS
from msi_psu_monitor.protocol import MSIPSU


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


def test_demo_reports_the_emulated_models_alert_order(monkeypatch):
    """A MEG demo must not answer with the TS bitmap (different meaning)."""
    monkeypatch.setenv('MSI_PSU_DEMO_MODEL', 'ai1300p')
    alerts = demo.DemoPSU(clock=Clock()).read_alert_status()
    assert list(alerts)[:3] == ['ovp_12v', 'ovp_5v', 'ovp_3v3']
    assert 'ocp_pin1' not in alerts

    monkeypatch.setenv('MSI_PSU_DEMO_MODEL', 'meg_ai1600')
    monkeypatch.setenv('MSI_PSU_DEMO_ALERT', 'ac')
    alerts = demo.DemoPSU(clock=Clock()).read_alert_status()
    assert len(alerts) == 13
    assert alerts['ac'] is True


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


def test_blackbox_demo_records_are_in_the_documented_slot_order():
    """Slot 1 is the newest trip, and the counters on the record have to say so.

    They did not: slot 2 held the larger lifetime uptime and trip count, so the
    demo printed (and the smoke test accepted) an order the real path would never
    produce. ``format_blackbox`` now sorts on those counters, so the demo's data
    and the display agree as well.
    """
    from msi_psu_monitor.monitor import format_blackbox

    records = demo.DemoPSU(clock=Clock()).read_blackbox()
    assert [rec['info_id'] for rec in records] == [1, 2]
    assert records[0]['total_time'] > records[1]['total_time']
    assert records[0]['total_count'] > records[1]['total_count']
    shown = format_blackbox(records)
    assert shown.index('#1') < shown.index('#2')


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
    path, available, blocked = monitor.resolve_device(None)
    assert path == demo.DEVICE_PATH
    assert available == [demo.DEMO_SERIAL]
    assert blocked == []

    path, _, _ = monitor.resolve_device(demo.DEMO_SERIAL)
    assert path == demo.DEVICE_PATH

    path, available, _ = monitor.resolve_device('SOMETHING-ELSE')
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


# ---- multi-model demo (MSI_PSU_DEMO_MODEL) ------------------------------


def test_model_defaults_to_the_ts_1600(monkeypatch):
    monkeypatch.delenv(demo.MODEL_ENV, raising=False)
    assert demo.model() == 'mpg_ai1600ts'
    assert demo.DemoPSU(clock=Clock()).product == demo.PRODUCT


@pytest.mark.parametrize('variant', sorted(demo.MODEL_WATTS))
def test_every_supported_variant_can_be_emulated(monkeypatch, variant):
    monkeypatch.setenv(demo.MODEL_ENV, variant)
    psu = demo.DemoPSU(clock=Clock())
    assert psu.variant == variant
    assert psu.product == f'{MSIPSU.VARIANTS[variant]["name"]} (demo)'


def test_unknown_model_falls_back_instead_of_failing(monkeypatch, caplog):
    """Falling back silently meant a typo could pass for the model under test."""
    monkeypatch.setenv(demo.MODEL_ENV, 'Ai9999X')
    with caplog.at_level(logging.WARNING, logger='msi_psu.demo'):
        assert demo.model() == demo.DEFAULT_MODEL
    assert any('Ignoring unknown' in record.message for record in caplog.records)


def test_the_demo_knows_every_protocol_variant():
    """A variant with no wattage would silently fall back to the TS default."""
    assert set(demo.MODEL_WATTS) == set(MSIPSU.VARIANTS)


def test_model_env_is_case_insensitive(monkeypatch):
    monkeypatch.setenv(demo.MODEL_ENV, ' AI1300P ')
    assert demo.model() == 'ai1300p'


def test_per_pin_payload_only_on_the_12v_2x6_models():
    ts = demo.DemoPSU(clock=Clock(), variant='mpg_ai1600ts').get_sensors()
    assert len(ts['iout_pins'][0]) == 12
    assert 'iout_12v_rails' not in ts

    p_model = demo.DemoPSU(clock=Clock(), variant='ai1300p').get_sensors()
    assert 'iout_pins' not in p_model
    assert len(p_model['iout_12v_rails'][0]) == 5

    t_model = demo.DemoPSU(clock=Clock(), variant='meg_ai1600').get_sensors()
    assert 'iout_pins' not in t_model
    assert 'iout_12v_rails' not in t_model


def test_rails_sum_to_the_reported_12v_total():
    sensors = demo.DemoPSU(clock=Clock(), variant='ai1000p').get_sensors()
    rails = sensors['iout_12v_rails'][0]
    assert sum(rails) == pytest.approx(sensors['iout_12v_total'][0], rel=0.12)


def test_rail_watts_are_derived_from_the_demo_rails():
    sensors = demo.DemoPSU(clock=Clock(), variant='ai1300p').get_sensors()
    watts = stats.rail_watts(sensors)
    assert watts is not None
    cpu, gpu = watts
    # 12V2 is the CPU rail, 12V3-5 feed the GPU, so the GPU always draws more.
    assert 0 < cpu < gpu


def test_wattage_ramp_follows_the_model_rating():
    clock = Clock()
    clock.now += demo.CYCLE_S / 4  # peak of the sine
    big = demo.DemoPSU(clock=clock, variant='mpg_ai1600ts').get_sensors()
    small = demo.DemoPSU(clock=clock, variant='ai1000p').get_sensors()
    assert big['power_total'][0] > small['power_total'][0]


@pytest.mark.parametrize(
    'variant,ocp,multirail',
    [
        ('mpg_ai1600ts', True, False),
        ('mpg_ai1300ts', True, False),
        ('ai1300p', False, True),
        ('ai1000p', False, True),
        ('meg_ai1600', False, False),
    ],
)
def test_demo_variant_gates_match_the_protocol(variant, ocp, multirail):
    psu = demo.DemoPSU(clock=Clock(), variant=variant)
    assert psu.supports_ocp_config is ocp
    assert psu.supports_multirail_ocp is multirail
    assert psu.read_multirail_ocp() is (True if multirail else None)


def test_demo_export_records_cpu_gpu_for_a_multi_rail_model(tmp_path, monkeypatch):
    """The no-hardware path that was previously unreachable: rails -> cpu/gpu CSV."""
    monkeypatch.setenv('MSI_PSU_DEMO', '1')
    monkeypatch.setenv(demo.MODEL_ENV, 'ai1300p')
    stats.append_history(tmp_path, demo.DemoPSU(clock=Clock()).get_sensors(), ts=1700000000.0)
    header, rows = stats.build_export(tmp_path, since_ts=None, columns=['cpu', 'gpu'])
    assert header == ['time', 'cpu', 'gpu']
    cpu, gpu = (float(value) for value in rows[0][1:3])
    assert 0 < cpu < gpu


def test_an_alert_the_model_cannot_report_is_not_silently_dropped(monkeypatch, caplog):
    """`MSI_PSU_DEMO_ALERT=pin_imbalance` used to be accepted and then never set.

    ALERT_DESCRIPTIONS is model-independent, so a name no model can report (the
    software mirror's ``pin_imbalance``) or one this model has no bit for
    (``ocp_pin1`` on a MEG) produced an all-clear run that looked like a pass.
    """
    import logging

    from msi_psu_monitor import demo

    monkeypatch.setenv('MSI_PSU_DEMO_ALERT', 'pin_imbalance')
    psu = demo.DemoPSU()
    with caplog.at_level(logging.WARNING):
        status = psu.read_alert_status()
        psu.read_alert_status()  # warned once, not per poll
    assert not any(status.values())
    assert caplog.text.count('pin_imbalance') == 1
    assert 'is not an alert the mpg_ai1600ts model reports' in caplog.text


def test_an_alert_the_model_does_report_is_still_forced(monkeypatch):
    from msi_psu_monitor import demo

    monkeypatch.setenv('MSI_PSU_DEMO_ALERT', 'fan')
    status = demo.DemoPSU().read_alert_status()
    assert status['fan'] is True
    assert sum(status.values()) == 1
