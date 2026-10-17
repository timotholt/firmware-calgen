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


@pytest.mark.parametrize('edits,check_id', [
    ({'ds.vin_min': 200, 'ds.vin_max': 150}, 'input_voltage_order'),
    ({'ds.fin_nom_lo': 65, 'ds.fin_nom_hi': 45}, 'input_frequency_order'),
    ({'ds.batt_series_cells': 28.5}, 'battery_cells_integer'),
    ({'ds.batt_series_cells': 0}, 'battery_cells_positive'),
    ({'ds.vout_tol_pct': 101}, 'output_regulation_below_100'),
    ({'ds.vout_tol_pct': -1}, 'output_regulation_nonnegative'),
])
def test_invalid_effective_inputs_block_generation(edits, check_id):
    r = run(SPECS, edits=edits)
    assert not r['ok'] and not r['header']
    assert any(c['id'] == check_id and c['status'] == 'fail' for c in r['checks'])


@pytest.mark.parametrize('kwargs', [
    {'target': 'f2803x'},
    {'board_rev': 'B', 'product': 'FA10449'},
    {'target': 'f2803x', 'edits': {'board.g_amp': 9}},
])
def test_diff_always_starts_from_shipped_header(kwargs):
    import difflib
    result = run(SPECS, **kwargs)
    shipped = run(SPECS, product=kwargs.get('product', 'FA10507'))
    assert result['ok'] and result['changed']
    expected = '\n'.join(difflib.unified_diff(shipped['header'].splitlines(), result['header'].splitlines(), 'baseline', 'edited', lineterm=''))
    assert result['diff'] == expected and expected


@pytest.mark.parametrize('product,label', [('FA10507', 'Half bridge · bipolar PWM'), ('FA10449', 'Full bridge · unipolar PWM'), ('FA10434', 'Full bridge · unipolar PWM')])
def test_declared_topology_stays_fixed_under_voltage_edits(product, label):
    shipped = run(SPECS, product)
    assert shipped['ok'] and label in shipped['summaries']['inv']
    edited = run(SPECS, product, edits={'ds.vout_nom': 240})
    assert label in edited['summaries']['inv']
    if product == 'FA10507':
        assert not edited['ok'] and not edited['header']
        assert next(c for c in edited['checks'] if c['id'] == 'bus_above_output_peak')['status'] == 'fail'
        assert 'out' not in edited['inductors']
        assert 'declared inverter topology is fixed' in edited['gate_message'] or 'declared inverter topology is fixed' in next(c for c in edited['checks'] if c['id'] == 'bus_above_output_peak')['fix']


@pytest.mark.parametrize('target,clock', [('f28004x', 100e6), ('f2803x', 60e6)])
def test_sizing_and_staleness_use_realized_pwm_frequency(target, clock):
    import math
    requested = 20.003  # kHz; deliberately not representable by an integer timer period
    result = run(SPECS, target=target, edits={'design.f_sw': requested})
    achieved = clock / (2 * round(clock / (2 * requested * 1000)))
    expected = 410 / (4 * achieved * .3 * math.sqrt(2) * 20) * 1e6
    assert result['inductors']['rect']['l_uh'] == pytest.approx(expected)
    assert 'requested 20.003 kHz → achieved' in result['summaries']['inv']
    # Here both clocks round to the original 20 kHz. A changed request alone does not invalidate gains.
    assert achieved == 20000 and result['ok']
    changed = run(SPECS, target=target, edits={'design.f_sw': 23})
    assert not changed['ok']
    assert all(s['against'] == 'actual.f_sw' and s['status'] == 'fail' for s in changed['staleness'])


@pytest.mark.parametrize('target,clock', [('f28004x', 100e6), ('f2803x', 60e6)])
def test_nonrepresentable_frequency_updates_both_inductor_requirements(target, clock):
    import math
    result = run(SPECS, target=target, edits={'design.f_sw': 23})
    achieved = clock / (2 * round(clock / 46000))
    assert achieved != 23000
    for stage, current in [('rect', 20), ('out', 12.5)]:
        assert result['inductors'][stage]['l_uh'] == pytest.approx(410 / (4 * achieved * .3 * math.sqrt(2) * current) * 1e6)
    assert all(s['current'] != '23 kHz' for s in result['staleness'])
