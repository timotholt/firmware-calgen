"""Typeset math is generated from the same tree the evaluator runs, and agrees with it."""

from pathlib import Path

import pytest

from calgen.build import OK, build
from calgen.latex import derive_check, derive_constant, render
from calgen.spec import load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"
RULES = load_rules(SPECS / "rules.yaml")
VARIANTS = ["fa10449", "fa10434", "fa10507", "fa10507_f2803x", "fa10507_revB"]


@pytest.mark.parametrize("name", VARIANTS)
def test_rendered_value_equals_evaluated_value_for_every_constant(name):
    b = build(load_variant(SPECS / "variants" / f"{name}.yaml"), RULES)
    checked = 0
    for c in b.constants:
        if c.status != OK or c.rule.kind != "numeric":
            continue
        d = derive_constant(b, c.rule.id)
        assert d.value == pytest.approx(c.value, rel=1e-12, abs=1e-12), c.rule.id
        checked += 1
    assert checked >= 20


def test_trip_dac_derivation_reads_like_hand_math():
    b = build(load_variant(SPECS / "variants" / "fa10507.yaml"), RULES)
    lines = derive_constant(b, "iout_pklim_dac_hi").lines
    assert lines[0].startswith(r"N_{\text{DAC,hi}} = \left\lfloor")
    assert r"\frac{V_{\text{ref}}}{2}" in lines[0]
    assert "3134.06" in lines[2] and lines[2].endswith("3134")


def test_render_fraction_and_parentheses():
    r = render("(a + b) * c / d", {"a": "a", "b": "b", "c": "c", "d": "d"}, {}, {})
    assert r.symbolic == r"\frac{\left(a + b\right) \cdot c}{d}"


def test_failed_check_is_marked():
    b = build(load_variant(SPECS / "variants" / "fa10507_revB.yaml"), RULES)
    d = derive_check(b, "iout_sense_range")
    assert r"\times" in d.lines[-1] and "43.75" in d.lines[-1]


def test_enum_and_supplied():
    b = build(load_variant(SPECS / "variants" / "fa10449.yaml"), RULES)
    assert r"UPS\_FOUT\_FOLLOWER" in derive_constant(b, "fout_mode").lines[0]
    assert "engineer-supplied" in derive_constant(b, "vloop_kp").lines[0]


def test_every_formula_parses_in_katex(tmp_path):
    """The site renders with throwOnError off, so a bad formula shows as red source text. Catch it here."""
    import json
    import shutil
    import subprocess
    import tarfile

    tgz = SPECS.parent / "vendor" / "katex-0.16.22.tgz"
    node = shutil.which("node")
    if not node or not tgz.exists():
        pytest.skip("needs node and `calgen vendor`")
    with tarfile.open(tgz) as t:
        (tmp_path / "katex.js").write_bytes(t.extractfile("package/dist/katex.min.js").read())
    formulas = []
    for name in VARIANTS:
        b = build(load_variant(SPECS / "variants" / f"{name}.yaml"), RULES)
        for c in b.constants:
            formulas += [(name, c.rule.id, line) for line in derive_constant(b, c.rule.id).lines]
        for k in b.checks:
            formulas += [(name, k.check.id, line) for line in derive_check(b, k.check.id).lines]
    (tmp_path / "f.json").write_text(json.dumps(formulas))
    js = (
        "const k=require('./katex.js');const f=require('./f.json');const bad=[];"
        "for(const [v,id,s] of f){try{k.renderToString(s,{throwOnError:true,displayMode:true})}catch(e){bad.push(v+' '+id+': '+e.message)}}"
        "console.log(JSON.stringify(bad))"
    )
    out = subprocess.run([node, "-e", js], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == []
    assert len(formulas) > 100
