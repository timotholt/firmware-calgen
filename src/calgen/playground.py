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
from calgen.build import roots as build_roots
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

# Data sheet fields offered as what-ifs, grouped like the data sheet: (name, unit, label, group).
# A test checks this covers every numeric data sheet field a rule consumes.
DS_EDITABLE = [
    ("vin_min", "V", "Min input voltage", "Input"),
    ("vin_max", "V", "Max input voltage", "Input"),
    ("fin_nom_lo", "Hz", "Mains frequency low", "Input"),
    ("fin_nom_hi", "Hz", "Mains frequency high", "Input"),
    ("fin_tol_hz", "Hz", "Frequency tolerance ±", "Input"),
    ("fin_tol_pct", "%", "Frequency tolerance ±", "Input"),
    ("iin_max", "A", "Max input current", "Input"),
    ("power_va", "VA", "Rated power", "Output"),
    ("vout_nom", "V", "Output voltage", "Output"),
    ("vout_tol_pct", "%", "Output regulation ±", "Output"),
    ("fout_hz", "Hz", "Output frequency", "Output"),
    ("overload_alarm_pct", "%", "Overload alarm level", "Overload"),
    ("overload_trip_pct", "%", "Overload trip level", "Overload"),
    ("batt_string_v", "V", "Battery string voltage", "Battery"),
    ("batt_series_cells", "counts", "Cells in series", "Battery"),
]

# editable inputs: (paramset, name, display unit, label, owner)
EDITABLE = [("ds", n, u, label, f"Data sheet · {group}") for n, u, label, group in DS_EDITABLE] + [
    ("board", "r_shunt", "mohm", "Current shunt", "Board"),
    ("board", "g_amp", "ratio", "Sense amp gain", "Board"),
    ("design", "f_sw", "kHz", "Switching frequency", "Design choice"),
    ("design", "vbus_margin", "%", "DC bus margin", "Design choice"),
]

# Market presets: nominal mains voltage and frequency per market. Applied as data
# sheet what-ifs; the product's own tolerance proportions are kept. Universal-input
# products (wide input range) keep their input range.
PRESETS = {
    "na": {"label": "North America · 120 V 60 Hz", "v": 120.0, "f": 60.0},
    "eu": {"label": "Europe · 230 V 50 Hz", "v": 230.0, "f": 50.0},
    "uk": {"label": "UK · 230 V 50 Hz", "v": 230.0, "f": 50.0},
    "jp_east": {"label": "Japan east · 100 V 50 Hz", "v": 100.0, "f": 50.0},
    "jp_west": {"label": "Japan west · 100 V 60 Hz", "v": 100.0, "f": 60.0},
    "mil400": {"label": "Military / aircraft · 115 V 400 Hz", "v": 115.0, "f": 400.0},
}


def preset_edits(base_datasheet, key: str) -> dict[str, float]:
    """Data sheet what-ifs for a market preset, keeping the product's tolerance proportions."""
    p = PRESETS[key]
    ds = base_datasheet.params

    def num(name):
        q = ds.get(name)
        return q.value if q is not None and q.numeric else None

    v_out = num("vout_nom") or 120.0
    v_in = num("vin_nom") or v_out  # the input window scales with the nominal input, when the sheet gives one
    edits = {"ds.vout_nom": p["v"], "ds.fout_hz": p["f"]}
    f_lo, f_hi = num("fin_nom_lo"), num("fin_nom_hi")
    single_freq = not (f_lo and f_hi and f_lo != f_hi)  # 50/60 Hz products keep both
    if single_freq:
        edits["ds.fin_nom_lo"] = edits["ds.fin_nom_hi"] = p["f"]
    vmin, vmax = num("vin_min"), num("vin_max")
    if vmin and vmax and vmax / vmin < 2.0:  # narrow input: scale with the market voltage
        edits["ds.vin_min"] = round(vmin * p["v"] / v_in, 1)
        edits["ds.vin_max"] = round(vmax * p["v"] / v_in, 1)
    tol = num("fin_tol_hz")
    if single_freq and tol:  # a tolerance in Hz scales with the mains frequency; one in % already does
        edits["ds.fin_tol_hz"] = round(tol / (f_hi or 60.0) * p["f"], 2)
    return edits


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
    """data sheet | derived (from data sheet and public chip facts only) | assumption | design | what-if."""
    c = b.constant(rule_id)
    roots = build_roots(b, rule_id)
    direct = dotted_name(parse(c.rule.formula).tree) if c.rule.kind == "numeric" else c.rule.formula
    if "override" in roots and direct and direct.startswith("ds."):
        return "override"
    if c.rule.supplied or (direct and direct.startswith("design.")):
        return "design"
    if direct and direct.startswith("ds."):
        return "datasheet"
    if roots & {"board", "design", "override"}:
        return "assumption"
    return "derived"


def run(specs: str | Path, product: str = "FA10507", board_rev: str = "A", target: str = "f28004x",
        edits: dict[str, float] | None = None, base_header: str | None = None, preset: str | None = None) -> dict:
    specs = Path(specs)
    base = load_variant(specs / "variants" / f"{PRODUCTS[product]['variant']}.yaml")
    preset_label = PRESETS[preset]["label"] if preset else None
    user_edits = dict(edits or {})
    edits = {**(preset_edits(base.datasheet, preset) if preset else {}), **user_edits}
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
            how = "what-if in playground" if k in user_edits or not preset_label else f"market preset {preset_label}"
            reason = f"{how}: data sheet says {was}"
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
    out["shipped_inputs"] = to_json(default)["inputs"]
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

    f_lo, f_hi = g("ds.fin_nom_lo", "Hz"), g("ds.fin_nom_hi", "Hz")
    f_hz, f_pct = g("ds.fin_tol_hz", "Hz"), g("ds.fin_tol_pct", "%")
    if f_lo and f_hi:
        freq = f"{f_lo:g} Hz" if f_lo == f_hi else f"{f_lo:g}/{f_hi:g} Hz"
        freq += f" ±{f_hz:.3g} Hz" if f_hz else f" ±{f_pct:.3g}%" if f_pct else ""
    else:
        freq = "freq. not stated on data sheet"
    mode = val["fout_mode"].enum_ident.split("_")[-1].lower() if val["fout_mode"].enum_ident else "?"
    action = val["overload_action"].enum_ident.split("_")[-1].lower() if val["overload_action"].enum_ident else "?"
    trip_pct = g("ds.overload_trip_pct", "%")
    chem = str(ds["batt_type"].value).replace("lifepo4", "LiFePO4") if "batt_type" in ds else ""
    return {
        "in": f"{v('vin_min')}–{v('vin_max')} V AC 1φ* · {freq} · ≤ {v('iin_limit', '{:.1f}')} A",
        "rect": f"Boost PFC · bus ≥ √2 × {v('vin_max')} V = {v('vbus_min')} V",
        "bus": f"{v('vbus_set')} V DC setpoint · sensor full scale {v('vbus_fs')} V",
        "inv": f"{v('vout_set')} V AC ±{g('ds.vout_tol_pct', '%') or 0:g}% · {v('fout_hz')} Hz {mode} · PWM {g('design.f_sw', 'kHz') or 0:g} kHz",
        "out": f"{g('ds.power_va', 'VA') or 0:g} VA · {v('iout_rated', '{:.2f}')} A rated · overload {v('iout_trip', '{:.2f}')} A RMS ({trip_pct or 0:g}%) for {(g('design.overload_delay', 's') or 0):g} s → {action} · peak limit {v('iout_pk_limit', '{:.1f}')} A",
        "sense": _sense_line(val, g("design.sense_headroom", "%")),
        "batt": f"{v('vbat_nom', '{:.1f}')} V {chem} · cutoff {v('vbat_cutoff', '{:.1f}')} V",
    }


def _sense_line(val: dict, headroom_pct: float | None) -> str:
    pk, fs = val.get("iout_pk_limit"), val.get("iout_fs_pk")
    if not pk or not fs or pk.value is None or fs.value is None:
        return ""
    used = 100 * pk.value / fs.value
    limit = headroom_pct or 95
    verdict = "OK" if used <= limit else "SATURATES before the limit fires"
    return f"Current sensor ±{fs.value:.1f} A peak · hardware peak limit {pk.value:.1f} A uses {used:.0f}% (max {limit:g}%) · {verdict}"


def protection(b: Build) -> dict | None:
    """Current-protection numbers for the gauge and waveform, in amps (drawing only; no new math)."""
    import math

    val = {c.rule.id: c for c in b.constants}
    need = ("iout_rated", "iout_trip", "iout_pk_limit", "iout_fs_pk")
    if not all(val.get(k) is not None and val[k].value is not None for k in need):
        return None
    rated = val["iout_rated"].value
    head = b.env.get("design.sense_headroom")
    cf = b.env["design.crest_factor"].value if "design.crest_factor" in b.env else 3.0
    return {
        "rated_rms": rated,
        "rated_pk": math.sqrt(2) * rated,
        "crest": cf,
        "crest_pk": cf * rated,
        "overload_rms": val["iout_trip"].value,
        "peak_limit": val["iout_pk_limit"].value,
        "sensor_fs": val["iout_fs_pk"].value,
        "headroom": head.value if head is not None else 0.95,
        "f_hz": val["fout_hz"].value if val.get("fout_hz") is not None and val["fout_hz"].value else 60.0,
        "overload_delay_s": b.env["design.overload_delay"].value if "design.overload_delay" in b.env else None,
    }


def suggestions(b: Build) -> dict[str, list[dict]]:
    """Concrete, one-click fixes for failures where the arithmetic is simple. check id -> suggestions."""
    import math

    from calgen.units import from_si

    out: dict[str, list[dict]] = {}
    env = b.env
    need = ("target.v_ref", "board.r_shunt", "board.g_amp", "design.sense_headroom")
    lim = next((c for c in b.constants if c.rule.id == "iout_pk_limit"), None)
    failing = {k.check.id for k in b.checks if k.status == FAIL} | {
        c.rule.id for c in b.constants if c.status == FAIL and c.rule.id.startswith("iout_pklim_dac")}
    if lim is None or lim.value is None or not all(n in env for n in need) or not failing & {
            "iout_sense_range", "dac_hi_in_range", "iout_pklim_dac_lo", "iout_pklim_dac_hi"}:
        return out
    v_half = env["target.v_ref"].value / 2
    rg_max = v_half * env["design.sense_headroom"].value / lim.value  # ohms x gain the sensor can afford
    r_now, g_now = env["board.r_shunt"].value, env["board.g_amp"].value
    r_max_mohm = from_si(rg_max / g_now, "mohm")
    g_max = rg_max / r_now
    r_pick = math.floor(r_max_mohm * 10) / 10
    g_pick = float(math.floor(g_max))
    items = []
    if r_pick > 0:
        items.append({"label": f"Use a {r_pick:g} mΩ shunt (needs ≤ {r_max_mohm:.2f} mΩ with gain {g_now:g})", "key": "board.r_shunt", "value": r_pick})
    if g_pick >= 1:
        items.append({"label": f"Use amp gain {g_pick:g} V/V (needs ≤ {g_max:.1f} with {from_si(r_now, 'mohm'):g} mΩ)", "key": "board.g_amp", "value": g_pick})
    for cid in ("iout_sense_range", "dac_hi_in_range"):
        out[cid] = items
    out["iout_pklim_dac_lo"] = items
    out["iout_pklim_dac_hi"] = items
    return out


def inductor_requirements(b: Build) -> dict[str, dict]:
    """First-pass inductor requirements from this build's values, for the Magnetics sizing link.
    Estimates with stated assumptions, not design values (stage id -> requirement)."""
    import math

    val = {c.rule.id: c.value for c in b.constants if c.value is not None}
    f = b.env.get("design.f_sw")
    if f is None or "vbus_set" not in val:
        return {}
    import yaml

    limits = yaml.safe_load((b.variant.path.parent.parent / "magnetics" / "limits.yaml").read_text(encoding="utf-8"))
    f_sw, vbus, r = f.value, val["vbus_set"], limits["ripple_fraction"]
    shared = "PFC and inverter assumed to share design.f_sw"
    out = {}
    if "iin_limit" in val:
        i_rms = val["iin_limit"]
        di = r * math.sqrt(2) * i_rms
        out["rect"] = {"name": "PFC boost inductor", "l_uh": vbus / (4 * f_sw * di) * 1e6, "i_rms": i_rms,
                       "i_pk": math.sqrt(2) * i_rms + di / 2, "min_retained": 0.5,
                       "basis": f"L = V_bus / (4 f_sw ΔI), ΔI = {r:g} × line peak at the data sheet's max input current; boost, worst case at V_in = V_bus/2; {shared}; "
                                "keeps ≥ 50% at peak, common for PFC, so a drawing of it would fail the 80% drawing check"}
    if all(k in val for k in ("iout_trip", "iout_rated", "iout_pk_limit", "vout_hi")):
        di = r * math.sqrt(2) * val["iout_rated"]
        # A half-bridge swings ±V_bus/2, so it can only serve outputs whose peak fits under half the bus;
        # otherwise a full bridge (unipolar PWM: ripple at 2 f_sw, worst case V_bus / (8 f_sw L)).
        m = b.env["design.m_max"].value if "design.m_max" in b.env else 1.0
        cf = b.env["design.crest_factor"].value if "design.crest_factor" in b.env else math.sqrt(2)
        half = m * vbus / 2 >= math.sqrt(2) * val["vout_hi"]
        k, topo = (4, f"half-bridge ({m:g} × V_bus/2 clears the output peak)") if half else (8, f"unipolar full bridge ({m:g} × V_bus/2 can't reach the output peak; ripple at 2 f_sw)")
        load_pk = max(cf * val["iout_rated"], math.sqrt(2) * val["iout_trip"])  # the inductor carries the load's current peaks
        out["out"] = {"name": "Output filter inductor", "l_uh": vbus / (k * f_sw * di) * 1e6, "i_rms": val["iout_rated"],
                      "i_pk": load_pk + di / 2, "min_retained": 0.8,
                      "basis": f"L = V_bus / ({k} f_sw ΔI), ΔI = {r:g} × rated peak; {topo}; "
                               f"peak = the larger of a rated {cf:g}:1 crest-factor load ({cf * val['iout_rated']:.1f} A) and a sinusoidal {val['iout_trip']:.1f} A RMS overload ({math.sqrt(2) * val['iout_trip']:.1f} A), plus ripple; RMS (heating) at rated; "
                               f"the {val['iout_pk_limit']:.1f} A hardware limit is a brief fault event, checked separately; {shared}"}
    return out


def to_json(b: Build, base_header: str | None = None) -> dict:
    try:
        c_text, gate_msg = header(b), ""
    except GateError as exc:
        c_text, gate_msg = "", "; ".join(exc.failures)
    diff = ""
    if c_text and base_header is not None and base_header != c_text:
        diff = "\n".join(difflib.unified_diff(base_header.splitlines(), c_text.splitlines(), "baseline", "edited", lineterm=""))
    sugg = suggestions(b)
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
            "suggest": sugg.get(c.rule.id, []),
        })
    checks = [{
        "id": k.check.id, "block": k.check.block, "describe": k.check.describe, "status": k.status,
        "message": k.message, "latex": derive_check(b, k.check.id).lines,
        "fix": k.check.fix, "suggest": sugg.get(k.check.id, []),
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
        "protection": protection(b),
        "inductors": inductor_requirements(b),
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


def _input_value(b: Build, kind: str, name: str, unit: str) -> float | None:
    from calgen.units import from_si

    q = b.env.get(f"{kind}.{name}")
    return None if q is None else round(from_si(q.value, unit), 6)


def options() -> dict:
    return {
        "products": {k: v["label"] for k, v in PRODUCTS.items()},
        "boards": list(BOARDS),
        "targets": list(TARGETS),
        "editable": [{"key": f"{k}.{n}", "unit": u, "label": label, "owner": owner} for k, n, u, label, owner in EDITABLE],
        "presets": {k: v["label"] for k, v in PRESETS.items()},
        "flow": FLOW_BLOCKS,
    }


def run_json(specs: str, request_json: str) -> str:
    """Entry point for the browser: JSON in, JSON out."""
    req = json.loads(request_json)
    return json.dumps(run(specs, req.get("product", "FA10507"), req.get("board", "A"), req.get("target", "f28004x"),
                          req.get("edits") or {}, req.get("base_header"), req.get("preset") or None))


__all__ = ["run", "run_json", "options", "to_json"]
