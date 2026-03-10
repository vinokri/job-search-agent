from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .collectors import collect_live_jobs_with_diagnostics
from .models import dump_json, load_json, utc_now
from .resume import (
    build_tailored_resume_markdown,
    extract_resume_text,
    load_structured_resume,
    parse_resume_structure,
    save_structured_resume,
    write_docx_if_possible,
)
from .shortlist import build_shortlist


@dataclass
class WorkflowPaths:
    profile: Path
    sample_jobs: Path
    live_jobs: Path
    shortlist: Path
    shortlist_markdown: Path
    queue: Path
    approved: Path
    runtime: Path
    memory: Path
    resume_structured: Path
    resume_sources: Path
    resume_drafts: Path
    application_packets: Path


def build_default_paths(root: Path) -> WorkflowPaths:
    data_dir = root / "data"
    return WorkflowPaths(
        profile=data_dir / "profile.json",
        sample_jobs=data_dir / "jobs.sample.json",
        live_jobs=data_dir / "jobs.live.json",
        shortlist=data_dir / "shortlist.json",
        shortlist_markdown=data_dir / "shortlist.md",
        queue=data_dir / "review-queue.json",
        approved=data_dir / "approved-jobs.json",
        runtime=data_dir / "agent-runtime.json",
        memory=data_dir / "agent-memory.json",
        resume_structured=data_dir / "resume-structured.json",
        resume_sources=data_dir / "source-resumes",
        resume_drafts=data_dir / "resume-drafts",
        application_packets=data_dir / "application-packets",
    )


class WorkflowStore:
    def __init__(self, paths: WorkflowPaths):
        self.paths = paths

    def load_runtime(self) -> dict:
        if not self.paths.runtime.exists():
            return {"updated_at": "", "jobs": {}, "last_search": {}}
        return load_json(self.paths.runtime)

    def save_runtime(self, payload: dict) -> None:
        payload["updated_at"] = utc_now()
        dump_json(self.paths.runtime, payload)

    def load_memory(self) -> list[dict]:
        if not self.paths.memory.exists():
            return []
        return load_json(self.paths.memory)

    def append_memory(self, agent: str, action: str, message: str, job_id: str | None = None, payload: dict | None = None) -> None:
        memory = self.load_memory()
        memory.append(
            {
                "timestamp": utc_now(),
                "agent": agent,
                "action": action,
                "job_id": job_id or "",
                "message": message,
                "payload": payload or {},
            }
        )
        dump_json(self.paths.memory, memory)

    def load_queue(self) -> list[dict]:
        if not self.paths.queue.exists():
            return []
        return load_json(self.paths.queue)

    def save_queue(self, queue: list[dict]) -> None:
        dump_json(self.paths.queue, queue)

    def save_approved(self, jobs: list[dict]) -> None:
        dump_json(self.paths.approved, jobs)


def default_job_state(item: dict) -> dict:
    return {
        "job_id": item["id"],
        "company": item["company"],
        "title": item["title"],
        "url": item["url"],
        "score": item["score"],
        "reasons": item.get("reasons", []),
        "review_status": "pending",
        "resume_status": "idle",
        "apply_status": "idle",
        "resume_preview_path": "",
        "resume_draft_path": "",
        "selected_resume_path": "",
        "application_packet_path": "",
        "last_agent": "search",
        "updated_at": utc_now(),
    }


class SearchJobAgent:
    name = "search-job-agent"

    def __init__(self, store: WorkflowStore):
        self.store = store

    def run(self, job_titles: list[str] | None, companies: list[str] | None, limit: int = 25) -> dict:
        live_jobs, diagnostics = collect_live_jobs_with_diagnostics(
            str(self.store.paths.live_jobs),
            job_titles=job_titles,
            companies=companies,
            limit_per_company=max(10, limit),
        )
        jobs_source = self.store.paths.live_jobs if live_jobs else self.store.paths.sample_jobs
        shortlist = build_shortlist(
            str(self.store.paths.profile),
            str(jobs_source),
            str(self.store.paths.shortlist),
            str(self.store.paths.shortlist_markdown),
            limit,
            job_titles,
            companies,
        )

        runtime = self.store.load_runtime()
        existing_jobs = runtime.get("jobs", {})
        updated_jobs: dict[str, dict] = {}
        queue: list[dict] = []
        for item in shortlist:
            current = existing_jobs.get(item["id"], default_job_state(item))
            current.update(
                {
                    "job_id": item["id"],
                    "company": item["company"],
                    "title": item["title"],
                    "url": item["url"],
                    "score": item["score"],
                    "reasons": item.get("reasons", []),
                    "last_agent": self.name,
                    "updated_at": utc_now(),
                }
            )
            updated_jobs[item["id"]] = current
            queue.append(
                {
                    "id": current["job_id"],
                    "company": current["company"],
                    "title": current["title"],
                    "url": current["url"],
                    "score": current["score"],
                    "status": current["review_status"],
                    "review_status": current["review_status"],
                    "resume_status": current["resume_status"],
                    "apply_status": current["apply_status"],
                    "resume_draft_path": current["resume_draft_path"],
                    "application_packet_path": current["application_packet_path"],
                    "notes": "",
                    "reasons": current["reasons"],
                    "last_agent": current["last_agent"],
                }
            )

        all_jobs = dict(existing_jobs)
        all_jobs.update(updated_jobs)
        runtime["jobs"] = all_jobs
        runtime["last_search"] = {
            "timestamp": utc_now(),
            "job_titles": job_titles or [],
            "companies": companies or [],
            "live_jobs_count": len(live_jobs),
            "shortlist_count": len(shortlist),
            "diagnostics": diagnostics,
            "jobs_source": str(jobs_source),
        }
        self.store.save_runtime(runtime)
        self.store.save_queue(queue)
        self.store.append_memory(
            self.name,
            "search",
            f"Collected {len(live_jobs)} live jobs and shortlisted {len(shortlist)} roles using {jobs_source.name}.",
            payload=runtime["last_search"],
        )
        return runtime["last_search"]


class ResumeUpdateAgent:
    name = "resume-update-agent"

    def __init__(self, store: WorkflowStore):
        self.store = store

    def run(self, job_id: str) -> dict:
        runtime = self.store.load_runtime()
        jobs = runtime.get("jobs", {})
        if job_id not in jobs:
            raise ValueError(f"Job ID '{job_id}' not found.")
        job = jobs[job_id]
        if job["review_status"] != "approved":
            raise ValueError("Resume update agent only runs after approval.")

        profile = load_json(self.store.paths.profile)
        structured_resume = load_structured_resume(self.store.paths.resume_structured)
        self.store.paths.resume_drafts.mkdir(parents=True, exist_ok=True)
        draft_path = self.store.paths.resume_drafts / f"{job_id}.md"
        draft = build_tailored_resume_markdown(profile, structured_resume, job)
        draft_path.write_text(draft, encoding="utf-8")
        docx_path = self.store.paths.resume_drafts / f"{job_id}.docx"
        generated_docx = write_docx_if_possible(draft, docx_path)

        job["resume_status"] = "draft_ready"
        job["resume_preview_path"] = str(draft_path)
        job["resume_draft_path"] = str(draft_path)
        job["selected_resume_path"] = generated_docx or str(draft_path)
        job["last_agent"] = self.name
        job["updated_at"] = utc_now()
        self.store.save_runtime(runtime)
        self._sync_queue(job_id, job)
        self.store.append_memory(
            self.name,
            "prepare-resume",
            f"Prepared resume draft for {job['title']}.",
            job_id=job_id,
            payload={
                "resume_draft_path": str(draft_path),
                "selected_resume_path": job["selected_resume_path"],
            },
        )
        return job

    def _sync_queue(self, job_id: str, job: dict) -> None:
        queue = self.store.load_queue()
        for item in queue:
            if item["id"] == job_id:
                item["resume_status"] = job["resume_status"]
                item["resume_preview_path"] = job["resume_preview_path"]
                item["resume_draft_path"] = job["resume_draft_path"]
                item["selected_resume_path"] = job["selected_resume_path"]
                item["last_agent"] = job["last_agent"]
        self.store.save_queue(queue)


class ApplyJobAgent:
    name = "apply-job-agent"

    def __init__(self, store: WorkflowStore):
        self.store = store

    def run(self, job_id: str) -> dict:
        runtime = self.store.load_runtime()
        jobs = runtime.get("jobs", {})
        if job_id not in jobs:
            raise ValueError(f"Job ID '{job_id}' not found.")
        job = jobs[job_id]
        if job["review_status"] != "approved":
            raise ValueError("Approve the job before applying.")
        if job["resume_status"] != "approved":
            raise ValueError("Resume must be approved before apply.")

        self.store.paths.application_packets.mkdir(parents=True, exist_ok=True)
        packet_path = self.store.paths.application_packets / f"{job_id}.json"
        packet = {
            "job_id": job["job_id"],
            "company": job["company"],
            "title": job["title"],
            "url": job["url"],
            "resume_file_path": job["selected_resume_path"],
            "resume_preview_path": job["resume_preview_path"],
            "status": "sent",
            "sent_at": utc_now(),
        }
        dump_json(packet_path, packet)

        job["apply_status"] = "sent"
        job["application_packet_path"] = str(packet_path)
        job["last_agent"] = self.name
        job["updated_at"] = utc_now()
        self.store.save_runtime(runtime)
        self._sync_queue(job_id, job)
        approved = [
            item
            for item in self.store.load_queue()
            if item.get("review_status") == "approved"
        ]
        self.store.save_approved(approved)
        self.store.append_memory(
            self.name,
            "apply",
            f"Application packet marked sent for {job['title']}.",
            job_id=job_id,
            payload={"application_packet_path": str(packet_path)},
        )
        return job

    def _sync_queue(self, job_id: str, job: dict) -> None:
        queue = self.store.load_queue()
        for item in queue:
            if item["id"] == job_id:
                item["apply_status"] = job["apply_status"]
                item["application_packet_path"] = job["application_packet_path"]
                item["last_agent"] = job["last_agent"]
        self.store.save_queue(queue)


class JobSearchOrchestrator:
    def __init__(self, store: WorkflowStore):
        self.store = store
        self.search_agent = SearchJobAgent(store)
        self.resume_agent = ResumeUpdateAgent(store)
        self.apply_agent = ApplyJobAgent(store)

    def run_search(self, job_titles: list[str] | None, companies: list[str] | None, limit: int = 25) -> dict:
        return self.search_agent.run(job_titles, companies, limit)

    def refresh_resume_source(self, resume_path: str) -> dict:
        profile = load_json(self.store.paths.profile)
        profile["candidate"]["resume_path"] = resume_path
        dump_json(self.store.paths.profile, profile)
        text = extract_resume_text(resume_path)
        structured = parse_resume_structure(text)
        save_structured_resume(self.store.paths.resume_structured, structured)
        self.store.append_memory(
            "resume-source",
            "parse",
            "Parsed source resume into structured content.",
            payload={"resume_path": resume_path},
        )
        return structured

    def approve_job(self, job_id: str) -> dict:
        runtime = self.store.load_runtime()
        jobs = runtime.get("jobs", {})
        if job_id not in jobs:
            raise ValueError(f"Job ID '{job_id}' not found.")
        jobs[job_id]["review_status"] = "approved"
        jobs[job_id]["last_agent"] = "user-approval"
        jobs[job_id]["updated_at"] = utc_now()
        self.store.save_runtime(runtime)

        queue = self.store.load_queue()
        for item in queue:
            if item["id"] == job_id:
                item["status"] = "approved"
                item["review_status"] = "approved"
                item["last_agent"] = "user-approval"
        self.store.save_queue(queue)
        self.store.append_memory(
            "user-approval",
            "approve",
            f"Approved {jobs[job_id]['title']}.",
            job_id=job_id,
        )
        return self.resume_agent.run(job_id)

    def approve_resume(self, job_id: str) -> dict:
        runtime = self.store.load_runtime()
        jobs = runtime.get("jobs", {})
        if job_id not in jobs:
            raise ValueError(f"Job ID '{job_id}' not found.")
        if jobs[job_id]["resume_status"] != "draft_ready":
            raise ValueError("Resume draft must be ready before approval.")
        jobs[job_id]["resume_status"] = "approved"
        jobs[job_id]["last_agent"] = "resume-approval"
        jobs[job_id]["updated_at"] = utc_now()
        self.store.save_runtime(runtime)

        queue = self.store.load_queue()
        for item in queue:
            if item["id"] == job_id:
                item["resume_status"] = "approved"
                item["selected_resume_path"] = jobs[job_id]["selected_resume_path"]
                item["last_agent"] = "resume-approval"
        self.store.save_queue(queue)
        self.store.append_memory(
            "resume-approval",
            "approve-resume",
            f"Approved tailored resume for {jobs[job_id]['title']}.",
            job_id=job_id,
            payload={"selected_resume_path": jobs[job_id]["selected_resume_path"]},
        )
        return jobs[job_id]

    def apply_job(self, job_id: str) -> dict:
        return self.apply_agent.run(job_id)
