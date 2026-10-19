"""Unit tests for the three output formatters (no hardware required)."""

from msi_psu_monitor.monitor import format_json, format_prometheus, format_text


def full_sensors():
    pins = [8.0, 8.7, 8.4, 8.4, 8.1, 7.7, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return {
        'vendor': 'MSI',
        'product': 'MPG Ai1300TS',
        'fw_revision': '1.0',
        'serial': 'DEMO0001',
        'vout_12v': (12.1, 'V'),
        'vout_5v': (5.04, 'V'),
        'vout_3v3': (3.32, 'V'),
        'iout_12v_total': (53.75, 'A'),
        'iout_5v': (1.94, 'A'),
        'iout_3v3': (0.88, 'A'),
        'iout_pins': (pins, 'A'),
        'power_total': (660.0, 'W'),
        'efficiency': (94.4, '%'),
        'temp': (56.0, 'C'),
        'fan_rpm': (2050, 'RPM'),
        'uptime': 2700,  # 0d 00:45:00
        'uptime_total': 446400,  # 5d 04:00:00
    }


def test_text_full():
    out = format_text(full_sensors())
    assert 'MSI PSU: MPG Ai1300TS' in out
    assert '+12V' in out and '12.100 V' in out
    assert '12V TOTAL' in out and '53.750 A' in out
    assert 'Conn1 Pin1' in out and 'Conn1 Pin6' in out
    assert 'Conn2 Pin1' in out and 'Conn2 Pin6' in out
    assert out.count('Conn1 Pin') == 6
    assert out.count('Conn2 Pin') == 6
    assert '660.0 W' in out
    assert '94.40 %' in out
    assert '2050 RPM' in out
    assert '0d 00:45:00' in out
    assert '5d 04:00:00' in out


def test_text_partial_dict_does_not_crash():
    # Locks the get_sensors() partial-dict defense: ident-only input renders.
    out = format_text({'product': 'unknown'})
    assert 'MSI PSU: unknown' in out


def test_json_shapes():
    import json

    out = json.loads(format_json(full_sensors()))
    assert out['product'] == 'MPG Ai1300TS'
    assert out['vout_12v'] == {'value': 12.1, 'unit': 'V'}
    assert out['temp'] == {'value': 56.0, 'unit': 'C'}
    assert out['uptime'] == 2700


def test_prometheus_reports_up_for_a_sample_with_readings():
    out = format_prometheus(full_sensors())
    assert 'msi_psu_up 1' in out
    assert 'msi_psu_error_info' not in out


def test_prometheus_reports_down_for_a_rejected_read():
    """An ident-only sample used to export msi_psu_info 1 and nothing else."""
    out = format_prometheus({'product': 'MPG Ai1600TS', 'error': 'unsupported model'})
    assert 'msi_psu_up 0' in out
    assert 'msi_psu_error_info{reason="unsupported model"} 1' in out


def test_prometheus_reports_down_for_a_short_payload():
    sensors = {'product': 'MPG Ai1600TS', 'payload_error': 'got 10 of 44 bytes'}
    out = format_prometheus(sensors)
    assert 'msi_psu_up 0' in out
    assert 'msi_psu_error_info{reason="got 10 of 44 bytes"} 1' in out


def test_prometheus_down_without_a_reason_still_explains_itself():
    out = format_prometheus({'product': 'MPG Ai1600TS', 'serial': 'SN1'})
    assert 'msi_psu_up 0' in out
    assert '0xE0 read failed' in out


def test_prometheus_shapes():
    out = format_prometheus(full_sensors())
    assert 'msi_psu_info{product="MPG Ai1300TS",vendor="MSI",fw="1.0",serial="DEMO0001"} 1' in out
    assert 'msi_psu_voltage_12v{rail="vout_12v"} 12.1' in out
    assert 'msi_psu_current_12v_total{rail="iout_12v_total"} 53.75' in out
    assert 'msi_psu_pin_current{connector="1",pin="1"} 8.0' in out
    assert 'msi_psu_pin_current{connector="2",pin="6"} 0.0' in out
    assert out.count('msi_psu_pin_current{') == 12
    assert '# TYPE msi_psu_uptime counter' in out
    assert 'msi_psu_power_total {} 660.0' in out
    assert 'msi_psu_fan_speed {} 2050' in out


def test_vin_has_a_text_line_and_a_prometheus_metric():
    sensors = {'product': 'MEG Ai1300P', 'vout_12v': (12.1, 'V'), 'vin': (230.0, 'V')}
    text = format_text(sensors)
    assert 'AC Input:    230.0 V' in text
    prom = format_prometheus(sensors)
    assert 'msi_psu_input_voltage 230.0' in prom


def test_blackbox_location_never_invents_a_connector_for_a_pin_id():
    from msi_psu_monitor.monitor import format_blackbox

    records = [
        {
            'info_id': 1,
            'pin_set': 7,
            'status': 1,
            'run_time': 60,
            'total_time': 600,
            'total_count': 3,
        }
    ]
    text = format_blackbox(records)
    assert 'pin 7' in text
    assert 'Conn7' not in text


def test_prometheus_labels_cannot_be_broken_by_device_control_characters():
    sensors = {
        'product': 'PSU\r\nmsi_psu_up 0',
        'vendor': 'MSI\x01',
        'fw_revision': '1.0',
        'serial': 'SN\x00\r',
        'vout_12v': (12.1, 'V'),
    }
    prom = format_prometheus(sensors)
    assert '\r' not in prom
    assert 'msi_psu_up 1' in prom.splitlines()
    info = [line for line in prom.splitlines() if line.startswith('msi_psu_info{')][0]
    assert 'PSU  msi_psu_up 0' in info
