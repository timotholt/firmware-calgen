"""AI step plumbing, with a scripted fake model (no network)."""

import json
from pathlib import Path

import pytest

from calgen.ai import (
    NoBackend,
    ReplayBackend,
    build_prompt,
    candidate_id,
    classify,
    output_schema,
    record,
    validate,
)
from calgen.audit import scan
from calgen.evals import KeyEntry, norm_unit, score
from calgen.spec import load_rules

SPECS = Path(__file__).resolve().parent.parent / "specs"
RULES = load_rules(SPECS / "rules.yaml")
RULE_IDS = [r.id for r in RULES.constants if r.kind == "numeric"]

SRC = """\
/* fixture written for this test */
#define TRIP_I     14.0f   /* amps */
#define UART_BAUD  115200
"""


class Scripted:
    """Answers like a model would, from a fixed table; counts calls."""

    name, model = "scripted", "fake-1"

    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def complete(self, system, prompt, schema):
        self.calls += 1
        assert "TRIP_I" in prompt and "ANSWER" not in prompt  # never sees a key
        return {"items": self.answers}, 100, 20


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "cfg.h").write_text(SRC)
    return tmp_path, scan(tmp_path)


def good_answers(cands):
    return [
        {"id": candidate_id(cands[0], 0), "category": "trip_limit", "units": "A", "typed": True,
         "maps_to_rule": "iout_trip", "confidence": "high", "reason": "trip current"},
        {"id": candidate_id(cands[1], 1), "category": "comms_or_buffer", "units": "baud", "typed": True,
         "maps_to_rule": None, "confidence": "high", "reason": "serial rate"},
    ]


KEY = [
    KeyEntry("cfg.h", 2, "TRIP_I", "14.0f", 14.0, "trip_limit", "A", True, "iout_trip", "mismatch", 15.0),
    KeyEntry("cfg.h", 3, "UART_BAUD", "115200", 115200.0, "comms_or_buffer", "baud", True, None, "not_applicable", None),
]


def test_schema_lists_rule_ids_and_forbids_extras():
    s = output_schema(RULE_IDS)
    item = s["properties"]["items"]["items"]
    assert item["additionalProperties"] is False
    assert "iout_trip" in item["properties"]["maps_to_rule"]["anyOf"][0]["enum"]


def test_validate_rejects_bad_items():
    ids = ["a", "b", "c"]
    raw = {"items": [
        {"id": "a", "category": "trip_limit", "units": "A", "typed": True, "maps_to_rule": "iout_trip", "confidence": "high", "reason": ""},
        {"id": "b", "category": "made_up", "units": "A", "typed": True, "maps_to_rule": None, "confidence": "high", "reason": ""},
        {"id": "c", "category": "timing", "units": "s", "typed": "yes", "maps_to_rule": None, "confidence": "high", "reason": ""},
        {"id": "zzz", "category": "timing", "units": "s", "typed": True, "maps_to_rule": None, "confidence": "high", "reason": ""},
    ]}
    good, invalid = validate(raw, ids, RULE_IDS)
    assert [g.id for g in good] == ["a"] and invalid == ["b", "c"]


def test_classify_and_score_perfect(corpus):
    root, cands = corpus
    model = Scripted(good_answers(cands))
    results = classify(root, cands, RULES, model)
    assert model.calls == 1
    s = score("fake-1", cands, KEY, results)
    assert (s.n, s.answered, s.category, s.units, s.rule) == (2, 2, 2, 2, 2)
    assert s.input_tokens == 100 and not s.missed_by_scanner


def test_record_then_replay_is_identical_and_offline(corpus, tmp_path):
    root, cands = corpus
    live = classify(root, cands, RULES, Scripted(good_answers(cands)))
    rec = tmp_path / "rec.json"
    record(live, Scripted([]), rec)
    replayed = classify(root, cands, RULES, ReplayBackend(rec))
    assert [i.__dict__ for i in replayed[0].items] == [i.__dict__ for i in live[0].items]
    assert json.loads(rec.read_text())["model"] == "fake-1"


def test_replay_refuses_when_prompt_changed(corpus, tmp_path):
    root, cands = corpus
    rec = tmp_path / "rec.json"
    record(classify(root, cands, RULES, Scripted(good_answers(cands))), Scripted([]), rec)
    (root / "cfg.h").write_text(SRC.replace("amps", "amperes"))
    with pytest.raises(LookupError, match="re-record"):
        classify(root, scan(root), RULES, ReplayBackend(rec))


def test_none_backend_answers_nothing(corpus):
    root, cands = corpus
    s = score("none", cands, KEY, classify(root, cands, RULES, NoBackend()))
    assert s.answered == 0 and len(s.errors) == 2


def test_unit_aliases():
    assert norm_unit("V/LSB") == "v/count" and norm_unit("bps") == "baud" and norm_unit(None) == "ratio"


def test_prompt_numbers_lines(corpus):
    root, cands = corpus
    prompt, ids = build_prompt(SRC, "cfg.h", cands, RULES)
    assert "   2| #define TRIP_I" in prompt and len(ids) == 2
