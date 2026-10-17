"""Render rule formulas as typeset math, from the same syntax tree the evaluator runs.

Each derivation has three lines an engineer can check on paper:

    symbolic      I_trip = I_rated * k_trip
    substituted   = 12.5 A x 1.2
    result        = 15 A

The renderer also recomputes the value while it walks the tree; a test asserts
that this value equals the evaluator's, so the math shown is the math run.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass

from calgen.expr import Quantity, dotted_name, parse
from calgen.units import format_dim

_PREC = {ast.Add: 1, ast.Sub: 1, ast.Mult: 2, ast.Div: 2, ast.Pow: 4}

UNIT_TEX = {"ohm": r"\Omega", "mohm": r"\mathrm{m}\Omega", "kohm": r"\mathrm{k}\Omega", "Mohm": r"\mathrm{M}\Omega", "%": r"\%", "1": "", "ratio": "", "counts": ""}


def unit_tex(unit: str | None) -> str:
    if not unit:
        return ""
    if unit in UNIT_TEX:
        return UNIT_TEX[unit]
    return r"\text{" + unit.replace("%", r"\%") + "}"


def number_tex(x: float) -> str:
    if x != 0 and (abs(x) >= 1e6 or abs(x) < 1e-3):
        mant, exp = f"{x:.4e}".split("e")
        return rf"{float(mant):g} \times 10^{{{int(exp)}}}"
    text = f"{x:.6g}"
    return text


def default_symbol(name: str) -> str:
    base = name.split(".")[-1].replace("_", r"\_")
    return r"\mathit{" + base + "}"


@dataclass
class Rendered:
    symbolic: str
    substituted: str
    value: float  # recomputed during rendering, must equal the evaluator's


def render(formula: str, symbols: dict[str, str], values: dict[str, Quantity], units: dict[str, str]) -> Rendered:
    """symbols: name -> LaTeX symbol; values: name -> SI quantity; units: name -> display unit."""
    tree = parse(formula).tree

    def sym(node: ast.expr, prec: int = 0) -> str:
        return _walk(node, prec, lambda n: symbols.get(n, default_symbol(n)))[0]

    def sub(node: ast.expr, prec: int = 0) -> tuple[str, float]:
        return _walk(node, prec, lambda n: _value_tex(n, values, units), values)

    s, v = sub(tree)
    return Rendered(sym(tree), s, v)


def _value_tex(name: str, values: dict[str, Quantity], units: dict[str, str]) -> str:
    from calgen.units import from_si

    q = values[name]
    unit = units.get(name) or format_dim(q.dim)
    shown = from_si(q.value, unit) if unit not in ("1", "") else q.value
    u = unit_tex(unit)
    return number_tex(shown) + (r"\,\mathrm{" + u + "}" if u and not u.startswith("\\") and not u.startswith("\\text") else (r"\," + u if u else ""))


def _walk(node: ast.expr, parent_prec: int, leaf, values: dict[str, Quantity] | None = None) -> tuple[str, float]:
    """Return (LaTeX, value). Value is NaN when values are not supplied."""
    nan = math.nan

    def val(name: str) -> float:
        return values[name].value if values is not None else nan

    if isinstance(node, ast.Constant):
        return number_tex(float(node.value)), float(node.value)
    name = dotted_name(node)
    if name is not None:
        return leaf(name), val(name)
    if isinstance(node, ast.UnaryOp):
        t, v = _walk(node.operand, 3, leaf, values)
        return ("-" + t, -v) if isinstance(node.op, ast.USub) else (t, v)
    if isinstance(node, ast.BinOp):
        op = type(node.op)
        prec = _PREC[op]
        if op is ast.Div:
            a, va = _walk(node.left, 0, leaf, values)
            b, vb = _walk(node.right, 0, leaf, values)
            return rf"\frac{{{a}}}{{{b}}}", va / vb
        if op is ast.Pow:
            a, va = _walk(node.left, prec + 1, leaf, values)
            n = node.right.value
            return f"{{{a}}}^{{{n}}}", va**n
        a, va = _walk(node.left, prec, leaf, values)
        b, vb = _walk(node.right, prec + (op is ast.Sub), leaf, values)
        if op is ast.Mult:
            text, v = rf"{a} \cdot {b}", va * vb
        elif op is ast.Add:
            text, v = f"{a} + {b}", va + vb
        else:
            text, v = f"{a} - {b}", va - vb
        if prec < parent_prec:
            text = rf"\left({text}\right)"
        return text, v
    if isinstance(node, ast.Call):
        fn = node.func.id
        parts = [_walk(a, 0, leaf, values) for a in node.args]
        texts = [p[0] for p in parts]
        vals = [p[1] for p in parts]
        if fn == "sqrt":
            return rf"\sqrt{{{texts[0]}}}", math.sqrt(vals[0]) if vals[0] == vals[0] else nan
        if fn == "ceil":
            return rf"\left\lceil {texts[0]} \right\rceil", float(math.ceil(vals[0])) if vals[0] == vals[0] else nan
        if fn == "floor":
            return rf"\left\lfloor {texts[0]} \right\rfloor", float(math.floor(vals[0])) if vals[0] == vals[0] else nan
        if fn == "abs":
            return rf"\left| {texts[0]} \right|", abs(vals[0])
        if fn == "round":
            return rf"\operatorname{{round}}\!\left({texts[0]}\right)", float(round(vals[0])) if vals[0] == vals[0] else nan
        pick = min if fn == "min" else max
        return rf"\{fn}\left({', '.join(texts)}\right)", pick(vals)
    raise ValueError(f"cannot render {ast.dump(node)}")  # pragma: no cover - parse() already validated
