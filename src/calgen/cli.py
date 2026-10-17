"""Command-line entry point."""

from __future__ import annotations

import argparse
import difflib
import os
import sys
from pathlib import Path

from calgen import __version__
from calgen.build import FAIL, OK, SKIPPED, Build, build
from calgen.codegen import GateError, PatchError, header, patch
from calgen.spec import SpecError, load_rules, load_variant

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
_STYLE = {OK: "32", FAIL: "31", SKIPPED: "33"}


def _tag(status: str) -> str:
    text = {OK: "pass", FAIL: "FAIL", SKIPPED: "n/a "}[status]
    return f"\033[{_STYLE[status]}m{text}\033[0m" if _COLOR else text


def _default_rules(variant_path: Path) -> Path:
    return variant_path.resolve().parent.parent / "rules.yaml"


def _load(args: argparse.Namespace) -> Build:
    vpath = Path(args.variant)  # audit passes --variant; check/build pass it positionally
    rules = Path(args.rules) if args.rules else _default_rules(vpath)
    return build(load_variant(vpath), load_rules(rules))


def _print_build(b: Build) -> None:
    print(f"variant {b.variant.name}: {b.variant.datasheet.part} / {b.variant.board.name} rev "
          f"{b.variant.board.extra.get('rev', '?')} / {b.variant.target.name}")
    for c in b.constants:
        value = c.enum_ident or (c.encoded.literal if c.encoded else "-")
        note = f"  {c.message}" if c.message else ""
        print(f"  {_tag(c.status)}  {c.rule.symbol:<26} {value:<16}{note}")
    for d in b.datasheet:
        tag = {"blocking": _tag(FAIL), "waived": "wavd", "flagged": "flag"}[d.status]
        print(f"  {tag}  data sheet {', '.join(d.finding.fields):<17} {d.finding.message}")
    for st in b.staleness:
        note = f"  {st.message}" if st.message else f"  {st.against} = {st.current} as designed"
        print(f"  {_tag(st.status)}  stale? {st.param:<19}{note}")
    for k in b.checks:
        note = f"  {k.message}" if k.message else ""
        print(f"  {_tag(k.status)}  check {k.check.id:<20}{note}")
    print("all gates passed" if b.ok else f"{len(b.failures)} failure(s); nothing written")


def _diff(old: str, new: str, name: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}"))


def cmd_check(args: argparse.Namespace) -> int:
    b = _load(args)
    _print_build(b)
    return 0 if b.ok else 1


def cmd_build(args: argparse.Namespace) -> int:
    b = _load(args)
    if not b.ok:
        _print_build(b)
        return 1
    if args.patch:
        target = Path(args.patch)
        old = target.read_text(encoding="utf-8")
        new = patch(old, b)
    else:
        target = Path(args.out) / f"calgen_{b.variant.name}.h"
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        new = header(b)
    if old == new:
        print(f"{target}: up to date")
        return 0
    if args.dry_run:
        sys.stdout.write(_diff(old, new, target.name))
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new, encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    return 0


def _backend(spec: str, root: Path):
    from calgen import ai

    kind, _, model = spec.partition(":")
    if kind == "none":
        return ai.NoBackend()
    if kind == "replay":
        return ai.ReplayBackend(Path(model) if model else root / "ai_runs" / "default.json")
    if kind == "openai":
        return ai.OpenAIBackend(model)
    if kind == "anthropic":
        return ai.AnthropicBackend(model)
    raise SystemExit(f"unknown --ai backend {spec!r}; use none | replay[:file] | openai:<model> | anthropic:<model>")


def cmd_audit(args: argparse.Namespace) -> int:
    from calgen.audit import MATCH, MISMATCH, UNMAPPED, conform, load_map, scan

    root = Path(args.source)
    cands = scan(root)
    b = _load(args)
    mapping = load_map(Path(args.map)) if args.map else []
    results = conform(cands, mapping, b)
    print(f"audit {root} against {b.variant.name}: {len(cands)} numeric constants")
    for r in results:
        c = r.candidate
        where = f"{c.file}:{c.line}"
        if r.status == MATCH:
            print(f"  {_tag(OK)}  {where:<16} {c.symbol:<14} {c.literal:<12} = {r.rule}")
        elif r.status == MISMATCH:
            print(f"  {_tag(FAIL)}  {where:<16} {c.symbol:<14} {c.literal:<12} spec says {r.expected:.6g} ({r.rule})")
    unmapped = [r.candidate for r in results if r.status == UNMAPPED]
    n_mis = sum(r.status == MISMATCH for r in results)
    print(f"{sum(r.status == MATCH for r in results)} match, {n_mis} mismatch, {len(unmapped)} unexplained")
    if args.ai and unmapped:
        from calgen import ai

        res = ai.classify(root, unmapped, b.rules, _backend(args.ai, root))
        print(f"AI draft for unexplained constants ({args.ai}) -- for human review, nothing applied:")
        by_id = {i.id: i for r in res for i in r.items}
        per_file: dict[str, int] = {}
        for c in unmapped:
            n = per_file.get(c.file, 0)
            per_file[c.file] = n + 1
            item = by_id.get(ai.candidate_id(c, n))
            text = f"{item.category}, {item.units}, {item.confidence}: {item.reason}" if item else "no valid answer"
            print(f"  {c.file}:{c.line:<4} {c.symbol:<14} {c.literal:<10} {text}")
    return 1 if n_mis else 0


def cmd_eval(args: argparse.Namespace) -> int:
    from calgen import ai
    from calgen.audit import scan
    from calgen.evals import load_key, score

    root = Path(args.source)
    cands = scan(root)
    key = load_key(Path(args.key))
    rules = load_rules(Path(args.rules) if args.rules else Path("specs/rules.yaml"))
    backend = _backend(args.ai, root)
    results = ai.classify(root, cands, rules, backend)
    if args.record:
        ai.record(results, backend, Path(args.record))
        print(f"recorded {args.record}")
    s = score(backend.model, cands, key, results)
    print(f"model {s.model}: {s.n} keyed constants, {s.answered} valid answers")
    for label, v in (("category", s.category), ("units", s.units), ("typed/derived", s.typed), ("rule mapping", s.rule)):
        print(f"  {label:<14} {v:>3}/{s.n}  {s.pct(v):5.1f}%")
    print(f"  tokens in/out  {s.input_tokens}/{s.output_tokens}   latency {s.latency_s:.1f}s")
    for e in s.errors:
        print(f"  miss: {e}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from calgen.report import write_report

    b = _load(args)
    committed = Path(args.compare_to) if args.compare_to else Path("firmware/include") / f"calgen_{b.variant.name}.h"
    previous = committed.read_text(encoding="utf-8") if committed.exists() else ""
    path = write_report(b, Path(args.out), previous)
    print(f"wrote {path} ({'all gates passed' if b.ok else f'{len(b.failures)} failure(s)'})")
    return 0 if b.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calgen",
        description="Generate firmware constants from engineering specs, with provenance and gates.",
    )
    parser.add_argument("--version", action="version", version=f"calgen {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    def variant_cmd(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("variant", help="variant YAML, e.g. specs/variants/fa10507.yaml")
        p.add_argument("--rules", help="rules YAML (default: <specs>/rules.yaml)")
        return p

    p = variant_cmd("check", "evaluate every constant and gate; write nothing")
    p.set_defaults(func=cmd_check)
    p = variant_cmd("build", "generate the C header (or patch marked blocks) if every gate passes")
    p.add_argument("--out", default="firmware/include", help="output directory for calgen_<variant>.h")
    p.add_argument("--patch", help="rewrite CALGEN:BEGIN/END blocks in this existing C file instead")
    p.add_argument("--dry-run", action="store_true", help="print the unified diff; write nothing")
    p.set_defaults(func=cmd_build)

    p = variant_cmd("report", "write the HTML review report for a variant (also for failing builds)")
    p.add_argument("--out", default="out/reports", help="output directory")
    p.add_argument("--compare-to", help="previous header to diff against (default: committed header)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("audit", help="read-only: check existing C firmware against a variant's spec")
    p.add_argument("source", help="directory of legacy .c/.h files")
    p.add_argument("--variant", required=True, help="variant YAML to compare against")
    p.add_argument("--rules", help="rules YAML")
    p.add_argument("--map", help="reviewed legacy-symbol -> rule mapping (calgen_map.yaml)")
    p.add_argument("--ai", help="classify unexplained constants: none | replay[:file] | openai:<model> | anthropic:<model>")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("eval", help="score an AI backend against a blind answer key")
    p.add_argument("source", help="directory of legacy .c/.h files")
    p.add_argument("--key", required=True, help="answer key YAML (never shown to the model)")
    p.add_argument("--rules", help="rules YAML (default specs/rules.yaml)")
    p.add_argument("--ai", default="replay", help="backend: replay[:file] | openai:<model> | anthropic:<model> | none")
    p.add_argument("--record", help="save responses for offline replay")
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (SpecError, GateError, PatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
