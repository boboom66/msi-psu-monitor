"""Unit tests for SMBus LINEAR11 decoding (protocol.lin11_to_int)."""

from msi_psu_monitor.protocol import lin11_to_int


def _encode(mantissa_u11, exponent_s5):
    """Pack 11-bit mantissa + 5-bit exponent into a u16 LINEAR11 word."""
    return ((exponent_s5 & 0x1F) << 11) | (mantissa_u11 & 0x7FF)


def test_zero():
    assert lin11_to_int(_encode(0, 0)) == 0


def test_positive_mantissa_no_shift():
    # mantissa=1000, exp=0, scale=1000 -> 1000*1000 = 1_000_000
    assert lin11_to_int(_encode(1000, 0)) == 1000 * 1000


def test_exponent_positive_shift():
    # mantissa=500, exp=+1 -> 500*1000 << 1
    assert lin11_to_int(_encode(500, 1)) == (500 * 1000) << 1


def test_exponent_negative_shift():
    # mantissa=1000, exp=-1 (0x1F) -> 1000*1000 >> 1
    assert lin11_to_int(_encode(1000, 0x1F)) == (1000 * 1000) >> 1


def test_negative_mantissa_signed():
    # mantissa -4 in 11-bit two's complement: 0x7FC; exp=0
    assert lin11_to_int(_encode(0x7FC, 0), signed=True) == -4 * 1000


def test_negative_mantissa_exponent_combo():
    # mantissa -8 (0x7F8), exp=-2 (0x1E) -> (-8*1000) >> 2
    assert lin11_to_int(_encode(0x7F8, 0x1E), signed=True) == (-8 * 1000) >> 2


def test_unsigned_mode_keeps_high_bit():
    # 0x400 with signed=True is -1024*1000; unsigned keeps +1024*1000
    assert lin11_to_int(_encode(0x400, 0), signed=True) == -1024 * 1000
    assert lin11_to_int(_encode(0x400, 0), signed=False) == 1024 * 1000


def test_fan_style_unsigned_scale_one():
    # fan path uses scale=1, signed=False
    assert lin11_to_int(_encode(536, 0), scale=1, signed=False) == 536
