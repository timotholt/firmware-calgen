"""Physical units as dimension vectors over volts, amperes, and seconds.

Every quantity in calgen carries a dimension so that formulas which mix
incompatible quantities (volts + amps) fail instead of producing a number.
Three base dimensions are enough for converter firmware constants:

    V (volt), A (ampere), s (second)

Derived units map onto them: W = VA = V*A, ohm = V/A, Hz = 1/s, and
counts / ratio / percent are dimensionless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class UnitError(ValueError):
    """A unit string is malformed or dimensions are incompatible."""


@dataclass(frozen=True)
class Dim:
    """Integer exponents of (V, A, s)."""

    v: int = 0
    a: int = 0
    s: int = 0

    def __mul__(self, other: Dim) -> Dim:
        return Dim(self.v + other.v, self.a + other.a, self.s + other.s)

    def __truediv__(self, other: Dim) -> Dim:
        return Dim(self.v - other.v, self.a - other.a, self.s - other.s)

    def __pow__(self, n: int) -> Dim:
        return Dim(self.v * n, self.a * n, self.s * n)

    @property
    def dimensionless(self) -> bool:
        return self == DIMENSIONLESS

    def __str__(self) -> str:
        return format_dim(self)


DIMENSIONLESS = Dim()

# symbol -> (scale to SI, dimension)
_UNITS: dict[str, tuple[float, Dim]] = {
    "1": (1.0, DIMENSIONLESS),
    "ratio": (1.0, DIMENSIONLESS),
    "counts": (1.0, DIMENSIONLESS),
    "cells": (1.0, DIMENSIONLESS),
    "%": (0.01, DIMENSIONLESS),
    "V": (1.0, Dim(v=1)),
    "A": (1.0, Dim(a=1)),
    "s": (1.0, Dim(s=1)),
    "W": (1.0, Dim(v=1, a=1)),
    "VA": (1.0, Dim(v=1, a=1)),
    "ohm": (1.0, Dim(v=1, a=-1)),
    "Hz": (1.0, Dim(s=-1)),
    "Ah": (3600.0, Dim(a=1, s=1)),
    "min": (60.0, Dim(s=1)),
    "h": (3600.0, Dim(s=1)),
}

_PREFIXES: dict[str, float] = {"G": 1e9, "M": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9}

_TOKEN = re.compile(r"^(?P<sym>[A-Za-z%]+|1)(?:\^(?P<exp>-?\d+))?$")


def _lookup(symbol: str) -> tuple[float, Dim]:
    if symbol in _UNITS:
        return _UNITS[symbol]
    prefix, rest = symbol[:1], symbol[1:]
    if prefix in _PREFIXES and rest in _UNITS and rest not in ("1", "ratio", "counts", "%"):
        scale, dim = _UNITS[rest]
        return _PREFIXES[prefix] * scale, dim
    raise UnitError(f"unknown unit {symbol!r}")


def parse_unit(text: str) -> tuple[float, Dim]:
    """Parse a unit string like ``V``, ``mohm``, ``V/A``, ``A*s``, ``1/s``, ``V^2/W``.

    Returns (scale to SI, dimension).
    """
    text = text.strip()
    if not text:
        raise UnitError("empty unit")
    scale, dim = 1.0, DIMENSIONLESS
    # split into numerator/denominator factors, keeping the operator
    parts = re.split(r"([*/])", text.replace(" ", ""))
    op = "*"
    for part in parts:
        if part in ("*", "/"):
            op = part
            continue
        m = _TOKEN.match(part)
        if not m:
            raise UnitError(f"bad unit factor {part!r} in {text!r}")
        s, d = _lookup(m.group("sym"))
        exp = int(m.group("exp") or 1)
        s, d = s**exp, d**exp
        if op == "*":
            scale, dim = scale * s, dim * d
        else:
            scale, dim = scale / s, dim / d
    return scale, dim


def dim_of(text: str) -> Dim:
    return parse_unit(text)[1]


def to_si(value: float, unit: str) -> float:
    return value * parse_unit(unit)[0]


def from_si(value: float, unit: str) -> float:
    return value / parse_unit(unit)[0]


_NAMES: dict[Dim, str] = {
    DIMENSIONLESS: "1",
    Dim(v=1): "V",
    Dim(a=1): "A",
    Dim(s=1): "s",
    Dim(v=1, a=1): "W",
    Dim(v=1, a=-1): "ohm",
    Dim(a=1, v=-1): "1/ohm",
    Dim(s=-1): "Hz",
    Dim(a=1, s=1): "A*s",
}


def format_dim(dim: Dim) -> str:
    if dim in _NAMES:
        return _NAMES[dim]
    num, den = [], []
    for sym, exp in (("V", dim.v), ("A", dim.a), ("s", dim.s)):
        if exp > 0:
            num.append(sym if exp == 1 else f"{sym}^{exp}")
        elif exp < 0:
            den.append(sym if exp == -1 else f"{sym}^{-exp}")
    top = "*".join(num) or "1"
    return top if not den else f"{top}/{'*'.join(den)}"


def check_compatible(expected: str, actual: Dim, context: str) -> None:
    want = dim_of(expected)
    if want != actual:
        raise UnitError(f"{context}: expected {expected} ({format_dim(want)}), got {format_dim(actual)}")
