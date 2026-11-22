"""Command-line entry point for ClawReflex."""
from __future__ import annotations

import argparse
from collections.abc import Sequence

from . import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"ClawReflex {__version__}")
    parser.add_argument("command", nargs="?", choices=("watch", "workspace", "server", "bench"))
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments[:1])
    remaining = arguments[1:]
    if args.command is None:
        parser.print_help()
        return 0
    from importlib import import_module

    module = import_module("clawreflex." + {"watch": "watch", "workspace": "workspace", "server": "server", "bench": "benchmark"}[args.command])
    original = sys.argv
    try:
        sys.argv = [f"clawreflex {args.command}", *remaining]
        result = module.main()
        return result if isinstance(result, int) else 0
    finally:
        sys.argv = original
