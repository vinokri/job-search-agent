from __future__ import annotations

import argparse

from .queue import export_approved, seed_queue, update_status
from .shortlist import build_shortlist


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shortlist target-company jobs and stop at approval."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    shortlist_parser = subparsers.add_parser("shortlist", help="Score and rank jobs.")
    shortlist_parser.add_argument("--profile", required=True)
    shortlist_parser.add_argument("--jobs", required=True)
    shortlist_parser.add_argument("--out", required=True)
    shortlist_parser.add_argument("--markdown")
    shortlist_parser.add_argument("--limit", type=int, default=25)

    seed_parser = subparsers.add_parser("seed-queue", help="Create review queue from shortlist.")
    seed_parser.add_argument("--shortlist", required=True)
    seed_parser.add_argument("--out", required=True)

    status_parser = subparsers.add_parser("set-status", help="Change queue item status.")
    status_parser.add_argument("--queue", required=True)
    status_parser.add_argument("--job-id", required=True)
    status_parser.add_argument("--status", required=True)
    status_parser.add_argument("--notes")

    export_parser = subparsers.add_parser("export-approved", help="Export approved jobs.")
    export_parser.add_argument("--queue", required=True)
    export_parser.add_argument("--out", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "shortlist":
        build_shortlist(args.profile, args.jobs, args.out, args.markdown, args.limit)
        return
    if args.command == "seed-queue":
        seed_queue(args.shortlist, args.out)
        return
    if args.command == "set-status":
        update_status(args.queue, args.job_id, args.status, args.notes)
        return
    if args.command == "export-approved":
        export_approved(args.queue, args.out)
        return


if __name__ == "__main__":
    main()
