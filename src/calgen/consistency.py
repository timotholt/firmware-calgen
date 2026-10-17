"""Data sheet consistency gate: does the data sheet agree with itself?

Firmware built from a contradictory spec is wrong no matter how carefully it
is generated, so these checks run before any constant is trusted. Each check
compares two places on the same data sheet that should say the same thing:

* label vs cell     a row labeled "Current (Amps)" whose cell holds a frequency
* model vs fields   model-string tokens (VA, kW, Isolated, FC, LiFe) vs table values
* description vs fields   the free-text unit description vs table values
* page vs page      the model number printed in two places
* arithmetic        W <= VA; battery string voltage vs cells x per-cell nominal

Findings on fields that a rule consumes block the build unless the variant
carries a written override; other findings are reported for the data sheet
owner but do not block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from calgen.spec import Datasheet

ERROR, WARNING = "error", "warning"

# per-cell nominal voltages by chemistry (generic public figures)
CELL_NOMINAL_V = {"lifepo4": (3.2, 3.3), "pbacid": (2.0, 2.0)}


@dataclass(frozen=True)
class Finding:
    severity: str
    fields: tuple[str, ...]
    check: str
    message: str
    evidence: tuple[str, ...] = ()  # verbatim quotes from the sheet


_LABEL_EXPECT = [
    # (label keyword, pattern the cell should match, what it is)
    (re.compile(r"current", re.I), re.compile(r"\bamps?\b|\d\s*A\b", re.I), "a current (A)"),
    (re.compile(r"frequency", re.I), re.compile(r"hz", re.I), "a frequency (Hz)"),
    (re.compile(r"voltage", re.I), re.compile(r"v(ac|dc)?\b", re.I), "a voltage (V)"),
]
_LOOKS_LIKE = [
    (re.compile(r"hz", re.I), "a frequency"),
    (re.compile(r"\bamps?\b", re.I), "a current"),
    (re.compile(r"\bv(ac|dc)\b", re.I), "a voltage"),
]


def _num(ds: Datasheet, name: str) -> float | None:
    p = ds.params.get(name)
    return p.value if p is not None and p.numeric else None


def _text(ds: Datasheet, name: str) -> str:
    p = ds.params.get(name)
    return str(p.value).lower() if p is not None else ""


def _raw(ds: Datasheet, name: str) -> str:
    p = ds.params.get(name)
    return p.raw if p is not None else ""


def check_labels(ds: Datasheet) -> list[Finding]:
    out = []
    for p in ds.params.values():
        for label_pat, cell_pat, what in _LABEL_EXPECT:
            if not label_pat.search(p.label) or not p.raw:
                continue
            if "voltage" in what and "current" in p.label.lower():
                continue
            if cell_pat.search(p.raw):
                continue
            looks = next((name for pat, name in _LOOKS_LIKE if pat.search(p.raw)), "something else")
            out.append(
                Finding(
                    ERROR,
                    (p.name,),
                    "label_vs_cell",
                    f"row labeled {p.label!r} should hold {what}, but the cell reads like {looks}",
                    (f"{p.label} {p.raw}",),
                )
            )
            break
    return out


def _model_tokens(model: str) -> dict[str, object]:
    t: dict[str, object] = {}
    if m := re.match(r"^I[A-Z]{1,3}(\d{3,5})", model):
        t["va"] = float(m.group(1))
    if m := re.search(r"-(\d+(?:\.\d+)?)Kw", model, re.I):
        t["kw"] = float(m.group(1))
    parts = model.split("-")
    t["isolated"] = "Isolated" in parts
    t["fc"] = any(re.fullmatch(r"FC\d+", x) for x in parts)
    t["lithium"] = bool(re.search(r"-(LiFe|\d*Li)", model))
    return t


def check_model(ds: Datasheet) -> list[Finding]:
    out = []
    model = str(ds.params["model_string"].value)
    tok = _model_tokens(model)
    va, w = _num(ds, "power_va"), _num(ds, "power_w")
    if "va" in tok and va is not None and tok["va"] != va:
        out.append(Finding(ERROR, ("power_va",), "model_vs_fields", f"model string encodes {tok['va']:g} VA but power rating is {va:g} VA", (model,)))
    if "kw" in tok and w is not None and abs(tok["kw"] * 1000 - w) > 0.5:
        out.append(Finding(ERROR, ("power_w",), "model_vs_fields", f"model string encodes {tok['kw']:g} kW but power rating is {w:g} W", (model,)))
    iso = _text(ds, "isolation")
    if iso:
        if iso == "isolated" and not tok["isolated"]:
            out.append(Finding(WARNING, ("isolation", "model_string"), "model_vs_fields", "isolation row says Isolated but this model string has no 'Isolated' token", (model, _raw(ds, "isolation"))))
        if iso == "non-isolated" and tok["isolated"]:
            out.append(Finding(WARNING, ("isolation", "model_string"), "model_vs_fields", "isolation row says Non-Isolated but the model string contains 'Isolated'", (model,)))
    mode = _text(ds, "fout_mode")
    if tok["fc"] and mode == "follower":
        out.append(
            Finding(
                WARNING,
                ("fout_mode", "model_string"),
                "model_vs_fields",
                "model string has an FC token (read as Frequency Changer; naming convention inferred, not documented) but the output row says Follower",
                (model, _raw(ds, "fout_mode")),
            )
        )
    if _text(ds, "batt_type") == "lifepo4" and not tok["lithium"]:
        out.append(Finding(WARNING, ("batt_type", "model_string"), "model_vs_fields", "battery is lithium iron phosphate but the model string has no lithium token", (model,)))
    return out


def check_pages(ds: Datasheet) -> list[Finding]:
    p1, p2 = ds.params.get("model_string_p1"), ds.params.get("model_string")
    if p1 is None or p2 is None or p1.value == p2.value:
        return []
    a, b = str(p1.value).split("-"), str(p2.value).split("-")
    only1 = [x for x in a if x not in b]
    only2 = [x for x in b if x not in a]
    detail = f"page-1 only: {', '.join(only1) or '-'}; table only: {', '.join(only2) or '-'}"
    return [Finding(WARNING, ("model_string",), "page_vs_page", f"the two printed model numbers differ ({detail})", (str(p1.value), str(p2.value)))]


def check_description(ds: Datasheet) -> list[Finding]:
    desc = _raw(ds, "unit_description")
    if not desc:
        return []
    out = []
    mode = _text(ds, "fout_mode")
    d = desc.lower()
    if "frequency changer" in d and mode == "follower":
        out.append(Finding(WARNING, ("fout_mode",), "description_vs_fields", "unit description says Frequency Changer but the output frequency row says Follower", (desc[:120], _raw(ds, "fout_mode"))))
    if "follower" in d and mode == "changer":
        out.append(Finding(WARNING, ("fout_mode",), "description_vs_fields", "unit description says Follower but the output frequency row says Changer", (desc[:120], _raw(ds, "fout_mode"))))
    iso = _text(ds, "isolation")
    if "non-isolated" in d and iso == "isolated":
        out.append(Finding(WARNING, ("isolation",), "description_vs_fields", "unit description says Non-Isolated but the isolation row says Isolated", (desc[:120],)))
    if m := re.search(r"(\d+)\s*VA,\s*(\d+)\s*W", desc):
        va, w = _num(ds, "power_va"), _num(ds, "power_w")
        if va is not None and float(m.group(1)) != va or w is not None and float(m.group(2)) != w:
            out.append(Finding(ERROR, ("power_va", "power_w"), "description_vs_fields", "unit description power differs from the power rating row", (m.group(0),)))
    return out


def check_arithmetic(ds: Datasheet) -> list[Finding]:
    out = []
    va, w = _num(ds, "power_va"), _num(ds, "power_w")
    if va is not None and w is not None and w > va:
        out.append(Finding(ERROR, ("power_w", "power_va"), "arithmetic", f"real power {w:g} W exceeds apparent power {va:g} VA"))
    vstr = _num(ds, "batt_string_v")
    chem = _text(ds, "batt_type")
    cells = _num(ds, "batt_series_cells")
    if vstr is not None and cells and chem in CELL_NOMINAL_V:
        lo, hi = CELL_NOMINAL_V[chem]
        if not (cells * lo * 0.98 <= vstr <= cells * hi * 1.02):
            out.append(Finding(WARNING, ("batt_string_v", "batt_series_cells"), "arithmetic", f"{vstr:g} V is not {cells:g} cells x {lo}-{hi} V nominal"))
    mods, mod_v = _num(ds, "batt_modules"), _num(ds, "batt_module_v")
    if vstr is not None and mods and mod_v and abs(mods * mod_v - vstr) > 0.02 * vstr:
        out.append(Finding(WARNING, ("batt_string_v", "batt_modules"), "arithmetic", f"{mods:g} x {mod_v:g} V modules is not {vstr:g} V"))
    return out


def check_datasheet(ds: Datasheet) -> list[Finding]:
    return check_labels(ds) + check_model(ds) + check_pages(ds) + check_description(ds) + check_arithmetic(ds)
