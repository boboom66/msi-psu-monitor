"""Synthetic PSU for the no-hardware demo mode (``MSI_PSU_DEMO=1``).

The demo exists so the whole pipeline -- CLI output, alert debounce, daemon
history, prometheus textfile and the dashboard -- can be exercised and shown
without a PSU attached. It is deliberately isolated in this module: nothing
else in the package imports it at module scope, and every value it produces is
fabricated, so it must never be reachable unless ``MSI_PSU_DEMO`` is set.

Environment:
    MSI_PSU_DEMO=1          enable the synthetic device
    MSI_PSU_DEMO_ALERT=fan  make one alert bit stick (any name from alerts.py)

The synthetic load follows a 5-minute cycle (idle -> full load -> idle) so a
short demo run produces visible curves instead of a flat line.
"""

from __future__ import annotations

import math
import os
import time

from msi_psu_monitor.alerts import ALERT_DESCRIPTIONS

DEVICE_PATH = 'demo:0'
PRODUCT = 'MPG Ai1600TS (demo)'
DEMO_SERIAL = 'DEMO00000001'
CYCLE_S = 300.0
_TRUTHY = ('1', 'true', 'yes', 'on')

# Sampling every step keeps the demo reproducible: no randomness, just the
# cycle phase plus a small fixed wobble derived from the sample counter.
VENDOR = 'MSI'
FW_REVISION = '1.0'


def enabled():
    """True when ``MSI_PSU_DEMO`` asks for the synthetic device."""
    return os.environ.get('MSI_PSU_DEMO', '').strip().lower() in _TRUTHY


def _stuck_alert():
    """Return the alert name forced by ``MSI_PSU_DEMO_ALERT`` (or empty)."""
    name = os.environ.get('MSI_PSU_DEMO_ALERT', '').strip()
    return name if name in ALERT_DESCRIPTIONS else ''


class DemoPSU:
    """Drop-in stand-in for :class:`msi_psu_monitor.protocol.MSIPSU`."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.started = clock()
        self.samples = 0
        self.product = PRODUCT
        self.serial = DEMO_SERIAL
        self.fan_mode = 1
        self.fan_duty = 30

    # ---- lifecycle -------------------------------------------------------

    def open(self):
        return self

    def close(self):
        return None

    def init(self):
        return self.product

    # ---- synthetic load --------------------------------------------------

    def _load(self):
        """Return (load 0..1, phase 0..1) for the current instant."""
        elapsed = self.clock() - self.started
        phase = (elapsed % CYCLE_S) / CYCLE_S
        return max(0.0, math.sin(2 * math.pi * phase)), phase

    def _wobble(self, index, amplitude=0.02):
        """Deterministic per-sample jitter (+/- amplitude)."""
        return amplitude * math.sin(self.samples * 1.7 + index * 2.3)

    def get_sensors(self):
        self.samples += 1
        load, _ = self._load()
        watts = 60.0 + load * 660.0 + self._wobble(0, 8.0)
        efficiency = 88.0 + 6.0 * (1.0 - abs(2.0 * load - 1.0))
        volts_12v = 12.10 - 0.06 * load + self._wobble(1, 0.01)
        total_a = (watts * 0.92) / volts_12v
        pins = [total_a / 12.0 * (1.0 + self._wobble(2 + index, 0.06)) for index in range(12)]

        zero_fan = load < 0.25
        fan_rpm = 0.0 if zero_fan else 700.0 + 1150.0 * load
        uptime = int(self.clock() - self.started)

        return {
            'vendor': VENDOR,
            'product': self.product,
            'fw_revision': FW_REVISION,
            'serial': self.serial,
            'vout_12v': (round(volts_12v, 3), 'V'),
            'vout_5v': (round(5.04 + self._wobble(3, 0.01), 3), 'V'),
            'vout_3v3': (round(3.32 + self._wobble(4, 0.01), 3), 'V'),
            'iout_12v_total': (round(total_a, 3), 'A'),
            'iout_5v': (round(1.8 + load * 1.5, 3), 'A'),
            'iout_3v3': (round(0.8 + load * 0.3, 3), 'A'),
            'iout_pins': ([round(pin, 3) for pin in pins], 'A'),
            'power_total': (round(watts, 1), 'W'),
            'efficiency': (round(efficiency, 2), '%'),
            'temp': (round(29.0 + 32.0 * load, 1), '\u00b0C'),
            'fan_rpm': (round(fan_rpm, 0), 'RPM'),
            'zero_fan': zero_fan,
            'uptime': uptime,
            'uptime_total': uptime + 446400,
        }

    # ---- control surface -------------------------------------------------

    def read_alert_status(self):
        stuck = _stuck_alert()
        return {name: name == stuck for name in ALERT_DESCRIPTIONS}

    def read_fan_state(self):
        return {'mode': self.fan_mode, 'duty': self.fan_duty, 'zero_fan': self._load()[0] < 0.25}

    def read_fan_setting(self):
        return (self.fan_mode, self.fan_duty)

    def set_fan_mode(self, mode, duty=0):
        self.fan_mode, self.fan_duty = mode, duty
        return True

    def read_blackbox(self, max_records=10):
        records = [
            {
                'info_id': 2,
                'pin_set': 1,
                'status': 2,
                'run_time': 3600,
                'total_time': 446400,
                'pins_1_6': [9.8, 9.4, 9.1, 8.9, 8.6, 3.4],
                'total_count': 3,
            },
            {
                'info_id': 1,
                'pin_set': 2,
                'status': 1,
                'run_time': 120,
                'total_time': 442800,
                'pins_1_6': [12.6, 12.2, 11.9, 11.7, 11.5, 11.2],
                'total_count': 1,
            },
        ]
        return records[:max_records]
