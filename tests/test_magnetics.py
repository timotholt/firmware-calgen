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
    (tmp_path / "f.json").write_text(json.dumps(formulas))
    js = ("const k=require('./katex.js');const f=require('./f.json');const bad=[];"
          "for(const [d,c,s] of f){try{k.renderToString(s,{throwOnError:true,displayMode:true})}catch(e){bad.push(d+' '+c+': '+e.message)}}"
          "console.log(JSON.stringify(bad))")
    out = subprocess.run([node, "-e", js], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == []
    assert len(formulas) > 30
