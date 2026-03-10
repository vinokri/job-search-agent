from __future__ import annotations

from .models import dump_json, load_json


VALID_STATUSES = {"pending", "approved", "rejected", "hold"}


def seed_queue(shortlist_path: str, out_path: str) -> list[dict]:
    shortlist = load_json(shortlist_path)
    queue = [
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
    dump_json(out_path, queue)
    return queue


def update_status(queue_path: str, job_id: str, status: str, notes: str | None = None) -> list[dict]:
    if status not in VALID_STATUSES:
        raise ValueError(f"Unsupported status '{status}'. Expected one of {sorted(VALID_STATUSES)}")

    queue = load_json(queue_path)
    for item in queue:
        if item.get("id") == job_id:
            item["status"] = status
            if notes is not None:
                item["notes"] = notes
            dump_json(queue_path, queue)
            return queue
    raise ValueError(f"Job ID '{job_id}' not found in queue.")


def export_approved(queue_path: str, out_path: str) -> list[dict]:
    queue = load_json(queue_path)
    approved = [item for item in queue if item.get("status") == "approved"]
    dump_json(out_path, approved)
    return approved
