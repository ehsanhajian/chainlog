"""Command line for chainlog-ai."""

from __future__ import annotations

import argparse
import sys

from chainlog_ai import __version__
from chainlog_ai.case import CaseError, CaseNotFoundError, load_case
from chainlog_ai.ingest import SOURCES, InputError, ingest


class _ClientInput(argparse.Action):
    """Attach a client name to the preceding file of the source in ``const``."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | None,
        option_string: str | None = None,
    ) -> None:
        inputs = getattr(namespace, "inputs", None) or []
        for item in reversed(inputs):
            if item[0] == self.const and item[2] is None:
                item[2] = values
                return
        parser.error(f"{option_string} needs a preceding --{self.const} file")


class _FileInput(argparse.Action):
    """Record a log file under the source named by ``const``."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | None,
        option_string: str | None = None,
    ) -> None:
        inputs = getattr(namespace, "inputs", None)
        if not inputs:
            inputs = []
            setattr(namespace, "inputs", inputs)
        inputs.append([self.const, values, None])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chainlog-ai",
        description="Explain why blockchain infrastructure failed, from the logs you already have.",
    )
    parser.add_argument("--version", action="version", version=f"chainlog-ai {__version__}")
    commands = parser.add_subparsers(dest="command")

    ingest_parser = commands.add_parser(
        "ingest",
        help="Read logs into a local case",
        description=(
            "Read plain text, JSON lines, or a Kubernetes events file into a case "
            "under ~/.chainlog-ai, or CHAINLOG_AI_HOME when that is set."
        ),
    )
    ingest_parser.set_defaults(inputs=[], func=_cmd_ingest)
    ingest_parser.add_argument(
        "--case",
        help="Append to this case. The case is created when it does not exist.",
    )
    _add_source(ingest_parser, "--execution", "execution", "Execution-client log")
    ingest_parser.add_argument(
        "--execution-client",
        action=_ClientInput,
        const="execution",
        metavar="CLIENT",
        help="Name the preceding execution log: geth, nethermind, erigon, besu, or reth",
    )
    _add_source(ingest_parser, "--consensus", "consensus", "Consensus-client log")
    ingest_parser.add_argument(
        "--consensus-client",
        action=_ClientInput,
        const="consensus",
        metavar="CLIENT",
        help="Name the preceding consensus log: lighthouse, prysm, teku, nimbus, or lodestar",
    )
    _add_source(ingest_parser, "--validator", "validator", "Validator or signer log")
    _add_source(ingest_parser, "--builder", "builder", "Builder log")
    _add_source(ingest_parser, "--kube", "kubernetes", "Kubernetes log or events file")

    why_parser = commands.add_parser(
        "why",
        help="Why did it fail?",
        description="Load a local case. A cause is stated only when the cited lines support one.",
    )
    why_parser.add_argument("--case", required=True, help="Case id printed by ingest")
    why_parser.set_defaults(func=_cmd_why)
    return parser


def _add_source(parser: argparse.ArgumentParser, flag: str, source: str, help_text: str) -> None:
    parser.add_argument(flag, action=_FileInput, const=source, metavar="FILE", help=help_text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code in (None, 0):
            return 0
        return 3
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


def _cmd_ingest(args: argparse.Namespace) -> int:
    inputs = [
        (source, path, client)
        for source, path, client in args.inputs
        if source in SOURCES
    ]
    if not inputs:
        print("ingest needs an input file", file=sys.stderr)
        return 3
    try:
        case_id = ingest(inputs, case_id=args.case)
    except (InputError, CaseError) as exc:
        print(exc, file=sys.stderr)
        return 3
    print(f"case {case_id}")
    return 0


def _cmd_why(args: argparse.Namespace) -> int:
    try:
        case = load_case(args.case)
    except CaseNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 3
    except CaseError as exc:
        print(exc, file=sys.stderr)
        return 3
    print(f"case {case.id}")
    print("evidence is not enough to state a cause")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
