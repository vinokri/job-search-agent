#!/usr/bin/env python3
import argparse
import json


VALID_STATUSES = {"pending", "approved", "rejected", "hold"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def seed_queue(shortlist):
    return [
        {
            "id": item["id"],
            "company": item["company"],
            "title": item["title"],
            "url": item["url"],
            "score": item["score"],
            "status": "pending",
            "notes": "",
            "reasons": item.get("reasons", []),
        }
        for item in shortlist
    ]


def set_status(queue, job_id, status, notes):
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status '{status}'. Expected one of: {sorted(VALID_STATUSES)}")

    for item in queue:
        if item.get("id") == job_id:
            item["status"] = status
            if notes is not None:
                item["notes"] = notes
            return queue

    raise ValueError(f"Job ID '{job_id}' not found in queue.")


def export_approved(queue):
    return [item for item in queue if item.get("status") == "approved"]


def main():
    parser = argparse.ArgumentParser(description="Manage the human approval queue for job applications.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    seed_parser = subparsers.add_parser("seed", help="Create a review queue from shortlist JSON.")
    seed_parser.add_argument("--shortlist", required=True)
    seed_parser.add_argument("--out", required=True)

    status_parser = subparsers.add_parser("set-status", help="Update one queue entry.")
    status_parser.add_argument("--queue", required=True)
    status_parser.add_argument("--job-id", required=True)
    status_parser.add_argument("--status", required=True, choices=sorted(VALID_STATUSES))
    status_parser.add_argument("--notes")

    export_parser = subparsers.add_parser("export-approved", help="Export approved roles only.")
    export_parser.add_argument("--queue", required=True)
    export_parser.add_argument("--out", required=True)

    args = parser.parse_args()

    if args.command == "seed":
        shortlist = load_json(args.shortlist)
        dump_json(args.out, seed_queue(shortlist))
        return

    if args.command == "set-status":
        queue = load_json(args.queue)
        dump_json(args.queue, set_status(queue, args.job_id, args.status, args.notes))
        return

    if args.command == "export-approved":
        queue = load_json(args.queue)
        dump_json(args.out, export_approved(queue))
        return


if __name__ == "__main__":
    main()
