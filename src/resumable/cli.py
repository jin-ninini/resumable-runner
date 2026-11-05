"""Command line interface: `resumable run | status | retry | export`.

Every command accepts --json so scripts and LLM agents can read the result without
parsing human text. Exit codes: 0 = nothing left to do, 1 = failed or unfinished
items remain, 2 = bad arguments or unreadable input.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from resumable import __version__
from resumable.loader import LoadError, load_task, read_items
from resumable.retry import RetryPolicy
from resumable.runner import Runner
from resumable.store import Status, Store, Summary

DEFAULT_STATE = ".resumable.db"

EXIT_OK = 0
EXIT_UNFINISHED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resumable",
        description="Run a Python function over many items. Stop any time, rerun to resume.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--state",
            default=DEFAULT_STATE,
            help=f"SQLite file that stores progress (default: {DEFAULT_STATE})",
        )
        p.add_argument("--json", action="store_true", help="print machine-readable JSON")

    run = sub.add_parser("run", help="process pending items")
    run.add_argument("task", help="'module:function' or 'path/to/file.py:function'")
    run.add_argument("--input", help=".csv, .jsonl or .txt file of items to add before running")
    run.add_argument("--key", default="id", help="column that identifies an item (default: id)")
    run.add_argument("--max-attempts", type=int, default=3, help="tries per item (default: 3)")
    run.add_argument("--base-delay", type=float, default=1.0, help="first retry wait, seconds")
    run.add_argument("--max-delay", type=float, default=30.0, help="longest retry wait, seconds")
    run.add_argument("--min-interval", type=float, default=0.0, help="min seconds between calls")
    run.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=None,
        help="stop the run after this many failed items in a row (e.g. when blocked)",
    )
    run.add_argument("--limit", type=int, default=None, help="process at most N items this run")
    common(run)

    status = sub.add_parser("status", help="show item counts by status")
    common(status)

    retry = sub.add_parser("retry", help="move failed items back to pending")
    common(retry)

    export = sub.add_parser("export", help="write items as JSON lines")
    export.add_argument("--status", choices=[s.value for s in Status], help="only this status")
    export.add_argument("--output", "-o", help="file to write (default: stdout)")
    common(export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {"run": _run, "status": _status, "retry": _retry, "export": _export}[args.command]
    try:
        return handler(args)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except ValueError as exc:  # invalid numbers such as --max-attempts 0
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _run(args: argparse.Namespace) -> int:
    policy = RetryPolicy(
        max_attempts=args.max_attempts, base_delay=args.base_delay, max_delay=args.max_delay
    )
    task = load_task(args.task)
    with Store(args.state) as store:
        added = store.add(read_items(args.input, args.key)) if args.input else 0
        runner = Runner(
            store,
            task,
            policy,
            min_interval=args.min_interval,
            max_consecutive_failures=args.max_consecutive_failures,
            log=None if args.json else _stderr,
        )
        report = runner.run(limit=args.limit)
        summary = store.summary()

    if args.json:
        _print_json({"added": added, "report": report.as_dict(), "summary": summary.as_dict()})
    else:
        print(
            f"added {added}, processed {report.processed}: {report.succeeded} done, "
            f"{report.failed} failed, {report.skipped} skipped (already done)"
        )
        if report.stopped_early:
            print(f"stopped early: {report.stop_reason}")
        _print_summary(summary)
    return _exit_code(summary)


def _status(args: argparse.Namespace) -> int:
    _require_state(args.state)
    with Store(args.state) as store:
        summary = store.summary()
        failed = store.items(Status.FAILED)
    if args.json:
        _print_json(
            {
                "summary": summary.as_dict(),
                "failed": [{"key": i.key, "error": i.last_error} for i in failed],
            }
        )
    else:
        _print_summary(summary)
        for item in failed[:10]:
            print(f"  failed  {item.key}: {item.last_error}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more (see `resumable export --status failed`)")
    return _exit_code(summary)


def _retry(args: argparse.Namespace) -> int:
    _require_state(args.state)
    with Store(args.state) as store:
        moved = store.retry_failed()
        summary = store.summary()
    if args.json:
        _print_json({"requeued": moved, "summary": summary.as_dict()})
    else:
        print(f"requeued {moved} failed item(s); run `resumable run TASK` to process them")
    return EXIT_OK


def _export(args: argparse.Namespace) -> int:
    _require_state(args.state)
    with Store(args.state) as store:
        items = store.items(Status(args.status) if args.status else None)
    out: TextIO = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout  # noqa: SIM115
    try:
        for item in items:
            row = {
                "key": item.key,
                "status": item.status.value,
                "attempts": item.attempts,
                "error": item.last_error,
                "result": item.result,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    finally:
        if out is not sys.stdout:
            out.close()
    return EXIT_OK


def _require_state(path: str) -> None:
    if not Path(path).is_file():
        raise LoadError(f"no state file at {path}; start with `resumable run TASK --input FILE`")


def _exit_code(summary: Summary) -> int:
    return EXIT_OK if summary.pending == summary.failed == summary.running == 0 else EXIT_UNFINISHED


def _print_summary(summary: Summary) -> None:
    counts = summary.as_dict()
    print("  ".join(f"{name} {count}" for name, count in counts.items()))


def _print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
