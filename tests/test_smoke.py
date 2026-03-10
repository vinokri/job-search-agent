from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main
from job_agent.collectors import extract_google_results, extract_jobposting_from_html
from job_agent.orchestration import JobSearchOrchestrator, WorkflowPaths, WorkflowStore
from job_agent.queue import export_approved, seed_queue, update_status
from job_agent.shortlist import build_shortlist
from job_agent import web
from job_agent.web import application


ROOT = Path(__file__).resolve().parents[1]


class SmokeTest(unittest.TestCase):
    def make_paths(self, tmp: Path) -> WorkflowPaths:
        return WorkflowPaths(
            profile=tmp / "profile.json",
            sample_jobs=tmp / "jobs.sample.json",
            live_jobs=tmp / "jobs.live.json",
            shortlist=tmp / "shortlist.json",
            shortlist_markdown=tmp / "shortlist.md",
            queue=tmp / "review-queue.json",
            approved=tmp / "approved.json",
            runtime=tmp / "agent-runtime.json",
            memory=tmp / "agent-memory.json",
            resume_drafts=tmp / "resume-drafts",
            application_packets=tmp / "application-packets",
        )

    def test_extract_google_results(self) -> None:
        html = """
        <a href="/about/careers/applications/jobs/results/123-software-engineer">Software Engineer</a>
        <a href="/about/careers/applications/jobs/results/456-data-engineer">Data Engineer</a>
        """
        jobs = extract_google_results(html)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["company"], "Google")

    def test_extract_jobposting_from_html(self) -> None:
        html = """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Staff Data Engineer",
          "description": "Build Python, SQL, and Spark data systems.",
          "datePosted": "2026-03-09",
          "jobLocation": {
            "@type": "Place",
            "address": {
              "addressLocality": "San Francisco",
              "addressRegion": "CA",
              "addressCountry": "US"
            }
          }
        }
        </script>
        """
        job = extract_jobposting_from_html(html, "https://example.com/job", "Databricks")
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["title"], "Staff Data Engineer")
        self.assertIn("python", job["skills"])

    def test_shortlist_and_queue_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shortlist_path = tmp / "shortlist.json"
            queue_path = tmp / "queue.json"
            approved_path = tmp / "approved.json"

            build_shortlist(
                str(ROOT / "data/profile.json"),
                str(ROOT / "data/jobs.sample.json"),
                str(shortlist_path),
                None,
                10,
            )
            queue = seed_queue(str(shortlist_path), str(queue_path))
            self.assertTrue(queue)

            top_job_id = queue[0]["id"]
            update_status(str(queue_path), top_job_id, "approved", "smoke test")
            approved = export_approved(str(queue_path), str(approved_path))
            self.assertEqual(len(approved), 1)
            self.assertEqual(approved[0]["id"], top_job_id)

    def test_runtime_company_and_title_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shortlist_path = tmp / "shortlist.json"

            shortlist = build_shortlist(
                str(ROOT / "data/profile.json"),
                str(ROOT / "data/jobs.sample.json"),
                str(shortlist_path),
                None,
                10,
                ["data engineer"],
                ["Snowflake"],
            )

            self.assertEqual(len(shortlist), 1)
            self.assertEqual(shortlist[0]["id"], "snowflake-001")

    def test_run_search_command_creates_shortlist_and_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shortlist_path = tmp / "shortlist.json"
            queue_path = tmp / "queue.json"
            markdown_path = tmp / "shortlist.md"

            with patch(
                "sys.argv",
                [
                    "job_agent",
                    "run-search",
                    "--profile",
                    str(ROOT / "data/profile.json"),
                    "--jobs",
                    str(ROOT / "data/jobs.sample.json"),
                    "--shortlist-out",
                    str(shortlist_path),
                    "--queue-out",
                    str(queue_path),
                    "--markdown",
                    str(markdown_path),
                    "--job-title",
                    "data engineer",
                    "--company",
                    "Snowflake",
                ],
            ):
                main()

            self.assertTrue(shortlist_path.exists())
            self.assertTrue(queue_path.exists())
            self.assertTrue(markdown_path.exists())
            queue = queue_path.read_text(encoding="utf-8")
            self.assertIn("snowflake-001", queue)

    def test_orchestrator_approve_and_apply_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            paths.profile.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.sample_jobs.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            orchestrator = JobSearchOrchestrator(WorkflowStore(paths))

            with patch(
                "job_agent.orchestration.collect_live_jobs",
                return_value=[],
            ):
                orchestrator.run_search(["data engineer"], ["Snowflake"], 10)

            approved = orchestrator.approve_job("snowflake-001")
            self.assertEqual(approved["resume_status"], "ready")
            self.assertTrue(Path(approved["resume_draft_path"]).exists())

            applied = orchestrator.apply_job("snowflake-001")
            self.assertEqual(applied["apply_status"], "sent")
            self.assertTrue(Path(applied["application_packet_path"]).exists())

    def test_web_app_home_and_run_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            paths.profile.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.sample_jobs.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.approved.write_text("[]\n", encoding="utf-8")

            statuses = []
            live_jobs = [
                {
                    "id": "snowflake-001",
                    "company": "Snowflake",
                    "title": "Data Engineer",
                    "url": "https://example.com/snowflake-001",
                    "location": "Remote",
                    "remote": "remote",
                    "employment_type": "full-time",
                    "posted_at": "2026-03-09",
                    "description": "Python SQL Spark",
                    "skills": ["python", "sql", "spark"],
                }
            ]

            def start_response(status, headers):  # noqa: ANN001,ANN202
                statuses.append((status, headers))

            orchestrator = JobSearchOrchestrator(WorkflowStore(paths))

            def fake_collect_live_jobs(out_path, job_titles, companies, limit_per_company):  # noqa: ANN001,ANN202
                Path(out_path).write_text(json.dumps(live_jobs), encoding="utf-8")
                return live_jobs

            with patch.object(web, "build_orchestrator", return_value=orchestrator), patch(
                "job_agent.orchestration.collect_live_jobs",
                side_effect=fake_collect_live_jobs,
            ):
                response = b"".join(
                    application(
                        {
                            "REQUEST_METHOD": "GET",
                            "PATH_INFO": "/",
                            "QUERY_STRING": "",
                            "wsgi.input": BytesIO(b""),
                        },
                        start_response,
                    )
                )
                self.assertIn(b"Job Search Agent", response)
                self.assertEqual(statuses[0][0], "200 OK")

                body = b"job_title1=data+engineer&company1=Snowflake"
                statuses.clear()
                application(
                    {
                        "REQUEST_METHOD": "POST",
                        "PATH_INFO": "/run-search",
                        "CONTENT_LENGTH": str(len(body)),
                        "QUERY_STRING": "",
                        "wsgi.input": BytesIO(body),
                    },
                    start_response,
                )
                self.assertEqual(statuses[0][0], "303 See Other")
                headers = dict(statuses[0][1])
                self.assertIn("/?message=", headers["Location"])

                queue_payload = json.loads(paths.queue.read_text(encoding="utf-8"))
                self.assertEqual(queue_payload[0]["id"], "snowflake-001")
                self.assertEqual(queue_payload[0]["resume_status"], "idle")

                statuses.clear()
                approve_body = b"job_id=snowflake-001"
                application(
                    {
                        "REQUEST_METHOD": "POST",
                        "PATH_INFO": "/approve-job",
                        "CONTENT_LENGTH": str(len(approve_body)),
                        "QUERY_STRING": "",
                        "wsgi.input": BytesIO(approve_body),
                    },
                    start_response,
                )
                self.assertEqual(statuses[0][0], "303 See Other")
                updated_queue = json.loads(paths.queue.read_text(encoding="utf-8"))
                self.assertEqual(updated_queue[0]["resume_status"], "ready")

    def test_collect_live_jobs_command_invokes_collector(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "live.json"

            with patch("job_agent.cli.collect_live_jobs") as mocked:
                with patch(
                    "sys.argv",
                    [
                        "job_agent",
                        "collect-live-jobs",
                        "--out",
                        str(out_path),
                        "--job-title",
                        "software engineer",
                        "--company",
                        "Google",
                    ],
                ):
                    main()

            mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
