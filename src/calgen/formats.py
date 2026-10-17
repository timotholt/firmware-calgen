"""Number formats a firmware constant can be stored in.

Supported formats:

* ``float32``            IEEE-754 single precision (C ``float``)
* ``uint8|16|32``        unsigned integer register value
* ``int8|16|32``         signed integer
* ``iqN``                TI IQmath-style signed 32-bit fixed point, N fractional bits (1..30)
* ``qM.N``               signed fixed point with M integer and N fractional bits (1 + M + N <= 32)

Rounding is round-half-to-even everywhere (Python's ``round``), stated in
every report. Values that don't fit raise ``FormatError`` — calgen never
saturates silently.
"""

from __future__ import annotations

import math
import re
import struct
from decimal import Decimal
from dataclasses import dataclass

ROUNDING = "round-half-to-even"
FLOAT32_MAX = 3.4028234663852886e38


class FormatError(ValueError):
    """The value cannot be represented in the requested format."""


@dataclass(frozen=True)
class Encoded:
    fmt: str
    requested: float
    stored: float  # the value firmware will actually see, in the same unit
    code: int | None  # integer bit pattern for integer / fixed-point formats
    literal: str  # C literal, e.g. "15.0f", "3723u", "251658240L"

    @property
    def abs_error(self) -> float:
        return abs(self.stored - self.requested)

    @property
    def rel_error(self) -> float:
        if self.requested == 0:
            return 0.0 if self.stored == 0 else math.inf
        return self.abs_error / abs(self.requested)


_INT = re.compile(r"^(u?)int(8|16|32)$")
_IQ = re.compile(r"^iq(\d+)$")
_Q = re.compile(r"^q(\d+)\.(\d+)$")


def is_valid_format(fmt: str) -> bool:
    try:
        _spec(fmt)
    except FormatError:
        return False
    return True


def _spec(fmt: str) -> tuple[str, int, int, bool]:
    """Return (kind, total_bits, frac_bits, signed)."""
    if fmt == "float32":
        return ("float", 32, 0, True)
    if m := _INT.match(fmt):
        return ("int", int(m.group(2)), 0, m.group(1) != "u")
    if m := _IQ.match(fmt):
        n = int(m.group(1))
        if not 1 <= n <= 30:
            raise FormatError(f"{fmt}: IQ fractional bits must be 1..30")
        return ("fixed", 32, n, True)
    if m := _Q.match(fmt):
        i, n = int(m.group(1)), int(m.group(2))
        if 1 + i + n > 32 or n < 1:
            raise FormatError(f"{fmt}: needs 1 + M + N <= 32 and N >= 1")
        return ("fixed", 1 + i + n, n, True)
    raise FormatError(f"unknown format {fmt!r}")


def int_range(bits: int, signed: bool) -> tuple[int, int]:
    if signed:
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


def to_float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def float32_literal(value: float) -> str:
    """Shortest decimal literal that round-trips to the same float32."""
    f32 = to_float32(value)
    for digits in range(1, 10):
        text = f"{f32:.{digits}g}"
        if to_float32(float(text)) == f32:
            break
    if f32 == 0 or 1e-4 <= abs(f32) < 1e7:
        text = format(Decimal(text), "f")  # positional: 210 not 2.1e+02
    if "e" not in text and "." not in text:
        text += ".0"
    return text + "f"


def encode(value: float, fmt: str) -> Encoded:
    if math.isnan(value) or math.isinf(value):
        raise FormatError(f"{fmt}: value is {value}")
    kind, bits, frac, signed = _spec(fmt)
    if kind == "float":
        if abs(value) > FLOAT32_MAX:
            raise FormatError(f"float32: {value:g} exceeds float range")
        stored = to_float32(value)
        return Encoded(fmt, value, stored, None, float32_literal(value))
    scaled = value * (1 << frac)
    code = round(scaled)
    lo, hi = int_range(bits, signed)
    if not lo <= code <= hi:
        lo_v, hi_v = lo / (1 << frac), hi / (1 << frac)
        raise FormatError(f"{fmt}: {value:g} out of range [{lo_v:g}, {hi_v:g}]")
    stored = code / (1 << frac)
    if kind == "int":
        literal = f"{code}u" if not signed else str(code)
    else:
        literal = f"{code}L"
    return Encoded(fmt, value, stored, code, literal)


def resolution(fmt: str) -> float:
    """Smallest representable step (LSB) for the format; 0 for float32 (relative)."""
    kind, _, frac, _ = _spec(fmt)
    if kind == "float":
        return 0.0
    return 1.0 / (1 << frac)
