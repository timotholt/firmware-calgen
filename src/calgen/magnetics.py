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
    ve_mm3: float
    wa_mm2: float
    wa_basis: str
    h80_oe: float | None
    h50_oe: float | None
    bsat_mt: float | None
    source: str
    od_mm: float | None = None  # toroid: uncoated OD; E core: overall width A
    id_mm: float | None = None  # toroid: uncoated ID; E core: center-leg width C
    ht_mm: float | None = None  # toroid: height; E core: window half-height E
    perm: float | None = None
    fit: tuple[float, float, float] | None = None  # vendor DC-bias fit (a, b, c): % initial perm = 1/(a + b H^c)


def load_cores(path: Path) -> dict[str, Core]:
    fits = {}
    fit_file = Path(path).with_name("dc_bias_fit.csv")
    if fit_file.exists():
        with open(fit_file, newline="", encoding="utf-8") as f:
            fits = {(r["material"], float(r["perm"])): (float(r["a"]), float(r["b"]), float(r["c"])) for r in csv.DictReader(f)}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            num = lambda k: float(r[k]) if r[k] else None  # noqa: E731
            out[r["core"]] = Core(r["core"], r["vendor"], r["family"], r["material"], num("al_nh"), num("al_tol_pct"),
                                  num("ae_mm2"), num("le_mm"), num("ve_mm3"), num("wa_mm2"), r["wa_basis"], num("h80_oe"), num("h50_oe"),
                                  num("bsat_mt"), r["source"], num("od_mm"), num("id_mm"), num("ht_mm"),
                                  num("perm"), fits.get((r["material"], num("perm"))) if r["perm"] else None)
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


def _fmt_l(uh: float) -> str:
    """Inductance for text: mH from 1000 µH up, as the page's tables do."""
    return f"{uh / 1000:.3g} mH" if uh >= 1000 else f"{uh:.4g} µH"


def _f(x: float, nd: int = 3) -> str:
    s = f"{x:.{nd}g}"
    return f"{x:.0f}" if "e+" in s else s  # 2500, not 2.5e+03


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
        out.append(Check("inductance", "Stated inductance matches Aₗ × N²", FLAG, f"cannot read inductance {d.l_text!r}", tex))
    else:
        err = (l_stated - l_calc) / l_calc
        # every core in the Aₗ spread must land inside the drawing's band, not just the nominal one
        at, lt = core.al_tol_pct / 100, d.l_tol_pct / 100
        lo, hi, d_lo, d_hi = l_calc * (1 - at), l_calc * (1 + at), l_stated * (1 - lt), l_stated * (1 + lt)
        ok = lo >= d_lo and hi <= d_hi
        tex += [rf"\text{{core spread: }} {_f(lo, 4)}\text{{ to }} {_f(hi, 4)}\,\mu\mathrm{{H}}\ (\pm {_f(core.al_tol_pct)}\%)",
                rf"\text{{drawing band: }} {_f(d_lo, 4)}\text{{ to }} {_f(d_hi, 4)}\,\mu\mathrm{{H}}\ ({_f(l_stated, 4)} \pm {_f(d.l_tol_pct)}\%)"]
        hint = "" if abs(err) <= at else (" (looks like a unit slip)" if abs(math.log10(l_stated / l_calc)) > 0.9 else " (check the turns count)")
        band = (f"; every core in the ±{_f(core.al_tol_pct)}% Aₗ spread ({_fmt_l(lo)} to {_fmt_l(hi)}) lands inside the drawing's {_fmt_l(d_lo)} to {_fmt_l(d_hi)}" if ok
                else f"; the ±{_f(core.al_tol_pct)}% Aₗ spread ({_fmt_l(lo)} to {_fmt_l(hi)}) leaves the drawing's {_fmt_l(d_lo)} to {_fmt_l(d_hi)} band")
        out.append(Check("inductance", "Stated inductance matches Aₗ × N²", PASS if ok else FLAG,
                         f"drawing {d.l_text} vs {_fmt_l(l_calc)} from the core and turns: {err * 100:+.1f}%{hint}{band}", tex))
    if core.family == "toroid":
        h_oe = 0.4 * math.pi * w.turns * d.i_pk_a / (core.le_mm / 10)
        pct = 80 if limits["toroid_bias_limit"] == "h80" else 50
        lim = core.h80_oe if pct == 80 else core.h50_oe
        ok = h_oe <= lim
        tex = [rf"H_{{pk}} = \frac{{0.4\pi N I_{{pk}}}}{{l_e}} = \frac{{0.4\pi \times {w.turns} \times {_f(d.i_pk_a)}\,\mathrm{{A}}}}{{{_f(core.le_mm / 10, 4)}\,\mathrm{{cm}}}} = {_f(h_oe)}\,\mathrm{{Oe}}",
               rf"\text{{limit: }} H_{{{pct}\%}} = {_f(lim)}\,\mathrm{{Oe}} \quad (\text{{data sheet min.: }} {pct}\% \text{{ of }} \mu_i)"]
        out.append(Check("dc_bias", f"Peak current keeps {pct}% of the inductance", PASS if ok else FLAG,
                         f"{_f(h_oe)} Oe at {_f(d.i_pk_a)} A peak vs {_f(lim)} Oe limit" + ("" if ok else f": the core loses more than {100 - pct}% of its inductance"), tex))
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
                     f"drawing requires {d.lm_text} minimum; core and turns give at least {_fmt_l(lm_min_calc)}", tex))
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
                     f"{_f(b_mt)} mT vs {_f(lim)} mT ({limits['bsat_margin'] * 100:.0f}% of {_f(core.bsat_mt)} mT Bₛₐₜ)",
                     [rf"B_{{pk}} = \frac{{V_{{pri}}}}{{4 f N_p A_e}} = \frac{{{_f(d.v_pri)}\,\mathrm{{V}}}}{{4 \times {_f(d.f_khz)}\,\mathrm{{kHz}} \times {p.turns} \times {_f(core.ae_mm2)}\,\mathrm{{mm^2}}}} = {_f(b_mt)}\,\mathrm{{mT}}",
                      rf"\text{{limit: }} {limits['bsat_margin']:g} \times B_{{sat}} = {_f(lim)}\,\mathrm{{mT}} \quad \text{{(square-wave drive, full primary voltage)}}"]))
    # Not modelled, but shown so a pass can't be read as covering it: skin effect at the switching frequency.
    delta = 66.2 / math.sqrt(d.f_khz * 1e3)  # mm, copper at 20 °C
    w = max(d.windings, key=lambda x: awg_area_mm2(x.awg))
    r_over_d = math.sqrt(awg_area_mm2(w.awg) / math.pi) / delta
    out.append(Check("ac_loss", "AC winding loss (skin and proximity effect)", NA,
                     f"not modelled in v1: at {d.f_khz:g} kHz the skin depth is {delta:.2f} mm, and the {w.awg} AWG {w.name} wire is "
                     f"{r_over_d:.1f} skin depths in radius; a production design would use Litz wire or foil and check AC resistance",
                     [rf"\delta = \frac{{66.2}}{{\sqrt{{f}}}}\,\mathrm{{mm}} = \frac{{66.2}}{{\sqrt{{{d.f_khz * 1e3:.0f}}}}} = {delta:.3f}\,\mathrm{{mm}} \quad (\text{{copper, 20}}\,{{}}^\circ\mathrm{{C}})"]))
    return out


def bobbin_build(core: Core, windings: list[tuple[str, int, int, int]], limits: dict) -> dict:
    """Lay the windings out on an E-core bobbin, to scale: turns per layer limited by the breadth
    between the margin tapes, layers balanced and space-wound across that breadth, stacking
    outward from the bobbin wall, tape between windings and over the outside. Shared by the
    check and the drawing."""
    w_win, h_win = core.wa_mm2 / (2 * core.ht_mm), 2 * core.ht_mm  # one window of the pair (bare)
    wall, margin, tape = limits["bobbin_wall_mm"], limits["margin_mm"], limits["tape_layer_mm"]
    y0, y1 = wall + margin, h_win - wall - margin
    x, conductors, spans, tapes, layers = wall, [], [], [], []
    for k, (name, turns, strands, awg) in enumerate(windings):
        d = _wire_od(awg)
        per = max(1, int((y1 - y0) // d))
        n = turns * strands
        # Balanced layers, each spread evenly across the breadth (space-wound), as good practice
        # winds them: 24 turns on a 16-turn layer go on as 12 + 12, not 16 + 8.
        n_layers = -(-n // per)
        x_start = x
        for layer in range(n_layers):
            cnt = n // n_layers + (1 if layer < n % n_layers else 0)
            pitch = (y1 - y0) / cnt
            step = d * limits.get("build_factor", 1.0)  # layers never nest perfectly: allow some bulge
            for j in range(cnt):
                conductors.append((k, x + step / 2, y0 + pitch * (j + 0.5), d / 2))
            layers.append((name, step, cnt))
            x += step
        spans.append((k, x_start, x))
        t = tape * (limits["tape_layers_between"] if k < len(windings) - 1 else limits["tape_layers_outer"])
        tapes.append((x, x + t))
        x += t
    return {"w": w_win, "h": h_win, "wall": wall, "margin": margin, "y0": y0, "y1": y1, "build": x,
            "fits": x <= w_win, "conductors": conductors, "spans": spans, "tapes": tapes, "layers": layers}


def _copper_checks(d: Design, core: Core, limits: dict) -> list[Check]:
    out = []
    worst, tex = 0.0, []
    for w in d.windings:
        a = awg_area_mm2(w.awg) * w.strands
        j = w.i_rms_a / a
        worst = max(worst, j)
        tex.append(rf"J_{{{w.name}}} = \frac{{{_f(w.i_rms_a)}\,\mathrm{{A}}}}{{{w.strands} \times {_f(awg_area_mm2(w.awg), 4)}\,\mathrm{{mm^2}}\ (\mathrm{{{w.awg}\ AWG}})}} = {_f(j)}\,\mathrm{{A/mm^2}}")
    ok = worst <= limits["j_max_a_per_mm2"]
    tex.append(rf"\text{{limit: }} {_f(limits['j_max_a_per_mm2'])}\,\mathrm{{A/mm^2}} \quad \text{{(assumption)}}")
    out.append(Check("current_density", "Wire is thick enough for the current", PASS if ok else FLAG,
                     f"worst winding {_f(worst)} A/mm² vs {_f(limits['j_max_a_per_mm2'])} A/mm²" + ("" if ok else ": wire too thin, it will run hot"), tex))
    if core.family != "toroid":
        b = bobbin_build(core, [(w.name, w.turns, w.strands, w.awg) for w in d.windings], limits)
        per_w = {}
        for name, dia, _ in b["layers"]:
            per_w.setdefault(name, []).append(dia)
        terms = " + ".join(f"{len(v)} \\times {_f(v[0])}" for v in per_w.values())
        tape_total = sum(t1 - t0 for t0, t1 in b["tapes"])
        out.append(Check("window_fill", "Windings fit the bobbin with insulation", PASS if b["fits"] else FLAG,
                         f"winding build {b['build']:.2f} mm of the {b['w']:.2f} mm window ({b['build'] / b['w'] * 100:.0f}%), "
                         f"with a {_f(b['wall'])} mm bobbin wall, {_f(b['margin'])} mm margin tape at each end, and tape between and over the windings"
                         + ("" if b["fits"] else ": it won't fit with this insulation"),
                         [rf"\text{{build}} = \underbrace{{{_f(b['wall'])}}}_{{\text{{bobbin}}}} + \underbrace{{{terms}}}_{{\text{{layers}} \times {limits.get('build_factor', 1.0):g}\,d_{{ins}}}} + \underbrace{{{_f(tape_total)}}}_{{\text{{tape}}}} = {b['build']:.2f}\,\mathrm{{mm}} \le {b['w']:.2f}\,\mathrm{{mm}}",
                          rf"\text{{breadth between margins}} = {_f(b['h'])} - 2({_f(b['wall'])} + {_f(b['margin'])}) = {_f(b['y1'] - b['y0'])}\,\mathrm{{mm}} \quad \text{{(assumptions)}}"]))
        return out
    # winding factor counts wire with its enamel, as Magnetics' 40% winding factor does
    cu = sum(w.turns * w.strands * math.pi * _wire_od(w.awg) ** 2 / 4 for w in d.windings)
    fill = cu / core.wa_mm2
    lim = limits["fill_max_toroid"]
    ok = fill <= lim
    out.append(Check("window_fill", "Winding fits the core window", PASS if ok else FLAG,
                     f"wire (with enamel) fills {fill * 100:.0f}% of the window vs a {lim * 100:.0f}% winding factor" + ("" if ok else ": the winding won't fit"),
                     [rf"\frac{{\sum N \cdot n \cdot \pi d_{{ins}}^2/4}}{{W_a}} = \frac{{{_f(cu, 4)}\,\mathrm{{mm^2}}}}{{{_f(core.wa_mm2, 4)}\,\mathrm{{mm^2}}}} = {fill * 100:.0f}\% \le {lim * 100:.0f}\%"]))
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

    core_txt = f"{d.core}, 2 PCS (PAIR) + BOBBIN" if d.kind == "transformer" else d.core
    y = table(300, H - 70, "CORE", ["CORE PART NUMBER"], [[core_txt]], [300])
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
    c.setFont("Helvetica", 7)
    c.drawRightString(x0 + 282, y0 + 62, "SHEET 1 OF 1   SCALE: NONE   UNITS: mm")
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, 150, "NOTES")
    c.setFont("Helvetica", 8)
    y = 136
    lim = load_limits(Path(__file__).resolve().parents[2] / "specs" / "magnetics" / "limits.yaml")
    build = (["5. MAGNET WIRE: HEAVY BUILD (DOUBLE COAT), CLASS 200 °C.",
              f"6. MARGIN TAPE {lim['margin_mm']:g} mm EACH END OF WINDING BREADTH.",
              f"7. {lim['tape_layers_between']} LAYERS {lim['tape_layer_mm']:g} mm POLYESTER TAPE PRI TO SEC; {lim['tape_layers_outer']} OVER THE OUTSIDE."]
             if d.kind == "transformer" else
             ["5. MAGNET WIRE: HEAVY BUILD (DOUBLE COAT), CLASS 200 °C.",
              "6. TAPE-WRAP CORE BEFORE WINDING; HIPOT DOES NOT RELY ON THE CORE COATING."])
    for n in ["1. WIND EVENLY IN ONE DIRECTION; LEADS AS SHOWN.", "2. VARNISH IMPREGNATE AFTER WINDING.",
              "3. MARK WITH DRAWING NUMBER AND DATE CODE.", "4. SYNTHETIC EXAMPLE FOR A SOFTWARE DEMO; NOT FOR MANUFACTURE.",
              *build, *d.notes]:
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
        take("core", core.split(",")[0].strip(), core)  # "E32/16/9-3C94, 2 PCS (PAIR) + BOBBIN" -> the part number
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
# Which evidence explains a verdict: the tab the page opens first.
TAB_FOR_CHECK = {"inductance": "curve", "dc_bias": "curve", "window_fill": "winding", "current_density": "winding",
                 "core_known": "drawing", "ratio": "drawing", "magnetizing": "drawing", "flux": "flux"}


def default_tab(checks: list[Check], has_curve: bool, has_flux: bool = False) -> str:
    for c in checks:
        if c.status == FLAG:
            tab = TAB_FOR_CHECK.get(c.id, "drawing")
            return "winding" if tab == "curve" and not has_curve else tab
    return "curve" if has_curve else ("flux" if has_flux else "winding")


def _named_figures(core: Core | None, d: Design, limits: dict) -> dict[str, str | None]:
    if core is None:
        return {"curve": None, "winding": None}
    win = svg_window(core, [(w.name, w.turns, w.strands, w.awg) for w in d.windings], limits=limits)
    curve = (svg_l_vs_i(core, d.windings[0].turns, d.i_pk_a, parse_inductance_uh(d.l_text), ref_at="zero")
             if d.kind == "inductor" and core.family == "toroid" else None)
    flux = svg_flux(core, d, limits["bsat_margin"]) if d.kind == "transformer" and core.bsat_mt else None
    return {"curve": curve, "flux": flux, "winding": win}


def svg_flux(core: Core, d: Design, margin: float) -> str:
    """Transformer evidence: peak flux density (square-wave drive) against the core's B_sat."""
    p = d.windings[0]
    b = d.v_pri / (4 * d.f_khz * 1e3 * p.turns * core.ae_mm2 * 1e-6) * 1e3
    lim, sat = margin * core.bsat_mt, core.bsat_mt
    W, x0, x1, yb, hb = 420, 20, 400, 40, 22
    x = lambda v: x0 + min(v, sat) / sat * (x1 - x0)  # noqa: E731
    over = b > lim
    g = (f'<rect class="fx-bar" x="{x0}" y="{yb}" width="{x1 - x0}" height="{hb}" rx="3"/>'
         f'<rect class="fx-hot" x="{x(lim):.1f}" y="{yb}" width="{x1 - x(lim):.1f}" height="{hb}"/>'
         f'<rect class="fx-val{" bad" if over else ""}" x="{x0}" y="{yb + 5}" width="{x(b) - x0:.1f}" height="{hb - 10}" rx="2"/>'
         f'<line class="fx-lim" x1="{x(lim):.1f}" x2="{x(lim):.1f}" y1="{yb - 6}" y2="{yb + hb + 6}"/>'
         f'<text class="mc-t" x="{x(lim):.1f}" y="{yb - 10}" text-anchor="middle">limit {lim:.0f} mT ({margin * 100:.0f}% of Bₛₐₜ)</text>'
         f'<text class="mc-t" x="{x1}" y="{yb + hb + 18}" text-anchor="end">Bₛₐₜ {sat:.0f} mT (min, 100 °C)</text>'
         f'<text class="mc-t" x="{x0}" y="{yb + hb + 18}">0</text>'
         f'<text class="mc-t fx-num" x="{x(b) + 6:.1f}" y="{yb + hb / 2 + 4}">{b:.0f} mT</text>')
    cap = (f"{core.name}, {p.turns} primary turns at {d.v_pri:g} V square, {d.f_khz:g} kHz: peak flux {b:.0f} mT, "
           f"{b / sat * 100:.0f}% of Bₛₐₜ. " + ("Over the limit: the core would run into saturation." if over else
           "Headroom for input transients and start-up flux walking."))
    return f'<figure class="mfig"><svg viewBox="0 0 {W} 92" role="img" aria-label="Peak flux {b:.0f} mT versus limit {lim:.0f} mT">{g}</svg><figcaption>{cap}</figcaption></figure>'


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
            "i_pk_a": rec.i_pk_a, "l_tol_pct": rec.l_tol_pct, "v_pri": rec.v_pri, "f_khz": rec.f_khz,
            "windings": [dataclasses.asdict(w) for w in rec.windings],
            "source": x["source"],
            "scope": "Modeled checks only; core loss, AC winding loss, and temperature rise are not evaluated.",
            "checks": [dataclasses.asdict(c) for c in checks],
            "flagged": any(c.status == FLAG for c in checks),
            "fig": _named_figures(core, rec, limits),
            "default_tab": default_tab(checks, core is not None and rec.kind == "inductor" and core.family == "toroid",
                                       core is not None and rec.kind == "transformer" and bool(core.bsat_mt)),
        })
    sim = similar(extracted)
    for r in recs:
        r["similar"] = [{"id": i, "distance": dist} for i, dist in sim[r["id"]]]
    return {
        "records": recs,
        "cores": [dataclasses.asdict(c) for c in cores.values()],
        "limits": limits,
    }


# ---- sizing: requirement -> candidate designs (first pass, deterministic) ----------------
MAX_STACK = 4
WIRES = [(awg, n) for awg in range(10, 25) for n in range(1, 7)]


def _fit_pct(fit: tuple[float, float, float], h_oe: float) -> float:
    a, b, c = fit
    return 1 / (a + b * h_oe ** c) / 100


def _fit_h(fit: tuple[float, float, float], frac: float) -> float:
    """Magnetizing force at which the vendor's typical curve falls to frac of initial permeability."""
    a, b, c = fit
    return ((1 / (frac * 100) - a) / b) ** (1 / c)


def derating(core: Core) -> float:
    """Scale on H so the vendor's typical curve passes at or below both guaranteed data sheet
    points (80% at H80 minimum, 50% at H50 minimum)."""
    return max(_fit_h(core.fit, 0.8) / core.h80_oe, _fit_h(core.fit, 0.5) / core.h50_oe)


def typical(core: Core, h_oe: float) -> float | None:
    """Vendor typical curve (catalog fit), or None when no fit is on file."""
    return _fit_pct(core.fit, h_oe) if core.fit else None


def retained(core: Core, h_oe: float) -> float | None:
    """Estimated fraction of initial permeability at magnetizing force h: the vendor's curve
    adjusted to the data sheet minimum points (or, without a fit, straight lines between the data
    sheet's 100/80/50% points). None past the data sheet's 50% point: no extrapolation."""
    if h_oe > core.h50_oe:
        return None
    if core.fit:
        return _fit_pct(core.fit, h_oe * derating(core))
    if h_oe <= core.h80_oe:
        return 1 - 0.2 * h_oe / core.h80_oe
    return 0.8 - 0.3 * (h_oe - core.h80_oe) / (core.h50_oe - core.h80_oe)


def pick_wire(i_rms: float, j_max: float) -> tuple[int, int, float]:
    """Copper (AWG 10-24, 1-6 strands) carrying i_rms at or below j_max: among choices within 10% of
    the smallest area, the fewest strands (a winder prefers one wire unless skin depth argues
    otherwise, which this first pass doesn't model)."""
    need = i_rms / j_max
    ok = [w for w in WIRES if awg_area_mm2(w[0]) * w[1] >= need]
    if not ok:
        raise ValueError("Wire catalog insufficient for the requested RMS current (AWG 10–24, up to 6 strands).")
    smallest = min(awg_area_mm2(a) * n for a, n in ok)
    awg, n = min((w for w in ok if awg_area_mm2(w[0]) * w[1] <= smallest * 1.10), key=lambda w: (w[1], awg_area_mm2(w[0]) * w[1]))
    return awg, n, awg_area_mm2(awg) * n


def size_inductor(cores: dict[str, Core], limits: dict, l_uh: float, i_rms: float, i_pk: float, min_retained: float = 0.5) -> dict:
    """Every toroid in the catalog, stacked 1..MAX_STACK: the fewest turns giving at least l_uh
    at the peak current while keeping at least min_retained of the inductance, then the
    smallest wire for the current, then window fill. Returns passing candidates ranked by
    core volume and copper, and why each core failed otherwise."""
    for label, value in (("Inductance", l_uh), ("RMS current", i_rms), ("Peak current", i_pk)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be a finite positive number.")
    if i_pk < i_rms:
        raise ValueError("Peak current must be at least the RMS current.")
    if not math.isfinite(min_retained) or not 0.5 <= min_retained <= 1:
        raise ValueError("Retained inductance must be between 50% and 100%.")
    j_max, fill_max = limits["j_max_a_per_mm2"], limits["fill_max_toroid"]
    try:
        wire = pick_wire(i_rms, j_max)
    except ValueError as exc:
        return {"candidates": [], "rejected": [], "error": str(exc)}
    passing, rejected = [], []
    for core in (c for c in cores.values() if c.family == "toroid"):
        reason = ""
        for n in range(1, MAX_STACK + 1):
            al = core.al_nh * n * (1 - core.al_tol_pct / 100)  # minimum A_L: every core in the spread must make it
            le_cm = core.le_mm / 10
            found = None
            for turns in range(1, 600):
                h = 0.4 * math.pi * turns * i_pk / le_cm
                f = retained(core, h)
                if f is None or f < min_retained:
                    reason = (f"×{n} stack: at {turns} turns the core is past its {min_retained * 100:.0f}% point at {_f(i_pk)} A peak; "
                              f"best case {_fmt_l(al * (turns - 1) ** 2 * (retained(core, 0.4 * math.pi * (turns - 1) * i_pk / le_cm) or 0) / 1000)} at peak")
                    break
                l_pk = al * turns * turns * f / 1000
                if l_pk >= l_uh:
                    found = (turns, h, f, l_pk)
                    break
            if not found:
                continue
            turns, h, f, l_pk = found
            awg, strands, cu = wire
            fill = turns * strands * math.pi * _wire_od(awg) ** 2 / 4 / core.wa_mm2  # with enamel, as the check
            if fill > fill_max:
                reason = f"×{n} stack: {turns} turns of {strands} × {awg} AWG fill {fill * 100:.0f}% of the window (limit {fill_max * 100:.0f}%)"
                continue
            l0 = al * turns * turns / 1000
            passing.append({
                "core": core.name, "stack": n, "turns": turns, "awg": awg, "strands": strands,
                "l0_uh": l0, "l_pk_uh": l_pk, "retained": f, "h_oe": h, "j": i_rms / cu, "fill": fill,
                "core_volume_mm3": core.ve_mm3 * n, "copper_mm2": cu, "material": core.material,
                "height_mm": (core.ht_mm or 0) * n,  # core stack height, before winding
                "fig": {"curve": svg_l_vs_i(core, turns, i_pk, l_uh, n, al_scale=1 - core.al_tol_pct / 100), "winding": svg_window(core, [("W1", turns, strands, awg)], n)},
                "latex": [
                    rf"H_{{pk}} = \frac{{0.4\pi \times {turns} \times {_f(i_pk)}\,\mathrm{{A}}}}{{{_f(le_cm, 4)}\,\mathrm{{cm}}}} = {_f(h)}\,\mathrm{{Oe}} \;\Rightarrow\; {f * 100:.0f}\%\ \text{{of }} A_L \text{{ remains}}",
                    rf"A_{{L,\min}} = {_f(core.al_nh)}\,\mathrm{{nH}} \times (1 - {_f(core.al_tol_pct)}\%) = {_f(core.al_nh * (1 - core.al_tol_pct / 100), 4)}\,\mathrm{{nH}}",
                    rf"L(I_{{pk}}) = {n} \times {_f(core.al_nh * (1 - core.al_tol_pct / 100), 4)}\,\mathrm{{nH}} \times {turns}^2 \times {f:.4f} = {_f(l_pk, 4)}\,\mu\mathrm{{H}} \geq {_f(l_uh, 4)}\,\mu\mathrm{{H}}",
                    rf"J = \frac{{{_f(i_rms)}\,\mathrm{{A}}}}{{{strands} \times {_f(awg_area_mm2(awg), 4)}\,\mathrm{{mm^2}}}} = {_f(i_rms / cu)}\,\mathrm{{A/mm^2}}",
                    rf"\text{{fill}} = \frac{{{turns} \times {strands} \times \pi \times ({_wire_od(awg):.3f}\,\mathrm{{mm}})^2/4}}{{{_f(core.wa_mm2)}\,\mathrm{{mm^2}}}} = {fill * 100:.0f}\%",
                ],
            })
            break
        else:
            rejected.append({"core": core.name, "reason": reason or "no turns count reaches the inductance"})
    passing.sort(key=lambda c: (c["core_volume_mm3"], c["copper_mm2"]))
    return {"candidates": passing, "rejected": rejected}


def screening_scope(application: str = "dc_bias") -> dict:
    if application not in {"dc_bias", "pfc", "ac_output"}:
        raise ValueError("Unknown inductor application.")
    return {
        "application": application,
        "verdict": "Screening only · passes modeled constraints, not a validated design",
        "curve": "Inductance at peak is estimated from an adjusted vendor typical DC-bias curve; the curve between guaranteed points is not guaranteed.",
        "remaining": ("AC output: large AC excitation requires separate loss and permeability validation. " if application == "ac_output" else "")
                     + "Core loss, AC winding loss, and temperature rise are not evaluated.",
    }


def size_json(specs_dir: str, request_json: str) -> str:
    """Browser entry point (Pyodide): JSON in, JSON out."""
    import json

    req = json.loads(request_json)
    specs = Path(specs_dir) / "magnetics"
    out = size_inductor(load_cores(specs / "cores.csv"), load_limits(specs / "limits.yaml"),
                        float(req["l_uh"]), float(req["i_rms"]), float(req["i_pk"]), float(req.get("min_retained", 0.5)))
    out["scope"] = screening_scope(req.get("application", "dc_bias"))
    if not out["candidates"]:
        out["scope"]["verdict"] = "Screening only · no candidate passes modeled constraints"
    out["past"] = closest_past(req.get("past", []), float(req["l_uh"]), float(req["i_rms"]))
    return json.dumps(out)


def closest_past(past: list[dict], l_uh: float, i_a: float, k: int = 3) -> list[dict]:
    """Past inductor records nearest a requirement, by log-scaled inductance and current."""
    def dist(p):
        return math.hypot(math.log10(max(p["l_uh"], 1e-9) / l_uh), math.log10(max(p["i_a"], 1e-9) / i_a))
    near = sorted((p for p in past if p.get("kind") == "inductor"), key=dist)[:k]
    return [{"id": p["id"], "distance": round(dist(p), 3)} for p in near]


# ---- drawings for the page: window cross-section and inductance vs current (SVG) ---------
def _wire_od(awg: int) -> float:
    """Bare diameter plus ~8% for heavy-build magnet-wire enamel (approximation for drawing)."""
    return 0.127 * 92 ** ((36 - awg) / 39) * 1.08


def svg_window(core: Core, windings: list[tuple[str, int, int, int]], stack: int = 1, limits: dict | None = None) -> str:
    """Cross-section through the core window with every wire drawn to scale.
    windings: (name, turns, strands, awg). Wires are packed in layers along the window edge."""
    wires = [(k, _wire_od(awg)) for k, (_, turns, strands, awg) in enumerate(windings) for _ in range(turns * strands)]
    cu = sum(t * n * math.pi * _wire_od(a) ** 2 / 4 for _, t, n, a in windings)  # with enamel
    fill = cu / core.wa_mm2
    placed, overflow = [], 0
    if core.family == "toroid":
        r_out, r_in = core.od_mm / 2, math.sqrt(core.wa_mm2 / math.pi)  # window = data sheet W_a (coated)
        i, layer_r, layer = 0, None, -1
        spokes = []
        while i < len(wires):
            d = wires[i][1]
            layer_r = (r_in - d / 2) if layer_r is None else layer_r - d
            layer += 1
            if layer_r < d / 2:
                overflow = len(wires) - i
                break
            cap = max(1, int(2 * math.pi * layer_r / d))
            count = min(cap, len(wires) - i)  # spread each layer evenly around the core, as it is wound
            for j in range(count):
                a = 2 * math.pi * j / count - math.pi / 2
                placed.append((wires[i][0], layer_r * math.cos(a), layer_r * math.sin(a), wires[i][1] / 2))
                r_o = r_out + d / 2 + layer * d  # the same turn returns around the outside, one layer further out
                spokes.append((wires[i][0], layer_r, r_o, a, d))
                i += 1
        vb = r_out + (layer + 1) * (wires[0][1] if wires else 0) + 3
        # From above only the last-wound (top) layer is visible; the layers under it show as copper
        # build-up around the outside edge.
        top = [sp for sp in spokes if sp[2] == max(x[2] for x in spokes)] if spokes else []
        build = (max(x[2] for x in spokes) - r_out - spokes[0][4] / 2) if spokes else 0
        spoke_svg = (f'<circle class="mw-build" cx="0" cy="0" r="{r_out + build / 2:.2f}" stroke-width="{build:.2f}"/>' if build > 0 else "") + "".join(
            f'<line class="mw-s{k}" x1="{ri * math.cos(a):.2f}" y1="{ri * math.sin(a):.2f}" x2="{ro * math.cos(a):.2f}" y2="{ro * math.sin(a):.2f}" stroke-width="{d * 0.9:.3f}"/>'
            f'<circle class="mw-w{k}" cx="{ro * math.cos(a):.2f}" cy="{ro * math.sin(a):.2f}" r="{d / 2:.3f}"/>'
            for k, ri, ro, a, d in top)
        body = (f'<path class="mw-core" fill-rule="evenodd" d="M{-r_out:.2f},0a{r_out:.2f},{r_out:.2f} 0 1,0 {2 * r_out:.2f},0a{r_out:.2f},{r_out:.2f} 0 1,0 {-2 * r_out:.2f},0'
                f'M{-r_in:.2f},0a{r_in:.2f},{r_in:.2f} 0 1,0 {2 * r_in:.2f},0a{r_in:.2f},{r_in:.2f} 0 1,0 {-2 * r_in:.2f},0"/>') + spoke_svg
        view = f"{-vb:.1f} {-vb:.1f} {2 * vb:.1f} {2 * vb:.1f}"
    else:
        if limits is None:
            raise ValueError("E-core drawings need the construction limits (bobbin, margins, tape)")
        bb = bobbin_build(core, windings, limits)
        w, h, wall, y0, y1 = bb["w"], bb["h"], bb["wall"], bb["y0"], bb["y1"]
        placed = list(bb["conductors"])
        overflow = 0 if bb["fits"] else sum(1 for c in placed if c[1] + c[3] > w)
        t = core.id_mm / 2  # half center leg (cut at the symmetry line); outer leg and yokes drawn at the same width
        x_end = bb["build"]
        parts = [f'<path class="mw-core" fill-rule="evenodd" d="M{-t:.2f},{-t:.2f}h{t + w + t:.2f}v{h + 2 * t:.2f}h{-(t + w + t):.2f}z'
                 f'M0,0h{w:.2f}v{h:.2f}h{-w:.2f}z"/>',
                 f'<line class="mw-cut" x1="{-t:.2f}" y1="{-t:.2f}" x2="{-t:.2f}" y2="{h + t:.2f}"/>',
                 f'<rect class="mw-win" x="0" y="0" width="{w:.2f}" height="{h:.2f}"/>',
                 # bobbin: wall along the center leg and flanges at both ends
                 f'<rect class="mw-bob" x="0" y="0" width="{wall:.2f}" height="{h:.2f}"/>',
                 f'<rect class="mw-bob" x="0" y="0" width="{min(x_end, w):.2f}" height="{wall:.2f}"/>',
                 f'<rect class="mw-bob" x="0" y="{h - wall:.2f}" width="{min(x_end, w):.2f}" height="{wall:.2f}"/>']
        for _, xs, xe in bb["spans"]:  # margin tape at both ends of each winding
            parts.append(f'<rect class="mw-margin" x="{xs:.2f}" y="{wall:.2f}" width="{xe - xs:.2f}" height="{y0 - wall:.2f}"/>'
                         f'<rect class="mw-margin" x="{xs:.2f}" y="{y1:.2f}" width="{xe - xs:.2f}" height="{y0 - wall:.2f}"/>')
        for xs, xe in bb["tapes"]:
            parts.append(f'<rect class="mw-tape" x="{xs:.2f}" y="{wall:.2f}" width="{max(xe - xs, 0.12):.2f}" height="{h - 2 * wall:.2f}"/>')
        body = "".join(parts)
        view = f"{-t - 2:.1f} {-t - 2:.1f} {w + 2 * t + 4:.1f} {h + 2 * t + 4:.1f}"
    circles = "".join(f'<circle class="mw-w{k}" cx="{x:.2f}" cy="{y:.2f}" r="{r:.3f}"/>' for k, x, y, r in placed)
    label = ", ".join(f"{name}: {t} turns of {n} × {a} AWG" for name, t, n, a in windings)
    if core.family != "toroid":
        note = (f"bobbin wall {_f(limits['bobbin_wall_mm'])} mm (grey), margin tape {_f(limits['margin_mm'])} mm at each end (tan), "
                f"{limits['tape_layers_between']} tape layers between windings; build {bb['build']:.2f} of {bb['w']:.2f} mm"
                + ("" if bb["fits"] else ", doesn't fit"))
        size = "bigfig" if overflow else "winfig"
        circles = "".join(f'<circle class="mw-w{k}" cx="{x:.2f}" cy="{y:.2f}" r="{r:.3f}"/>' for k, x, y, r in placed)
        t = core.id_mm / 2
        # Presentation only: retain the shared bobbin geometry, with build upward.
        scale = min(380 / h, 150 / max(w, bb["build"]))
        left, bottom = 65, 225
        right, top = left + h * scale, bottom - w * scale
        build_top = bottom - bb["build"] * scale
        def dim(x1, y1, x2, y2, text, tx, ty):
            return (f'<path class="mw-dimension" d="M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}" marker-start="url(#mw-arrow)" marker-end="url(#mw-arrow)"/>'
                    f'<text class="mw-label" x="{tx:.2f}" y="{ty:.2f}" text-anchor="middle">{text}</text>')
        annotations = dim(left, 265, right, 265, f"{h:.2f} mm window breadth", (left + right) / 2, 285)
        annotations += dim(40, top, 40, bottom, f"{w:.2f} mm available", 105, top - 12)
        annotations += dim(right + 18, build_top, right + 18, bottom, "", 0, 0)
        annotations += f'<text class="mw-label" x="{right + 20:.2f}" y="245">{bb["build"]:.2f} mm build</text>'
        for k, xs, xe in bb["spans"]:
            name, turns, strands, awg = windings[k]
            title = {"PRI": "Primary", "SEC": "Secondary", "AUX": "Auxiliary"}.get(name.upper(), name)
            yy = bottom - (xs + xe) / 2 * scale
            ly = top + 2 + (len(bb["spans"]) - 1 - k) * 64
            annotations += (f'<path class="mw-leader" d="M{right - 35:.2f},{yy:.2f} L{right + 20:.2f},{ly + 7}"/>'
                            f'<text class="mw-label" x="{right + 25:.2f}" y="{ly - 9}">{title}<tspan x="{right + 25:.2f}" dy="19">{turns} turns</tspan><tspan x="{right + 25:.2f}" dy="19">{strands} × {awg} AWG</tspan></text>')
        if bb["tapes"]:
            xs, xe = bb["tapes"][0]
            yy = bottom - (xs + xe) / 2 * scale
            annotations += (f'<path class="mw-leader" d="M{left + 25:.2f},{yy:.2f} L{left + 140},{top - 5:.2f} H{left + 300}"/>'
                            f'<text class="mw-label" x="{left + 145}" y="{top - 12:.2f}">Insulation tape</text>')
        annotations += f'<text class="mw-label" x="{left:.2f}" y="310">Bobbin wall {wall:.2f} mm · end margins {limits["margin_mm"]:g} mm</text>'
        crop_top = max(0, top - 36)  # remove unused canvas without changing drawing scale
        rview = f"0 {crop_top:.2f} 600 {325 - crop_top:.2f}"
        section_body = (f'<rect class="mw-core" x="-1.5" y="0" width="1.5" height="{h:.2f}"/>' + "".join(parts[2:]))
        diagram = (f'<defs><marker id="mw-arrow" viewBox="0 0 8 8" refX="4" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8" fill="none" stroke="currentColor"/></marker></defs>'
                   f'<g transform="translate({left} {bottom}) scale({scale:.5f}) rotate(-90)">{section_body}{circles}</g>{annotations}')
        dimensions = (f'<dl class="winding-dimensions"><div><dt>Window</dt><dd>{w:.2f} × {h:.2f} mm</dd></div>'
                      f'<div><dt>Winding build</dt><dd>{bb["build"]:.2f} / {w:.2f} mm</dd></div>'
                      f'<div><dt>Bobbin wall</dt><dd>{wall:.2f} mm</dd></div>'
                      f'<div><dt>End margin</dt><dd>{limits["margin_mm"]:g} mm</dd></div></dl>')
        return ('<section class="winding-evidence"><h4>Winding cross-section</h4>'
                + dimensions + f'<figure class="mfig winding-section {size}"><svg viewBox="{rview}" role="img" aria-label="Winding window: {label}; build {bb["build"]:.2f} of {bb["w"]:.2f} mm">'
                f'{diagram}</svg>'
                f'<figcaption>E-core window (one side), to scale, center leg at the bottom · {note}</figcaption></figure>'
                '<p class="winding-caveat">Idealized section using the demo bobbin and insulation assumptions. Not a winding instruction or validated insulation design.</p></section>')
    note = (f"{len(wires) - overflow} of {len(wires)} conductors drawn at ideal packing" + (f"; {overflow} don't fit even then" if overflow else "")
            + ("; the 40% winding factor leaves room for the shuttle, lead-outs and uneven layers" if core.family == "toroid" else ""))
    opening_view = f"{-r_in - 2:.2f} {-r_in - 2:.2f} {2 * r_in + 4:.2f} {2 * r_in + 4:.2f}"
    dimensions = (f'<dl class="winding-dimensions"><div><dt>Catalog core OD</dt><dd>{core.od_mm:g} mm</dd></div>'
                  f'<div><dt>Catalog core ID</dt><dd>{core.id_mm:g} mm</dd></div>'
                  f'<div><dt>Bare stack height</dt><dd>{stack} × {core.ht_mm:g} = {stack * core.ht_mm:g} mm</dd></div>'
                  f'<div><dt>Effective opening Ø</dt><dd>{2 * r_in:.2f} mm</dd></div></dl>')
    status = "Geometric overflow" if overflow else "Ideal packing shown"
    return (f'<section class="winding-evidence"><h4>Illustrative winding arrangement</h4><p class="winding-description">{label}</p>'
            + dimensions + '<div class="winding-views">'
            f'<figure class="mfig winding-top"><svg viewBox="{view}" role="img" aria-label="Winding view: {label}; wire (with enamel) fills {fill * 100:.0f}% of the window">'
            f'{body}{circles}</svg><figcaption>Top view · simplified wire paths{f" · ×{stack} stack" if stack > 1 else ""}</figcaption></figure>'
            f'<figure class="mfig winding-section"><svg viewBox="{opening_view}" role="img" aria-label="Window occupancy: {len(placed)} of {len(wires)} conductor cross-sections, {fill * 100:.0f}% calculated fill">'
            f'<circle class="mw-window-boundary" cx="0" cy="0" r="{r_in:.2f}"/>{circles}</svg>'
            '<figcaption>Window cross-section · each disk is one insulated conductor pass</figcaption></figure></div>'
            f'<p class="winding-fit"><b>{status}</b> · wire with enamel fills {fill * 100:.0f}% of the window · {note}</p>'
            '<p class="winding-caveat">Views are scaled independently; use the dimensions above. Fill uses conductor cross-sections and catalog window area, not orange coverage. Effective opening is derived from that area. Enamel allowance is approximate; tape, leads, tooling clearance, and wound outer dimensions are not modeled. Not a manufacturing layout.</p></section>')


def svg_l_vs_i(core: Core, turns: int, i_pk: float, l_req_uh: float | None, stack: int = 1, ref_at: str = "peak", al_scale: float = 1.0) -> str:
    """Inductance vs DC current over the design's operating range (0 to 1.5x peak).
    Solid: an estimate adjusted to the data sheet minimum points, not a guaranteed envelope.
    Faint: the vendor's typical curve. Squares: the data sheet's guaranteed 80% and 50% points.
    ref_at: "peak" = l_req_uh is required at peak current (sizing); "zero" = a drawing's 0 A
    value, which says nothing about peak current (records)."""
    le_cm = core.le_mm / 10
    amps_per_oe = le_cm / (0.4 * math.pi * turns)
    h = lambda i: i / amps_per_oe  # noqa: E731
    l0 = core.al_nh * al_scale * stack * turns * turns / 1000
    i_max = 1.5 * i_pk
    W, H, ml, mb, mt, mr = 600, 250, 54, 46, 24, 18
    pw, ph = W - ml - mr, H - mb - mt
    x = lambda i: ml + i / i_max * pw  # noqa: E731
    # a drawing value up to 2x above the core's reach rescales the chart (the gap is the evidence);
    # beyond that it is pinned at the top and marked, so the curve stays readable
    off_scale = bool(l_req_uh) and l_req_uh > 2 * l0
    top = (l0 if off_scale else max(l0, l_req_uh or 0)) * 1.08
    y = lambda l: mt + (1 - l / top) * ph  # noqa: E731
    i_end = min(i_max, core.h50_oe * amps_per_oe)
    solid = " ".join(f"{x(i):.1f},{y(l0 * retained(core, min(h(i), core.h50_oe))):.1f}" for i in (i_end * k / 120 for k in range(121)))
    g = []
    # Plot values, not annotations: reference values live in the legend below.
    unit_scale, unit = (1000, "mH") if top >= 1000 else (1, "µH")
    rough = top / 4
    magnitude = 10 ** math.floor(math.log10(rough))
    tick_step = next(n * magnitude for n in (1, 2, 5, 10) if n * magnitude >= rough)
    for k in range(math.floor(top / tick_step) + 1):
        value = k * tick_step
        g.append(f'<line class="mc-g" x1="{ml}" x2="{ml + pw}" y1="{y(value):.2f}" y2="{y(value):.2f}"/>'
                 f'<text class="mc-t" x="{ml - 7}" y="{y(value) + 4:.2f}" text-anchor="end">{value / unit_scale:.3g}</text>')
    if i_end < i_max:
        g.append(f'<rect class="mc-unmodeled" x="{x(i_end):.2f}" y="{mt}" width="{x(i_max) - x(i_end):.2f}" height="{ph}"/>')
    if core.fit:
        faint = " ".join(f"{x(i):.1f},{y(l0 * typical(core, h(i))):.1f}" for i in (i_end * k / 120 for k in range(121)))
        g.append(f'<polyline class="mc-typ" points="{faint}"/>')
    g.append(f'<polyline class="mc-l" points="{solid}"/>')
    for hmin, frac in ((core.h80_oe, 0.8), (core.h50_oe, 0.5)):
        i_g = hmin * amps_per_oe
        if i_g <= i_max:
            g.append(f'<rect class="mc-min" x="{x(i_g) - 3.5:.1f}" y="{y(l0 * frac) - 3.5:.1f}" width="7" height="7"/>')
    if l_req_uh and not off_scale:
        yr = y(l_req_uh)
        g.append(f'<line class="mc-req" x1="{ml}" x2="{ml + pw}" y1="{yr:.1f}" y2="{yr:.1f}"/>')
    f_pk = retained(core, h(i_pk))
    g.append(f'<line class="mc-pk" x1="{x(i_pk):.1f}" x2="{x(i_pk):.1f}" y1="{mt}" y2="{mt + ph}"/>')
    if f_pk is not None:
        g.append(f'<circle class="mc-dot" cx="{x(i_pk):.1f}" cy="{y(l0 * f_pk):.1f}" r="3"/>')
    g.append(f'<line class="mc-ax" x1="{ml}" x2="{ml + pw}" y1="{mt + ph}" y2="{mt + ph}"/>')
    current_mag = 10 ** math.floor(math.log10(i_max / 4))
    current_step = next(n * current_mag for n in (1, 2, 5, 10) if n * current_mag >= i_max / 4)
    for k in range(math.floor(i_max / current_step) + 1):
        current = current_step * k
        anchor = "start" if k == 0 else "middle"
        g.append(f'<text class="mc-t" x="{x(current):.2f}" y="{mt + ph + 18}" text-anchor="{anchor}">{current:.3g}</text>')
    g.append(f'<text class="mc-t" x="{ml}" y="14">Inductance ({unit})</text>'
             f'<text class="mc-t" x="{ml + pw / 2}" y="{H - 4}" text-anchor="middle">DC bias current (A)</text>')
    cap = (f"{core.name}{f' ×{stack}' if stack > 1 else ''}, {turns} turns: {_fmt_l(l0)} at 0 A{' (minimum Aₗ)' if al_scale < 1 else ''}; "
           + (f"{_fmt_l(l0 * f_pk)} ({f_pk * 100:.0f}%) at {i_pk:g} A peak" if f_pk is not None else f"past the data sheet's 50% point at {i_pk:g} A")
           + (". Drawing specifies 0 A inductance only; the required inductance at peak current is unknown." if ref_at == "zero" else ".")
           + (" The curve between those points is not guaranteed; AC excitation and losses need separate validation." if core.fit else ""))
    sw = lambda body: f'<svg class="mc-sw" viewBox="0 0 22 10" aria-hidden="true">{body}</svg>'  # noqa: E731
    line = lambda cls: sw(f'<line class="{cls}" x1="1" y1="5" x2="21" y2="5"/>')  # noqa: E731
    keys = [(line("mc-l"), "adjusted estimate (not guaranteed)" if core.fit else "interpolated estimate (not guaranteed)")]
    if core.fit:
        keys.append((line("mc-typ"), "catalog typical curve"))
    keys.append((sw('<rect class="mc-min" x="7.5" y="1.5" width="7" height="7"/>'), "guaranteed minimum (80%, 50%)" + (" · outside shown range" if core.h80_oe * amps_per_oe > i_max else "")))
    if l_req_uh:
        keys.append((line("mc-req"), (f"required at peak: {_fmt_l(l_req_uh)}" if ref_at == "peak" else f"drawing: {_fmt_l(l_req_uh)} at 0 A") + (" · above plot range" if off_scale else "")))
    keys.append((sw('<line class="mc-pk" x1="11" y1="0" x2="11" y2="10"/>' + ('<circle class="mc-dot" cx="11" cy="5" r="3.5"/>' if f_pk is not None else "")),
                 f"Peak current: {i_pk:g} A" + (f" · estimated L: {_fmt_l(l0 * f_pk)}" if f_pk is not None else " · outside curve range")))
    if i_end < i_max:
        keys.append((sw('<rect class="mc-unmodeled" x="1" y="1" width="20" height="8"/>'), "Shaded region: beyond catalog curve range"))
    leg = '<div class="mc-leg">' + "".join(f"<span>{s}{t}</span>" for s, t in keys) + "</div>"
    return f'<figure class="mfig mc-chart"><svg class="mc-plot" viewBox="0 0 {W} {H}" role="img" aria-label="Inductance versus current">{"".join(g)}</svg>{leg}<figcaption>{cap}</figcaption></figure>'
