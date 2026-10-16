"""Unit tests for the edge-triggered alert engine (alerts.AlertEngine)."""

import pytest

from msi_psu_monitor.alerts import (
    AlertEngine,
    describe,
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
