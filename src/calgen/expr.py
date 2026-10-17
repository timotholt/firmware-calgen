"""Restricted formula evaluator with dimension checking.

Formulas in rules.yaml are Python-syntax arithmetic, parsed with ``ast`` and
evaluated by walking a whitelist of node types. Nothing is ever passed to
``eval``. Names may be dotted (``ds.power_va``, ``board.r_shunt``) and resolve
against a flat symbol table of ``Quantity`` values.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass

from calgen.units import DIMENSIONLESS, Dim, UnitError, format_dim


class ExprError(ValueError):
    """A formula is malformed, uses a forbidden construct, or references an unknown name."""


@dataclass(frozen=True)
class Quantity:
    """A value in SI units with its dimension."""

    value: float
    dim: Dim = DIMENSIONLESS

    def __str__(self) -> str:
        return f"{self.value:g} {format_dim(self.dim)}"


@dataclass(frozen=True)
class Formula:
    source: str
    tree: ast.expr
    names: tuple[str, ...]


_FUNCS_SAME_DIM = {"abs", "round", "ceil", "floor"}
_FUNCS_MULTI = {"min", "max"}
_ALLOWED_FUNCS = _FUNCS_SAME_DIM | _FUNCS_MULTI | {"sqrt"}


def dotted_name(node: ast.expr) -> str | None:
    """Return 'a.b.c' for Name/Attribute chains, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def parse(source: str) -> Formula:
    try:
        tree = ast.parse(source, mode="eval").body
    except SyntaxError as exc:
        raise ExprError(f"cannot parse formula {source!r}: {exc.msg}") from None
    names: list[str] = []
    _validate(tree, source, names)
    return Formula(source=source, tree=tree, names=tuple(dict.fromkeys(names)))


def _validate(node: ast.expr, source: str, names: list[str]) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(f"only numeric constants allowed in {source!r}")
        return
    name = dotted_name(node)
    if name is not None:
        names.append(name)
        return
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            raise ExprError(f"operator {type(node.op).__name__} not allowed in {source!r}")
        if isinstance(node.op, ast.Pow) and not (
            isinstance(node.right, ast.Constant) and isinstance(node.right.value, int)
        ):
            raise ExprError(f"exponent must be an integer literal in {source!r}")
        _validate(node.left, source, names)
        _validate(node.right, source, names)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        _validate(node.operand, source, names)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ExprError(f"function not allowed in {source!r}")
        if node.keywords or not node.args:
            raise ExprError(f"bad call to {node.func.id} in {source!r}")
        if node.func.id not in _FUNCS_MULTI and len(node.args) != 1:
            raise ExprError(f"{node.func.id} takes one argument in {source!r}")
        for arg in node.args:
            _validate(arg, source, names)
        return
    raise ExprError(f"construct {type(node).__name__} not allowed in {source!r}")


def evaluate(formula: Formula, env: dict[str, Quantity]) -> Quantity:
    return _eval(formula.tree, env, formula.source)


def _eval(node: ast.expr, env: dict[str, Quantity], src: str) -> Quantity:
    if isinstance(node, ast.Constant):
        return Quantity(float(node.value))
    name = dotted_name(node)
    if name is not None:
        if name not in env:
            raise ExprError(f"unknown name {name!r} in {src!r}")
        return env[name]
    if isinstance(node, ast.UnaryOp):
        q = _eval(node.operand, env, src)
        return Quantity(-q.value if isinstance(node.op, ast.USub) else q.value, q.dim)
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, env, src)
        if isinstance(node.op, ast.Pow):
            n = node.right.value  # validated integer literal
            return Quantity(left.value**n, left.dim**n)
        right = _eval(node.right, env, src)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if left.dim != right.dim:
                raise UnitError(
                    f"cannot {'add' if isinstance(node.op, ast.Add) else 'subtract'} "
                    f"{format_dim(left.dim)} and {format_dim(right.dim)} in {src!r}"
                )
            v = left.value + right.value if isinstance(node.op, ast.Add) else left.value - right.value
            return Quantity(v, left.dim)
        if isinstance(node.op, ast.Mult):
            return Quantity(left.value * right.value, left.dim * right.dim)
        if right.value == 0:
            raise ExprError(f"division by zero in {src!r}")
        return Quantity(left.value / right.value, left.dim / right.dim)
    if isinstance(node, ast.Call):
        fn = node.func.id
        args = [_eval(a, env, src) for a in node.args]
        if fn in _FUNCS_MULTI:
            dims = {a.dim for a in args}
            if len(dims) != 1:
                raise UnitError(f"{fn}() arguments have different units in {src!r}")
            pick = min if fn == "min" else max
            return Quantity(pick(a.value for a in args), args[0].dim)
        (a,) = args
        if fn == "sqrt":
            d = a.dim
            if d.v % 2 or d.a % 2 or d.s % 2:
                raise UnitError(f"sqrt of {format_dim(d)} is not a whole unit in {src!r}")
            if a.value < 0:
                raise ExprError(f"sqrt of negative value in {src!r}")
            return Quantity(math.sqrt(a.value), Dim(d.v // 2, d.a // 2, d.s // 2))
        op = {"abs": abs, "round": round, "ceil": math.ceil, "floor": math.floor}[fn]
        return Quantity(float(op(a.value)), a.dim)
    raise ExprError(f"construct {type(node).__name__} not allowed in {src!r}")  # pragma: no cover
