"""Magnetics demo: real core data, synthetic drawings, extraction, physics checks, search."""

import dataclasses
from pathlib import Path

import pytest
import yaml

from calgen import magnetics as mg

ROOT = Path(__file__).resolve().parent.parent
SPECS, CORPUS = ROOT / "specs" / "magnetics", ROOT / "corpus" / "magnetics"
CORES = mg.load_cores(SPECS / "cores.csv")
LIMITS = mg.load_limits(SPECS / "limits.yaml")
DESIGNS = mg.load_designs(CORPUS / "designs.yaml")
KEY = yaml.safe_load((CORPUS / "ANSWER_KEY.yaml").read_text())


def test_core_catalog_matches_data_sheet_spot_checks():
    c = CORES["0077083A7"]  # Magnetics data sheet rev 10/6/2021
    assert (c.al_nh, c.al_tol_pct, c.wa_mm2, c.ae_mm2, c.le_mm, c.h80_oe) == (81, 8, 427, 107, 98.4, 39)
    e = CORES["E32/16/9-3C94"]  # Ferroxcube 2016; window derived from (B - C)/2 x 2E
    assert (e.al_nh, e.ae_mm2, e.bsat_mt) == (2500, 83, 320)
    assert e.wa_mm2 == pytest.approx((22.70 - 9.50) / 2 * 2 * 11.20)
    assert all(c.source for c in CORES.values())


def test_awg_area_matches_standard_table():
    assert mg.awg_area_mm2(14) == pytest.approx(2.08, rel=0.01)
    assert mg.awg_area_mm2(22) == pytest.approx(0.326, rel=0.01)


def test_data_sheet_dc_bias_agrees_with_its_own_curve():
    # 0077083A7: the plotted 80% point is near 350 A·T; the table's 39 Oe minimum must sit just below it
    c = CORES["0077083A7"]
    h_at_350 = 0.4 * 3.141592653589793 * 350 / (c.le_mm / 10)
    assert c.h80_oe < h_at_350 < c.h80_oe * 1.2


@pytest.mark.parametrize("d", DESIGNS, ids=[d.id for d in DESIGNS])
def test_extraction_round_trips_every_drawing(d):
    got = mg.design_from_extract(mg.extract(CORPUS / "drawings" / f"{d.id}.pdf"))
    assert dataclasses.asdict(got) == dataclasses.asdict(dataclasses.replace(d, notes=[]))


@pytest.mark.parametrize("d", DESIGNS, ids=[d.id for d in DESIGNS])
def test_checks_on_extracted_drawings_match_blind_key(d):
    rec = mg.design_from_extract(mg.extract(CORPUS / "drawings" / f"{d.id}.pdf"))
    flagged = sorted(c.id for c in mg.check(rec, CORES, LIMITS) if c.status == mg.FLAG)
    assert flagged == sorted(KEY[d.id])


def test_key_covers_every_design_and_both_outcomes():
    assert set(KEY) == {d.id for d in DESIGNS}
    assert sum(1 for v in KEY.values() if v) >= 5 and sum(1 for v in KEY.values() if not v) >= 4


def test_committed_drawings_are_current(tmp_path):
    for d in DESIGNS:
        mg.render_pdf(d, tmp_path / f"{d.id}.pdf")
        assert (tmp_path / f"{d.id}.pdf").read_bytes() == (CORPUS / "drawings" / f"{d.id}.pdf").read_bytes(), \
            f"{d.id}.pdf is stale; run `calgen magnetics render`"


def test_similar_designs_same_kind_never_self():
    sim = mg.similar(DESIGNS)
    kind = {d.id: d.kind for d in DESIGNS}
    for did, near in sim.items():
        assert near and all(n != did and kind[n] == kind[did] for n, _ in near)
    assert sim["MAG-010"][0][0] == "MAG-001"  # same drawing except the core typo


def test_inductance_text_units():
    assert mg.parse_inductance_uh("4.5 mH") == pytest.approx(4500)
    assert mg.parse_inductance_uh("330 µH") == 330
    assert mg.parse_inductance_uh("330") is None


def test_every_magnetics_formula_parses_in_katex(tmp_path):
    import json
    import shutil
    import subprocess
    import tarfile

    tgz = ROOT / "vendor" / "katex-0.16.22.tgz"
    node = shutil.which("node")
    if not node or not tgz.exists():
        pytest.skip("needs node and `calgen vendor`")
    with tarfile.open(tgz) as t:
        (tmp_path / "katex.js").write_bytes(t.extractfile("package/dist/katex.min.js").read())
    formulas = [(d.id, c.id, s) for d in DESIGNS for c in mg.check(d, CORES, LIMITS) for s in c.latex]
    formulas += [("size", c["core"], s) for c in mg.size_inductor(CORES, LIMITS, 783, 7.9, 12.8, 0.5)["candidates"] for s in c["latex"]]
    (tmp_path / "f.json").write_text(json.dumps(formulas))
    js = ("const k=require('./katex.js');const f=require('./f.json');const bad=[];"
          "for(const [d,c,s] of f){try{k.renderToString(s,{throwOnError:true,displayMode:true})}catch(e){bad.push(d+' '+c+': '+e.message)}}"
          "console.log(JSON.stringify(bad))")
    out = subprocess.run([node, "-e", js], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == []
    assert len(formulas) > 30


# ---- sizing and playground requirements ---------------------------------------------
@pytest.mark.parametrize("name", ["0077908A7", "0077083A7", "0077548A7"])  # 26u, 60u, 125u
def test_retained_is_vendor_curve_derated_to_data_sheet_minimums(name):
    # The catalog fit is the typical curve; what the checks count on must never beat the
    # per-part guaranteed points (80% at H80 minimum, 50% at H50 minimum).
    c = CORES[name]
    assert c.fit is not None
    assert mg.retained(c, 0) == pytest.approx(1.0)
    assert mg.retained(c, c.h80_oe) <= 0.8 + 1e-9 and mg.retained(c, c.h50_oe) <= 0.5 + 1e-9
    assert max(mg.retained(c, c.h80_oe), mg.retained(c, c.h50_oe) / 0.5 * 0.8) == pytest.approx(0.8)  # one point binds
    assert mg.typical(c, c.h80_oe) > mg.retained(c, c.h80_oe)  # typical is more optimistic
    assert mg.retained(c, c.h50_oe * 1.01) is None  # no extrapolation past the data sheet


@pytest.mark.parametrize("req", [(330, 4, 4.5, 0.8), (783, 7.9, 12.8, 0.5), (603.6, 20, 32.5, 0.5), (1000, 0.8, 1.0, 0.8)])
def test_every_sizing_candidate_rechecks_independently(req):
    import math

    l_uh, i_rms, i_pk, keep = req
    res = mg.size_inductor(CORES, LIMITS, l_uh, i_rms, i_pk, keep)
    assert res["candidates"] or res["rejected"]
    for c in res["candidates"]:
        core = CORES[c["core"]]
        h = 0.4 * math.pi * c["turns"] * i_pk / (core.le_mm / 10)
        f = mg.retained(core, h)
        assert f is not None and f >= keep
        assert core.al_nh * c["stack"] * c["turns"] ** 2 * f / 1000 >= l_uh
        area = mg.awg_area_mm2(c["awg"]) * c["strands"]
        assert i_rms / area <= LIMITS["j_max_a_per_mm2"]
        assert c["turns"] * area / core.wa_mm2 <= LIMITS["fill_max_toroid"]
        assert 1 <= c["stack"] <= mg.MAX_STACK
    vols = [c["core_volume_mm3"] for c in res["candidates"]]
    assert vols == sorted(vols)


def test_playground_requirements_and_known_sizing_outcomes():
    from calgen.playground import run

    specs = ROOT / "specs"
    req = run(specs, "FA10507")["inductors"]
    pfc, out = req["rect"], req["out"]
    # L = V_bus / (4 f_sw dI), dI = 0.3 x sqrt(2) x 20 A at 410 V, 20 kHz
    assert pfc["l_uh"] == pytest.approx(410 / (4 * 20e3 * 0.3 * 2 ** 0.5 * 20) * 1e6)
    assert pfc["i_pk"] == pytest.approx(2 ** 0.5 * 20 * 1.15)
    # output filter: peak = max(3:1 crest load at rated = 37.5 A, sine overload 21.2 A) + ripple/2, heating at rated;
    # 410 V bus -> half-bridge (0.95 x 205 V = 194.75 V > 175 V peak)
    assert out["i_pk"] == pytest.approx(3 * 12.5 + 0.15 * 2 ** 0.5 * 12.5) and out["i_rms"] == pytest.approx(12.5)
    assert out["l_uh"] == pytest.approx(410 / (4 * 20e3 * 0.3 * 2 ** 0.5 * 12.5) * 1e6) and "Half bridge · bipolar PWM" in out["basis"]
    # FA10434 explicitly declares a full bridge with unipolar PWM: L = V_bus / (8 f_sw dI)
    small = run(specs, "FA10434")["inductors"]["out"]
    assert small["l_uh"] == pytest.approx(210 / (8 * 20e3 * 0.3 * 2 ** 0.5 * 800 / 120) * 1e6) and "Full bridge · unipolar PWM" in small["basis"]
    assert out["min_retained"] == 0.8 and pfc["min_retained"] == 0.5
    big = mg.size_inductor(CORES, LIMITS, pfc["l_uh"], pfc["i_rms"], pfc["i_pk"], pfc["min_retained"])
    assert [(c["core"], c["stack"]) for c in big["candidates"]] == [("0077908A7", 4)]
    assert mg.size_inductor(CORES, LIMITS, out["l_uh"], out["i_rms"], out["i_pk"], out["min_retained"])["candidates"] == []


def test_size_json_includes_closest_past_designs():
    import json

    past = [{"id": d.id, "kind": d.kind, **{k: v for k, v in mg.features(d).items() if k in ("l_uh", "i_a")}} for d in DESIGNS]
    out = json.loads(mg.size_json(str(ROOT / "specs"), json.dumps({"l_uh": 330, "i_rms": 4, "i_pk": 4.5, "min_retained": 0.8, "past": past})))
    assert out["past"][0]["id"] in ("MAG-001", "MAG-010") and out["candidates"]


def test_window_drawing_shows_overflow_only_when_the_winding_cannot_fit():
    import re

    by = {d.id: d for d in DESIGNS}
    for did, overflows in (("MAG-001", False), ("MAG-008", True), ("XFMR-001", False)):
        d = by[did]
        svg = mg.svg_window(CORES[d.core], [(w.name, w.turns, w.strands, w.awg) for w in d.windings], limits=LIMITS)
        if d.kind == "inductor":
            total = sum(w.turns * w.strands for w in d.windings)
            drawn, of = map(int, re.search(r"(\d+) of (\d+) conductors drawn", svg).groups())
            assert of == total and (drawn < total) == overflows, did
        assert ("don't fit" in svg) == overflows, did


def test_inductance_curve_matches_the_check_at_peak():
    d = {x.id: x for x in DESIGNS}["MAG-001"]
    core = CORES[d.core]
    svg = mg.svg_l_vs_i(core, d.windings[0].turns, d.i_pk_a, 330)
    f = mg.retained(core, 0.4 * 3.141592653589793 * d.windings[0].turns * d.i_pk_a / (core.le_mm / 10))
    assert f"{mg._fmt_l(core.al_nh * d.windings[0].turns ** 2 / 1000 * f)} ({f * 100:.0f}%)" in svg


def test_curve_label_says_what_the_reference_inductance_means():
    from pathlib import Path as _P  # noqa: F401

    recs = {r["id"]: r for r in mg.site_records(ROOT)["records"]}
    curve = recs["MAG-001"]["fig"]["curve"]
    assert "drawing: 330 µH at 0 A" in curve and "required at peak" not in curve
    sized = mg.size_inductor(CORES, LIMITS, 330, 4, 4.5, 0.8)["candidates"][0]["fig"]["curve"]
    assert "required at peak: 330 µH" in sized
    assert recs["XFMR-001"]["fig"]["curve"] is None  # transformers have no inductance curve



def test_default_tab_opens_the_evidence_for_the_verdict():
    recs = {r["id"]: r for r in mg.site_records(ROOT)["records"]}
    want = {"MAG-001": "curve", "MAG-003": "curve", "MAG-005": "curve", "MAG-009": "curve", "MAG-006": "winding",
            "MAG-008": "winding", "MAG-010": "drawing", "XFMR-002": "drawing", "XFMR-001": "flux"}
    assert {k: recs[k]["default_tab"] for k in want} == want



def test_transformer_build_includes_bobbin_margins_and_tape():
    d = {x.id: x for x in DESIGNS}["XFMR-001"]
    b = mg.bobbin_build(CORES[d.core], [(w.name, w.turns, w.strands, w.awg) for w in d.windings], LIMITS)
    # 24 x 20 AWG in 2 layers, 6 x 14 AWG in 1 layer (each layer 1.1 x wire OD), 1 mm bobbin, 3 + 2 tape layers of 0.05 mm
    expect = 1.0 + LIMITS["build_factor"] * (2 * mg._wire_od(20) + mg._wire_od(14)) + 5 * 0.05
    assert b["build"] == pytest.approx(expect) and b["fits"]
    assert b["y1"] - b["y0"] == pytest.approx(2 * 11.2 - 2 * (1.0 + 3.0))  # breadth between the margin tapes
    assert all(b["y0"] <= y - r and y + r <= b["y1"] + 1e-9 for _, _, y, r in b["conductors"])  # no wire in the margins
    tight = dict(LIMITS, margin_mm=6.0)  # bigger margins push the same winding out of the window
    assert not mg.bobbin_build(CORES[d.core], [(w.name, w.turns, w.strands, w.awg) for w in d.windings], tight)["fits"]



def test_transformer_layers_are_balanced_and_spread():
    d = {x.id: x for x in DESIGNS}["XFMR-001"]
    b = mg.bobbin_build(CORES[d.core], [(w.name, w.turns, w.strands, w.awg) for w in d.windings], LIMITS)
    assert [cnt for _, _, cnt in b["layers"]] == [12, 12, 6]  # 24 primary turns as 12 + 12, not 16 + 8; secondary in one layer
    first = sorted(y for k, x, y, r in b["conductors"] if k == 0 and x < b["conductors"][0][1] + 1e-9)
    assert first[0] > b["y0"] and first[-1] < b["y1"] and (first[-1] - first[0]) > 0.8 * (b["y1"] - b["y0"])  # spans the breadth



def test_wire_choice_prefers_one_wire_over_many_thin_ones():
    awg, strands, area = mg.pick_wire(4.0, LIMITS["j_max_a_per_mm2"])  # needs 0.8 mm²
    assert strands == 1 and area >= 0.8  # 18 AWG (0.823 mm²), not 4 x 24 AWG


def test_inductance_check_requires_core_tolerance_inside_drawing_tolerance():
    import dataclasses

    d = dataclasses.replace({x.id: x for x in DESIGNS}["MAG-001"], l_tol_pct=5)  # tighter than the core's ±8% A_L
    c = next(c for c in mg.check(d, CORES, LIMITS) if c.id == "inductance")
    assert c.status == mg.FLAG and "leaves the drawing's" in c.message


def test_inductance_check_flags_offset_that_pushes_the_spread_out_of_band():
    """A +7% offset is inside the core's ±8% but a -8% core then misses the drawing's -10% limit."""
    import dataclasses

    d = dataclasses.replace({x.id: x for x in DESIGNS}["MAG-001"], l_text="355 µH")
    c = next(c for c in mg.check(d, CORES, LIMITS) if c.id == "inductance")
    assert c.status == mg.FLAG and "leaves the drawing's" in c.message


def test_ripple_fraction_has_one_source():
    import re

    for f in ("src/calgen/playground.py", "src/calgen/magnetics.py"):
        assert not re.search(r"RIPPLE_FRACTION\s*=|ripple_fraction\s*=\s*0", (ROOT / f).read_text()), f


def test_sizer_math_lines_reproduce_their_results():
    """The numbers printed in each sizing derivation multiply out to the printed result."""
    import math
    import re

    for c in mg.size_inductor(CORES, LIMITS, 330, 4, 4.5, 0.8)["candidates"]:
        a_line, l_line, j_line = c["latex"][1], c["latex"][2], c["latex"][4]
        al, tol, al_min = (float(v) for v in re.match(r"A_\{L,\\min\} = ([\d.]+)\\,\\mathrm\{nH\} \\times \(1 - ([\d.]+)\\%\) = ([\d.]+)", a_line).groups())
        assert al * (1 - tol / 100) == pytest.approx(al_min, rel=1e-3)
        n, al_m, turns, f, l_pk = (float(v) for v in re.match(r"L\(I_\{pk\}\) = (\d+) \\times ([\d.]+)\\,\\mathrm\{nH\} \\times (\d+)\^2 \\times ([\d.]+) = ([\d.]+)", l_line).groups())
        assert al_m == al_min and n * al_m * turns ** 2 * f / 1000 == pytest.approx(l_pk, rel=1e-3)
        t, s, d, wa, pct = (float(v) for v in re.search(r"\\frac\{(\d+) \\times (\d+) \\times \\pi \\times \(([\d.]+)\\,\\mathrm\{mm\}\)\^2/4\}\{([\d.]+)\\,\\mathrm\{mm\^2\}\} = (\d+)", j_line).groups())
        assert round(t * s * math.pi * d ** 2 / 4 / wa * 100) == pytest.approx(pct, abs=1)


def test_check_lines_reproduce_their_results():
    """Printed inputs in the record checks reproduce the printed results (H, J, toroid fill)."""
    import math
    import re

    num = r"([\d.]+)"
    for d in DESIGNS:
        if d.core not in CORES:
            continue
        for c in mg.check(d, CORES, LIMITS):
            for line in c.latex:
                if m := re.search(rf"\\frac{{0.4\\pi \\times {num} \\times {num}\\,\\mathrm{{A}}}}{{{num}\\,\\mathrm{{cm}}}} = {num}", line):
                    n, i, le, h = map(float, m.groups())
                    assert 0.4 * math.pi * n * i / le == pytest.approx(h, rel=6e-3), (d.id, line)
                if m := re.search(rf"\\frac{{{num}\\,\\mathrm{{A}}}}{{{num} \\times {num}\\,\\mathrm{{mm\^2}}.*?= {num}\\,\\mathrm{{A/mm\^2}}", line):
                    i, n, a, j = map(float, m.groups())
                    assert i / (n * a) == pytest.approx(j, rel=6e-3), (d.id, line)
                if m := re.search(rf"\\frac{{{num}\\,\\mathrm{{mm\^2}}}}{{{num}\\,\\mathrm{{mm\^2}}}} = (\d+)\\%", line):
                    cu, wa, pct = map(float, m.groups())
                    assert round(cu / wa * 100) == pct, (d.id, line)


@pytest.mark.parametrize('values', [(330, 4, 1), (0, 4, 5), (330, float('inf'), 5), (330, 4, float('nan'))])
def test_sizer_rejects_invalid_requirements(values):
    with pytest.raises(ValueError):
        mg.size_inductor(CORES, LIMITS, *values)


def test_sizer_reports_wire_catalog_limit_without_crashing():
    result = mg.size_inductor(CORES, LIMITS, 1, 200, 201)
    assert result['candidates'] == []
    assert 'Wire catalog insufficient' in result['error']


@pytest.mark.parametrize('application', ['dc_bias', 'pfc', 'ac_output'])
def test_sizing_scope_follows_application_without_claiming_validation(application):
    import json
    result = json.loads(mg.size_json(str(ROOT / 'specs'), json.dumps(dict(l_uh=330, i_rms=4, i_pk=4.5, application=application))))
    assert result['candidates']
    assert 'not a validated design' in result['scope']['verdict']
    assert 'not guaranteed' in result['scope']['curve']
    assert 'temperature rise are not evaluated' in result['scope']['remaining']
    assert ('large AC excitation' in result['scope']['remaining']) == (application == 'ac_output')
    for candidate in result['candidates']:
        curve = candidate['fig']['curve']
        assert 'adjusted estimate (not guaranteed)' in curve
        assert 'curve between those points is not guaranteed' in curve
        assert 'conservative' not in curve


def test_records_keep_modeled_pass_separate_from_loss_and_thermal_validation():
    for record in mg.site_records(ROOT)['records']:
        assert 'Modeled checks only' in record['scope']
        assert 'temperature rise are not evaluated' in record['scope']


def test_empty_sizing_results_do_not_claim_a_pass():
    import json
    result = json.loads(mg.size_json(str(ROOT / 'specs'), json.dumps(dict(l_uh=966.3792676216149, i_rms=12.5, i_pk=40.15165042944955, min_retained=.8, application='ac_output'))))
    assert not result['candidates']
    assert result['scope']['verdict'] == 'Screening only · no candidate passes modeled constraints'
    assert 'large AC excitation' in result['scope']['remaining']


def test_window_comparison_symbol_agrees_with_verdict():
    """A failed inequality must not be printed as if the constraint passed."""
    by = {d.id: d for d in DESIGNS}
    for did, limits, expected in (
        ('MAG-001', LIMITS, mg.PASS), ('MAG-008', LIMITS, mg.FLAG),
        ('XFMR-001', LIMITS, mg.PASS), ('XFMR-001', dict(LIMITS, margin_mm=6), mg.FLAG),
    ):
        c = next(c for c in mg.check(by[did], CORES, limits) if c.id == 'window_fill')
        assert c.status == expected
        assert (r'\le' in c.latex[0]) == (expected == mg.PASS)
        assert (' > ' in c.latex[0]) == (expected == mg.FLAG)
