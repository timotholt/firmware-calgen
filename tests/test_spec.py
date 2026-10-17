import textwrap

import pytest

from calgen.spec import SpecError, load_datasheet, load_paramset, load_rules, load_variant

HEADER = "field,label,raw,value,unit,source\n"


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    return p


def test_datasheet_loads_numeric_and_text(tmp_path):
    p = write(
        tmp_path,
        "ds.csv",
        HEADER
        + 'part_number,IP Part #,FA10507,FA10507,,DS p2\n'
        + 'model_string,IP Model #,IHT1500RM,IHT1500RM,,DS p2\n'
        + 'power_va,Power Rating,"1500 VA, 1250 W",1500,VA,DS p2\n'
        + 'fout_mode,Output Frequency,"60 Hz, Changer",changer,,DS p2\n',
    )
    ds = load_datasheet(p)
    assert ds.part == "FA10507"
    assert ds.params["power_va"].quantity().value == 1500
    assert ds.params["fout_mode"].value == "changer"
    assert ds.params["power_va"].raw == "1500 VA, 1250 W"


def test_datasheet_collects_all_issues(tmp_path):
    p = write(
        tmp_path,
        "ds.csv",
        HEADER + "power_va,x,x,abc,VA,\n" + "vout,x,x,120,furlong,DS\n" + "vout,x,x,1,V,DS\n",
    )
    with pytest.raises(SpecError) as exc:
        load_datasheet(p)
    text = str(exc.value)
    for fragment in ("needs a source", "not a number", "unknown unit", "duplicate", "part_number"):
        assert fragment in text


def test_datasheet_wrong_columns(tmp_path):
    p = write(tmp_path, "ds.csv", "a,b\n1,2\n")
    with pytest.raises(SpecError, match="columns"):
        load_datasheet(p)


def test_paramset(tmp_path):
    p = write(
        tmp_path,
        "b.yaml",
        """
        board: ups_ctrl
        rev: A
        params:
          r_shunt: {value: 10, unit: mohm, note: invented}
          g_amp: {value: 20, unit: ratio}
        """,
    )
    b = load_paramset(p, "board")
    assert b.name == "ups_ctrl" and b.extra["rev"] == "A"
    assert b.params["r_shunt"].quantity().value == pytest.approx(0.01)


def test_paramset_bad_values(tmp_path):
    p = write(
        tmp_path,
        "b.yaml",
        """
        board: x
        params:
          a: {value: yes, unit: V}
          b: {value: 1}
          c: {value: 1, unit: zz}
        """,
    )
    with pytest.raises(SpecError) as exc:
        load_paramset(p, "board")
    assert len(exc.value.issues) == 3


def test_rules_validation(tmp_path):
    p = write(
        tmp_path,
        "r.yaml",
        """
        blocks: {out: AC output}
        constants:
          - {id: a, symbol: A_, formula: "ds.x / ds.y", unit: A, format: float32, block: out}
          - {id: a, symbol: B_, formula: "eval('1')", unit: A, format: float64, block: nowhere}
        checks:
          - {id: c1, lhs: a, op: "=<", rhs: "1"}
        """,
    )
    with pytest.raises(SpecError) as exc:
        load_rules(p)
    text = str(exc.value)
    for fragment in ("duplicate id", "not allowed", "unknown format", "unknown block", "op must be"):
        assert fragment in text


def test_variant_resolves_relative_paths(tmp_path):
    (tmp_path / "datasheets").mkdir()
    (tmp_path / "variants").mkdir()
    write(tmp_path, "datasheets/d.csv", HEADER + "part_number,a,P1,P1,,s\nmodel_string,a,M,M,,s\n")
    write(tmp_path, "b.yaml", "board: b\nparams: {}\n")
    write(tmp_path, "t.yaml", "target: t\nparams: {}\n")
    v = write(
        tmp_path,
        "variants/v.yaml",
        """
        variant: v1
        inverter: {topology: full_bridge, pwm: unipolar}
        datasheet: ../datasheets/d.csv
        board: ../b.yaml
        target: ../t.yaml
        design:
          f_sw: {value: 20, unit: kHz, designed_against: {}}
          kp: {value: 0.8, unit: ratio, designed_against: {design.f_sw: 20 kHz}}
        """,
    )
    var = load_variant(v)
    assert var.datasheet.part == "P1"
    assert var.design.params["kp"].designed_against == {"design.f_sw": "20 kHz"}
    assert len(var.digest()) == 64


@pytest.mark.parametrize('config', ['', 'inverter: {topology: half_bridge, pwm: unipolar}', 'inverter: {topology: invented, pwm: bipolar}'])
def test_missing_or_unsupported_inverter_contract_is_rejected(tmp_path, config):
    path = write(tmp_path, 'v.yaml', 'variant: x\ndatasheet: d.csv\nboard: b.yaml\ntarget: t.yaml\n' + config)
    with pytest.raises(SpecError, match='supported topology/PWM pair'):
        load_variant(path)
