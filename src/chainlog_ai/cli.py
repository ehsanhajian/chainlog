"""Command line for chainlog-ai."""

from __future__ import annotations

import argparse

from chainlog_ai import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chainlog-ai",
        description="Explain why blockchain infrastructure failed, from the logs you already have.",
    )
    parser.add_argument("--version", action="version", version=f"chainlog-ai {__version__}")
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
