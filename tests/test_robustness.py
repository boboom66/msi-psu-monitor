"""Deterministic fuzz/property checks for the parser and formatters.

The hardware is not required: every payload is synthetic, but the invariants are
the ones a hostile or flaky device must never break - no exception, no NaN/inf
leaking into JSON or Prometheus, and no crash from arbitrary config text.
"""

import argparse
import json
import math
import random

from msi_psu_monitor import config, monitor
from msi_psu_monitor.protocol import MSIPSU

VARIANTS = (
    'MPG Ai1600TS',
    'MPG Ai1300TS',
    'MEG Ai1300P',
    'MEG Ai1000P',
    'MEG Ai1600T',
)


class FakeHID:
    def __init__(self, product, payload):
        self.payload = payload
        self.registers = {
            0x10: b'MSI\x00',
            0x11: product.encode() + b'\x00',
            0x12: b'10',
            0x13: b'\x08SNFUZZ0001',
        }
        self.commands = {(0xFA, 0x51): product.encode() + b'\x00'}

    def send_command(self, data, timeout_ms=250):
        return self.commands.get(tuple(data))

    def read_register(self, reg):
        return self.registers.get(reg)

    def read_all(self):
        return self.payload

    def open(self):
        return self

    def close(self):
        pass


def _psu(product, payload):
    psu = MSIPSU(FakeHID(product, payload))
    psu.init()
    return psu


def _finite_readings(sensors):
    for key, value in sensors.items():
        if not isinstance(value, tuple):
            continue
        reading, unit = value
        assert isinstance(unit, str), (key, value)
        if isinstance(reading, list):
            for item in reading:
                assert math.isfinite(float(item)), (key, item)
        else:
            assert math.isfinite(float(reading)), (key, reading)


def test_random_bulk_payloads_never_crash_a_variant_or_a_formatter():
    rng = random.Random(20261019)
    for product in VARIANTS:
        for _ in range(80):
            payload = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 65)))
            sensors = _psu(product, payload).get_sensors()
            assert isinstance(sensors, dict)
            _finite_readings(sensors)
            text = monitor.format_text(sensors)
            assert 'MSI PSU' in text
            json.loads(monitor.format_json(sensors))
            prom = monitor.format_prometheus(sensors)
            assert 'msi_psu_up' in prom
            assert '\x00' not in prom


def test_random_threshold_config_text_never_escapes_as_an_unexpected_error(tmp_path):
    rng = random.Random(7)
    alphabet = 'abcdefghijklmnopqrstuvwxyz0123456789_-.=[]% \n\t#'
    for index in range(120):
        body = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 400)))
        path = tmp_path / f'fuzz-{index}.conf'
        path.write_text(body, encoding='utf-8')
        try:
            cfg = config.load_config(str(path))
        except config.ConfigError:
            continue
        for key in config.THRESHOLD_KEYS:
            assert math.isfinite(cfg[key]), (key, cfg[key])
        assert cfg['sample_interval'] > 0
        assert cfg['port'] >= 0


def test_random_ocp_set_specs_are_rejected_cleanly():
    rng = random.Random(11)
    alphabet = '0123456789,onfyl '
    for _ in range(120):
        spec = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 18)))
        try:
            value = monitor._ocp_setting(spec)
        except argparse.ArgumentTypeError:
            continue
        assert isinstance(value, dict)
        for key in ('point_a', 'diff_a', 'trigger_s', 'diff_trigger_s', 'warning_s'):
            low, high = monitor._OCP_RANGES[key]
            assert low <= value[key] <= high
