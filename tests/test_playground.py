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


def test_shunt_change_is_visible_in_sensor_line():
    base = run(SPECS)["summaries"]["sense"]
    r = run(SPECS, edits={"board.r_shunt": 6})
    assert base.startswith("Current sensor ±33.0 A peak") and "uses 64%" in base
    assert "±27.5 A" in r["summaries"]["sense"] and "uses 77%" in r["summaries"]["sense"]
    assert {"iout_fs_pk", "iout_trip_dac_hi"} <= set(r["changed"])


def test_product_what_if_overrides_data_sheet_and_is_marked():
    ok = run(SPECS, edits={"ds.power_va": 2000})
    assert ok["ok"] and "OVERRIDE ds.power_va: what-if in playground: data sheet says 1500 VA" in ok["header"]
    assert next(c for c in ok["constants"] if c["id"] == "iout_rated")["display"] == "16.67 A"
    too_big = run(SPECS, edits={"ds.power_va": 2500})
    assert not too_big["ok"] and "SATURATES before trip" in too_big["summaries"]["sense"]


def test_input_voltage_what_if_moves_the_bus():
    r = run(SPECS, edits={"ds.vin_max": 277})
    assert {"vin_max", "vbus_min", "vbus_set"} <= set(r["changed"])
    assert next(c for c in r["constants"] if c["id"] == "vbus_set")["display"] == "420 V"  # ceil(391.7*1.07/10)*10


def test_tags_trace_values_to_their_weakest_root():
    tags = {c["id"]: c["tag"] for c in run(SPECS, product="FA10449")["constants"]}
    assert tags["vbat_nom"] == "datasheet"  # "92.4 VDC" on the sheet
    assert tags["vbat_cutoff"] == "assumption"  # uses a generic LiFePO4 ratio
    assert tags["iout_trip"] == "derived"  # data sheet values only
    assert tags["vbus_set"] == "assumption"  # invented bus margin
    assert tags["iout_trip_dac_hi"] == "assumption"  # invented shunt and amplifier
    assert tags["vloop_kp"] == "design"
    what_if = {c["id"]: c["tag"] for c in run(SPECS, edits={"ds.power_va": 2000})["constants"]}
    assert what_if["iout_rated"] == "assumption"  # now rests on an override
