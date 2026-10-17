import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from calgen.formats import FormatError, encode, float32_literal, int_range, resolution, to_float32


def test_uint_round_half_even():
    assert encode(3722.5, "uint16").code == 3722
    assert encode(3723.5, "uint16").code == 3724
    assert encode(3722.727, "uint16").literal == "3723u"


def test_uint_overflow_is_an_error_not_saturation():
    with pytest.raises(FormatError, match="out of range"):
        encode(70000, "uint16")
    with pytest.raises(FormatError):
        encode(-1, "uint32")


def test_signed_int_literal():
    assert encode(-5, "int16").literal == "-5"


def test_iq24():
    e = encode(15.0, "iq24")
    assert e.code == 15 * (1 << 24)
    assert e.literal == f"{15 * (1 << 24)}L"
    assert e.stored == 15.0


def test_iq24_overflow():
    # IQ24 covers [-128, 128)
    with pytest.raises(FormatError):
        encode(128.0, "iq24")
    assert encode(127.99999, "iq24").code < (1 << 31)


def test_q15_resolution():
    assert resolution("q0.15") == pytest.approx(1 / 32768)
    with pytest.raises(FormatError):
        encode(1.0, "q0.15")


def test_float32_literal_round_trips_and_is_short():
    assert float32_literal(15.0) == "15.0f"
    assert float32_literal(12.5) == "12.5f"
    assert float32_literal(0.1) == "0.1f"
    assert float32_literal(1e-7).endswith("f")


def test_nan_rejected():
    with pytest.raises(FormatError):
        encode(math.nan, "float32")


@pytest.mark.parametrize("bad", ["float64", "iq0", "iq31", "q20.20", "uint12", "int"])
def test_bad_formats(bad):
    with pytest.raises(FormatError):
        encode(1.0, bad)


@given(st.floats(min_value=-127.0, max_value=127.0, allow_nan=False))
def test_iq24_error_within_half_lsb(x):
    e = encode(x, "iq24")
    assert e.abs_error <= 0.5 / (1 << 24) + 1e-15


@given(st.integers(min_value=0, max_value=65535))
def test_uint16_exact_for_integers(n):
    e = encode(float(n), "uint16")
    assert e.code == n and e.abs_error == 0


@given(st.floats(min_value=-1e30, max_value=1e30, allow_nan=False, allow_infinity=False))
def test_float32_literal_parses_back_to_stored(x):
    e = encode(x, "float32")
    assert to_float32(float(e.literal[:-1])) == e.stored


@given(st.sampled_from(["int8", "int16", "int32", "uint8", "uint16", "uint32"]))
def test_int_range_edges_encode(fmt):
    bits = int(fmt.replace("u", "").replace("int", ""))
    lo, hi = int_range(bits, not fmt.startswith("u"))
    assert encode(lo, fmt).code == lo
    assert encode(hi, fmt).code == hi
    with pytest.raises(FormatError):
        encode(hi + 1, fmt)
