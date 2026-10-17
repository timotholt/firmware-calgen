from pathlib import Path

import pytest

from calgen.build import build
from calgen.cli import main
from calgen.codegen import GateError, PatchError, find_markers, header, patch
from calgen.spec import load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"
RULES = load_rules(SPECS / "rules.yaml")


def b(name):
    return build(load_variant(SPECS / "variants" / f"{name}.yaml"), RULES)


def test_header_is_deterministic_and_ascii():
    h1, h2 = header(b("fa10507")), header(b("fa10507"))
    assert h1 == h2
    h1.encode("ascii")
    assert "#define UPS_IOUT_PKLIM_DAC_HI      3134u" in h1
    assert "#define UPS_FOUT_MODE              UPS_FOUT_CHANGER" in h1
    assert "NOT GENERATED" in h1  # alarm current, absent from this data sheet


def test_header_cites_datasheet_quotes():
    h = header(b("fa10507"))
    assert 'DS-10507 Rev.101119 p2: "Shutdown at 20% Overload"' in h
    assert "designed against: design.f_sw = 20 kHz (staleness-tracked)" in h


def test_header_shows_override_reason():
    h = header(b("fa10434"))
    assert "OVERRIDE ds.iin_max" in h and "labels are swapped" in h


def test_failed_build_refuses_to_generate():
    with pytest.raises(GateError) as exc:
        header(b("fa10507_revB"))
    assert any("iout_sense_range" in f for f in exc.value.failures)


TEMPLATE = """\
#include <stdint.h>
/* hand-written code above is untouched */
/* CALGEN:BEGIN out */
#define UPS_IOUT_TRIP_A 14.0f /* stale hand edit */
/* CALGEN:END out */
int keep_me(void) { return 42; }
  /* CALGEN:BEGIN bus */
  /* CALGEN:END bus */
"""


def test_patch_rewrites_only_marked_blocks_and_is_idempotent():
    bld = b("fa10507")
    once = patch(TEMPLATE, bld)
    assert "14.0f" not in once and "#define UPS_IOUT_TRIP_A            15.0f" in once
    assert once.startswith("#include <stdint.h>\n/* hand-written code above is untouched */\n")
    assert "int keep_me(void) { return 42; }" in once
    assert "UPS_VBUS_SET_V" in once
    assert patch(once, bld) == once


@pytest.mark.parametrize(
    "bad, msg",
    [
        ("/* CALGEN:BEGIN out */\n", "no matching END"),
        ("/* CALGEN:END out */\n", "has no BEGIN"),
        ("/* CALGEN:BEGIN out */\n/* CALGEN:END out */\n/* CALGEN:BEGIN out */\n/* CALGEN:END out */\n", "duplicate"),
        ("/* CALGEN:BEGIN nope */\n/* CALGEN:END nope */\n", "not defined in rules"),
    ],
)
def test_patch_marker_errors(bad, msg):
    with pytest.raises(PatchError, match=msg):
        patch(bad, b("fa10507"))


def test_find_markers_overlap():
    with pytest.raises(PatchError, match="overlap|no matching"):
        find_markers("/* CALGEN:BEGIN a */\n/* CALGEN:BEGIN b */\n/* CALGEN:END a */\n/* CALGEN:END b */\n")


def test_cli_build_writes_then_reports_up_to_date(tmp_path, capsys):
    v = str(SPECS / "variants" / "fa10449.yaml")
    assert main(["build", v, "--out", str(tmp_path)]) == 0
    assert (tmp_path / "calgen_fa10449.h").exists()
    assert main(["build", v, "--out", str(tmp_path)]) == 0
    assert "up to date" in capsys.readouterr().out


def test_cli_dry_run_prints_diff_and_writes_nothing(tmp_path, capsys):
    v = str(SPECS / "variants" / "fa10449.yaml")
    assert main(["build", v, "--out", str(tmp_path), "--dry-run"]) == 0
    assert "+#define UPS_IOUT_RATED_A" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_cli_failed_gates_exit_nonzero_and_write_nothing(tmp_path, capsys):
    v = str(SPECS / "variants" / "fa10507_revB.yaml")
    assert main(["build", v, "--out", str(tmp_path)]) == 1
    assert "nothing written" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
