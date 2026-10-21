"""Unit tests for CLI formatters (monitor.format_*). No hardware access."""

import json

from msi_psu_monitor.monitor import format_json, format_prometheus, format_text


def _sample_sensors():
    return {
        "vendor": "MSI",
        "product": "MPG Ai1600TS",
        "fw_revision": "49.48",
        "serial": "SN123",
        "vout_12v": (12.062, "V"),
        "vout_5v": (5.007, "V"),
        "vout_3v3": (3.304, "V"),
        "iout_12v_total": (82.0, "A"),
        "iout_5v": (8.187, "A"),
        "iout_3v3": (3.375, "A"),
        "iout_pins": ([5.312] * 12, "A"),
        "power_total": (1040.0, "W"),
        "efficiency": (94.5, "%"),
        "temp": (51.0, "\u00b0C"),
        "fan_rpm": (536, "RPM"),
        "uptime": 3 * 86400 + 23 * 3600 + 37 * 60 + 20,
        "uptime_total": 9 * 86400 + 10 * 3600 + 50 * 60 + 20,
    }


def test_format_text_contains_keys():
    out = format_text(_sample_sensors())
    assert "MSI PSU: MPG Ai1600TS" in out
    assert "12.062" in out
    assert "POWER" in out
    assert "Conn1 Pin1" in out
    assert "Conn2 Pin6" in out
    assert "Uptime" in out


def test_format_text_partial_dict_never_raises():
    # get_sensors returns partial dict on failed bulk; formatters must guard.
    out = format_text({"product": "unknown"})
    assert "MSI PSU: unknown" in out


def test_format_json_roundtrip():
    out = json.loads(format_json(_sample_sensors()))
    assert out["vout_12v"] == {"value": 12.062, "unit": "V"}
    assert out["fan_rpm"] == {"value": 536, "unit": "RPM"}
    assert out["vendor"] == "MSI"
    assert out["uptime"] == _sample_sensors()["uptime"]


def test_format_prometheus_metrics():
    out = format_prometheus(_sample_sensors())
    assert 'msi_psu_info{product="MPG Ai1600TS"' in out
    assert "msi_psu_voltage_12v" in out
    assert "msi_psu_current_12v_total" in out
    assert 'msi_psu_pin_current{connector="1",pin="1"} 5.312' in out
    assert 'msi_psu_pin_current{connector="2",pin="6"} 5.312' in out
    assert "msi_psu_power_total{} 1040.0" in out
    assert "msi_psu_temperature{} 51.0" in out
    assert "msi_psu_fan_speed{} 536" in out
