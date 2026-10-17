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


def test_fixed_point_header_defines_global_q_before_types():
    text = (ROOT / "firmware" / "include" / "calgen_fa10507_f2803x.h").read_text()
    # regression: CALGEN_REAL() in calgen_types.h is chosen by #ifdef CALGEN_GLOBAL_Q
    assert text.index("#define CALGEN_GLOBAL_Q 20") < text.index('#include "calgen_types.h"')
