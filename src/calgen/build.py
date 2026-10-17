"""Evaluate rules against a variant: every constant, every check, with provenance.

``build()`` never raises for engineering problems (out of range, overflow,
failed check, missing input). It records them in the result so the report can
show all of them at once. Code generation then refuses to write anything if
``Build.ok`` is false (fail closed).
"""

from __future__ import annotations

import hashlib
import operator
from dataclasses import dataclass, field, replace

from calgen.consistency import ERROR, Finding, check_datasheet
from calgen.expr import ExprError, Formula, Quantity, evaluate, parse
from calgen.formats import Encoded, FormatError, encode
from calgen.spec import Check, Param, Rule, Rules, Variant
from calgen.units import UnitError, check_compatible, format_dim, from_si, parse_unit, to_si

OK, FAIL, SKIPPED = "ok", "fail", "skipped"
BLOCKING, WAIVED, FLAGGED = "blocking", "waived", "flagged"

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
class DatasheetFinding:
    finding: Finding
    status: str  # blocking | waived | flagged
    note: str = ""


@dataclass
class StaleResult:
    """An engineer-supplied value checked against the inputs it was designed for."""

    param: str  # e.g. design.vloop_kp
    against: str  # e.g. design.f_sw
    designed: str  # e.g. "20 kHz"
    current: str  # e.g. "25 kHz"
    status: str
    message: str = ""


@dataclass
class Build:
    variant: Variant
    rules: Rules
    constants: list[ConstResult]
    checks: list[CheckResult]
    digest: str
    datasheet: list[DatasheetFinding] = field(default_factory=list)
    staleness: list[StaleResult] = field(default_factory=list)
    env: dict[str, Quantity] = field(default_factory=dict)  # every input and constant, SI
    units: dict[str, str] = field(default_factory=dict)  # display unit per name

    @property
    def failures(self) -> list[str]:
        out = [f"{c.rule.symbol}: {c.message}" for c in self.constants if c.status == FAIL]
        out += [f"check {c.check.id}: {c.message}" for c in self.checks if c.status == FAIL]
        out += [f"data sheet {', '.join(d.finding.fields)}: {d.finding.message}" for d in self.datasheet if d.status == BLOCKING]
        out += [f"stale {s.param}: {s.message}" for s in self.staleness if s.status == FAIL]
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
            add(kind, p, p.source, p.note)
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
        if rule.fallback and any(n.startswith("ds.") and n not in env for n in formula.names):
            alt = parse(rule.fallback)
            if all(n in env for n in alt.names):  # the sheet states this fact in the other form
                rule, formula = replace(rule, formula=rule.fallback, fallback=None), alt
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
    findings = _classify(check_datasheet(variant.datasheet), _consumed_ds_fields(rules), variant)
    stale = _staleness(variant, env)
    h = hashlib.sha256(variant.digest().encode())
    h.update(rules.path.read_bytes())
    units = {n: src.unit for n, src in sources.items() if src.unit}
    units.update({r.rule.id: r.rule.unit for r in results if r.status == OK and r.rule.kind == "numeric"})
    return Build(variant, rules, results, checks, h.hexdigest(), findings, stale, dict(env), units)


def _staleness(variant: Variant, env: dict[str, Quantity]) -> list[StaleResult]:
    """Flag engineer-supplied values whose design inputs have changed since they were tuned."""
    out = []
    for p in variant.design.params.values():
        for against, designed in sorted(p.designed_against.items()):
            name = f"design.{p.name}"
            parts = designed.split()
            if against not in env or len(parts) != 2:
                out.append(StaleResult(name, against, designed, "?", FAIL, f"cannot check: {against} unknown or {designed!r} is not 'value unit'"))
                continue
            try:
                was = to_si(float(parts[0]), parts[1])
            except (ValueError, UnitError) as exc:
                out.append(StaleResult(name, against, designed, "?", FAIL, f"cannot check: {exc}"))
                continue
            now = env[against].value
            now_text = f"{from_si(now, parts[1]):g} {parts[1]}"
            if abs(now - was) <= 1e-9 * max(abs(was), 1e-30):
                out.append(StaleResult(name, against, designed, now_text, OK))
            else:
                msg = (f"tuned for {against} = {designed}, now {now_text}; "
                       f"re-tune {name} or re-approve it by updating designed_against")
                out.append(StaleResult(name, against, designed, now_text, FAIL, msg))
    return out


def _consumed_ds_fields(rules: Rules) -> set[str]:
    used: set[str] = set()
    for r in rules.constants:
        names = [r.formula] if r.kind == "enum" else [*parse(r.formula).names, *(parse(r.fallback).names if r.fallback else ())]
        used |= {n[3:] for n in names if n.startswith("ds.")}
    return used


def _classify(findings: list[Finding], consumed: set[str], variant: Variant) -> list[DatasheetFinding]:
    """Errors on consumed fields block unless overridden; everything else is reported."""
    out = []
    for f in findings:
        hit = [x for x in f.fields if x in consumed]
        if f.severity == ERROR and hit:
            if all(x in variant.overrides for x in hit):
                note = "; ".join(" ".join(variant.overrides[x].note.split()) for x in hit)
                out.append(DatasheetFinding(f, WAIVED, f"waived by override: {note}"))
            else:
                out.append(DatasheetFinding(f, BLOCKING, "field is used by a rule; fix the transcription or add a reasoned override"))
        elif f.severity == ERROR:
            out.append(DatasheetFinding(f, FLAGGED, "field not used by any rule; report to the data sheet owner"))
        else:
            out.append(DatasheetFinding(f, FLAGGED, "needs engineer review"))
    return out

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


def roots(build: Build, rule_id: str, _seen: set[str] | None = None) -> set[str]:
    """Input kinds a constant ultimately rests on: ds, override, board, target, design (transitively)."""
    seen = _seen if _seen is not None else set()
    c = build.constant(rule_id)
    names = [c.rule.formula] if c.rule.kind == "enum" else parse(c.rule.formula).names
    out: set[str] = set()
    for n in names:
        if "." in n:
            kind = n.split(".", 1)[0]
            out.add("override" if kind == "ds" and n[3:] in build.variant.overrides else kind)
        elif n not in seen:
            seen.add(n)
            out |= roots(build, n, seen)
    return out


def rests_on_data_sheet_only(build: Build, rule_id: str) -> bool:
    """True when a constant follows from the data sheet and public chip facts alone (no invented values)."""
    return roots(build, rule_id) <= {"ds", "target"}
