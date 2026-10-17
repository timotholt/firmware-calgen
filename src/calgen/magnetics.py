"""Magnetics records: structured, physics-checked, searchable (demo of AMETEK initiative 1).

The flow mirrors calgen: messy input (a component drawing) becomes a structured
record, simple textbook physics checks it against vendor core data, and anything
that fails goes to a review list with the reason. Nothing here designs magnetics.

* ``render_pdf`` draws a synthetic drawing from a design record (reportlab).
* ``extract`` reads a drawing's PDF text layer back into a record (pypdf).
* ``check`` runs the physics gates and returns typeset derivations.
* ``similar`` ranks past designs by closeness for the search page.

reportlab and pypdf are imported lazily: the browser bundle never needs them.
"""

from __future__ import annotations

import csv
import math
import re
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PASS, FLAG, NA = "pass", "flag", "n/a"


# ---- data ------------------------------------------------------------------
@dataclass(frozen=True)
class Core:
    name: str
    vendor: str
    family: str  # "toroid" | "E pair"
    material: str
    al_nh: float
    al_tol_pct: float
    ae_mm2: float
    le_mm: float
    wa_mm2: float
    wa_basis: str
    h80_oe: float | None
    h50_oe: float | None
    bsat_mt: float | None
    source: str


def load_cores(path: Path) -> dict[str, Core]:
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            num = lambda k: float(r[k]) if r[k] else None  # noqa: E731
            out[r["core"]] = Core(r["core"], r["vendor"], r["family"], r["material"], num("al_nh"), num("al_tol_pct"),
                                  num("ae_mm2"), num("le_mm"), num("wa_mm2"), r["wa_basis"], num("h80_oe"), num("h50_oe"),
                                  num("bsat_mt"), r["source"])
    return out


def load_limits(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@dataclass
class Winding:
    name: str
    start: int
    finish: int
    turns: int
    awg: int
    strands: int
    i_rms_a: float


@dataclass
class Design:
    id: str
    rev: str
    kind: str  # "inductor" | "transformer"
    title: str
    core: str
    windings: list[Winding]
    # inductor
    l_text: str = ""  # inductance as drawn, e.g. "450 µH" (kept as text: unit slips are part of the data)
    l_tol_pct: float = 0.0
    i_pk_a: float = 0.0
    # transformer
    lm_text: str = ""  # minimum magnetizing inductance as drawn
    v_pri: float = 0.0
    f_khz: float = 0.0
    ratio_text: str = ""  # e.g. "4:1"
    notes: list[str] = field(default_factory=list)


def load_designs(path: Path) -> list[Design]:
    out = []
    for d in yaml.safe_load(path.read_text(encoding="utf-8")):
        wd = [Winding(**w) for w in d.pop("windings")]
        out.append(Design(windings=wd, **d))
    return out


def awg_area_mm2(awg: int) -> float:
    """Bare copper area of solid round AWG wire (standard AWG diameter formula)."""
    d = 0.127 * 92 ** ((36 - awg) / 39)
    return math.pi * d * d / 4


def parse_inductance_uh(text: str) -> float | None:
    m = re.fullmatch(r"\s*([\d.]+)\s*(µH|uH|mH|H)\s*", text)
    if not m:
        return None
    return float(m.group(1)) * {"µH": 1.0, "uH": 1.0, "mH": 1e3, "H": 1e6}[m.group(2)]


# ---- checks -------------------------------------------------------------------
@dataclass
class Check:
    id: str
    title: str
    status: str
    message: str
    latex: list[str] = field(default_factory=list)


def _f(x: float, nd: int = 3) -> str:
    return f"{x:.{nd}g}"


def check(d: Design, cores: dict[str, Core], limits: dict) -> list[Check]:
    core = cores.get(d.core)
    if core is None:
        return [Check("core_known", "Core is in the catalog", FLAG,
                      f"core {d.core!r} is not in the vendor catalog; likely a part-number typo")]
    out = [Check("core_known", "Core is in the catalog", PASS, f"{core.vendor} {core.name} ({core.material})")]
    if d.kind == "inductor":
        out += _inductor_checks(d, core, limits)
    else:
        out += _transformer_checks(d, core, limits)
    out += _copper_checks(d, core, limits)
    return out


def _inductor_checks(d: Design, core: Core, limits: dict) -> list[Check]:
    w = d.windings[0]
    out = []
    l_calc = core.al_nh * w.turns ** 2 / 1000  # µH
    l_stated = parse_inductance_uh(d.l_text)
    tex = [rf"L = A_L N^2 = {_f(core.al_nh)}\,\mathrm{{nH}} \times {w.turns}^2 = {_f(l_calc, 4)}\,\mu\mathrm{{H}}"]
    if l_stated is None:
        out.append(Check("inductance", "Stated inductance matches A_L × N²", FLAG, f"cannot read inductance {d.l_text!r}", tex))
    else:
        err = (l_stated - l_calc) / l_calc
        ok = abs(err) <= core.al_tol_pct / 100
        tex.append(rf"\text{{drawing: }} {_f(l_stated, 4)}\,\mu\mathrm{{H}} \quad ({err * 100:+.1f}\%,\ \text{{core tolerance}} \pm {_f(core.al_tol_pct)}\%)")
        hint = "" if ok else (" (looks like a unit slip)" if abs(math.log10(l_stated / l_calc)) > 0.9 else " (check the turns count)")
        out.append(Check("inductance", "Stated inductance matches A_L × N²", PASS if ok else FLAG,
                         f"drawing {d.l_text} vs {_f(l_calc, 4)} µH from the core and turns: {err * 100:+.1f}%{hint}", tex))
    if core.family == "toroid":
        h_oe = 0.4 * math.pi * w.turns * d.i_pk_a / (core.le_mm / 10)
        lim = core.h80_oe if limits["toroid_bias_limit"] == "h80" else core.h50_oe
        ok = h_oe <= lim
        tex = [rf"H_{{pk}} = \frac{{0.4\pi N I_{{pk}}}}{{l_e}} = \frac{{0.4\pi \times {w.turns} \times {_f(d.i_pk_a)}\,\mathrm{{A}}}}{{{_f(core.le_mm / 10)}\,\mathrm{{cm}}}} = {_f(h_oe)}\,\mathrm{{Oe}}",
               rf"\text{{limit: }} H_{{80\%}} = {_f(lim)}\,\mathrm{{Oe}} \quad \text{{(data sheet: keeps }} \geq 80\% \text{{ of the inductance at peak current)}}"]
        out.append(Check("dc_bias", "Peak current keeps 80% of the inductance", PASS if ok else FLAG,
                         f"{_f(h_oe)} Oe at {_f(d.i_pk_a)} A peak vs {_f(lim)} Oe limit" + ("" if ok else ": the core loses more than 20% of its inductance"), tex))
    return out


def _transformer_checks(d: Design, core: Core, limits: dict) -> list[Check]:
    p, s = d.windings[0], d.windings[1]
    out = []
    lm_calc = core.al_nh * p.turns ** 2 / 1000
    lm_min_calc = lm_calc * (1 - core.al_tol_pct / 100)
    lm_stated = parse_inductance_uh(d.lm_text)
    tex = [rf"L_m = A_L N_p^2 = {_f(core.al_nh)}\,\mathrm{{nH}} \times {p.turns}^2 = {_f(lm_calc, 4)}\,\mu\mathrm{{H}} \quad (\geq {_f(lm_min_calc, 4)}\,\mu\mathrm{{H}} \text{{ at }} -{_f(core.al_tol_pct)}\%)"]
    ok = lm_stated is not None and lm_min_calc >= lm_stated
    out.append(Check("magnetizing", "Minimum magnetizing inductance is met", PASS if ok else FLAG,
                     f"drawing requires {d.lm_text} minimum; core and turns give at least {_f(lm_min_calc, 4)} µH", tex))
    m = re.fullmatch(r"\s*([\d.]+)\s*:\s*([\d.]+)\s*", d.ratio_text)
    ratio_stated = float(m.group(1)) / float(m.group(2)) if m else None
    ratio = p.turns / s.turns
    ok = ratio_stated is not None and abs(ratio - ratio_stated) / ratio_stated <= limits["ratio_tol_pct"] / 100
    out.append(Check("ratio", "Turns ratio matches the winding table", PASS if ok else FLAG,
                     f"drawing says {d.ratio_text}; winding table gives {p.turns}:{s.turns} = {ratio:.3g}:1",
                     [rf"\frac{{N_p}}{{N_s}} = \frac{{{p.turns}}}{{{s.turns}}} = {ratio:.3g} \quad \text{{vs drawing }} {d.ratio_text.replace(':', '{:}')}"]))
    b_mt = d.v_pri / (4 * d.f_khz * 1e3 * p.turns * core.ae_mm2 * 1e-6) * 1e3  # square wave
    lim = limits["bsat_margin"] * core.bsat_mt
    ok = b_mt <= lim
    out.append(Check("flux", "Peak flux stays below saturation", PASS if ok else FLAG,
                     f"{_f(b_mt)} mT vs {_f(lim)} mT ({limits['bsat_margin'] * 100:.0f}% of {_f(core.bsat_mt)} mT B_sat)",
                     [rf"B_{{pk}} = \frac{{V}}{{4 f N_p A_e}} = \frac{{{_f(d.v_pri)}\,\mathrm{{V}}}}{{4 \times {_f(d.f_khz)}\,\mathrm{{kHz}} \times {p.turns} \times {_f(core.ae_mm2)}\,\mathrm{{mm^2}}}} = {_f(b_mt)}\,\mathrm{{mT}}",
                      rf"\text{{limit: }} {limits['bsat_margin']:g} \times B_{{sat}} = {_f(lim)}\,\mathrm{{mT}} \quad \text{{(square-wave drive)}}"]))
    return out


def _copper_checks(d: Design, core: Core, limits: dict) -> list[Check]:
    out = []
    worst, tex = 0.0, []
    for w in d.windings:
        a = awg_area_mm2(w.awg) * w.strands
        j = w.i_rms_a / a
        worst = max(worst, j)
        tex.append(rf"J_{{{w.name}}} = \frac{{{_f(w.i_rms_a)}\,\mathrm{{A}}}}{{{w.strands} \times {_f(awg_area_mm2(w.awg))}\,\mathrm{{mm^2}}\ (\mathrm{{{w.awg}\ AWG}})}} = {_f(j)}\,\mathrm{{A/mm^2}}")
    ok = worst <= limits["j_max_a_per_mm2"]
    tex.append(rf"\text{{limit: }} {_f(limits['j_max_a_per_mm2'])}\,\mathrm{{A/mm^2}} \quad \text{{(assumption)}}")
    out.append(Check("current_density", "Wire is thick enough for the current", PASS if ok else FLAG,
                     f"worst winding {_f(worst)} A/mm² vs {_f(limits['j_max_a_per_mm2'])} A/mm²" + ("" if ok else ": wire too thin, it will run hot"), tex))
    cu = sum(w.turns * w.strands * awg_area_mm2(w.awg) for w in d.windings)
    fill = cu / core.wa_mm2
    lim = limits["fill_max_toroid"] if core.family == "toroid" else limits["fill_max_ecore"]
    ok = fill <= lim
    out.append(Check("window_fill", "Copper fits the core window", PASS if ok else FLAG,
                     f"{fill * 100:.0f}% of the window vs {lim * 100:.0f}% limit" + ("" if ok else ": the winding won't fit"),
                     [rf"\frac{{\sum N \cdot n \cdot A_{{wire}}}}{{W_a}} = \frac{{{_f(cu)}\,\mathrm{{mm^2}}}}{{{_f(core.wa_mm2)}\,\mathrm{{mm^2}}}} = {fill * 100:.0f}\% \quad (\text{{limit }} {lim * 100:.0f}\%,\ \text{{assumption}})"]))
    return out


# ---- drawings: render and extract ----------------------------------------------
def render_pdf(d: Design, path: Path) -> None:
    """Draw a synthetic component drawing. Deterministic output (reportlab invariant mode)."""
    from reportlab import rl_config

    rl_config.invariant = 1
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfgen import canvas

    W, H = landscape(letter)
    c = canvas.Canvas(str(path), pagesize=(W, H), invariant=1)
    c.setTitle(f"{d.id} {d.title}")
    c.setLineWidth(1.2)
    c.rect(24, 24, W - 48, H - 48)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(36, H - 44, "SYNTHETIC DEMO DRAWING - NOT A REAL PRODUCT")

    def table(x, y, title, header, rows, widths):
        """Title above the box; header row and data rows inside it. Returns the y for the next table."""
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y, title)
        top = y - 8
        hy = top - 13
        c.setFont("Helvetica-Bold", 8.5)
        cx = x
        for h, wd in zip(header, widths):
            c.drawString(cx + 5, hy, h)
            cx += wd
        c.line(x, hy - 5, x + sum(widths), hy - 5)
        c.setFont("Helvetica", 9)
        ry = hy
        for r in rows:
            ry -= 16
            cx = x
            for v, wd in zip(r, widths):
                c.drawString(cx + 5, ry, str(v))
                cx += wd
        bottom = ry - 7
        c.rect(x, bottom, sum(widths), top - bottom)
        cx = x
        for wd in widths[:-1]:  # column rules
            cx += wd
            c.line(cx, bottom, cx, top)
        return bottom - 26

    # schematic sketch: a coil between pins
    c.setLineWidth(1)
    for k, w in enumerate(d.windings):
        y0 = H - 110 - k * 70
        c.circle(70, y0, 4)
        c.circle(230, y0, 4)
        c.setFont("Helvetica", 8)
        c.drawString(62, y0 - 16, str(w.start))
        c.drawString(222, y0 - 16, str(w.finish))
        for i in range(6):
            c.arc(80 + i * 23, y0 - 8, 103 + i * 23, y0 + 14, 0, 180)
        c.drawString(130, y0 + 20, w.name)
    if d.kind == "transformer":
        c.line(76, H - 145, 226, H - 145)
        c.line(76, H - 149, 226, H - 149)

    y = table(300, H - 70, "CORE", ["CORE PART NUMBER"], [[d.core]], [300])
    y = table(300, y, "WINDING TABLE", ["WDG", "START", "FINISH", "TURNS", "WIRE", "STRANDS", "CURRENT"],
              [[w.name, w.start, w.finish, w.turns, f"{w.awg} AWG", w.strands, f"{w.i_rms_a:g} A RMS"] for w in d.windings],
              [40, 50, 50, 50, 60, 60, 80])
    if d.kind == "inductor":
        rows = [["INDUCTANCE (0 A DC, 10 kHz)", f"{d.l_text} +/-{d.l_tol_pct:g}%"],
                ["PEAK CURRENT", f"{d.i_pk_a:g} A"],
                ["HIPOT, WINDING TO CORE", "1500 VAC, 60 s"]]
    else:
        rows = [["MAGNETIZING INDUCTANCE (PRI, 10 kHz)", f"{d.lm_text} MIN"],
                ["PRIMARY DRIVE", f"{d.v_pri:g} V SQUARE, {d.f_khz:g} kHz"],
                ["TURNS RATIO (PRI:SEC)", d.ratio_text],
                ["HIPOT, PRI TO SEC", "3000 VAC, 60 s"]]
    table(300, y, "ELECTRICAL", ["PARAMETER", "VALUE"], rows, [230, 170])
    # title block
    x0, y0 = W - 324, 36
    c.setLineWidth(1.2)
    c.rect(x0, y0, 288, 74)
    c.setFont("Helvetica", 7.5)
    c.drawString(x0 + 6, y0 + 62, "TITLE")
    c.drawString(x0 + 6, y0 + 30, "DRAWING NO.")
    c.drawString(x0 + 200, y0 + 30, "REV")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0 + 6, y0 + 46, d.title)
    c.drawString(x0 + 6, y0 + 14, d.id)
    c.drawString(x0 + 200, y0 + 14, d.rev)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, 150, "NOTES")
    c.setFont("Helvetica", 8)
    y = 136
    for n in ["1. WIND EVENLY IN ONE DIRECTION; LEADS AS SHOWN.", "2. VARNISH IMPREGNATE AFTER WINDING.",
              "3. MARK WITH DRAWING NUMBER AND DATE CODE.", "4. SYNTHETIC EXAMPLE FOR A SOFTWARE DEMO; NOT FOR MANUFACTURE.",
              *d.notes]:
        c.drawString(40, y, n)
        y -= 12
    c.showPage()
    c.save()


def extract(path: Path) -> dict:
    """Read a drawing's PDF text layer back into fields. Every field records the text it came from.

    PDF text comes out one table cell per line, so this walks the token stream using the
    table headings as anchors (the template is fixed; real drawings would need a sample-driven
    schema, or a vision model with human review, as noted on the site)."""
    from pypdf import PdfReader

    tok = [t.strip() for t in PdfReader(str(path)).pages[0].extract_text().splitlines() if t.strip()]
    found: dict = {"windings": [], "source": {}}

    def take(key, value, text):
        found[key] = value
        found["source"][key] = text

    def after(label):
        return tok[tok.index(label) + 1] if label in tok and tok.index(label) + 1 < len(tok) else None

    if core := after("CORE PART NUMBER"):
        take("core", core, core)
    if "CURRENT" in tok and "ELECTRICAL" in tok:  # winding table: 7 cells per row
        cells = tok[tok.index("CURRENT") + 1: tok.index("ELECTRICAL")]
        for k in range(0, len(cells) - 6, 7):
            name, start, finish, turns, wire, strands, cur = cells[k:k + 7]
            m_w, m_i = re.fullmatch(r"(\d+) AWG", wire), re.fullmatch(r"([\d.]+) A RMS", cur)
            if not (m_w and m_i):
                continue
            found["windings"].append({"name": name, "start": int(start), "finish": int(finish), "turns": int(turns),
                                      "awg": int(m_w[1]), "strands": int(strands), "i_rms_a": float(m_i[1])})
            found["source"][name] = " | ".join(cells[k:k + 7])
    if v := after("INDUCTANCE (0 A DC, 10 kHz)"):
        if m := re.fullmatch(r"([\d.]+\s*(?:µH|uH|mH|H)) \+/-([\d.]+)%", v):
            take("l_text", m[1], v)
            take("l_tol_pct", float(m[2]), v)
    if (v := after("PEAK CURRENT")) and (m := re.fullmatch(r"([\d.]+) A", v)):
        take("i_pk_a", float(m[1]), v)
    if (v := after("MAGNETIZING INDUCTANCE (PRI, 10 kHz)")) and (m := re.fullmatch(r"([\d.]+\s*(?:µH|uH|mH|H)) MIN", v)):
        take("lm_text", m[1], v)
    if (v := after("PRIMARY DRIVE")) and (m := re.fullmatch(r"([\d.]+) V SQUARE, ([\d.]+) kHz", v)):
        take("v_pri", float(m[1]), v)
        take("f_khz", float(m[2]), v)
    if (v := after("TURNS RATIO (PRI:SEC)")) and re.fullmatch(r"[\d.]+\s*:\s*[\d.]+", v):
        take("ratio_text", v, v)
    if "REV" in tok and tok.index("REV") + 3 < len(tok):  # title block: labels, then title, number, rev
        i = tok.index("REV")
        take("title", tok[i + 1], tok[i + 1])
        take("id", tok[i + 2], tok[i + 2])
        take("rev", tok[i + 3], tok[i + 3])
    found["kind"] = "transformer" if "ratio_text" in found else "inductor"
    return found


def design_from_extract(x: dict) -> Design:
    keep = {k: v for k, v in x.items() if k not in ("windings", "source")}
    return Design(windings=[Winding(**w) for w in x["windings"]], **keep)


# ---- search ------------------------------------------------------------------------
def features(d: Design) -> dict[str, float]:
    if d.kind == "inductor":
        l_uh = parse_inductance_uh(d.l_text) or 0.0
    else:
        l_uh = parse_inductance_uh(d.lm_text) or 0.0
    return {"l_uh": l_uh, "i_a": max(w.i_rms_a for w in d.windings), "turns": d.windings[0].turns}


def similar(designs: list[Design], k: int = 3) -> dict[str, list[tuple[str, float]]]:
    """Closest past designs of the same kind: distance on log-scaled inductance, current, and turns."""
    feats = {d.id: features(d) for d in designs}
    out = {}
    for d in designs:
        fa = feats[d.id]
        scored = []
        for e in designs:
            if e.id == d.id or e.kind != d.kind:
                continue
            fb = feats[e.id]
            dist = math.sqrt(sum((math.log10(max(fa[q], 1e-9)) - math.log10(max(fb[q], 1e-9))) ** 2 for q in fa))
            scored.append((e.id, round(dist, 3)))
        out[d.id] = sorted(scored, key=lambda t: t[1])[:k]
    return out


# ---- site data -----------------------------------------------------------------------
def site_records(root: Path) -> dict:
    """Everything the Magnetics page shows, computed at build time from the PDFs themselves."""
    specs, corpus = root / "specs" / "magnetics", root / "corpus" / "magnetics"
    cores, limits = load_cores(specs / "cores.csv"), load_limits(specs / "limits.yaml")
    designs = load_designs(corpus / "designs.yaml")
    recs, extracted = [], []
    for d in designs:
        x = extract(corpus / "drawings" / f"{d.id}.pdf")
        rec = design_from_extract(x)
        extracted.append(rec)
        checks = check(rec, cores, limits)
        core = cores.get(rec.core)
        f = features(rec)
        recs.append({
            "id": rec.id, "rev": rec.rev, "kind": rec.kind, "title": rec.title, "core": rec.core,
            "core_desc": f"{core.vendor} {core.material} {core.family}" if core else "not in catalog",
            "material": core.material if core else "", "family": core.family if core else "",
            "l_uh": f["l_uh"], "l_text": rec.l_text or rec.lm_text, "i_a": f["i_a"],
            "windings": [dataclasses.asdict(w) for w in rec.windings],
            "source": x["source"],
            "checks": [dataclasses.asdict(c) for c in checks],
            "flagged": any(c.status == FLAG for c in checks),
        })
    sim = similar(extracted)
    for r in recs:
        r["similar"] = [{"id": i, "distance": dist} for i, dist in sim[r["id"]]]
    return {
        "records": recs,
        "cores": [dataclasses.asdict(c) for c in cores.values()],
        "limits": limits,
    }
