"""The consistency gate on the three real data sheets: exactly the known issues, no false alarms."""

from pathlib import Path

from calgen.build import BLOCKING, FLAGGED, WAIVED, build
from calgen.consistency import ERROR, WARNING, check_datasheet
from calgen.spec import load_datasheet, load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"


def findings(part):
    return {(f.severity, f.check, f.fields) for f in check_datasheet(load_datasheet(SPECS / "datasheets" / f"{part}.csv"))}


def test_fa10449_changer_vs_follower():
    assert findings("fa10449") == {
        (WARNING, "model_vs_fields", ("fout_mode", "model_string")),
        (WARNING, "description_vs_fields", ("fout_mode",)),
    }


def test_fa10434_swapped_labels():
    assert findings("fa10434") == {
        (ERROR, "label_vs_cell", ("iin_max",)),
        (ERROR, "label_vs_cell", ("fin_nom",)),
    }


def test_fa10507_two_model_numbers():
    assert findings("fa10507") == {
        (WARNING, "model_vs_fields", ("isolation", "model_string")),
        (WARNING, "page_vs_page", ("model_string",)),
    }


def test_swapped_label_is_waived_by_override_and_unused_field_is_flagged():
    b = build(load_variant(SPECS / "variants" / "fa10434.yaml"), load_rules(SPECS / "rules.yaml"))
    status = {d.finding.fields: d.status for d in b.datasheet}
    assert status[("iin_max",)] == WAIVED
    assert status[("fin_nom",)] == FLAGGED  # no rule reads input frequency
    assert b.ok


def test_consumed_error_without_override_blocks(tmp_path):
    text = (SPECS / "variants" / "fa10434.yaml").read_text().split("datasheet_overrides:")[0]
    v = tmp_path / "v.yaml"
    v.write_text(text.replace("../", str(SPECS) + "/"))
    b = build(load_variant(v), load_rules(SPECS / "rules.yaml"))
    assert any(d.status == BLOCKING for d in b.datasheet)
    assert any(f.startswith("data sheet iin_max") for f in b.failures)


def test_warnings_never_block():
    b = build(load_variant(SPECS / "variants" / "fa10449.yaml"), load_rules(SPECS / "rules.yaml"))
    assert b.ok and len(b.datasheet) == 2 and all(d.status == FLAGGED for d in b.datasheet)
