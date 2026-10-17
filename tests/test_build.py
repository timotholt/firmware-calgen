"""Hand-worked known answers for the real data sheet variants.

Every expected value below was computed by hand from the formulas in
specs/rules.yaml, independent of the code under test.
"""

from pathlib import Path

import pytest

from calgen.build import FAIL, OK, SKIPPED, build
from calgen.spec import load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"
RULES = load_rules(SPECS / "rules.yaml")


def b(name):
    return build(load_variant(SPECS / "variants" / f"{name}.yaml"), RULES)


def value(bld, rule_id):
    c = bld.constant(rule_id)
    assert c.status == OK, c.message
    return c.encoded.stored if c.encoded else c.enum_ident


def test_fa10507_known_answers():
    x = b("fa10507")
    assert x.ok, x.failures
    assert value(x, "iout_rated") == pytest.approx(1500 / 120)  # 12.5 A
    assert value(x, "iout_trip") == pytest.approx(12.5 * 1.20)  # 15.0 A
    assert value(x, "iout_pk_limit") == pytest.approx(3.5 * 12.5)  # 43.75 A hardware peak limit
    assert value(x, "iout_fs_pk") == pytest.approx(1.65 / (0.002 * 10))  # 82.5 A
    # CMPSS DAC, V = code * V_ref / 4096; rounded toward mid-rail (never above the design limit):
    # (1.65 V + 43.75 A * 0.02 V/A) / 3.3 V * 4096 = 3134.06 -> floor 3134
    assert value(x, "iout_pklim_dac_hi") == 3134
    # (1.65 V - 0.875 V) / 3.3 V * 4096 = 961.94 -> ceil 962
    assert value(x, "iout_pklim_dac_lo") == 962
    assert value(x, "overload_delay") == 30000  # 30 s, invented design value
    assert value(x, "vbus_min") == pytest.approx(265 * 2**0.5, rel=1e-6)  # 374.77 V
    assert value(x, "vbus_set") == 410  # ceil(374.77 * 1.07 / 10) * 10
    assert value(x, "pwm_period") == 2500  # 100 MHz / (2 * 20 kHz), up-down count
    assert value(x, "pwm_deadband") == 100  # 1 us * 100 MHz
    assert value(x, "vbat_cutoff") == pytest.approx(70.0)  # 28 cells * 2.5 V
    assert value(x, "fout_mode") == "UPS_FOUT_CHANGER"
    assert value(x, "overload_action") == "UPS_OL_SHUTDOWN"
    assert x.constant("iout_alarm").status == SKIPPED  # FA10507 sheet gives no alarm level


def test_fa10449_follower_and_alarm():
    x = b("fa10449")
    assert x.ok, x.failures
    assert value(x, "fout_mode") == "UPS_FOUT_FOLLOWER"
    assert value(x, "iout_alarm") == pytest.approx(650 / 120 * 1.05, rel=1e-6)  # 5.6875 A
    assert value(x, "vbus_set") == 210  # ceil(138*sqrt2*1.07/10)*10 = ceil(20.88)*10


def test_fa10434_needs_and_uses_override():
    x = b("fa10434")
    assert x.ok, x.failures
    assert value(x, "iin_limit") == pytest.approx(7.4, rel=1e-6)
    src = x.constant("iin_limit").sources[0]
    assert src.override and "OVERRIDE" in src.origin
    assert value(x, "overload_action") == "UPS_OL_BYPASS"


def test_fa10434_without_override_fails_closed(tmp_path):
    text = (SPECS / "variants" / "fa10434.yaml").read_text().split("datasheet_overrides:")[0]
    v = tmp_path / "variants" / "fa10434.yaml"
    v.parent.mkdir()
    v.write_text(text.replace("../", str(SPECS) + "/"))
    x = build(load_variant(v), RULES)
    assert not x.ok
    assert x.constant("iin_limit").status == FAIL
    assert "not in data sheet" in x.constant("iin_limit").message


def test_rev_b_alternate_amplifier_breaks_only_the_big_unit():
    big = b("fa10507_revB")
    assert not big.ok
    failed = {c.check.id for c in big.checks if c.status == FAIL}
    assert {"iout_sense_range", "dac_hi_in_range"} <= failed
    assert big.constant("iout_pklim_dac_lo").status == FAIL  # negative code -> uint16 underflow


def test_legacy_target_uses_iq20_and_10bit_dac():
    x = b("fa10507_f2803x")
    assert x.ok, x.failures
    c = x.constant("vbus_set")
    assert c.fmt == "iq20" and c.encoded.code == 410 * (1 << 20)
    assert value(x, "pwm_period") == 1500  # 60 MHz / (2 * 20 kHz)
    # 10-bit comparator DAC, V = DACVAL * VDDA / 1023 (SPRUGE5F 2.3.1): 782.75 -> floor 782, lo 240.25 -> ceil 241
    assert value(x, "iout_pklim_dac_hi") == 782
    assert value(x, "iout_pklim_dac_lo") == 241


def test_legacy_target_with_iq24_overflows_volt_scaled_constants():
    # IQ24 spans [-128, 128); a 265 V input limit cannot be stored, and every
    # constant derived from it reports the cascade instead of a misleading value.
    x = b("fa10507_f2803x")
    x.variant.target.extra["default_format"] = "iq24"
    y = build(x.variant, RULES)
    assert "iq24: 265 out of range" in y.constant("vin_max").message
    assert y.constant("vbus_min").message == "depends on failed constant vin_max"
    assert y.constant("vbus_set").message == "depends on failed constant vbus_min"
    assert y.constant("iout_trip").status == "ok"  # 15 A fits


def test_every_ds_source_is_cited():
    x = b("fa10507")
    for c in x.constants:
        for s in c.sources:
            if s.name.startswith("ds."):
                assert s.origin.startswith("DS-10507"), s
