"""The playground engine (same code the browser runs)."""

from pathlib import Path

import pytest

from calgen.playground import run

SPECS = Path(__file__).resolve().parent.parent / "specs"


def test_shipped_product_has_no_changes_and_readable_summaries():
    r = run(SPECS, product="FA10449")
    assert r["ok"] and r["changed"] == []
    assert r["summaries"]["in"] == "90–138 V AC 1φ* · 60 Hz ±5 Hz · ≤ 7.9 A"
    assert "overload 6.23 A RMS (115%) for 30 s → shutdown · peak limit 18.96 A" in r["summaries"]["out"]
    assert "implied" in r["footnote"]


def test_alternate_amplifier_changes_exactly_the_current_sense_chain():
    r = run(SPECS, product="FA10507", board_rev="B")
    assert not r["ok"]
    assert set(r["changed"]) == {"iout_fs_pk", "iout_pklim_dac_hi", "iout_pklim_dac_lo"}
    assert r["baseline"]["iout_pklim_dac_hi"] == "3134"


def test_target_switch_ignores_quantization_noise():
    r = run(SPECS, product="FA10449", target="f2803x")
    assert "iout_alarm" not in r["changed"]  # 5.6875 vs 5.68749996 is not a change
    assert {"pwm_period", "iout_pklim_dac_hi"} <= set(r["changed"])


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
    r = run(SPECS, edits={"board.r_shunt": 3})
    assert base.startswith("Current sensor ±82.5 A peak") and "uses 53%" in base
    assert "±55 A" in r["summaries"]["sense"] and "uses 80%" in r["summaries"]["sense"]
    assert {"iout_fs_pk", "iout_pklim_dac_hi"} <= set(r["changed"])


def test_product_what_if_overrides_data_sheet_and_is_marked():
    ok = run(SPECS, edits={"ds.power_va": 2000})
    assert ok["ok"] and "OVERRIDE ds.power_va: what-if in playground: data sheet says 1500 VA" in ok["header"]
    assert next(c for c in ok["constants"] if c["id"] == "iout_rated")["display"] == "16.67 A"
    too_big = run(SPECS, edits={"ds.power_va": 3000})  # 3.5 x 25 A = 87.5 A peak limit > 95% of 82.5 A
    assert not too_big["ok"] and "SATURATES" in too_big["summaries"]["sense"]


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
    assert tags["iout_pklim_dac_hi"] == "assumption"  # invented shunt and amplifier
    assert tags["vloop_kp"] == "design"
    what_if = {c["id"]: c["tag"] for c in run(SPECS, edits={"ds.power_va": 2000})["constants"]}
    assert what_if["iout_rated"] == "assumption"  # now rests on an override


def test_market_preset_retargets_voltage_and_frequency():
    r = run(SPECS, product="FA10449", preset="eu")
    d = {c["id"]: c["display"] for c in r["constants"]}
    assert (d["vout_set"], d["fout_hz"], d["vin_min"], d["vin_max"]) == ("230 V", "50 Hz", "172.5 V", "264.5 V")
    assert d["iout_rated"] == "2.826 A" and r["ok"]
    assert "market preset Europe - 230 V 50 Hz" in r["header"]


def test_universal_input_keeps_its_range_under_a_preset():
    d = {c["id"]: c["display"] for c in run(SPECS, product="FA10507", preset="eu")["constants"]}
    assert (d["vin_min"], d["vin_max"]) == ("85 V", "265 V")


def test_every_consumed_numeric_data_sheet_field_is_editable():
    from calgen.build import _consumed_ds_fields
    from calgen.playground import DS_EDITABLE
    from calgen.spec import load_datasheet, load_rules

    used = _consumed_ds_fields(load_rules(SPECS / "rules.yaml"))
    numeric = {n for p in ("fa10449", "fa10434", "fa10507") for n, q in load_datasheet(SPECS / "datasheets" / f"{p}.csv").params.items() if n in used and q.numeric}
    assert numeric <= {n for n, *_ in DS_EDITABLE}


def test_failure_offers_fix_that_actually_passes():
    r = run(SPECS, board_rev="B")
    check = next(k for k in r["checks"] if k["id"] == "iout_sense_range")
    assert check["status"] == "fail" and "smaller shunt" in check["fix"]
    for s in check["suggest"]:
        fixed = run(SPECS, board_rev="B", edits={s["key"]: s["value"]})
        assert fixed["ok"], (s, fixed["failures"])


def test_protection_numbers_for_gauge_and_waveform():
    a = run(SPECS, "FA10507")["protection"]
    assert a["sensor_fs"] == pytest.approx(82.5) and a["peak_limit"] == pytest.approx(43.75)
    assert a["crest_pk"] == pytest.approx(37.5)
    assert a["crest_pk"] < a["peak_limit"] <= a["headroom"] * a["sensor_fs"]
    b = run(SPECS, "FA10507", "B")["protection"]
    assert b["sensor_fs"] == pytest.approx(41.25)
    assert b["sensor_fs"] < b["peak_limit"]  # rev B: the limit is off the sensor's scale


def test_unedited_download_is_the_committed_header():
    """'Same inputs, byte-identical output': the default playground build equals firmware/include."""
    for product, variant in (("FA10507", "fa10507"), ("FA10449", "fa10449"), ("FA10434", "fa10434")):
        r = run(SPECS, product)
        assert r["variant"] == variant
        assert r["header"] == (SPECS.parent / "firmware" / "include" / f"calgen_{variant}.h").read_text(encoding="utf-8")
