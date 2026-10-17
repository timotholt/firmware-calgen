"""Audit existing C firmware against the spec (read-only, deterministic).

Step 1 (scan): find every numeric constant in C files — ``#define``s,
``const`` initializers, and magic numbers inline in code — with file, line,
and the surrounding comment.

Step 2 (conform): for constants an engineer has mapped to a rule
(``calgen_map.yaml``), compare the legacy value with what calgen generates
for the chosen variant. Unmapped constants are listed as "unexplained" —
the inventory a reviewer (or the optional AI step) works through next.

Nothing here modifies the scanned files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from calgen.build import OK, Build
from calgen.expr import ExprError, Quantity, evaluate, parse

MATCH, MISMATCH, UNMAPPED, NO_VALUE = "match", "mismatch", "unmapped", "no_value"

_NUM = r"(?:0[xX][0-9A-Fa-f]+|\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)"
_SUFFIX = r"[uUlLfF]*"
_NUM_RE = re.compile(rf"(?<![\w.])({_NUM}){_SUFFIX}(?![\w.])")
_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+(.+?)\s*$")
_CONST = re.compile(r"^\s*(?:static\s+)?const\s+[\w\s]+?\s([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*=\s*([^;]+);")
_CAST = re.compile(r"\(\s*(?:unsigned\s+|signed\s+)?(?:float|double|int|long|short|char|u?int\d+_t|int\d+_t)\s*\)")
TRIVIAL = {0.0, 1.0}


@dataclass(frozen=True)
class Candidate:
    file: str
    line: int
    symbol: str  # macro/const name, or "<inline>"
    literal: str  # as written (expression for derived macros)
    value: float | None  # numeric value if known
    typed: bool  # hand-typed literal (vs derived from other macros)
    comment: str
    context: str  # the source line, stripped

    @property
    def key(self) -> str:
        return f"{self.file}:{self.line}:{self.symbol}"


def _split_comment(line: str) -> tuple[str, str]:
    code, comment = line, ""
    if "//" in code:
        code, comment = code.split("//", 1)
    m = re.search(r"/\*(.*?)(\*/|$)", code)
    if m:
        comment = (m.group(1) + " " + comment).strip()
        code = code[: m.start()] + code[m.end():]
    return code.rstrip(), comment.strip()


def _strip_block_comments(text: str) -> list[str]:
    """Blank out multi-line /* */ comment bodies (keeping line count) except on their first line."""
    out, in_block = [], False
    for line in text.splitlines():
        if in_block:
            if "*/" in line:
                in_block = False
                line = " " * (line.index("*/") + 2) + line[line.index("*/") + 2:]
            else:
                out.append("")
                continue
        start = line.find("/*")
        if start >= 0 and "*/" not in line[start:]:
            in_block = True
            line = line[:start] + "/*" + line[start + 2:] + "*/"
        out.append(line)
    return out


def _to_float(text: str) -> float:
    text = re.sub(r"[uUlLfF]+$", "", text)
    return float(int(text, 16)) if text.lower().startswith("0x") else float(text)


def _python_expr(c_expr: str) -> str:
    e = _CAST.sub("", c_expr)
    return _NUM_RE.sub(lambda m: m.group(1), e)


def _eval_c(c_expr: str, known: dict[str, float]) -> float | None:
    try:
        f = parse(_python_expr(c_expr))
        return evaluate(f, {k: Quantity(v) for k, v in known.items()}).value
    except (ExprError, ValueError, ZeroDivisionError):
        return None


def scan_file(path: Path, root: Path | None = None) -> list[Candidate]:
    rel = str(path.relative_to(root)) if root else path.name
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = _strip_block_comments(path.read_text(encoding="utf-8"))
    known: dict[str, float] = {}
    out: list[Candidate] = []
    for i, line in enumerate(lines, start=1):
        code, comment = _split_comment(line)
        context = raw_lines[i - 1].strip()
        if not code.strip():
            continue
        if m := _DEFINE.match(code):
            name, expr = m.group(1), m.group(2).strip()
            bare = _CAST.sub("", expr).strip().strip("()").strip()
            if re.fullmatch(rf"[-+]?{_NUM}{_SUFFIX}", bare):
                v = _to_float(bare.lstrip("+"))
                known[name] = v
                out.append(Candidate(rel, i, name, expr, v, True, comment, context))
            elif _NUM_RE.search(expr) or re.search(r"[A-Za-z_]\w*", expr):
                v = _eval_c(expr, known)
                if v is not None:
                    known[name] = v
                if _NUM_RE.search(expr) or v is not None:
                    out.append(Candidate(rel, i, name, expr, v, False, comment, context))
            continue
        if code.lstrip().startswith("#"):
            continue
        if m := _CONST.match(code):
            name, expr = m.group(1), m.group(2).strip()
            if "{" in expr:  # array initializer: each element is inline data
                for n in _NUM_RE.finditer(expr):
                    out.append(Candidate(rel, i, f"{name}[]", n.group(0), _to_float(n.group(0)), True, comment, context))
                continue
            v = _eval_c(expr, known)
            typed = bool(re.fullmatch(rf"[-+]?{_NUM}{_SUFFIX}", _CAST.sub("", expr).strip()))
            if v is not None:
                known[name] = v
            out.append(Candidate(rel, i, name, expr, v, typed, comment, context))
            continue
        for n in _NUM_RE.finditer(code):
            v = _to_float(n.group(0))
            if v in TRIVIAL:
                continue
            out.append(Candidate(rel, i, "<inline>", n.group(0), v, True, comment, context))
    return out


def scan(root: Path) -> list[Candidate]:
    files = sorted(p for p in root.rglob("*") if p.suffix in (".c", ".h"))
    return [c for f in files for c in scan_file(f, root)]


# --- conformance ------------------------------------------------------------


@dataclass(frozen=True)
class MapEntry:
    file: str
    symbol: str
    rule: str
    scale: float  # multiply legacy value by this to get the rule's unit
    reviewed_by: str
    note: str = ""
    line: int | None = None  # required for "<inline>" magic numbers


@dataclass(frozen=True)
class Conformance:
    candidate: Candidate
    status: str
    rule: str | None = None
    expected: float | None = None
    legacy: float | None = None
    rel_diff: float | None = None
    note: str = ""


def load_map(path: Path) -> list[MapEntry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for e in data.get("map", []):
        out.append(
            MapEntry(
                file=str(e["file"]),
                symbol=str(e["symbol"]),
                rule=str(e["rule"]),
                scale=float(e.get("scale", 1.0)),
                reviewed_by=str(e.get("reviewed_by", "")),
                note=str(e.get("note", "")),
                line=int(e["line"]) if e.get("line") is not None else None,
            )
        )
    return out


def conform(candidates: list[Candidate], mapping: list[MapEntry], build: Build, rel_tol: float = 0.005) -> list[Conformance]:
    by_line = {(m.file, m.symbol, m.line): m for m in mapping if m.line is not None}
    by_name = {(m.file, m.symbol): m for m in mapping if m.line is None and m.symbol != "<inline>"}
    out = []
    for c in candidates:
        m = by_line.get((c.file, c.symbol, c.line)) or by_name.get((c.file, c.symbol))
        if m is None:
            out.append(Conformance(c, UNMAPPED))
            continue
        r = next((x for x in build.constants if x.rule.id == m.rule), None)
        if r is None or r.status != OK or r.encoded is None:
            out.append(Conformance(c, NO_VALUE, m.rule, note="rule has no generated numeric value for this variant"))
            continue
        if c.value is None:
            out.append(Conformance(c, NO_VALUE, m.rule, note="legacy value could not be evaluated"))
            continue
        legacy = c.value * m.scale
        expected = r.encoded.stored
        is_int = r.encoded.code is not None and r.fmt and r.fmt.startswith(("uint", "int"))
        diff = abs(legacy - expected)
        rel = diff / abs(expected) if expected else (0.0 if diff == 0 else float("inf"))
        ok = diff <= 1.0 if is_int else rel <= rel_tol
        out.append(Conformance(c, MATCH if ok else MISMATCH, m.rule, expected, legacy, rel, m.note))
    return out
