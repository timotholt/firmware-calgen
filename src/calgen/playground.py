"""One function the website calls, in the browser (Pyodide) and at build time.

``run(product, board_rev, target, overrides)`` builds a variant with edited
inputs and returns plain JSON: constants with typeset derivations, checks,
data sheet findings, staleness, power-flow block values, and the generated C
(or why nothing was generated). The site pre-renders the default call, and the
live playground calls the same code, so the page never re-implements the math.
"""

from __future__ import annotations

import dataclasses
import difflib
import json
from pathlib import Path

from calgen.build import FAIL, OK, Build, build
from calgen.codegen import GateError, header
from calgen.expr import dotted_name, parse
from calgen.latex import derive_check, derive_constant
from calgen.spec import Param, ParamSet, load_paramset, load_rules, load_variant

PRODUCTS = {
    "FA10449": {"variant": "fa10449", "label": "FA10449 · 650 VA · half rack"},
    "FA10434": {"variant": "fa10434", "label": "FA10434 · 800 VA · 2U"},
    "FA10507": {"variant": "fa10507", "label": "FA10507 · 1500 VA · 3U military"},
}
BOARDS = {"A": "ups_ctrl_revA.yaml", "B": "ups_ctrl_revB.yaml"}
TARGETS = {"f28004x": "f28004x.yaml", "f2803x": "f2803x.yaml"}

# editable inputs: (paramset, name, display unit, label, owner)
EDITABLE = [
    ("ds", "power_va", "VA", "Rated power", "Product what-if"),
    ("ds", "vin_max", "V", "Max input voltage", "Product what-if"),
    ("ds", "vout_nom", "V", "Output voltage", "Product what-if"),
    ("ds", "overload_trip_pct", "%", "Overload trip level", "Product what-if"),
    ("board", "r_shunt", "mohm", "Current shunt", "Board"),
    ("board", "g_amp", "ratio", "Sense amp gain", "Board"),
    ("design", "f_sw", "kHz", "Switching frequency", "Design choice"),
    ("design", "vbus_margin", "%", "DC bus margin", "Design choice"),
]

FLOW_BLOCKS = ["in", "rect", "bus", "inv", "out", "batt"]


def _with_params(ps: ParamSet, edits: dict[str, float]) -> ParamSet:
    if not edits:
        return ps
    params = dict(ps.params)
    for name, value in edits.items():
        p = params[name]
        params[name] = dataclasses.replace(p, value=float(value), source=f"{ps.kind} {ps.path.name}, EDITED in playground")
    return dataclasses.replace(ps, params=params)


def _tag(b: Build, rule_id: str) -> str:
    c = b.constant(rule_id)
    if any(s.override for s in c.sources) and dotted_name(parse(c.rule.formula).tree) is not None:
        return "override"
    if c.rule.supplied:
        return "design"
    if c.rule.kind == "enum":
        return "datasheet"
    name = dotted_name(parse(c.rule.formula).tree)
    if name and name.startswith("ds."):
        return "datasheet"
    if name and name.startswith("design."):
        return "design"
    return "derived"


def run(specs: str | Path, product: str = "FA10507", board_rev: str = "A", target: str = "f28004x",
        edits: dict[str, float] | None = None, base_header: str | None = None) -> dict:
    specs = Path(specs)
    edits = edits or {}
    base = load_variant(specs / "variants" / f"{PRODUCTS[product]['variant']}.yaml")
    board = load_paramset(specs / "boards" / BOARDS[board_rev], "board")
    tgt = load_paramset(specs / "targets" / TARGETS[target], "target")
    board_edits = {k.split(".", 1)[1]: v for k, v in edits.items() if k.startswith("board.")}
    design_edits = {k.split(".", 1)[1]: v for k, v in edits.items() if k.startswith("design.")}
    overrides = dict(base.overrides)
    for k, v in edits.items():
        if k.startswith("ds."):
            name = k.split(".", 1)[1]
            orig = base.datasheet.params.get(name)
            unit = next(u for kind, n, u, _, _ in EDITABLE if kind == "ds" and n == name)
            was = f"{orig.value:g} {orig.unit}" if orig is not None and orig.numeric else "not stated"
            reason = f"what-if in playground: data sheet says {was}"
            overrides[name] = Param(name=name, value=float(v), unit=unit, source=f"OVERRIDE ({reason})", note=reason)
    variant = dataclasses.replace(
        base,
        name=f"{PRODUCTS[product]['variant']}_rev{board_rev}_{target}",
        board=_with_params(board, board_edits),
        target=tgt,
        design=_with_params(base.design, design_edits),
        overrides=overrides,
    )
    rules = load_rules(specs / "rules.yaml")
    b = build(variant, rules)
    # baseline = the product as shipped: board rev A, F28004x-class target, no edits
    default = build(base, rules)
    baseline = {c.rule.id: (_display(c), c.value, c.enum_ident, c.status) for c in default.constants}
    if base_header is None and edits:
        unedited = dataclasses.replace(variant, board=board, design=base.design, overrides=base.overrides)
        try:
            base_header = header(build(unedited, rules))
        except GateError:
            base_header = ""
    out = to_json(b, base_header)
    out["baseline"] = {k: v[0] for k, v in baseline.items()}
    out["changed"] = [c.rule.id for c in b.constants if _differs(baseline.get(c.rule.id), c)]
    return out


def _differs(base, c) -> bool:
    """Meaningful change vs the shipped product: status, enum, or value beyond 0.01%."""
    if base is None:
        return True
    _, value, ident, status = base
    if status != c.status or ident != c.enum_ident:
        return True
    if value is None or c.value is None:
        return value != c.value
    return abs(c.value - value) > 1e-4 * max(abs(value), 1e-12)


def _num(b: Build, name: str, unit: str) -> float | None:
    from calgen.units import from_si

    q = b.env.get(name)
    return None if q is None else from_si(q.value, unit)


def summaries(b: Build) -> dict[str, str]:
    """One-line engineering summary per power-flow block, built from the same values."""
    ds = b.variant.datasheet.params
    g = lambda name, unit="1": _num(b, name, unit)  # noqa: E731
    val = {c.rule.id: c for c in b.constants}

    def v(rule_id: str, fmt: str = "{:.0f}") -> str:
        c = val.get(rule_id)
        return fmt.format(c.value) if c is not None and c.value is not None else "?"

    fin = ds.get("fin_nom")
    if fin is not None and fin.numeric:
        freq = fin.raw.replace("+/-", "±").replace(", ", " ").replace("(", "").replace(")", "").replace("± ", "±")
    else:
        freq = "freq. unreadable on data sheet"
    mode = val["fout_mode"].enum_ident.split("_")[-1].lower() if val["fout_mode"].enum_ident else "?"
    action = val["overload_action"].enum_ident.split("_")[-1].lower() if val["overload_action"].enum_ident else "?"
    trip_pct = g("ds.overload_trip_pct", "%")
    chem = str(ds["batt_type"].value).replace("lifepo4", "LiFePO4") if "batt_type" in ds else ""
    return {
        "in": f"{v('vin_min')}–{v('vin_max')} V AC 1φ* · {freq} · ≤ {v('iin_limit', '{:.1f}')} A",
        "rect": f"Boost PFC · bus ≥ √2 × {v('vin_max')} V = {v('vbus_min')} V",
        "bus": f"{v('vbus_set')} V DC setpoint · sensor full scale {v('vbus_fs')} V",
        "inv": f"{v('vout_set')} V AC ±{g('ds.vout_tol_pct', '%') or 0:g}% · {v('fout_hz')} Hz {mode} · PWM {g('design.f_sw', 'kHz') or 0:g} kHz",
        "out": f"{g('ds.power_va', 'VA') or 0:g} VA · {v('iout_rated', '{:.2f}')} A rated · trip {v('iout_trip', '{:.2f}')} A ({trip_pct or 0:g}%) · {action}",
        "sense": _sense_line(val, g("design.sense_headroom", "%")),
        "batt": f"{v('vbat_nom', '{:.1f}')} V {chem} · cutoff {v('vbat_cutoff', '{:.1f}')} V",
    }


def _sense_line(val: dict, headroom_pct: float | None) -> str:
    pk, fs = val.get("iout_trip_pk"), val.get("iout_fs_pk")
    if not pk or not fs or pk.value is None or fs.value is None:
        return ""
    used = 100 * pk.value / fs.value
    limit = headroom_pct or 95
    verdict = "OK" if used <= limit else "SATURATES before trip"
    return f"Current sensor ±{fs.value:.1f} A peak · trip peak {pk.value:.1f} A uses {used:.0f}% (limit {limit:g}%) · {verdict}"


def to_json(b: Build, base_header: str | None = None) -> dict:
    try:
        c_text, gate_msg = header(b), ""
    except GateError as exc:
        c_text, gate_msg = "", "; ".join(exc.failures)
    diff = ""
    if c_text and base_header is not None and base_header != c_text:
        diff = "\n".join(difflib.unified_diff(base_header.splitlines(), c_text.splitlines(), "baseline", "edited", lineterm=""))
    constants = []
    for c in b.constants:
        d = derive_constant(b, c.rule.id)
        constants.append({
            "id": c.rule.id,
            "symbol": c.rule.symbol,
            "block": c.rule.block,
            "describe": c.rule.describe,
            "status": c.status,
            "message": c.message,
            "value": c.enum_ident or (c.encoded.literal if c.encoded else None),
            "display": _display(c),
            "tag": _tag(b, c.rule.id),
            "latex": d.lines,
            "sources": [{"name": s.name, "origin": s.origin, "quote": s.quote} for s in c.sources if s.origin != "constant"],
        })
    checks = [{
        "id": k.check.id, "block": k.check.block, "describe": k.check.describe, "status": k.status,
        "message": k.message, "latex": derive_check(b, k.check.id).lines,
    } for k in b.checks]
    return {
        "variant": b.variant.name,
        "part": b.variant.datasheet.part,
        "ok": b.ok,
        "failures": b.failures,
        "gate_message": gate_msg,
        "blocks": b.rules.blocks,
        "constants": constants,
        "checks": checks,
        "datasheet": [{"status": d.status, "message": d.finding.message, "note": d.note, "evidence": list(d.finding.evidence)} for d in b.datasheet],
        "staleness": [{"param": s.param, "against": s.against, "designed": s.designed, "current": s.current, "status": s.status, "message": s.message} for s in b.staleness],
        "header": c_text,
        "diff": diff,
        "inputs": {f"{kind}.{name}": _input_value(b, kind, name, unit) for kind, name, unit, _, _ in EDITABLE},
        "summaries": summaries(b),
        "footnote": "* single-phase is implied by the IEC C14 inlet and NEMA 5-15 outlets on the data sheet, not stated as a rating",
    }


def _display(c) -> str:
    if c.enum_ident:
        return c.enum_ident.split("_")[-1].lower()
    if c.status != OK or c.encoded is None:
        return "—" if c.status != FAIL else "FAIL"
    v = c.value
    unit = "" if c.rule.unit in ("counts", "ratio", "1") else f" {c.rule.unit}"
    return f"{v:.4g}{unit}" if abs(v) < 1e4 else f"{v:.0f}{unit}"


def _input_value(b: Build, kind: str, name: str, unit: str) -> float:
    from calgen.units import from_si

    q = b.env[f"{kind}.{name}"]
    return round(from_si(q.value, unit), 6)


def options() -> dict:
    return {
        "products": {k: v["label"] for k, v in PRODUCTS.items()},
        "boards": list(BOARDS),
        "targets": list(TARGETS),
        "editable": [{"key": f"{k}.{n}", "unit": u, "label": label, "owner": owner} for k, n, u, label, owner in EDITABLE],
        "flow": FLOW_BLOCKS,
    }


def run_json(specs: str, request_json: str) -> str:
    """Entry point for the browser: JSON in, JSON out."""
    req = json.loads(request_json)
    return json.dumps(run(specs, req.get("product", "FA10507"), req.get("board", "A"), req.get("target", "f28004x"),
                          req.get("edits") or {}, req.get("base_header")))


__all__ = ["run", "run_json", "options", "to_json"]
