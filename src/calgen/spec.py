"""Load and validate the four kinds of input files.

* data sheet transcription (CSV)   — what the product is (public, cited)
* board definition (YAML)          — sense-chain hardware (hardware engineer)
* target profile (YAML)            — the processor (chip facts)
* variant (YAML)                   — picks the three above + engineer-supplied design values
* rules (YAML)                     — how each firmware constant is derived

Validation collects every problem it finds and raises one ``SpecError`` listing
them all, so an engineer fixes a file in one pass instead of one error at a time.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from calgen.expr import ExprError, Quantity, parse
from calgen.formats import is_valid_format
from calgen.units import UnitError, parse_unit


class SpecError(ValueError):
    def __init__(self, source: str, issues: list[str]):
        self.source = source
        self.issues = issues
        super().__init__(f"{source}: " + "; ".join(issues))


@dataclass(frozen=True)
class Param:
    """A named input value with its unit and where it came from."""

    name: str
    value: float | str
    unit: str | None
    source: str
    note: str = ""
    label: str = ""  # data sheet row label, verbatim
    raw: str = ""  # data sheet cell, verbatim
    designed_against: dict[str, str] = field(default_factory=dict)

    @property
    def numeric(self) -> bool:
        return isinstance(self.value, float)

    def quantity(self) -> Quantity:
        if not self.numeric:
            raise SpecError(self.source, [f"{self.name} is not numeric"])
        scale, dim = parse_unit(self.unit or "1")
        return Quantity(self.value * scale, dim)


@dataclass(frozen=True)
class Datasheet:
    part: str
    path: Path
    params: dict[str, Param]


@dataclass(frozen=True)
class ParamSet:
    """Board, target, or variant design values."""

    kind: str
    name: str
    path: Path
    description: str
    params: dict[str, Param]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    id: str
    symbol: str
    formula: str
    unit: str
    format: str
    block: str
    describe: str
    latex: str
    min: float | None
    max: float | None
    tolerance: float | None  # max relative quantization error
    supplied: bool  # engineer-supplied value carried through, not derived
    optional: bool = False  # skip (reported) when an input is absent for this product
    kind: str = "numeric"  # "numeric" | "enum"
    choices: dict[str, str] = field(default_factory=dict)  # enum: data sheet text -> C identifier
    fallback: str | None = None  # formula used when `formula`'s data sheet inputs are absent (same fact, other form)
    display_unit: str | None = None  # unit as printed (e.g. V/count for a scale factor); `unit` stays the dimensional one

    @property
    def shown_unit(self) -> str:
        return self.display_unit or self.unit


@dataclass(frozen=True)
class Check:
    id: str
    lhs: str
    op: str
    rhs: str
    describe: str
    block: str
    fix: str = ""  # how an engineer would resolve a failure


@dataclass(frozen=True)
class Rules:
    path: Path
    constants: list[Rule]
    checks: list[Check]
    blocks: dict[str, str]
    symbols: dict[str, str] = field(default_factory=dict)  # input name -> LaTeX


@dataclass(frozen=True)
class Inverter:
    """Declared hardware and modulation; never inferred from the requested voltage."""

    topology: str
    pwm: str

    def __post_init__(self):
        if (self.topology, self.pwm) not in (("half_bridge", "bipolar"), ("full_bridge", "unipolar")):
            raise ValueError("Unsupported inverter topology/PWM pair")

    @property
    def output_factor(self) -> float:
        return 0.5 if self.topology == "half_bridge" else 1.0

    @property
    def ripple_divisor(self) -> int:
        return 4 if self.topology == "half_bridge" else 8

    @property
    def label(self) -> str:
        return "Half bridge · bipolar PWM" if self.topology == "half_bridge" else "Full bridge · unipolar PWM"


@dataclass(frozen=True)
class Variant:
    name: str
    path: Path
    datasheet: Datasheet
    board: ParamSet
    target: ParamSet
    design: ParamSet
    inverter: Inverter
    overrides: dict[str, Param] = field(default_factory=dict)  # reviewer-visible data sheet waivers

    def digest(self) -> str:
        """sha256 over the exact bytes of every input file, in a fixed order."""
        h = hashlib.sha256()
        for p in (self.path, self.datasheet.path, self.board.path, self.target.path):
            h.update(p.name.encode())
            h.update(p.read_bytes())
        return h.hexdigest()


DATASHEET_COLUMNS = ["field", "label", "raw", "value", "unit", "source"]
CHECK_OPS = ("<=", "<", ">=", ">", "==")


def _num(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _check_unit(unit: str | None, where: str, issues: list[str]) -> None:
    if unit is None:
        return
    try:
        parse_unit(unit)
    except UnitError as exc:
        issues.append(f"{where}: {exc}")


def load_datasheet(path: str | Path) -> Datasheet:
    path = Path(path)
    issues: list[str] = []
    params: dict[str, Param] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != DATASHEET_COLUMNS:
            raise SpecError(str(path), [f"columns must be {DATASHEET_COLUMNS}, got {reader.fieldnames}"])
        for line, row in enumerate(reader, start=2):
            name = (row["field"] or "").strip()
            where = f"line {line} ({name or '?'})"
            if not name:
                issues.append(f"line {line}: empty field name")
                continue
            if name in params:
                issues.append(f"{where}: duplicate field")
                continue
            if not (row["source"] or "").strip():
                issues.append(f"{where}: every data sheet value needs a source")
            text = (row["value"] or "").strip()
            unit = (row["unit"] or "").strip() or None
            num = _num(text)
            if unit is not None and num is None:
                issues.append(f"{where}: unit {unit!r} given but value {text!r} is not a number")
            _check_unit(unit, where, issues)
            params[name] = Param(
                name=name,
                value=num if num is not None else text,
                unit=unit if num is not None else None,
                source=row["source"].strip(),
                label=(row["label"] or "").strip(),
                raw=(row["raw"] or "").strip(),
            )
    for required in ("part_number", "model_string"):
        if required not in params:
            issues.append(f"missing required field {required!r}")
    if issues:
        raise SpecError(str(path), issues)
    return Datasheet(part=str(params["part_number"].value), path=path, params=params)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(str(path), [f"invalid YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise SpecError(str(path), ["top level must be a mapping"])
    return data


def _params(raw: Any, path: Path, kind: str, issues: list[str]) -> dict[str, Param]:
    out: dict[str, Param] = {}
    if not isinstance(raw, dict):
        issues.append("'params' must be a mapping")
        return out
    for name, spec in raw.items():
        where = f"params.{name}"
        if not isinstance(spec, dict) or "value" not in spec or "unit" not in spec:
            issues.append(f"{where}: needs 'value' and 'unit'")
            continue
        value = spec["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(f"{where}: value must be a number")
            continue
        unit = str(spec["unit"])
        _check_unit(unit, where, issues)
        against = spec.get("designed_against") or {}
        if not isinstance(against, dict):
            issues.append(f"{where}: designed_against must be a mapping of name -> 'value unit'")
            against = {}
        out[name] = Param(
            name=name,
            value=float(value),
            unit=unit,
            source=f"{kind} {path.name}",
            note=str(spec.get("note", "")),
            designed_against={str(k): str(v) for k, v in against.items()},
        )
    return out


def load_paramset(path: str | Path, kind: str) -> ParamSet:
    path = Path(path)
    data = _load_yaml(path)
    issues: list[str] = []
    name = data.get(kind)
    if not isinstance(name, str) or not name:
        issues.append(f"missing '{kind}' name")
    params = _params(data.get("params", {}), path, kind, issues)
    if issues:
        raise SpecError(str(path), issues)
    extra = {k: v for k, v in data.items() if k not in (kind, "params", "description")}
    return ParamSet(kind, name, path, str(data.get("description", "")), params, extra)


def load_variant(path: str | Path) -> Variant:
    path = Path(path)
    data = _load_yaml(path)
    issues = [f"missing '{k}'" for k in ("variant", "datasheet", "board", "target") if k not in data]
    if issues:
        raise SpecError(str(path), issues)
    config = data.get("inverter")
    supported = (("half_bridge", "bipolar"), ("full_bridge", "unipolar"))
    if not isinstance(config, dict) or (config.get("topology"), config.get("pwm")) not in supported:
        raise SpecError(str(path), ["inverter must declare a supported topology/PWM pair: half_bridge/bipolar or full_bridge/unipolar"])
    inverter = Inverter(config["topology"], config["pwm"])
    base = path.parent
    design_data = data.get("design", {})
    design_issues: list[str] = []
    design = ParamSet(
        "design",
        str(data["variant"]),
        path,
        "engineer-supplied design values",
        _params(design_data, path, "design", design_issues),
    )
    overrides: dict[str, Param] = {}
    for name, spec in (data.get("datasheet_overrides") or {}).items():
        reason = str((spec or {}).get("reason", "")).strip() if isinstance(spec, dict) else ""
        if not isinstance(spec, dict) or "value" not in spec or not reason:
            design_issues.append(f"datasheet_overrides.{name}: needs 'value' and a written 'reason'")
            continue
        value, unit = spec["value"], spec.get("unit")
        if unit is not None:
            _check_unit(str(unit), f"datasheet_overrides.{name}", design_issues)
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        overrides[name] = Param(
            name=name,
            value=float(value) if numeric else str(value),
            unit=str(unit) if (numeric and unit is not None) else None,
            source=f"OVERRIDE in {path.name} (reason in header)",
            note=reason,
        )
    if design_issues:
        raise SpecError(str(path), design_issues)
    return Variant(
        name=str(data["variant"]),
        path=path,
        datasheet=load_datasheet(base / data["datasheet"]),
        board=load_paramset(base / data["board"], "board"),
        target=load_paramset(base / data["target"], "target"),
        design=design,
        inverter=inverter,
        overrides=overrides,
    )


def load_rules(path: str | Path) -> Rules:
    path = Path(path)
    data = _load_yaml(path)
    issues: list[str] = []
    blocks = data.get("blocks") or {}
    if not isinstance(blocks, dict):
        issues.append("'blocks' must be a mapping of id -> title")
        blocks = {}
    constants: list[Rule] = []
    seen: set[str] = set()
    for i, c in enumerate(data.get("constants") or []):
        where = f"constants[{i}]"
        if not isinstance(c, dict):
            issues.append(f"{where}: must be a mapping")
            continue
        kind = str(c.get("kind", "numeric"))
        needed = ("id", "symbol", "formula", "unit", "format", "block") if kind == "numeric" else ("id", "symbol", "source", "choices", "block")
        if kind not in ("numeric", "enum"):
            issues.append(f"{where}: kind must be numeric or enum")
            continue
        missing = [k for k in needed if k not in c]
        if missing:
            issues.append(f"{where}: missing {', '.join(missing)}")
            continue
        where = f"constants.{c['id']}"
        if c["id"] in seen:
            issues.append(f"{where}: duplicate id")
        seen.add(c["id"])
        if kind == "enum":
            choices = c["choices"]
            if not isinstance(choices, dict) or not choices:
                issues.append(f"{where}: choices must be a non-empty mapping")
                choices = {}
            c = {**c, "formula": str(c["source"]), "unit": "1", "format": "enum",
                 "choices": {str(k).lower(): str(v) for k, v in choices.items()}}
        else:
            for key in ("formula", "fallback") if "fallback" in c else ("formula",):
                try:
                    parse(str(c[key]))
                except ExprError as exc:
                    issues.append(f"{where}.{key}: {exc}")
            _check_unit(str(c["unit"]), where, issues)
            fmt = str(c["format"])
            if fmt != "target" and not is_valid_format(fmt):
                issues.append(f"{where}: unknown format {fmt!r}")
        if c["block"] not in blocks:
            issues.append(f"{where}: unknown block {c['block']!r}")
        constants.append(
            Rule(
                id=str(c["id"]),
                symbol=str(c["symbol"]),
                formula=str(c["formula"]),
                unit=str(c["unit"]),
                format=str(c["format"]),
                block=str(c["block"]),
                describe=str(c.get("describe", "")),
                latex=str(c.get("latex", c["id"])),
                min=c.get("min"),
                max=c.get("max"),
                tolerance=c.get("tolerance"),
                supplied=bool(c.get("supplied", False)),
                optional=bool(c.get("optional", False)),
                kind=kind,
                choices=dict(c.get("choices", {})) if kind == "enum" else {},
                fallback=str(c["fallback"]) if c.get("fallback") is not None else None,
                display_unit=str(c["display_unit"]) if c.get("display_unit") else None,
            )
        )
    checks: list[Check] = []
    for i, c in enumerate(data.get("checks") or []):
        where = f"checks[{i}]"
        if not isinstance(c, dict) or any(k not in c for k in ("id", "lhs", "op", "rhs")):
            issues.append(f"{where}: needs id, lhs, op, rhs")
            continue
        if c["op"] not in CHECK_OPS:
            issues.append(f"{where}: op must be one of {CHECK_OPS}")
        for side in ("lhs", "rhs"):
            try:
                parse(str(c[side]))
            except ExprError as exc:
                issues.append(f"{where}.{side}: {exc}")
        block = str(c.get("block", ""))
        if block and block not in blocks:
            issues.append(f"{where}: unknown block {block!r}")
        checks.append(Check(str(c["id"]), str(c["lhs"]), str(c["op"]), str(c["rhs"]), str(c.get("describe", "")), block, str(c.get("fix", ""))))
    if issues:
        raise SpecError(str(path), issues)
    symbols = data.get("symbols") or {}
    if not isinstance(symbols, dict):
        raise SpecError(str(path), ["'symbols' must be a mapping of input name -> LaTeX"])
    return Rules(
        path=path,
        constants=constants,
        checks=checks,
        blocks={str(k): str(v) for k, v in blocks.items()},
        symbols={str(k): str(v) for k, v in symbols.items()},
    )
