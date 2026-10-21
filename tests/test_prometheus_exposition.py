"""Strict Prometheus text-exposition checks (a stdlib promtool substitute).

promtool is not available in this environment. This parser enforces the subset
the project emits: metric/label grammar, HELP/TYPE ordering, finite values,
duplicate-series detection and the canonical empty-label form. It is not a full
Prometheus parser, but it turns the NR-001 "is 'metric {} value' legal?" gap into
a machine-checked invariant for our own output.
"""

import math
import re

import pytest

from msi_psu_monitor import monitor

NAME_RE = re.compile('[A-Za-z_:][A-Za-z0-9_:]*')
NUMBER_RE = re.compile('[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$')
LABEL_NAME_RE = re.compile('[A-Za-z_][A-Za-z0-9_]*')
BACKSLASH = chr(92)
VALID_LABEL_ESCAPES = {BACKSLASH: BACKSLASH, '"': '"', 'n': 'n'}
TYPES = {'gauge', 'counter', 'histogram', 'summary', 'untyped'}


class ExpositionError(AssertionError):
    pass


def _parse_labels(text, lineno):
    """Parse the inside of {...}; return (labels tuple, index after closing brace)."""
    labels = []
    index = 0
    while index < len(text):
        if text[index] == '}':
            return tuple(labels), index + 1
        match = LABEL_NAME_RE.match(text, index)
        if not match:
            raise ExpositionError(f'line {lineno}: bad label name at {text[index:]!r}')
        name = match.group(0)
        index = match.end()
        if not text.startswith('="', index):
            raise ExpositionError(f'line {lineno}: label {name} is not quoted')
        index += 2
        value = []
        while index < len(text):
            char = text[index]
            if char == BACKSLASH:
                index += 1
                if index >= len(text) or text[index] not in VALID_LABEL_ESCAPES:
                    raise ExpositionError(f'line {lineno}: bad escape in label {name}')
                value.append(VALID_LABEL_ESCAPES[text[index]])
                index += 1
                continue
            if char == '"':
                index += 1
                break
            value.append(char)
            index += 1
        else:
            raise ExpositionError(f'line {lineno}: unterminated label {name}')
        labels.append((name, ''.join(value)))
        if index < len(text) and text[index] == ',':
            index += 1
            continue
        if index < len(text) and text[index] != '}':
            raise ExpositionError(f'line {lineno}: expected , or }} after label {name}')
    raise ExpositionError(f'line {lineno}: unterminated label set')


def parse_exposition(text):
    """Parse our exposition output; return the set of metric family names."""
    families = set()
    types = {}
    series = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        if line != line.rstrip():
            raise ExpositionError(f'line {lineno}: trailing whitespace')
        if line.startswith('#'):
            parts = line.split(' ', 2)
            if len(parts) < 3 or parts[1] not in ('HELP', 'TYPE'):
                raise ExpositionError(f'line {lineno}: bad comment: {line!r}')
            name = parts[2].split(' ', 1)[0]
            if not NAME_RE.fullmatch(name):
                raise ExpositionError(f'line {lineno}: bad family name {name!r}')
            if parts[1] == 'HELP':
                if name in families and types.get(name) == 'seen-help':
                    raise ExpositionError(f'line {lineno}: duplicate HELP for {name}')
                types.setdefault('help', set()).add(name)
                continue
            type_name = parts[2].split(' ', 1)[1].strip() if ' ' in parts[2] else ''
            if type_name not in TYPES:
                raise ExpositionError(f'line {lineno}: bad TYPE {type_name!r}')
            if name in types.get('type', set()):
                raise ExpositionError(f'line {lineno}: duplicate TYPE for {name}')
            types.setdefault('type', set()).add(name)
            continue

        match = NAME_RE.match(line)
        if not match:
            raise ExpositionError(f'line {lineno}: bad metric name: {line!r}')
        name = match.group(0)
        rest = line[match.end() :]
        labels = ()
        if rest.startswith('{'):
            inner = rest[1:]
            labels, consumed = _parse_labels(inner, lineno)
            rest = inner[consumed:]
        if not rest.startswith(' '):
            raise ExpositionError(
                f'line {lineno}: metric {name} needs one space before the value '
                f'(empty labels are written as {name}{{}} value)'
            )
        value_text = rest[1:]
        if not NUMBER_RE.fullmatch(value_text):
            raise ExpositionError(f'line {lineno}: bad value {value_text!r}')
        value = float(value_text)
        if not math.isfinite(value):
            raise ExpositionError(f'line {lineno}: non-finite value')
        if name not in types.get('type', set()):
            raise ExpositionError(f'line {lineno}: TYPE missing before samples of {name}')
        if name in types.get('type', set()) and name in types.get('type', set()):
            pass
        key = (name, labels)
        if key in series:
            raise ExpositionError(f'line {lineno}: duplicate series {name}{labels}')
        series.add(key)
        families.add(name)

    for name in families:
        if name not in types.get('help', set()):
            raise ExpositionError(f'family {name} has no HELP line')
    return families


def _rich_sensors():
    return {
        'vendor': 'MSI',
        'product': 'MPG Ai1300TS',
        'fw_revision': '1.0',
        'serial': 'SN1',
        'vout_12v': (12.1, 'V'),
        'vout_5v': (5.04, 'V'),
        'vout_3v3': (3.32, 'V'),
        'iout_12v_total': (50.0, 'A'),
        'iout_5v': (2.0, 'A'),
        'iout_3v3': (1.0, 'A'),
        'iout_pins': ([8.0] * 12, 'A'),
        'power_total': (600.0, 'W'),
        'power_avg': (590.0, 'W'),
        'efficiency': (94.0, '%'),
        'efficiency_avg': (93.5, '%'),
        'temp': (56.0, 'C'),
        'fan_rpm': (2050, 'RPM'),
        'zero_fan': True,
        'status': 'Normal',
        'total_energy': (12.5, 'kWh'),
        'alerts': ['ocp_pin1'],
        'threshold_limits': {'power_w': 1200.0, 'pin_max_a': 12.0},
        'threshold_alerts': ['power_high'],
        'uptime': 100,
        'uptime_total': 1000,
    }


def test_format_prometheus_passes_a_strict_exposition_parser():
    families = parse_exposition(monitor.format_prometheus(_rich_sensors()))
    for expected in (
        'msi_psu_power_total',
        'msi_psu_total_energy_kwh',
        'msi_psu_energy_kwh_total',
        'msi_psu_threshold_limit',
        'msi_psu_threshold_alert',
        'msi_psu_alert',
        'msi_psu_pin_current',
        'msi_psu_status_12v_2x6',
    ):
        assert expected in families


def test_error_and_ocp_exposition_are_valid_too():
    parse_exposition(monitor.format_prometheus({'product': 'Mystery', 'error': 'no payload'}))
    config = {
        'enabled': True,
        'point_a': 12.0,
        'diff_a': 5.0,
        'trigger_s': 20,
        'diff_trigger_s': 20,
        'warning_s': 180,
    }
    parse_exposition(monitor.format_ocp_prometheus(config, None, 'MPG Ai1300TS'))
    parse_exposition(monitor.format_multirail_prometheus(True, 'MEG Ai1300P'))


def test_the_parser_rejects_the_old_space_before_empty_braces():
    with pytest.raises(ExpositionError):
        parse_exposition('msi_psu_up {} 1')


def test_the_parser_rejects_duplicate_series_and_bad_values():
    with pytest_raises(ExpositionError):
        parse_exposition('# HELP msi_psu_up x\n# TYPE msi_psu_up gauge\nmsi_psu_up 1\nmsi_psu_up 1')
    with pytest_raises(ExpositionError):
        parse_exposition('# HELP msi_psu_up x\n# TYPE msi_psu_up gauge\nmsi_psu_up nope')


def pytest_raises(exc_type):
    class _Context:
        def __enter__(self):
            return self

        def __exit__(self, exc_type_, exc, tb):
            if exc is None:
                raise AssertionError(f'{exc_type.__name__} was not raised')
            return isinstance(exc, exc_type)

    return _Context()
