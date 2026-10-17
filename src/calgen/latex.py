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
        return _walk(node, prec, lambda n: _value_tex(n, values, units) if n in values else symbols.get(n, default_symbol(n)), values)

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
        return values[name].value if values is not None and name in values else nan

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


# --- derivations for reports ------------------------------------------------

_OP_TEX = {"<=": r"\le", "<": "<", ">=": r"\ge", ">": ">", "==": "="}


@dataclass
class Derivation:
    """Typeset equations for one constant or check, plus its numeric result."""

    lines: list[str]  # LaTeX display equations, top to bottom
    value: float | None  # recomputed while rendering (None for enums)


def _symbols_for(build) -> dict[str, str]:
    syms = dict(build.rules.symbols)
    for r in build.rules.constants:
        syms[r.id] = r.latex
    return syms


def _quantity_tex(value: float, unit: str) -> str:
    u = unit_tex(unit)
    num = number_tex(value)
    if not u:
        return num
    return num + r"\," + (u if u.startswith("\\") else r"\mathrm{" + u + "}")


def _tex_escape(s: str) -> str:
    """Escape characters that are special inside \\text{} (KaTeX shows a red error otherwise)."""
    return "".join({"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%", "&": r"\&", "#": r"\#",
                    "$": r"\$", "{": r"\{", "}": r"\}"}.get(ch, ch) for ch in s)


def derive_constant(build, rule_id: str) -> Derivation:
    from calgen.units import from_si

    c = build.constant(rule_id)
    r = c.rule
    if r.kind == "enum":
        src = c.sources[0].value if c.sources else "?"
        sym, ident, src = (_tex_escape(str(x)) for x in (r.symbol, c.enum_ident or "n/a", src))
        return Derivation([rf"\texttt{{{sym}}} = \texttt{{{ident}}} \quad (\text{{data sheet: {src}}})"], None)
    if c.status != "ok" and c.value is None:
        return _symbolic_only(build, r)  # could not be computed at all
    rd = render(r.formula, _symbols_for(build), build.env, build.units)
    value = from_si(rd.value, r.unit)  # computed, possibly failed to encode or out of range
    tree = parse(r.formula).tree
    head = rf"{r.latex} = {rd.symbolic}"
    if r.supplied:
        return Derivation([rf"{r.latex} = {_quantity_tex(value, r.unit)} \quad (\text{{engineer-supplied}})"], value)
    if isinstance(tree, ast.Call) and tree.func.id == "round":
        inner = render(ast.unparse(tree.args[0]), _symbols_for(build), build.env, build.units)
        inner_v = from_si(inner.value, r.unit)
        lines = [head, rf"= \operatorname{{round}}\!\left({inner.substituted}\right)", rf"= \operatorname{{round}}({number_tex(round(inner_v, 4))}) = {_quantity_tex(value, r.unit)}"]
    elif rd.substituted == rd.symbolic or dotted_name(tree) is not None:
        lines = [rf"{head} = {_quantity_tex(value, r.unit)}"]
    else:
        lines = [head, rf"= {rd.substituted}", rf"= {_quantity_tex(value, r.unit)}"]
    return Derivation(lines, value)


def _symbolic_only(build, r) -> Derivation:
    """Formula without numbers, for constants that could not be computed."""
    syms = _symbols_for(build)
    tree = parse(r.formula).tree
    sym = _walk(tree, 0, lambda n: syms.get(n, default_symbol(n)))[0]
    return Derivation([rf"{r.latex} = {sym}"], None)


def derive_check(build, check_id: str) -> Derivation:
    k = next(x for x in build.checks if x.check.id == check_id)
    syms = _symbols_for(build)
    op = _OP_TEX[k.check.op]
    lhs_s = _walk(parse(k.check.lhs).tree, 0, lambda n: syms.get(n, default_symbol(n)))[0]
    rhs_s = _walk(parse(k.check.rhs).tree, 0, lambda n: syms.get(n, default_symbol(n)))[0]
    if k.status == "skipped" or k.lhs is None:
        return Derivation([rf"{lhs_s} {op} {rhs_s} \quad (\text{{not applicable}})"], None)
    unit = k.unit if k.unit not in (None, "1") else ""
    mark = r"\quad \checkmark" if k.status == "ok" else r"\quad \color{#c0392b}{\times}"
    return Derivation(
        [rf"{lhs_s} {op} {rhs_s}", rf"\Rightarrow {_quantity_tex(k.lhs, unit)} {op} {_quantity_tex(k.rhs, unit)}{mark}"],
        k.lhs,
    )
