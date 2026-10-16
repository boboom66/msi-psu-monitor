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
