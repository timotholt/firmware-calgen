from pathlib import Path

import pytest

from calgen.audit import MATCH, MISMATCH, UNMAPPED, MapEntry, conform, scan_file
from calgen.build import build
from calgen.spec import load_rules, load_variant

SPECS = Path(__file__).resolve().parent.parent / "specs"

LEGACY = """\
/* test fixture, written for this test */
#define TRIP_I        14.0f   /* amps */
#define VBUS_FS       498.3f
#define VBUS_PER_CNT  (VBUS_FS / 4095.0f)  // derived
#define PWM_PRD       (5000u)
#define UART_BAUD     115200
/* a multi-line comment with numbers 42 and 3.14
   that must not be scanned 99 */
static const float K_VS = 0.12168f;
static const unsigned short TBL[3] = { 10, 20, 30 };

int check(float i) {
    if (i > 13.5f) { return 2; }   /* inline magic number */
    return 0;
}
"""


@pytest.fixture
def cands(tmp_path):
    p = tmp_path / "legacy.c"
    p.write_text(LEGACY)
    return {(c.symbol, c.line): c for c in scan_file(p)}


def test_scan_defines_consts_and_inline(cands):
    syms = {s for s, _ in cands}
    assert {"TRIP_I", "VBUS_FS", "VBUS_PER_CNT", "PWM_PRD", "UART_BAUD", "K_VS", "TBL[]", "<inline>"} <= syms
    assert cands[("TRIP_I", 2)].value == 14.0 and cands[("TRIP_I", 2)].typed
    assert cands[("TRIP_I", 2)].comment == "amps"
    assert cands[("PWM_PRD", 5)].value == 5000 and cands[("PWM_PRD", 5)].typed


def test_derived_macro_is_evaluated_and_marked_derived(cands):
    c = cands[("VBUS_PER_CNT", 4)]
    assert not c.typed
    assert c.value == pytest.approx(498.3 / 4095)


def test_multiline_comment_numbers_ignored(cands):
    assert not any(line in (7, 8) for _, line in cands)


def test_inline_literal_found_with_trivial_literals_skipped(tmp_path):
    p = tmp_path / "legacy.c"
    p.write_text(LEGACY)
    inline = [c for c in scan_file(p) if c.symbol == "<inline>"]
    assert [(c.line, c.value) for c in inline] == [(13, 13.5), (13, 2.0)]


def test_conformance_match_and_mismatch(tmp_path):
    p = tmp_path / "legacy.c"
    p.write_text(LEGACY)
    cs = scan_file(p)
    b = build(load_variant(SPECS / "variants" / "fa10507.yaml"), load_rules(SPECS / "rules.yaml"))
    mapping = [
        MapEntry("legacy.c", "TRIP_I", "iout_trip", 1.0, "test"),
        MapEntry("legacy.c", "K_VS", "vbus_scale", 1.0, "test"),
        MapEntry("legacy.c", "PWM_PRD", "pwm_period", 1.0, "test"),
    ]
    res = {r.candidate.symbol: r for r in conform(cs, mapping, b)}
    assert res["TRIP_I"].status == MISMATCH and res["TRIP_I"].expected == 15.0
    assert res["K_VS"].status == MATCH  # 0.12168 vs 0.121684976: within 0.5%
    assert res["PWM_PRD"].status == MATCH
    assert res["UART_BAUD"].status == UNMAPPED


def test_corpus_conformance_reproduces_answer_key():
    """Deterministic audit of the synthetic legacy corpus agrees with the blind key on every constant."""
    from calgen.audit import NO_VALUE, load_map, scan
    from calgen.evals import load_key, match_key

    root = Path(__file__).resolve().parent.parent / "corpus" / "legacy_ups"
    cands = scan(root)
    key = load_key(root / "ANSWER_KEY.yaml")
    pairs, missed = match_key(cands, key)
    assert not missed and len(pairs) == len(cands) == len(key)
    b = build(load_variant(SPECS / "variants" / "fa10507.yaml"), load_rules(SPECS / "rules.yaml"))
    results = conform(cands, load_map(root / "calgen_map.yaml"), b)
    want = {"match": MATCH, "mismatch": MISMATCH, "not_applicable": UNMAPPED}
    for i, r in enumerate(results):
        k = pairs[i]
        assert r.status != NO_VALUE, (k.symbol, r.note)
        assert r.status == want[k.expected_conformance], (k.file, k.line, k.symbol, r.status, k.expected_conformance)
