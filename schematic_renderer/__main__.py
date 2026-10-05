from __future__ import annotations

import argparse
import sys

from .errors import SchematicError
from .model import load_schematic
from .render import render_schematic


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a YAML digital-schematic diagram to PNG or SVG.")
    parser.add_argument("input", help="Input YAML file.")
    parser.add_argument("-o", "--output", required=True, help="Output PNG or SVG file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        schematic = load_schematic(args.input)
        render_schematic(schematic, args.output)
    except SchematicError as exc:
        print(f"schematic-renderer: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
