from __future__ import annotations

import argparse

from .queue import export_approved, seed_queue, update_status
from .shortlist import build_shortlist


def limited_list(value: str, label: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise argparse.ArgumentTypeError(f"{label} cannot be empty.")
    return cleaned


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
    shortlist_parser.add_argument(
        "--job-title",
        dest="job_titles",
        action="append",
        type=lambda value: limited_list(value, "job title", 3),
        help="Job title filter. Repeat up to 3 times.",
    )
    shortlist_parser.add_argument(
        "--company",
        dest="companies",
        action="append",
        type=lambda value: limited_list(value, "company", 5),
        help="Company filter. Repeat up to 5 times.",
    )

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
        if args.job_titles and len(args.job_titles) > 3:
            parser.error("--job-title can be provided at most 3 times.")
        if args.companies and len(args.companies) > 5:
            parser.error("--company can be provided at most 5 times.")
        build_shortlist(
            args.profile,
            args.jobs,
            args.out,
            args.markdown,
            args.limit,
            args.job_titles,
            args.companies,
        )
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
