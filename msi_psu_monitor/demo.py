"""Synthetic PSU for the no-hardware demo mode (``MSI_PSU_DEMO=1``).

The demo exists so the whole pipeline -- CLI output, alert debounce, daemon
history, prometheus textfile and the dashboard -- can be exercised and shown
without a PSU attached. It is deliberately isolated in this module -- no other
module reads its values -- and every value it produces is fabricated, so it must
never be reachable unless ``MSI_PSU_DEMO`` is set: the only two call sites
(``monitor._open_psu`` / ``monitor.resolve_device``) are gated by ``enabled()``.

Environment:
    MSI_PSU_DEMO=1              enable the synthetic device
    MSI_PSU_DEMO_ALERT=fan      make one alert bit stick; must be a name the
                                emulated model can report (see protocol.ALERT_NAMES),
                                otherwise nothing is forced and a warning says so
    MSI_PSU_DEMO_MODEL=ai1300p  emulate another supported variant (default
                                mpg_ai1600ts); each model reports its own payload
                                shape, so the multi-rail and single-rail code
                                paths are reachable without hardware

The synthetic load follows a 5-minute cycle (idle -> full load -> idle) so a
short demo run produces visible curves instead of a flat line.
"""

from __future__ import annotations

import logging
import math
import os
import time

from msi_psu_monitor.alerts import ALERT_DESCRIPTIONS
from msi_psu_monitor.protocol import ALERT_NAMES, MSIPSU

logger = logging.getLogger('msi_psu.demo')

DEVICE_PATH = 'demo:0'
DEMO_SERIAL = 'DEMO00000001'
CYCLE_S = 300.0
MODEL_ENV = 'MSI_PSU_DEMO_MODEL'
ALERT_ENV = 'MSI_PSU_DEMO_ALERT'
DEFAULT_MODEL = 'mpg_ai1600ts'
_TRUTHY = ('1', 'true', 'yes', 'on')

# Variant -> rated wattage, which sets the top of the synthetic load ramp.
MODEL_WATTS = {
    'mpg_ai1600ts': 1600.0,
    'mpg_ai1300ts': 1300.0,
    'meg_ai1600': 1600.0,
    'ai1300p': 1300.0,
    'ai1000p': 1000.0,
}
# The multi-rail MEG models split their 12V output across five rails. Shares are
# the wiring MSI Center assumes: 12V1 = board, 12V2 = CPU, 12V3-5 = GPU.
RAIL_SHARES = (0.12, 0.28, 0.22, 0.20, 0.18)
PRODUCT = f'{MSIPSU.VARIANTS[DEFAULT_MODEL]["name"]} (demo)'

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


def model():
    """Return the variant requested by ``MSI_PSU_DEMO_MODEL`` (default TS 1600).

    An unknown name still falls back to the default -- a typo must not take the
    demo down -- but it warns, because otherwise ``meg_ai1300p`` (not a variant
    name) would quietly present itself as an MPG Ai1600TS and an acceptance run
    against the wrong model would look like a pass.
    """
    name = os.environ.get(MODEL_ENV, '').strip().lower()
    if name and name not in MODEL_WATTS:
        logger.warning(
            f'Ignoring unknown {MODEL_ENV}={name!r}; using {DEFAULT_MODEL}. '
            f'Known models: {", ".join(sorted(MODEL_WATTS))}'
        )
        return DEFAULT_MODEL
    return name or DEFAULT_MODEL


def product_name(variant):
    """Return the product string ``variant`` reports (as the real PSU would)."""
    return f'{MSIPSU.VARIANTS[variant]["name"]} (demo)'


class DemoPSU:
    """Drop-in stand-in for :class:`msi_psu_monitor.protocol.MSIPSU`."""

    def __init__(self, clock=time.time, variant=None):
        self.clock = clock
        self.started = clock()
        self.samples = 0
        self.variant = variant or model()
        self.watts_max = MODEL_WATTS[self.variant]
        self.product = product_name(self.variant)
        self.serial = DEMO_SERIAL
        self.fan_mode = 1
        self.fan_duty = 30
        self._alert_warned = False
        #: Set by --zero-fan; None keeps the load-dependent demo behaviour.
        self.zero_fan_override = None
        self.buzzer_silenced = False

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

    def _pin_currents(self, total_a):
        """Split the 12V total across the 12 pins with a small fixed skew."""
        return [
            round(total_a / 12.0 * (1.0 + self._wobble(2 + index, 0.06)), 3) for index in range(12)
        ]

    def _rail_currents(self, total_a):
        """Split the 12V total across the five discrete rails of the MEG P models."""
        return [
            round(total_a * share * (1.0 + self._wobble(2 + index, 0.05)), 3)
            for index, share in enumerate(RAIL_SHARES)
        ]

    def get_sensors(self):
        self.samples += 1
        load, _ = self._load()
        watts = 0.05 * self.watts_max + load * 0.45 * self.watts_max + self._wobble(0, 8.0)
        efficiency = 88.0 + 6.0 * (1.0 - abs(2.0 * load - 1.0))
        volts_12v = 12.10 - 0.06 * load + self._wobble(1, 0.01)
        total_a = (watts * 0.92) / volts_12v
        pins = self._pin_currents(total_a)

        zero_fan = self._zero_fan_state(load)
        fan_rpm = 0.0 if zero_fan else 700.0 + 1150.0 * load
        uptime = int(self.clock() - self.started)

        sensors = {
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
            'power_total': (round(watts, 1), 'W'),
            'efficiency': (round(efficiency, 2), '%'),
            'temp': (round(29.0 + 32.0 * load, 1), '\u00b0C'),
            'fan_rpm': (round(fan_rpm, 0), 'RPM'),
            'zero_fan': zero_fan,
            'uptime': uptime,
            'uptime_total': uptime + 446400,
        }
        if self.variant in MSIPSU.SEVEN_ZPU_VARIANTS:
            sensors['iout_pins'] = (pins, 'A')
        if self.variant in MSIPSU.MULTIRAIL_VARIANTS:
            sensors['vout_12v_rails'] = ([round(volts_12v, 3)] * 5, 'V')
            sensors['iout_12v_rails'] = (self._rail_currents(total_a), 'A')
        return sensors

    # ---- control surface -------------------------------------------------

    @property
    def alert_names(self):
        """E1h byte order of the emulated model (see ``protocol.ALERT_INDEXES``)."""
        return ALERT_NAMES.get(self.variant, ())

    def read_alert_status(self):
        stuck = _stuck_alert()
        if stuck and stuck not in self.alert_names:
            # ALERT_DESCRIPTIONS is model-independent and includes the software
            # mirror's names, so a typo or a name this model cannot report
            # (pin_imbalance anywhere, ocp_pin1 on a MEG) used to be accepted and
            # then never set: the acceptance run reported all-clear.
            self._warn_unreportable_alert(stuck)
        return {name: name == stuck for name in self.alert_names}

    def _warn_unreportable_alert(self, stuck):
        """Say once that MSI_PSU_DEMO_ALERT cannot be honoured by this model."""
        if self._alert_warned:
            return
        self._alert_warned = True
        logger.warning(
            f'{ALERT_ENV}={stuck!r} is not an alert the {self.variant} model reports; '
            f'nothing will be forced. This model reports: {", ".join(self.alert_names)}.'
        )

    # ---- 12V-2x6 OCP (C0h read-only + C1h state) ------------------------

    @property
    def supports_ocp_config(self):
        return self.variant in MSIPSU.SEVEN_ZPU_VARIANTS

    @property
    def supports_multirail_ocp(self):
        return self.variant in MSIPSU.MULTIRAIL_VARIANTS

    def read_multirail_ocp(self):
        """Report the fixture's per-rail protection state for the MEG P models."""
        if not self.supports_multirail_ocp:
            return None
        return True

    def read_ocp_thresholds(self):
        """Factory OCP configuration as shipped by MSI (CPSU.cs defaults).

        Only the 12V-2x6 models answer the 8-byte 0xC0 read; on the others the
        same address means something else (or nothing), so the emulation must
        report the same absence the hardware does.
        """
        if not self.supports_ocp_config:
            return None
        return {
            'enabled': True,
            'point_a': 12.0,
            'diff_a': 5.0,
            'trigger_s': 20,
            'diff_trigger_s': 20,
            'warning_s': 180,
        }

    def read_ocp_state(self):
        """C1h state: pin currents derived from the same load model as the report."""
        load, _ = self._load()
        watts = 60.0 + load * 660.0 + self._wobble(0, 8.0)
        pins = self._pin_currents((watts * 0.92) / (12.10 - 0.06 * load))
        uptime = int(self.clock() - self.started)
        # Keep the status consistent with the stuck-alert knob, so a demo that
        # shows an alert bit never also claims the connector is Normal.
        stuck = _stuck_alert()
        status = 0
        if stuck.startswith('ocp_pin'):
            status = 1 if int(stuck[len('ocp_pin') :]) <= 6 else 2
        return {
            'status_12v5': 1 if status == 1 else 0,
            'run_time': 0,
            'total_time': uptime + 446400,
            'pins_1_6': pins[:6],
            'status_12v3': 2 if status == 2 else 0,
            'run_time_2': 0,
            'total_time_2': uptime + 446400,
            'pins_7_12': pins[6:],
        }

    def _zero_fan_state(self, load=None):
        """Zero Fan state: the explicit override, else the load-dependent default."""
        if self.zero_fan_override is not None:
            return self.zero_fan_override
        return (self._load()[0] if load is None else load) < 0.25

    def read_fan_state(self):
        return {'mode': self.fan_mode, 'duty': self.fan_duty, 'zero_fan': self._zero_fan_state()}

    def read_fan_setting(self):
        return (self.fan_mode, self.fan_duty)

    def set_fan_mode(self, mode, duty=0):
        self.fan_mode, self.fan_duty = mode, duty
        return True

    def set_zero_fan(self, enabled):
        if self.variant not in MSIPSU.SEVEN_ZPU_VARIANTS:
            return False
        self.zero_fan_override = bool(enabled)
        return True

    def read_zero_fan(self):
        return self._zero_fan_state()

    def silence_buzzer(self):
        if self.variant not in MSIPSU.SEVEN_ZPU_VARIANTS:
            return False
        self.buzzer_silenced = True
        return True

    def read_blackbox(self, max_records=10):
        # Slot order, newest first: REV6 p.13 defines InfoID 1 as the latest, and
        # slot 1 also carries the larger lifetime counters. The two used to
        # disagree (slot 2 held the bigger counters here), so an acceptance run
        # against the demo trained on an order the real path would never print.
        records = [
            {
                'info_id': 1,
                'pin_set': 1,
                'status': 2,
                'run_time': 3600,
                'total_time': 446400,
                'pins_1_6': [9.8, 9.4, 9.1, 8.9, 8.6, 3.4],
                'total_count': 3,
            },
            {
                'info_id': 2,
                'pin_set': 2,
                'status': 1,
                'run_time': 120,
                'total_time': 442800,
                'pins_1_6': [12.6, 12.2, 11.9, 11.7, 11.5, 11.2],
                'total_count': 1,
            },
        ]
        return records[:max_records]
