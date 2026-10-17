"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from calgen import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calgen",
        description="Generate firmware constants from engineering specs, with provenance and gates.",
    )
    parser.add_argument("--version", action="version", version=f"calgen {__version__}")
    parser.add_subparsers(dest="command", metavar="command")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
