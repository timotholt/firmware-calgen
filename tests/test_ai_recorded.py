"""Offline regression over the committed model recordings.

The bar was set in docs/PLAN.md before any model was run: mean >= 90% category
and >= 85% units across recorded runs. These tests check that recordings still
replay and that the published verdict (pass or not) matches the numbers; they do
not force a model to pass.
"""

from pathlib import Path

from calgen.ai import ReplayBackend, classify
from calgen.audit import scan
from calgen.evals import load_key, score
from calgen.spec import load_rules

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "legacy_ups"
RECORDINGS = sorted((CORPUS / "ai_runs").glob("*.json"))
BAR_CATEGORY, BAR_UNITS = 90.0, 85.0


def scores():
    cands = scan(CORPUS)
    key = load_key(CORPUS / "ANSWER_KEY.yaml")
    rules = load_rules(ROOT / "specs" / "rules.yaml")
    out = []
    for rec in RECORDINGS:
        backend = ReplayBackend(rec)
        out.append(score(backend.model, cands, key, classify(CORPUS, cands, rules, backend)))
    return out


def test_every_recording_replays_with_valid_answers():
    s = scores()
    assert s, "no recorded AI run; the demo site needs at least one"
    assert all(x.answered == x.n == 33 for x in s)


def test_nano_verdict_is_reported_honestly():
    runs = [x for x in scores() if x.model == "gpt-5.4-nano"]
    assert len(runs) >= 3
    cat = sum(x.pct(x.category) for x in runs) / len(runs)
    units = sum(x.pct(x.units) for x in runs) / len(runs)
    rule = sum(x.pct(x.rule) for x in runs) / len(runs)
    passes = cat >= BAR_CATEGORY and units >= BAR_UNITS
    readme = (ROOT / "README.md").read_text()
    # the README must state the same verdict the numbers give
    assert ("passes the bar" in readme) == passes
    assert rule >= 90.0  # rule mapping is what the audit uses
