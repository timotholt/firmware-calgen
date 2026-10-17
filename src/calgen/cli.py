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
    vpath = Path(args.variant)
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
