"""The playground engine (same code the browser runs)."""

from pathlib import Path

from calgen.playground import run

SPECS = Path(__file__).resolve().parent.parent / "specs"


def test_shipped_product_has_no_changes_and_readable_summaries():
    r = run(SPECS, product="FA10449")
    assert r["ok"] and r["changed"] == []
    assert r["summaries"]["in"] == "90–138 V AC 1φ* · 60 Hz ±5.0 Hz · ≤ 7.9 A"
    assert r["summaries"]["out"].endswith("trip 6.23 A (115%) · shutdown")
    assert "implied" in r["footnote"]


def test_alternate_amplifier_changes_exactly_the_current_sense_chain():
    r = run(SPECS, product="FA10507", board_rev="B")
    assert not r["ok"]
    assert set(r["changed"]) == {"iout_fs_pk", "iout_trip_dac_hi", "iout_trip_dac_lo"}
    assert r["baseline"]["iout_trip_dac_hi"] == "3364"


def test_target_switch_ignores_quantization_noise():
    r = run(SPECS, product="FA10449", target="f2803x")
    assert "iout_alarm" not in r["changed"]  # 5.6875 vs 5.68749996 is not a change
    assert {"pwm_period", "iout_trip_dac_hi"} <= set(r["changed"])


def test_margin_change_can_round_to_same_setpoint():
    r = run(SPECS, product="FA10449", edits={"design.vbus_margin": 3})
    assert "vbus_set" not in r["changed"]  # 201 V rounds up to 210 V, same as 7%
    r = run(SPECS, product="FA10449", edits={"design.vbus_margin": 10})
    assert "vbus_set" in r["changed"]


def test_frequency_edit_regenerates_pwm_and_flags_stale_gains():
    r = run(SPECS, edits={"design.f_sw": 25})
    assert "pwm_period" in r["changed"] and not r["ok"]
    assert {s["param"] for s in r["staleness"] if s["status"] == "fail"} == {"design.vloop_kp", "design.vloop_ki"}
