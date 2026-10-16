"""Unit tests for SMBus LINEAR11 decoding (protocol.lin11_to_int).

Vectors are built as raw = (exp & 0x1F) << 11 | (mantissa & 0x7FF) and
checked against integer-exact expectations. Exponent is 5-bit two's
complement (positive range 0..15); mantissa is 11-bit two's complement
(positive range 0..1023). Each vector mirrors a real call-site pattern
from MSIPSU.get_sensors(), including its scale, rounding and unit.
"""

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
