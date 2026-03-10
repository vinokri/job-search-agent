from __future__ import annotations

import argparse

from .collectors import collect_live_jobs
from .queue import export_approved, seed_queue, update_status
from .shortlist import build_shortlist
from .web import serve_ui


def limited_list(value: str, label: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise argparse.ArgumentTypeError(f"{label} cannot be empty.")
    return cleaned


def validate_runtime_filters(parser: argparse.ArgumentParser, job_titles: list[str] | None, companies: list[str] | None) -> None:
    if job_titles and len(job_titles) > 3:
        parser.error("--job-title can be provided at most 3 times.")
    if companies and len(companies) > 5:
        parser.error("--company can be provided at most 5 times.")


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

    run_parser = subparsers.add_parser(
        "run-search",
        help="Generate the shortlist and seed the review queue in one step.",
    )
    run_parser.add_argument("--profile", required=True)
    run_parser.add_argument("--jobs", required=True)
    run_parser.add_argument("--shortlist-out", required=True)
    run_parser.add_argument("--queue-out", required=True)
    run_parser.add_argument("--markdown")
    run_parser.add_argument("--limit", type=int, default=25)
    run_parser.add_argument("--collect-live", action="store_true")
    run_parser.add_argument("--live-jobs-out")
    run_parser.add_argument(
        "--job-title",
        dest="job_titles",
        action="append",
        type=lambda value: limited_list(value, "job title", 3),
        help="Job title filter. Repeat up to 3 times.",
    )
    run_parser.add_argument(
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

    live_parser = subparsers.add_parser(
        "collect-live-jobs",
        help="Fetch live jobs from the supported company career sites.",
    )
    live_parser.add_argument("--out", required=True)
    live_parser.add_argument("--limit-per-company", type=int, default=20)
    live_parser.add_argument(
        "--job-title",
        dest="job_titles",
        action="append",
        type=lambda value: limited_list(value, "job title", 3),
        help="Job title filter. Repeat up to 3 times.",
    )
    live_parser.add_argument(
        "--company",
        dest="companies",
        action="append",
        type=lambda value: limited_list(value, "company", 5),
        help="Company filter. Repeat up to 5 times.",
    )

    serve_parser = subparsers.add_parser("serve-ui", help="Run the local web UI.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "shortlist":
        validate_runtime_filters(parser, args.job_titles, args.companies)
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
    if args.command == "run-search":
        validate_runtime_filters(parser, args.job_titles, args.companies)
        jobs_path = args.jobs
        if args.collect_live:
            live_out = args.live_jobs_out or args.jobs
            collect_live_jobs(live_out, args.job_titles, args.companies, args.limit)
            jobs_path = live_out
        build_shortlist(
            args.profile,
            jobs_path,
            args.shortlist_out,
            args.markdown,
            args.limit,
            args.job_titles,
            args.companies,
        )
        seed_queue(args.shortlist_out, args.queue_out)
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
    if args.command == "collect-live-jobs":
        validate_runtime_filters(parser, args.job_titles, args.companies)
        collect_live_jobs(args.out, args.job_titles, args.companies, args.limit_per_company)
        return
    if args.command == "serve-ui":
        serve_ui(args.host, args.port)
        return


if __name__ == "__main__":
    main()
