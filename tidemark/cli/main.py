"""
tidemark.cli.main
─────────────────
Minimal CLI entry point. M0′ only provides ``--version`` so the console
script resolves and imports cleanly. The functional commands
(``init``, ``device``, ``backup``, ``history``, ``diff``, ``import-yaml``)
land in M1.
"""

from __future__ import annotations

import argparse
import sys

from tidemark import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidemark",
        description="Tidemark — network device configuration backup over SSH.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tidemark {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tidemark`` console script."""
    parser = _build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
