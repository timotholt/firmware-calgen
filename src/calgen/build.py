"""Evaluate rules against a variant: every constant, every check, with provenance.

``build()`` never raises for engineering problems (out of range, overflow,
failed check, missing input). It records them in the result so the report can
show all of them at once. Code generation then refuses to write anything if
``Build.ok`` is false (fail closed).
"""

from __future__ import annotations

import hashlib
import operator
from dataclasses import dataclass, field

from calgen.expr import ExprError, Formula, Quantity, evaluate, parse
from calgen.formats import Encoded, FormatError, encode
from calgen.spec import Check, Param, Rule, Rules, Variant
from calgen.units import UnitError, check_compatible, format_dim, from_si, parse_unit

OK, FAIL, SKIPPED = "ok", "fail", "skipped"

@dataclass
class Source:
    """One input a constant depends on, and where it came from."""

    name: str
    value: Quantity | str
    unit: str | None
    origin: str  # e.g. 'DS-10507 Rev.101119 p2', 'board ups_ctrl_revA.yaml', 'constant'
    quote: str = ""  # verbatim data sheet text when applicable
    override: bool = False

@dataclass
class ConstResult:
    rule: Rule
    status: str
    value: float | None = None  # in the rule's unit (before encoding)
    encoded: Encoded | None = None
    enum_ident: str | None = None
    fmt: str | None = None
    sources: list[Source] = field(default_factory=list)
    message: str = ""

@dataclass
class CheckResult:
    check: Check
    status: str
    lhs: float | None = None
    rhs: float | None = None
    unit: str | None = None
    message: str = ""

@dataclass
class Build:
    variant: Variant
    rules: Rules
    constants: list[ConstResult]
    checks: list[CheckResult]
    digest: str

    @property
    def failures(self) -> list[str]:
        out = [f"{c.rule.symbol}: {c.message}" for c in self.constants if c.status == FAIL]
        out += [f"check {c.check.id}: {c.message}" for c in self.checks if c.status == FAIL]
        return out

    @property
    def ok(self) -> bool:
        return not self.failures

    def constant(self, rule_id: str) -> ConstResult:
        return next(c for c in self.constants if c.rule.id == rule_id)

_OPS = {"<=": operator.le, "<": operator.lt, ">=": operator.ge, ">": operator.gt, "==": operator.eq}

def _symbols(variant: Variant) -> tuple[dict[str, Quantity], dict[str, str], dict[str, Source]]:
    numeric: dict[str, Quantity] = {}
    text: dict[str, str] = {}
    sources: dict[str, Source] = {}

    def add(prefix: str, p: Param, origin: str, quote: str = "", override: bool = False) -> None:
        name = f"{prefix}.{p.name}"
        if p.numeric:
            q = p.quantity()
            numeric[name] = q
            sources[name] = Source(name, q, p.unit, origin, quote, override)
        elif isinstance(p.value, str) and p.value:
            text[name] = p.value
            sources[name] = Source(name, p.value, None, origin, quote, override)

    for p in variant.datasheet.params.values():
        add("ds", p, p.source, p.raw)
    for p in variant.overrides.values():
        numeric.pop(f"ds.{p.name}", None)
        text.pop(f"ds.{p.name}", None)
        add("ds", p, p.source, override=True)
    for kind, ps in (("board", variant.board), ("target", variant.target), ("design", variant.design)):
        for p in ps.params.values():
            add(kind, p, f"{kind} {ps.path.name}", p.note)
    return numeric, text, sources

def _resolve_format(rule: Rule, variant: Variant) -> str:
    if rule.format == "target":
        return str(variant.target.extra.get("default_format", "float32"))
    return rule.format

def build(variant: Variant, rules: Rules) -> Build:
    env, text, sources = _symbols(variant)
    results: list[ConstResult] = []
    failed_ids: set[str] = set()

    for rule in rules.constants:
        if rule.kind == "enum":
            results.append(_enum(rule, text, sources))
            continue
        formula = parse(rule.formula)
        deps = [sources.get(n) or Source(n, env[n], None, "constant") for n in formula.names if n in env]
        missing = [n for n in formula.names if n not in env]
        if missing:
            failed = [n for n in missing if n in failed_ids]
            if failed:
                msg = f"depends on failed constant {', '.join(failed)}"
                results.append(ConstResult(rule, FAIL, sources=deps, message=msg))
                failed_ids.add(rule.id)
                continue
            status = SKIPPED if rule.optional else FAIL
            why = "not in data sheet" if all(n.startswith("ds.") for n in missing) else "undefined"
            results.append(ConstResult(rule, status, sources=deps, message=f"input {', '.join(missing)} {why}"))
            if status == FAIL:
                failed_ids.add(rule.id)
            continue
        results.append(_numeric(rule, formula, env, deps, variant))
        r = results[-1]
        if r.status == FAIL:
            failed_ids.add(rule.id)
        if r.status == OK:
            # later rules see the value the firmware will actually hold
            scale, dim = parse_unit(rule.unit)
            env[rule.id] = Quantity(r.encoded.stored * scale, dim)
            sources[rule.id] = Source(rule.id, env[rule.id], rule.unit, "constant")

    checks = [_check(c, env) for c in rules.checks]
    h = hashlib.sha256(variant.digest().encode())
    h.update(rules.path.read_bytes())
    return Build(variant, rules, results, checks, h.hexdigest())

def _enum(rule: Rule, text: dict[str, str], sources: dict[str, Source]) -> ConstResult:
    src = sources.get(rule.formula)
    deps = [src] if src else []
    if rule.formula not in text:
        status = SKIPPED if rule.optional else FAIL
        return ConstResult(rule, status, sources=deps, message=f"input {rule.formula} not in data sheet")
    raw = text[rule.formula].strip().lower()
    ident = rule.choices.get(raw)
    if ident is None:
        return ConstResult(
            rule, FAIL, sources=deps, message=f"{rule.formula} = {raw!r}; expected one of {sorted(rule.choices)}"
        )
    return ConstResult(rule, OK, enum_ident=ident, fmt="enum", sources=deps)

def _numeric(rule: Rule, formula: Formula, env: dict[str, Quantity], deps: list[Source], variant: Variant) -> ConstResult:
    fmt = _resolve_format(rule, variant)
    try:
        q = evaluate(formula, env)
        check_compatible(rule.unit, q.dim, rule.symbol)
    except (ExprError, UnitError) as exc:
        return ConstResult(rule, FAIL, fmt=fmt, sources=deps, message=str(exc))
    value = from_si(q.value, rule.unit)
    result = ConstResult(rule, OK, value=value, fmt=fmt, sources=deps)
    if rule.min is not None and value < rule.min:
        result.status, result.message = FAIL, f"{value:g} {rule.unit} below rule minimum {rule.min:g}"
        return result
    if rule.max is not None and value > rule.max:
        result.status, result.message = FAIL, f"{value:g} {rule.unit} above rule maximum {rule.max:g}"
        return result
    try:
        result.encoded = encode(value, fmt)
    except FormatError as exc:
        result.status, result.message = FAIL, str(exc)
        return result
    if rule.tolerance is not None and result.encoded.rel_error > rule.tolerance:
        result.status = FAIL
        result.message = f"quantization error {result.encoded.rel_error:.3g} exceeds tolerance {rule.tolerance:g}"
    return result

def _check(check: Check, env: dict[str, Quantity]) -> CheckResult:
    try:
        lhs, rhs = evaluate(parse(check.lhs), env), evaluate(parse(check.rhs), env)
    except ExprError as exc:
        if "unknown name" in str(exc):
            name = str(exc).split("'")[1]
            return CheckResult(check, SKIPPED, message=f"not applicable: {name} not generated for this product")
        return CheckResult(check, FAIL, message=str(exc))
    if lhs.dim != rhs.dim:
        return CheckResult(check, FAIL, message=f"compares different units ({lhs} vs {rhs})")

    unit = format_dim(lhs.dim)
    passed = _OPS[check.op](lhs.value, rhs.value)
    shown = f"{lhs.value:.6g} {check.op} {rhs.value:.6g}" + ("" if unit == "1" else f" {unit}")
    msg = "" if passed else f"{shown} is false: {check.describe}"
    return CheckResult(check, OK if passed else FAIL, lhs.value, rhs.value, unit, msg)
