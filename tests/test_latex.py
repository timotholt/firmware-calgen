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
    assert lines[0].startswith(r"N_{\text{DAC,hi}} = \operatorname{round}")
    assert r"\frac{V_{\text{ref}}}{2}" in lines[0]
    assert "3133.3" in lines[2] and lines[2].endswith("3133")


def test_render_fraction_and_parentheses():
    r = render("(a + b) * c / d", {"a": "a", "b": "b", "c": "c", "d": "d"}, {}, {})
    assert r.symbolic == r"\frac{\left(a + b\right) \cdot c}{d}"


def test_failed_check_is_marked():
    b = build(load_variant(SPECS / "variants" / "fa10507_revB.yaml"), RULES)
    d = derive_check(b, "iout_sense_range")
    assert r"\times" in d.lines[-1] and "43.75" in d.lines[-1]


def test_enum_and_supplied():
    b = build(load_variant(SPECS / "variants" / "fa10449.yaml"), RULES)
    assert "UPS_FOUT_FOLLOWER" in derive_constant(b, "fout_mode").lines[0]
    assert "engineer-supplied" in derive_constant(b, "vloop_kp").lines[0]
