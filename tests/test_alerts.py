"""Unit tests for the edge-triggered alert engine (alerts.AlertEngine)."""

import pytest

from msi_psu_monitor.alerts import (
    AlertEngine,
    describe,
    evaluate_pin_alerts,
    format_alert_line,
    severity_of,
)


def _all_ok():
    return {'ocp_12v': False, 'opp': False, 'otp': False, 'fan': False}


def test_severity_levels():
    assert severity_of('fan') == 'critical'
    assert severity_of('ocp_12v') == 'warning'
    assert severity_of('opp') == 'warning'
    assert severity_of('otp') == 'warning'
    assert severity_of('ocp_pin7') == 'warning'


def test_describe_known_and_unknown():
    assert 'blocked' in describe('fan')
    assert '12+4 pin 3' in describe('ocp_pin3')
    assert describe('something_new') == 'something_new'


def test_format_alert_line():
    from msi_psu_monitor.alerts import Alert

    line = format_alert_line(Alert(name='fan', severity='critical', description='d'))
    assert line == 'ALERT [critical] fan: d'


def test_single_shot_mode_fires_immediately():
    engine = AlertEngine(consecutive_required=1)
    fired = engine.update({'ocp_12v': True})
    assert [a.name for a in fired] == ['ocp_12v']
    assert fired[0].severity == 'warning'


def test_debounce_needs_two_consecutive_polls():
    engine = AlertEngine()
    assert engine.update({'opp': True}) == []
    fired = engine.update({'opp': True})
    assert [a.name for a in fired] == ['opp']


def test_no_spam_while_active():
    engine = AlertEngine()
    engine.update({'otp': True})
    engine.update({'otp': True})
    assert engine.update({'otp': True}) == []
    assert engine.active_alerts == ['otp']


def test_recovery_clears_on_first_ok():
    engine = AlertEngine()
    engine.update({'fan': True})
    engine.update({'fan': True})
    assert engine.update({'fan': False}) == []
    assert engine.active_alerts == []
    # Re-fire needs a fresh streak after recovery.
    assert engine.update({'fan': True}) == []
    assert [a.name for a in engine.update({'fan': True})] == ['fan']


def test_blip_below_threshold_never_fires():
    engine = AlertEngine()
    assert engine.update({'ocp_5v': True}) == []
    assert engine.update({'ocp_5v': False}) == []
    assert engine.update({'ocp_5v': True}) == []
    assert engine.active_alerts == []


def test_invalid_consecutive_required():
    with pytest.raises(ValueError):
        AlertEngine(consecutive_required=0)


def test_retain_drops_what_the_device_cannot_report():
    """A swap to another model must not leave a foreign alert latched.

    Only a poll that reports a name ``False`` clears it, so a name the new model
    has no bit for (``ocp_pin1`` on a MEG) would fire forever.
    """
    engine = AlertEngine(consecutive_required=1)
    engine.update({'ocp_pin1': True, 'pin_imbalance': True, 'fan': True})
    assert engine.active_alerts == ['fan', 'ocp_pin1', 'pin_imbalance']

    engine.retain({'fan', 'otp'})
    assert engine.active_alerts == ['fan']
    # The streak is gone too: a name that comes back has to re-earn its debounce.
    assert engine._streaks == {'fan': 1}

    engine.retain({'fan'})
    engine.update({'fan': True})
    assert engine.active_alerts == ['fan'], 'a retained name stays fired'
    engine.update({'fan': False})
    assert engine.active_alerts == []


def test_the_pin_mirror_trips_at_the_threshold_not_above_it():
    """The documented boundary is `>= 12 A`, matching the C0h trip point.

    README said "> 12 A" and nothing pinned the boundary, so a maintainer
    "fixing" the code to strict `>` would weaken the mirror by one quantisation
    step -- the PSU trips *at* the configured point, not above it.
    """
    exactly_twelve = [name for name, active in evaluate_pin_alerts([12.0] * 12).items() if active]
    assert sorted(exactly_twelve, key=lambda name: int(name.removeprefix('ocp_pin'))) == [
        f'ocp_pin{index}' for index in range(1, 13)
    ]
    just_below = evaluate_pin_alerts([11.9] * 12)
    assert not any(just_below.values())
    # The spread rule is strict (`> 5 A`): exactly 5 A apart is not an imbalance,
    # and it is evaluated per 6-pin connector, not across the whole 12.
    exactly_five = [12.0, 7.0, 7.0, 7.0, 7.0, 7.0] * 2
    assert not evaluate_pin_alerts(exactly_five)['pin_imbalance']
    just_over = [12.1, 7.0, 7.0, 7.0, 7.0, 7.0] * 2
    assert evaluate_pin_alerts(just_over)['pin_imbalance']
    # 6 A across the two connectors, but only 1 A inside either one.
    per_connector = [13.0, 13.0, 13.0, 13.0, 13.0, 13.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0]
    assert not evaluate_pin_alerts(per_connector)['pin_imbalance']


def test_a_recovery_is_reported_once_and_reset():
    engine = AlertEngine(consecutive_required=1)
    engine.update({'ocp_pin1': True})
    assert engine.take_cleared() == []
    engine.update({'ocp_pin1': False})
    cleared = engine.take_cleared()
    assert [alert.name for alert in cleared] == ['ocp_pin1']
    assert engine.take_cleared() == []


def test_a_model_swap_is_not_a_recovery():
    engine = AlertEngine(consecutive_required=1)
    engine.update({'ocp_pin1': True})
    engine.retain(set())
    assert engine.take_cleared() == []


# ---- local early-warning thresholds (REQ-13/14) -------------------------

LIMITS = {
    'power_w': 1200.0,
    'temp_c': 70.0,
    'pin_max_a': 12.0,
    'pin_imbalance_a': 5.0,
    'connector_a': 50.0,
    'rail_12v_a': 108.0,
    'rail_5v_a': 22.0,
    'rail_3v3_a': 22.0,
}


def _threshold_sensors(**extra):
    sensors = {
        'power_total': (600.0, 'W'),
        'temp': (56.0, 'C'),
        'iout_12v_total': (50.0, 'A'),
        'iout_5v': (2.0, 'A'),
        'iout_3v3': (1.0, 'A'),
    }
    sensors.update(extra)
    return sensors


def test_threshold_alerts_trip_at_the_configured_limits():
    from msi_psu_monitor.alerts import evaluate_threshold_alerts

    active = evaluate_threshold_alerts(
        _threshold_sensors(
            power_total=(1200.0, 'W'),  # inclusive: the configured point trips
            temp=(70.1, 'C'),
            iout_12v_total=(108.0, 'A'),
            iout_5v=(21.9, 'A'),
            iout_3v3=(22.1, 'A'),
        ),
        LIMITS,
    )
    assert active['power_high'] is True
    assert active['temp_high'] is True
    assert active['rail_12v_high'] is True
    assert active['rail_5v_high'] is False
    assert active['rail_3v3_high'] is True


def test_a_zero_limit_disables_that_threshold():
    from msi_psu_monitor.alerts import evaluate_threshold_alerts

    limits = dict(LIMITS, power_w=0.0, temp_c=0.0, rail_12v_a=0.0)
    active = evaluate_threshold_alerts(
        _threshold_sensors(
            power_total=(9999.0, 'W'), temp=(99.0, 'C'), iout_12v_total=(999.0, 'A')
        ),
        limits,
    )
    assert 'power_high' not in active
    assert 'temp_high' not in active
    assert 'rail_12v_high' not in active
    assert active['rail_5v_high'] is False


def test_a_missing_reading_is_left_out_not_reported_as_ok():
    from msi_psu_monitor.alerts import evaluate_threshold_alerts

    active = evaluate_threshold_alerts({'power_total': (600.0, 'W')}, LIMITS)
    assert active == {'power_high': False}, 'no temperature/rail reading must not mean Normal'


def test_connector_limits_are_per_12v2x6_connector():
    from msi_psu_monitor.alerts import evaluate_threshold_alerts

    pins = [8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
    active = evaluate_threshold_alerts({'iout_pins': (pins, 'A')}, dict(LIMITS, connector_a=40.0))
    assert active['connector1_high'] is True  # 48 A
    assert active['connector2_high'] is False  # 30 A


def test_configured_threshold_names_requires_pins_for_connectors():
    from msi_psu_monitor.alerts import configured_threshold_names

    names = configured_threshold_names(LIMITS, has_per_pin_data=False)
    assert 'power_high' in names and 'rail_12v_high' in names
    assert 'connector1_high' not in names

    names = configured_threshold_names(LIMITS, has_per_pin_data=True)
    assert {'connector1_high', 'connector2_high'} <= names

    disabled = configured_threshold_names(dict(LIMITS, connector_a=0.0), has_per_pin_data=True)
    assert 'connector1_high' not in disabled


def test_pin_thresholds_and_imbalance_are_configurable():
    pins = [11.0] * 12
    assert not any(evaluate_pin_alerts(pins).values())
    assert evaluate_pin_alerts(pins, pin_max_a=10.0)['ocp_pin1'] is True
    assert not any(name.startswith('ocp_pin') for name in evaluate_pin_alerts(pins, pin_max_a=0.0))

    spread = [10.0, 4.0, 4.0, 4.0, 4.0, 4.0] * 2
    assert evaluate_pin_alerts(spread)['pin_imbalance'] is True
    assert 'pin_imbalance' not in evaluate_pin_alerts(spread, imbalance_a=0.0)


def test_threshold_alert_names_are_distinct_from_the_e1h_bits():
    from msi_psu_monitor.alerts import THRESHOLD_ALERT_NAMES

    assert 'power_high' in THRESHOLD_ALERT_NAMES
    assert 'ocp_12v' not in THRESHOLD_ALERT_NAMES
    assert 'fan' not in THRESHOLD_ALERT_NAMES
