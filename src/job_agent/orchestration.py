from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .ats import ApplicationRunStore, select_adapter
from .collectors import collect_live_jobs_with_diagnostics
from .models import dump_json, load_json, session_id_now, utc_now
from .resume import (
    load_structured_resume,
    ResumeRenderAgent,
    ResumeSourceManager,
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
    application_runs: Path


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
        application_runs=data_dir / "application-runs",
    )


class WorkflowStore:
    def __init__(self, paths: WorkflowPaths):
        self.paths = paths

    def load_runtime(self) -> dict:
        if not self.paths.runtime.exists():
            return {"updated_at": "", "current_session_id": "", "jobs": {}, "last_search": {}}
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
        "session_id": "",
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
        "rendered_resume_markdown_path": "",
        "rendered_resume_docx_path": "",
        "rendered_resume_pdf_path": "",
        "application_packet_path": "",
        "application_run_id": "",
        "application_run_path": "",
        "apply_provider": "",
        "apply_launch_command": "",
        "apply_bundle_path": "",
        "last_agent": "search",
        "updated_at": utc_now(),
    }


class SearchJobAgent:
    name = "search-job-agent"

    def __init__(self, store: WorkflowStore):
        self.store = store

    def run(self, job_titles: list[str] | None, companies: list[str] | None, limit: int = 25) -> dict:
        session_id = session_id_now()
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
        updated_jobs: dict[str, dict] = {}
        queue: list[dict] = []
        for item in shortlist:
            current = default_job_state(item)
            current.update(
                {
                    "session_id": session_id,
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
                    "session_id": current["session_id"],
                    "company": current["company"],
                    "title": current["title"],
                    "url": current["url"],
                    "score": current["score"],
                    "status": current["review_status"],
                    "review_status": current["review_status"],
                    "resume_status": current["resume_status"],
                    "apply_status": current["apply_status"],
                    "resume_draft_path": current["resume_draft_path"],
                    "rendered_resume_docx_path": current["rendered_resume_docx_path"],
                    "rendered_resume_pdf_path": current["rendered_resume_pdf_path"],
                    "application_packet_path": current["application_packet_path"],
                    "application_run_path": current["application_run_path"],
                    "apply_provider": current["apply_provider"],
                    "apply_launch_command": current["apply_launch_command"],
                    "apply_bundle_path": current["apply_bundle_path"],
                    "notes": "",
                    "reasons": current["reasons"],
                    "last_agent": current["last_agent"],
                }
            )
        runtime["current_session_id"] = session_id
        runtime["jobs"] = updated_jobs
        runtime["last_search"] = {
            "session_id": session_id,
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
        self.store.save_approved([])
        self.store.append_memory(
            self.name,
            "search",
            f"Started {session_id}: collected {len(live_jobs)} live jobs and shortlisted {len(shortlist)} roles using {jobs_source.name}.",
            payload=runtime["last_search"],
        )
        return runtime["last_search"]


class ResumeUpdateAgent:
    name = "resume-update-agent"

    def __init__(self, store: WorkflowStore):
        self.store = store
        self.render_agent = ResumeRenderAgent()

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
        rendered = self.render_agent.render_tailored_resume(
            profile,
            structured_resume,
            job,
            self.store.paths.resume_drafts,
        )

        job["resume_status"] = "draft_ready"
        job.update(rendered)
        job["last_agent"] = self.name
        job["updated_at"] = utc_now()
        self.store.save_runtime(runtime)
        self._sync_queue(job_id, job)
        self.store.append_memory(
            self.name,
            "prepare-resume",
            f"Prepared resume draft for {job['title']}.",
            job_id=job_id,
            payload=rendered,
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
                item["rendered_resume_docx_path"] = job["rendered_resume_docx_path"]
                item["rendered_resume_pdf_path"] = job["rendered_resume_pdf_path"]
                item["last_agent"] = job["last_agent"]
        self.store.save_queue(queue)


class ApplyJobAgent:
    name = "apply-job-agent"

    def __init__(self, store: WorkflowStore):
        self.store = store
        self.run_store = ApplicationRunStore(store.paths.application_runs)

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

        profile = load_json(self.store.paths.profile)
        adapter = select_adapter(job)
        if adapter is None:
            raise ValueError(f"No ATS adapter configured for {job['company']}.")

        self.store.paths.application_packets.mkdir(parents=True, exist_ok=True)
        packet_path = self.store.paths.application_packets / f"{job_id}.json"
        run = adapter.prepare_run(self.run_store, profile, job, job["selected_resume_path"])
        packet = {
            "job_id": job["job_id"],
            "company": job["company"],
            "title": job["title"],
            "url": job["url"],
            "resume_file_path": job["selected_resume_path"],
            "resume_preview_path": job["resume_preview_path"],
            "resume_docx_path": job["rendered_resume_docx_path"],
            "resume_pdf_path": job["rendered_resume_pdf_path"],
            "provider": adapter.provider,
            "application_run_id": run["run_id"],
            "application_run_path": run["run_dir"],
            "launch_command": run.get("local_launch_command", ""),
            "bundle_path": run.get("bundle_path", ""),
            "status": run["status"],
            "prepared_at": utc_now(),
        }
        dump_json(packet_path, packet)

        job["apply_status"] = run["status"]
        job["application_packet_path"] = str(packet_path)
        job["application_run_id"] = run["run_id"]
        job["application_run_path"] = run["run_dir"]
        job["apply_provider"] = adapter.provider
        job["apply_launch_command"] = run.get("local_launch_command", "")
        job["apply_bundle_path"] = run.get("bundle_path", "")
        job["last_agent"] = self.name
        job["updated_at"] = utc_now()
        self.store.save_runtime(runtime)
        self._sync_queue(job_id, job)
        self.store.append_memory(
            self.name,
            "apply",
            f"Prepared browser apply run for {job['title']}.",
            job_id=job_id,
            payload={
                "application_packet_path": str(packet_path),
                "application_run_path": run["run_dir"],
                "launch_command": run.get("local_launch_command", ""),
                "bundle_path": run.get("bundle_path", ""),
            },
        )
        return job

    def mark_submitted(self, job_id: str) -> dict:
        runtime = self.store.load_runtime()
        jobs = runtime.get("jobs", {})
        if job_id not in jobs:
            raise ValueError(f"Job ID '{job_id}' not found.")
        job = jobs[job_id]
        if not job.get("application_run_id"):
            raise ValueError("Prepare the browser apply run before marking submitted.")

        run = self.run_store.append_event(
            job["application_run_id"],
            "manual-submission",
            "User confirmed final ATS submission.",
        )
        run["status"] = "submitted"
        run["submitted_at"] = utc_now()
        self.run_store.save_run(run)

        packet_path = Path(job["application_packet_path"])
        if packet_path.exists():
            packet = load_json(packet_path)
            packet["status"] = "submitted"
            packet["submitted_at"] = utc_now()
            dump_json(packet_path, packet)

        job["apply_status"] = "submitted"
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
            "mark-submitted",
            f"Confirmed external submission for {job['title']}.",
            job_id=job_id,
            payload={"application_packet_path": str(packet_path)},
        )
        return job

    def runner_event(self, run_id: str, event: str, payload: dict | None = None) -> dict:
        runtime = self.store.load_runtime()
        jobs = runtime.get("jobs", {})
        target_job: dict | None = None
        target_job_id = ""
        for job_id, job in jobs.items():
            if job.get("application_run_id") == run_id:
                target_job = job
                target_job_id = job_id
                break
        if target_job is None:
            raise ValueError(f"Application run '{run_id}' not found.")

        run = self.run_store.append_event(run_id, event, f"Runner reported {event}.", payload)
        if event == "launched":
            target_job["apply_status"] = "local_browser_started"
        elif event == "launch_failed":
            target_job["apply_status"] = "launch_failed"
        target_job["last_agent"] = self.name
        target_job["updated_at"] = utc_now()
        self.store.save_runtime(runtime)
        self._sync_queue(target_job_id, target_job)
        self.store.append_memory(
            self.name,
            f"runner-{event}",
            f"Local runner reported {event} for {target_job['title']}.",
            job_id=target_job_id,
            payload=payload or {},
        )
        return run

    def _sync_queue(self, job_id: str, job: dict) -> None:
        queue = self.store.load_queue()
        for item in queue:
            if item["id"] == job_id:
                item["apply_status"] = job["apply_status"]
                item["application_packet_path"] = job["application_packet_path"]
                item["application_run_path"] = job["application_run_path"]
                item["apply_provider"] = job["apply_provider"]
                item["apply_launch_command"] = job["apply_launch_command"]
                item["apply_bundle_path"] = job["apply_bundle_path"]
                item["last_agent"] = job["last_agent"]
        self.store.save_queue(queue)


class JobSearchOrchestrator:
    def __init__(self, store: WorkflowStore):
        self.store = store
        self.search_agent = SearchJobAgent(store)
        self.resume_agent = ResumeUpdateAgent(store)
        self.apply_agent = ApplyJobAgent(store)
        self.resume_source_manager = ResumeSourceManager()

    def run_search(self, job_titles: list[str] | None, companies: list[str] | None, limit: int = 25) -> dict:
        return self.search_agent.run(job_titles, companies, limit)

    def clear_run_state(self) -> None:
        dump_json(self.store.paths.shortlist, [])
        self.store.paths.shortlist_markdown.write_text("", encoding="utf-8")
        self.store.save_queue([])
        self.store.save_approved([])
        runtime = self.store.load_runtime()
        runtime["current_session_id"] = ""
        runtime["jobs"] = {}
        runtime["last_search"] = {}
        self.store.save_runtime(runtime)
        self.store.append_memory(
            "system",
            "clear-run-state",
            "Cleared shortlist, queue, approved jobs, and last search state.",
        )

    def refresh_resume_source(self, resume_path: str) -> dict:
        profile = load_json(self.store.paths.profile)
        profile["candidate"]["resume_path"] = resume_path
        dump_json(self.store.paths.profile, profile)
        structured = self.resume_source_manager.ingest_source(
            resume_path,
            self.store.paths.resume_sources,
            self.store.paths.resume_structured,
        )
        self.store.append_memory(
            "resume-source",
            "parse",
            "Parsed source resume and built canonical resume artifacts.",
            payload=structured.get("source", {}),
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

    def mark_submitted(self, job_id: str) -> dict:
        return self.apply_agent.mark_submitted(job_id)
