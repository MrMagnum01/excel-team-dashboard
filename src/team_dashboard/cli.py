from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import generator
from .dashboard import build_dashboards
from .input_workbook import build_input_workbook
from .sample_inbox import build_sample_inbox_workbook
from .sync import sync as sync_step


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="team_dashboard")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Build the synthetic CSV dataset")
    p_gen.add_argument("--out", type=Path, required=True)
    p_gen.add_argument("--seed", type=int, default=generator.DEFAULT_SEED)
    p_gen.add_argument("--as-of", type=_parse_date, default=generator.DEFAULT_AS_OF)

    p_input = sub.add_parser("input", help="Build a blank member input workbook")
    p_input.add_argument("--out", type=Path, required=True)

    p_sync = sub.add_parser("sync", help="Validate inbox workbooks and append accepted rows to the CSVs")
    p_sync.add_argument("--inbox", type=Path, required=True)
    p_sync.add_argument("--data", type=Path, required=True)
    p_sync.add_argument("--exceptions", type=Path, required=True)

    p_sample = sub.add_parser("sample-inbox", help="Build one filled demo input workbook (valid rows + every bad-input class)")
    p_sample.add_argument("--out", type=Path, required=True)
    p_sample.add_argument("--data", type=Path, required=True)
    p_sample.add_argument("--as-of", type=_parse_date, default=generator.DEFAULT_AS_OF)

    p_refresh = sub.add_parser("refresh", help="Build the master + team dashboards from the CSVs")
    p_refresh.add_argument("--data", type=Path, required=True)
    p_refresh.add_argument("--out", type=Path, required=True)
    p_refresh.add_argument("--as-of", type=_parse_date, default=generator.DEFAULT_AS_OF)

    args = parser.parse_args(argv)

    if args.command == "generate":
        totals = generator.generate(args.out, seed=args.seed, as_of=args.as_of)
        print(f"Generated CSVs in {args.out} (seed={args.seed}, as_of={args.as_of.isoformat()})")
        print(json.dumps(totals["overall"], indent=2))
    elif args.command == "input":
        build_input_workbook(args.out)
        print(f"Wrote input workbook to {args.out}")
    elif args.command == "sample-inbox":
        build_sample_inbox_workbook(args.out, args.data, args.as_of.isoformat())
        print(f"Wrote sample inbox workbook to {args.out}")
    elif args.command == "sync":
        summary = sync_step(args.inbox, args.data, args.exceptions)
        print(json.dumps(summary, indent=2))
    elif args.command == "refresh":
        result = build_dashboards(args.data, args.out, as_of=args.as_of)
        print(f"Wrote master dashboard: {result['master']}")
        for team, path in result["teams"].items():
            print(f"Wrote team dashboard ({team}): {path}")
    else:  # pragma: no cover - argparse enforces choices
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
