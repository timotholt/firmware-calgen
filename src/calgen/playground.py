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
from calgen.spec import ParamSet, load_paramset, load_rules, load_variant

PRODUCTS = {
    "FA10449": {"variant": "fa10449", "label": "FA10449 · 650 VA · half rack"},
    "FA10434": {"variant": "fa10434", "label": "FA10434 · 800 VA · 2U"},
    "FA10507": {"variant": "fa10507", "label": "FA10507 · 1500 VA · 3U military"},
}
BOARDS = {"A": "ups_ctrl_revA.yaml", "B": "ups_ctrl_revB.yaml"}
TARGETS = {"f28004x": "f28004x.yaml", "f2803x": "f2803x.yaml"}

# editable inputs: (paramset, name, display unit, label, owner)
EDITABLE = [
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
    variant = dataclasses.replace(
        base,
        name=f"{PRODUCTS[product]['variant']}_rev{board_rev}_{target}",
        board=_with_params(board, board_edits),
        target=tgt,
        design=_with_params(base.design, design_edits),
    )
    rules = load_rules(specs / "rules.yaml")
    b = build(variant, rules)
    if base_header is None and edits:
        unedited = dataclasses.replace(variant, board=board, design=base.design)
        try:
            base_header = header(build(unedited, rules))
        except GateError:
            base_header = ""
    return to_json(b, base_header)


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
