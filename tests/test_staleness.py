from pathlib import Path

from calgen.build import FAIL, OK, build
from calgen.codegen import GateError, header
from calgen.spec import load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"
RULES = load_rules(SPECS / "rules.yaml")


def variant_with(tmp_path, old, new):
    text = (SPECS / "variants" / "fa10507.yaml").read_text().replace("../", str(SPECS) + "/")
    assert old in text
    v = tmp_path / "v.yaml"
    v.write_text(text.replace(old, new))
    return load_variant(v)


def test_gains_are_current_at_design_frequency():
    b = build(load_variant(SPECS / "variants" / "fa10507.yaml"), RULES)
    assert {(s.param, s.status) for s in b.staleness} == {("design.vloop_kp", OK), ("design.vloop_ki", OK)}


def test_changing_switching_frequency_makes_gains_stale(tmp_path):
    v = variant_with(tmp_path, "f_sw:              {value: 20, unit: kHz", "f_sw:              {value: 25, unit: kHz")
    b = build(v, RULES)
    stale = [s for s in b.staleness if s.status == FAIL]
    assert {s.param for s in stale} == {"design.vloop_kp", "design.vloop_ki"}
    assert "now 25 kHz" in stale[0].message
    assert b.constant("pwm_period").encoded.code == 4000  # the period itself regenerates fine
    try:
        header(b)
    except GateError as exc:
        assert any(f.startswith("stale design.vloop_kp") for f in exc.failures)
    else:
        raise AssertionError("stale gains must block generation")


def test_reapproval_by_updating_designed_against(tmp_path):
    v = variant_with(tmp_path, "{value: 20, unit: kHz, note: inverter", "{value: 25, unit: kHz, note: inverter")
    text = v.path.read_text().replace("designed_against: {design.f_sw: 20 kHz}", "designed_against: {design.f_sw: 25 kHz}")
    v.path.write_text(text)
    b = build(load_variant(v.path), RULES)
    assert all(s.status == OK for s in b.staleness) and b.ok
