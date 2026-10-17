"""Committed generated files must equal a fresh generation.

Catches both hand edits to generated code and spec changes that weren't
regenerated. Fix with:
    calgen build specs/variants/<v>.yaml --out firmware/include
    calgen build specs/variants/fa10507.yaml --patch firmware/src/board.h
"""

from pathlib import Path

import pytest

from calgen.build import build
from calgen.codegen import header, patch
from calgen.spec import load_rules, load_variant

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules(ROOT / "specs" / "rules.yaml")
GENERATED = ["fa10449", "fa10434", "fa10507", "fa10507_f2803x"]


@pytest.mark.parametrize("name", GENERATED)
def test_committed_header_is_current(name):
    fresh = header(build(load_variant(ROOT / "specs" / "variants" / f"{name}.yaml"), RULES))
    committed = (ROOT / "firmware" / "include" / f"calgen_{name}.h").read_text(encoding="utf-8")
    assert committed == fresh, f"calgen_{name}.h is stale or hand-edited; regenerate it"


def test_committed_board_h_is_current():
    board = ROOT / "firmware" / "src" / "board.h"
    text = board.read_text(encoding="utf-8")
    fresh = patch(text, build(load_variant(ROOT / "specs" / "variants" / "fa10507.yaml"), RULES))
    assert text == fresh, "board.h CALGEN blocks are stale or hand-edited; re-run patch"


def test_failing_variant_has_no_header():
    assert not (ROOT / "firmware" / "include" / "calgen_fa10507_revB.h").exists()


def test_number_format_lives_in_each_generated_header():
    # regression: CALGEN_REAL() once lived in calgen_types.h, chosen by #ifdef at first
    # inclusion, so including calgen_types.h before an IQ header silently skipped scaling.
    inc = ROOT / "firmware" / "include"
    assert "#define CALGEN_REAL" not in (inc / "calgen_types.h").read_text()
    for name in ("fa10449", "fa10434", "fa10507", "fa10507_f2803x"):
        text = (inc / f"calgen_{name}.h").read_text()
        assert "typedef" in text and "calgen_num_t;" in text and "#define CALGEN_REAL(x)" in text, name


def _compile(tmp_path, source, run=False):
    """Compile (and optionally run) a small C file against the generated headers; returns the exit code."""
    import shutil
    import subprocess

    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("needs a C compiler")
    (tmp_path / "t.c").write_text(source)
    inc = ROOT / "firmware" / "include"
    built = subprocess.run([cc, "-std=c99", "-Wall", "-Werror", "-pedantic", f"-I{inc}", "t.c", "-o", "t"],
                           cwd=tmp_path, capture_output=True, text=True)
    if built.returncode or not run:
        return built.returncode
    return subprocess.run([str(tmp_path / "t")], cwd=tmp_path).returncode


def test_include_order_cannot_change_fixed_point_scaling(tmp_path):
    src = (
        '#include "calgen_types.h"\n#include "calgen_fa10507_f2803x.h"\n'
        "int main(void) {\n"
        "    int ok = CALGEN_REAL(UPS_IOUT_TRIP_A) == 15.0f;  /* scaled, not read as 15.7 million */\n"
        "    ok = ok && (calgen_num_t)0.5 == 0;               /* integer type: fixed-point compares */\n"
        "    return ok ? 0 : 1;\n"
        "}\n"
    )
    assert _compile(tmp_path, src, run=True) == 0


def test_mixing_float_and_fixed_point_headers_fails_to_compile(tmp_path):
    src = '#include "calgen_fa10507.h"\n#include "calgen_fa10507_f2803x.h"\nint main(void) { return 0; }\n'
    assert _compile(tmp_path, src) != 0
