"""JSON schema freeze: top-level keys and value shapes must stay stable."""

import json

from msi_psu_monitor.monitor import format_json

FULL_SENSORS = {
    'vendor': 'MSI',
    'product': 'MPG Ai1600TS',
    'fw_revision': '1.0',
    'serial': 'SN1',
    'vout_12v': (12.0, 'V'),
    'vout_5v': (5.0, 'V'),
    'vout_3v3': (3.3, 'V'),
    'iout_12v_total': (2.5, 'A'),
    'iout_5v': (1.0, 'A'),
    'iout_3v3': (0.5, 'A'),
    'iout_pins': ([1.0] * 12, 'A'),
    'power_total': (500.0, 'W'),
    'efficiency': (90.0, '%'),
    'temp': (51.0, '°C'),
    'fan_rpm': (536, 'RPM'),
    'uptime': 60,
    'uptime_total': 600,
    'alerts': ['opp'],
}

EXPECTED_KEYS = {
    'vendor',
    'product',
    'fw_revision',
    'serial',
    'vout_12v',
    'vout_5v',
    'vout_3v3',
    'iout_12v_total',
    'iout_5v',
    'iout_3v3',
    'iout_pins',
    'power_total',
    'efficiency',
    'temp',
    'fan_rpm',
    'uptime',
    'uptime_total',
    'alerts',
}


def test_json_schema_keys_frozen():
    doc = json.loads(format_json(dict(FULL_SENSORS)))
    assert set(doc.keys()) == EXPECTED_KEYS


def test_json_value_shapes():
    doc = json.loads(format_json(dict(FULL_SENSORS)))
    assert doc['vout_12v'] == {'value': 12.0, 'unit': 'V'}
    assert doc['uptime'] == 60
    assert doc['alerts'] == ['opp']
    assert doc['vendor'] == 'MSI'


def test_error_shape_is_scalar():
    doc = json.loads(format_json({'product': 'Mystery', 'error': 'unsupported PSU variant'}))
    assert doc == {'product': 'Mystery', 'error': 'unsupported PSU variant'}
