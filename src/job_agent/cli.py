from __future__ import annotations

import argparse
from pathlib import Path

from .collectors import collect_live_jobs
from .local_runner import LocalApplyRunner
from .orchestration import JobSearchOrchestrator, WorkflowStore, build_default_paths
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

    approve_parser = subparsers.add_parser("approve-job", help="Approve a job and trigger the resume agent.")
    approve_parser.add_argument("--job-id", required=True)

    approve_resume_parser = subparsers.add_parser(
        "approve-resume",
        help="Approve a generated tailored resume so the apply agent can use it.",
    )
    approve_resume_parser.add_argument("--job-id", required=True)

    apply_parser = subparsers.add_parser("apply-job", help="Trigger the apply agent for an approved job.")
    apply_parser.add_argument("--job-id", required=True)

    mark_submitted_parser = subparsers.add_parser(
        "mark-submitted",
        help="Confirm that the external ATS submission was completed after browser review.",
    )
    mark_submitted_parser.add_argument("--job-id", required=True)

    resume_source_parser = subparsers.add_parser(
        "parse-resume-source",
        help="Parse a resume source file into structured editable content.",
    )
    resume_source_parser.add_argument("--resume-path", required=True)

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

    runner_parser = subparsers.add_parser(
        "run-local-runner",
        help="Poll a deployed app for browser-apply bundles and launch them locally.",
    )
    runner_parser.add_argument("--base-url", required=True)
    runner_parser.add_argument("--workspace", default=str(Path.home() / ".job-search-agent-runner"))
    runner_parser.add_argument("--poll-seconds", type=int, default=20)
    runner_parser.add_argument("--once", action="store_true")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    orchestrator = JobSearchOrchestrator(
        WorkflowStore(build_default_paths(Path(__file__).resolve().parents[2]))
    )

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
        if args.collect_live:
            orchestrator.run_search(args.job_titles, args.companies, args.limit)
        else:
            build_shortlist(
                args.profile,
                args.jobs,
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
    if args.command == "approve-job":
        orchestrator.approve_job(args.job_id)
        return
    if args.command == "approve-resume":
        orchestrator.approve_resume(args.job_id)
        return
    if args.command == "apply-job":
        orchestrator.apply_job(args.job_id)
        return
    if args.command == "mark-submitted":
        orchestrator.mark_submitted(args.job_id)
        return
    if args.command == "parse-resume-source":
        orchestrator.refresh_resume_source(args.resume_path)
        return
    if args.command == "collect-live-jobs":
        validate_runtime_filters(parser, args.job_titles, args.companies)
        collect_live_jobs(args.out, args.job_titles, args.companies, args.limit_per_company)
        return
    if args.command == "serve-ui":
        serve_ui(args.host, args.port)
        return
    if args.command == "run-local-runner":
        runner = LocalApplyRunner(args.base_url, args.workspace, args.poll_seconds)
        if args.once:
            runner.poll_once()
        else:
            runner.run_forever()
        return


if __name__ == "__main__":
    main()
