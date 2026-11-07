"""Command-line interface for trace-waste.

Usage:
    trace-waste analyze TRACE.jsonl [--json] [--judge-command CMD]
                        [--similarity 0.8] [--price-per-1m 3.00]
                        [--fail-above 25]
    trace-waste demo

Exit codes: 0 = report produced (and, with --fail-above, the waste
share is at or below the threshold); 1 = waste share above the
--fail-above threshold; 2 = the trace could not be read or parsed, the
judge command failed, or the arguments were invalid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .judge import JudgeError, get_judge
from .report import analyze, render_json, render_text
from .sample import SAMPLE_TRACE
from .traceio import TraceFormatError, parse_trace


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _run_analysis(text: str, args) -> int:
    try:
        events = parse_trace(text)
    except TraceFormatError as exc:
        print(f"trace-waste: {exc}", file=sys.stderr)
        return 2
    judge = get_judge(
        judge_command=getattr(args, "judge_command", None),
        similarity=getattr(args, "similarity", 0.8),
    )
    try:
        report = analyze(events, judge)
    except JudgeError as exc:
        print(f"trace-waste: {exc}", file=sys.stderr)
        return 2
    price = getattr(args, "price_per_1m", None)
    if getattr(args, "json", False):
        print(json.dumps(render_json(report, price), indent=2))
    else:
        print(render_text(report, price))
    fail_above = getattr(args, "fail_above", None)
    if fail_above is not None and report.waste_percent > fail_above:
        return 1
    return 0


def _cmd_analyze(args) -> int:
    try:
        text = _read_input(args.trace)
    except OSError as exc:
        print(f"trace-waste: cannot read {args.trace}: {exc}", file=sys.stderr)
        return 2
    return _run_analysis(text, args)


def _cmd_demo(args) -> int:
    print("built-in sample trace (one instance of each waste category):")
    print()
    print(SAMPLE_TRACE)
    return _run_analysis(SAMPLE_TRACE, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trace-waste",
        description="Audit an agent run trace for wasted tokens.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    analyze_parser = sub.add_parser(
        "analyze", help="analyze a JSONL trace file (or - for stdin)"
    )
    analyze_parser.add_argument("trace", help="path to the trace file, or -")
    _add_report_options(analyze_parser)
    analyze_parser.set_defaults(func=_cmd_analyze)

    demo_parser = sub.add_parser(
        "demo", help="analyze the built-in sample trace"
    )
    _add_report_options(demo_parser)
    demo_parser.set_defaults(func=_cmd_demo)
    return parser


def _add_report_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of text",
    )
    parser.add_argument(
        "--judge-command",
        metavar="CMD",
        default=None,
        help=(
            "external judge command (reads events JSON on stdin, prints "
            "findings JSON); replaces the built-in heuristic judge"
        ),
    )
    parser.add_argument(
        "--similarity",
        type=float,
        default=0.8,
        metavar="FLOAT",
        help="word-overlap threshold for redundant reasoning (default 0.8)",
    )
    parser.add_argument(
        "--price-per-1m",
        type=float,
        default=None,
        metavar="USD",
        help="token price per 1M tokens, to convert savings into dollars",
    )
    parser.add_argument(
        "--fail-above",
        type=float,
        default=None,
        metavar="PCT",
        help="exit with status 1 when the waste share exceeds PCT percent",
    )


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 0 < args.similarity <= 1:
        parser.error("--similarity must be in (0, 1]")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
