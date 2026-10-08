"""Command line for ChainLog."""

from __future__ import annotations

import argparse

from chainlog import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chainlog",
        description="Explain why blockchain infrastructure failed, from the logs you already have.",
    )
    parser.add_argument("--version", action="version", version=f"chainlog {__version__}")
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
