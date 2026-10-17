"""Offline regression: committed model recordings must still replay and pass the accuracy bar.

The bar was set in docs/PLAN.md before any model was run: >= 90% category, >= 85% units.
"""

from pathlib import Path

import pytest

from calgen.ai import ReplayBackend, classify
from calgen.audit import scan
from calgen.evals import load_key, score
from calgen.spec import load_rules

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "legacy_ups"
RECORDINGS = sorted((CORPUS / "ai_runs").glob("*.json"))


@pytest.mark.parametrize("rec", RECORDINGS, ids=[r.stem for r in RECORDINGS])
def test_recording_replays_and_meets_bar(rec):
    cands = scan(CORPUS)
    backend = ReplayBackend(rec)
    s = score(backend.model, cands, load_key(CORPUS / "ANSWER_KEY.yaml"), classify(CORPUS, cands, load_rules(ROOT / "specs" / "rules.yaml"), backend))
    assert s.answered == s.n == 33
    assert s.pct(s.category) >= 90 and s.pct(s.units) >= 85, (s.pct(s.category), s.pct(s.units))


def test_at_least_one_recording_committed():
    assert RECORDINGS, "no recorded AI run; the demo site needs one"
