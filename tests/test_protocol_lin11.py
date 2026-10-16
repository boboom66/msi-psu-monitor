"""Unit tests for SMBus LINEAR11 decoding (protocol.lin11_to_int).

Vectors are built as raw = (exp & 0x1F) << 11 | (mantissa & 0x7FF) and
checked against integer-exact expectations. Exponent is 5-bit two's
complement (range -16..15); mantissa is 11-bit **unsigned** (range 0..2047),
exactly as MSI's ``ValueCalc`` decodes it (``CPSU.cs:1248``) and as REV6
specifies. Each vector mirrors a real call-site pattern from
MSIPSU.get_sensors(), including its scale, rounding and unit.
"""

import pytest

from msi_psu_monitor.protocol import lin11_to_int


def enc(mantissa, exp):
    return ((exp & 0x1F) << 11) | (mantissa & 0x7FF)


def test_zero():
    assert lin11_to_int(0x0000, 1000, True) == 0


def test_voltage_12v():
    # 96 * 2^-3 = 12 V -> 12000 mV -> 12.000 V (round(/1000, 3))
    raw = enc(96, -3)
    assert raw == 0xE860
    assert lin11_to_int(raw, 1000, True) == 12000
    assert round(lin11_to_int(raw, 1000, True) / 1000, 3) == 12.0


def test_current_12v_total():
    # 860 * 2^-4 = 53.75 A -> 53750 mA
    assert lin11_to_int(enc(860, -4), 1000, True) == 53750


def test_negative_exponent():
    # 500 * 2^-1 = 250 (m units); exercises exponent sign extension
    assert lin11_to_int(enc(500, -1), 1000, True) == 250000


def test_negative_temperature():
    # -8 * 2^-3 = -1.0 C -> -1000 mC; exercises mantissa sign extension
    assert lin11_to_int(enc(-8, -3), 1000, True) == -1000


def test_efficiency():
    # 755 * 2^-3 = 94.375 % -> 9437 (x100) -> 94.37 % (round(/100, 2))
    raw = enc(755, -3)
    assert raw == 0xEAF3
    assert lin11_to_int(raw, 100, True) == 9437
    assert round(lin11_to_int(raw, 100, True) / 100, 2) == 94.37


def test_power():
    # 165 * 2^2 = 660 W -> 660000000 uW -> 660.0 W (round(/1e6, 1))
    raw = enc(165, 2)
    assert raw == 0x10A5
    assert lin11_to_int(raw, 1000000, True) == 660000000
    assert round(lin11_to_int(raw, 1000000, True) / 1000000, 1) == 660.0


def test_fan_unsigned_vs_signed():
    # 1025 * 2^1 = 2050 RPM unsigned; the same bits are negative signed
    # (mantissa bit 0x400 set -> 1025 - 2048 = -1023, *2 = -2046)
    assert lin11_to_int(enc(1025, 1), 1, False) == 2050
    assert lin11_to_int(enc(1025, 1), 1, True) == -2046


def test_defaults_match_voltage_call_pattern():
    assert lin11_to_int(0xE860) == 12000


def _value_calc(low, high):
    """Transcription of MSI's ``ValueCalc`` (``CPSU.cs:1248``), int32 and all."""
    shifted = (high << 24) & 0xFFFFFFFF  # C# int32 overflow, kept explicit
    if shifted & 0x80000000:
        shifted -= 1 << 32
    exponent = shifted >> 27  # arithmetic shift = sign-extended 5-bit exponent
    mantissa = ((high & 7) << 8) + low  # never sign-extended
    return mantissa * 2**exponent


@pytest.mark.parametrize('raw', [0x0000, 0xE860, 0xEAF3, 0x10A5, 0xFFFF, 0x07FF, 0x87FF, 0x7C00])
def test_every_word_agrees_with_msi_value_calc(raw):
    """The reference decoder, reimplemented from the C# — unsigned mantissa.

    Scaled to 2^16 so the integer shifts stay exact: the function returns scaled
    integers, so comparing at 1000 would only measure truncation.
    """
    low, high = raw & 0xFF, raw >> 8
    scale = 1 << 16
    assert lin11_to_int(raw, scale) / scale == _value_calc(low, high)


def test_default_mantissa_is_unsigned_not_twos_complement():
    """A mantissa with bit 0x400 set must stay a large positive number.

    Reading it as two's complement would turn a fan's 2050 RPM into -2046 and a
    near-full-scale power reading into a nonsensical negative.
    """
    assert lin11_to_int(enc(1025, 1), 1) == 2050
    assert lin11_to_int(enc(2047, 0), 1) == 2047
