"""Score AI classifications against a blind answer key.

The key is written independently of the classifier and is never shown to it.
Scores measure the pipeline on a synthetic corpus, not real-world accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from calgen.ai import FileResult
from calgen.audit import Candidate

# unit spellings treated as equal
_UNIT_ALIASES = {
    "v/count": {"v/count", "v/counts", "v per count", "v/lsb"},
    "a/count": {"a/count", "a/counts", "a per count", "a/lsb"},
    "counts": {"counts", "count", "lsb", "ticks", "cycles"},
    "ratio": {"ratio", "none", "1", "unitless", "dimensionless"},
    "ms": {"ms", "millisecond", "milliseconds"},
    "s": {"s", "sec", "seconds"},
    "us": {"us", "µs", "microseconds"},
    "baud": {"baud", "bps", "bit/s"},
    "bytes": {"bytes", "byte", "b"},
}


def norm_unit(u: str | None) -> str:
    u = (u or "none").strip().lower()
    for canon, names in _UNIT_ALIASES.items():
        if u in names:
            return canon
    return u


@dataclass(frozen=True)
class KeyEntry:
    file: str
    line: int
    symbol: str
    literal: str
    value: float | None
    category: str
    units: str
    typed: bool
    maps_to_rule: str | None
    expected_conformance: str
    correct_value: float | None
    notes: str = ""


def load_key(path: Path) -> list[KeyEntry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    entries = data if isinstance(data, list) else data.get("entries", [])
    return [
        KeyEntry(
            file=str(e["file"]),
            line=int(e["line"]),
            symbol=str(e["symbol"]),
            literal=str(e["literal"]),
            value=None if e.get("value") is None else float(e["value"]),
            category=str(e["category"]),
            units=str(e.get("units", "none")),
            typed=bool(e.get("typed", True)),
            maps_to_rule=e.get("maps_to_rule"),
            expected_conformance=str(e.get("expected_conformance", "not_applicable")),
            correct_value=None if e.get("correct_value") is None else float(e["correct_value"]),
            notes=str(e.get("notes", "")),
        )
        for e in entries
    ]


def _norm_literal(s: str) -> str:
    return s.strip().rstrip("uUlLfF").lstrip("+").strip("()")


def match_key(cands: list[Candidate], key: list[KeyEntry]) -> tuple[dict[int, KeyEntry], list[KeyEntry]]:
    """Pair scanner candidates with key entries by (file, line, literal); returns (index -> entry, unmatched key)."""
    pool = list(key)
    out: dict[int, KeyEntry] = {}
    for i, c in enumerate(cands):
        for k in pool:
            same_place = k.file == c.file and k.line == c.line
            same_value = _norm_literal(k.literal) == _norm_literal(c.literal) or (
                k.value is not None and c.value is not None and abs(k.value - c.value) <= 1e-9 * max(1.0, abs(k.value))
            )
            if same_place and (same_value or (k.symbol == c.symbol and c.symbol != "<inline>")):
                out[i] = k
                pool.remove(k)
                break
    return out, pool


@dataclass
class Score:
    model: str
    n: int  # key entries the scanner found
    answered: int
    category: int
    units: int
    typed: int
    rule: int
    input_tokens: int
    output_tokens: int
    latency_s: float
    missed_by_scanner: list[str] = field(default_factory=list)
    extra_from_scanner: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def pct(self, x: int) -> float:
        return 100.0 * x / self.n if self.n else 0.0


def score(model: str, cands: list[Candidate], key: list[KeyEntry], results: list[FileResult]) -> Score:
    from calgen.ai import candidate_id

    pairs, unmatched = match_key(cands, key)
    ids_by_file: dict[str, list[tuple[int, Candidate]]] = {}
    for i, c in enumerate(cands):
        ids_by_file.setdefault(c.file, []).append((i, c))
    answers = {}
    for r in results:
        for item in r.items:
            answers[item.id] = item
    s = Score(model, len(pairs), 0, 0, 0, 0, 0,
              sum(r.input_tokens for r in results), sum(r.output_tokens for r in results), sum(r.latency_s for r in results))
    s.missed_by_scanner = [f"{k.file}:{k.line} {k.symbol} {k.literal}" for k in unmatched]
    s.extra_from_scanner = [f"{c.file}:{c.line} {c.symbol} {c.literal}" for i, c in enumerate(cands) if i not in pairs]
    for file, items in ids_by_file.items():
        for local, (i, c) in enumerate(items):
            if i not in pairs:
                continue
            k = pairs[i]
            a = answers.get(candidate_id(c, local))
            if a is None:
                s.errors.append(f"no valid answer for {c.file}:{c.line} {c.symbol}")
                continue
            s.answered += 1
            s.category += a.category == k.category
            s.units += norm_unit(a.units) == norm_unit(k.units)
            s.typed += a.typed == k.typed
            s.rule += a.maps_to_rule == k.maps_to_rule
            if a.category != k.category or a.maps_to_rule != k.maps_to_rule:
                s.errors.append(
                    f"{c.file}:{c.line} {c.symbol}: said {a.category}/{a.maps_to_rule}, key {k.category}/{k.maps_to_rule}"
                )
    return s
