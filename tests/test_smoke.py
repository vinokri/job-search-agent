from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main
from job_agent.collectors import (
    collect_nvidia_jobs_with_diagnostics,
    extract_google_results,
    extract_jobposting_from_html,
)
from job_agent.ats import select_adapter
from job_agent.local_runner import LocalApplyRunner
from job_agent.orchestration import JobSearchOrchestrator, WorkflowPaths, WorkflowStore
from job_agent.queue import export_approved, seed_queue, update_status
from job_agent.resume import parse_resume_structure
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
            resume_structured=tmp / "resume-structured.json",
            resume_sources=tmp / "source-resumes",
            resume_drafts=tmp / "resume-drafts",
            application_packets=tmp / "application-packets",
            application_runs=tmp / "application-runs",
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

    def test_collect_nvidia_jobs_uses_public_api(self) -> None:
        payload = json.dumps(
            {
                "status": 200,
                "error": {"message": "", "body": ""},
                "data": {
                    "positions": [
                        {
                            "id": 893391832799,
                            "displayJobId": "JR2006328",
                            "name": "Senior Solutions Architect - Simulation",
                            "locations": ["US, CA, Santa Clara"],
                            "standardizedLocations": ["Santa Clara, CA, US"],
                            "postedTs": 1767916800,
                            "department": "Architect, Solutions",
                            "workLocationOption": "remote_local",
                            "positionUrl": "/careers/job/893391832799",
                        }
                    ],
                    "count": 1,
                },
            }
        )

        with patch("job_agent.collectors.fetch_url", return_value=payload) as mocked_fetch:
            jobs, diagnostics = collect_nvidia_jobs_with_diagnostics(["Senior Solutions Architect"], limit=10)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["company"], "NVIDIA")
        self.assertEqual(jobs[0]["remote"], "remote")
        self.assertEqual(diagnostics["response_type"], "json")
        self.assertIn("positions", diagnostics["top_level_keys"])
        self.assertEqual(mocked_fetch.call_count, 1)

    def test_select_adapter_supports_google_and_nvidia(self) -> None:
        google = select_adapter({"company": "Google", "url": "https://www.google.com/about/careers/applications/jobs/results/123"})
        nvidia = select_adapter({"company": "NVIDIA", "url": "https://jobs.nvidia.com/careers/job/123"})
        self.assertIsNotNone(google)
        self.assertIsNotNone(nvidia)

    def test_parse_resume_structure(self) -> None:
        text = """Vinodh Krishnamoorthy
Professional Summary
Senior engineer building data and ML platforms.
Skills
Python, SQL, Spark
Experience
Built distributed systems
Education
MS Computer Science
"""
        structured = parse_resume_structure(text)
        self.assertEqual(structured["name"], "Vinodh Krishnamoorthy")
        self.assertIn("skills", structured["sections"])
        self.assertIn("python", structured["skills"])

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

    def test_new_search_replaces_active_session_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            paths.profile.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.sample_jobs.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            orchestrator = JobSearchOrchestrator(WorkflowStore(paths))

            with patch(
                "job_agent.orchestration.collect_live_jobs_with_diagnostics",
                return_value=([], {}),
            ):
                orchestrator.run_search(["data engineer"], ["Snowflake"], 10)
                first_runtime = json.loads(paths.runtime.read_text(encoding="utf-8"))
                self.assertEqual(sorted(first_runtime["jobs"].keys()), ["snowflake-001"])

                orchestrator.run_search(["software engineer"], ["Google"], 10)
                second_runtime = json.loads(paths.runtime.read_text(encoding="utf-8"))
                self.assertEqual(sorted(second_runtime["jobs"].keys()), ["google-001"])
                self.assertNotEqual(
                    first_runtime.get("current_session_id", ""),
                    second_runtime.get("current_session_id", ""),
                )

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
            resume_path = tmp / "resume.txt"
            resume_path.write_text(
                "Vinodh Krishnamoorthy\nProfessional Summary\nSenior engineer building data systems.\nSkills\nPython, SQL, Spark\nExperience\nBuilt ML platforms.\n",
                encoding="utf-8",
            )
            orchestrator = JobSearchOrchestrator(WorkflowStore(paths))
            orchestrator.refresh_resume_source(str(resume_path))

            with patch(
                "job_agent.orchestration.collect_live_jobs_with_diagnostics",
                return_value=(
                    [],
                    {
                        "Google": {
                            "status": "ok",
                            "jobs_collected": 0,
                            "requested_titles": ["software engineer"],
                            "response_type": "html",
                            "top_level_keys": [],
                            "response_preview": "empty",
                            "sample_titles": [],
                        }
                    },
                ),
            ):
                result = orchestrator.run_search(["software engineer"], ["Google"], 10)
            self.assertIn("diagnostics", result)

            approved = orchestrator.approve_job("google-001")
            self.assertEqual(approved["resume_status"], "draft_ready")
            self.assertTrue(Path(approved["resume_draft_path"]).exists())
            self.assertTrue(Path(approved["selected_resume_path"]).exists())

            resume_approved = orchestrator.approve_resume("google-001")
            self.assertEqual(resume_approved["resume_status"], "approved")

            with patch("job_agent.ats.playwright_python_available", return_value=True):
                applied = orchestrator.apply_job("google-001")
            self.assertEqual(applied["apply_status"], "bundle_ready")
            self.assertTrue(Path(applied["application_packet_path"]).exists())
            self.assertTrue(Path(applied["application_run_path"]).exists())
            self.assertTrue(Path(applied["apply_bundle_path"]).exists())

            submitted = orchestrator.mark_submitted("google-001")
            self.assertEqual(submitted["apply_status"], "submitted")

    def test_web_app_home_and_run_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            paths.profile.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.sample_jobs.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.approved.write_text("[]\n", encoding="utf-8")
            resume_path = tmp / "resume.txt"
            resume_path.write_text(
                "Vinodh Krishnamoorthy\nProfessional Summary\nSenior engineer building data systems.\nSkills\nPython, SQL, Spark\nExperience\nBuilt ML platforms.\n",
                encoding="utf-8",
            )

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
            orchestrator.refresh_resume_source(str(resume_path))

            def fake_collect_live_jobs(out_path, job_titles, companies, limit_per_company):  # noqa: ANN001,ANN202
                Path(out_path).write_text(json.dumps(live_jobs), encoding="utf-8")
                return (
                    live_jobs,
                    {
                        "Snowflake": {
                            "status": "ok",
                            "jobs_collected": len(live_jobs),
                            "requested_titles": job_titles or [],
                            "response_type": "html",
                            "top_level_keys": [],
                            "response_preview": "preview",
                            "sample_titles": ["Data Engineer"],
                        }
                    },
                )

            with patch.object(web, "build_orchestrator", return_value=orchestrator), patch(
                "job_agent.orchestration.collect_live_jobs_with_diagnostics",
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

    def test_pending_apply_runs_api_and_local_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            paths.profile.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.sample_jobs.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.approved.write_text("[]\n", encoding="utf-8")
            resume_path = tmp / "resume.txt"
            resume_path.write_text(
                "Vinodh Krishnamoorthy\nProfessional Summary\nSenior engineer building data systems.\nSkills\nPython, SQL, Spark\nExperience\nBuilt ML platforms.\n",
                encoding="utf-8",
            )
            orchestrator = JobSearchOrchestrator(WorkflowStore(paths))
            orchestrator.refresh_resume_source(str(resume_path))

            with patch(
                "job_agent.orchestration.collect_live_jobs_with_diagnostics",
                return_value=(
                    [],
                    {
                        "Google": {
                            "status": "ok",
                            "jobs_collected": 0,
                            "requested_titles": ["software engineer"],
                            "response_type": "html",
                            "top_level_keys": [],
                            "response_preview": "empty",
                            "sample_titles": [],
                        }
                    },
                ),
            ):
                orchestrator.run_search(["software engineer"], ["Google"], 10)
            orchestrator.approve_job("google-001")
            orchestrator.approve_resume("google-001")
            with patch("job_agent.ats.playwright_python_available", return_value=True):
                orchestrator.apply_job("google-001")

            statuses = []

            def start_response(status, headers):  # noqa: ANN001,ANN202
                statuses.append((status, headers))

            with patch.object(web, "build_orchestrator", return_value=orchestrator), patch.object(
                web, "DEFAULT_QUEUE", paths.queue
            ), patch.object(web, "DATA_DIR", tmp):
                response = b"".join(
                    application(
                        {
                            "REQUEST_METHOD": "GET",
                            "PATH_INFO": "/api/pending-apply-runs",
                            "QUERY_STRING": "",
                            "HTTP_HOST": "example.test",
                            "wsgi.url_scheme": "https",
                            "wsgi.input": BytesIO(b""),
                        },
                        start_response,
                    )
                )
            self.assertEqual(statuses[0][0], "200 OK")
            payload = json.loads(response.decode("utf-8"))
            self.assertEqual(len(payload["items"]), 1)
            self.assertIn("/artifact?path=", payload["items"][0]["bundle_url"])

            runner = LocalApplyRunner("https://example.test", tmp / "runner-workspace", poll_seconds=1)
            bundle_source = Path(orchestrator.store.load_runtime()["jobs"]["google-001"]["apply_bundle_path"])
            launched = []
            posted_events = []

            def fake_get_json(url):  # noqa: ANN001,ANN202
                return {"items": payload["items"]}

            def fake_download(url, destination):  # noqa: ANN001,ANN202
                destination.write_bytes(bundle_source.read_bytes())
                return destination

            def fake_popen(cmd, cwd=None):  # noqa: ANN001,ANN202
                launched.append((cmd, cwd))
                class Dummy:
                    pass
                return Dummy()

            def fake_post(base_url, run_id, event, payload=None):  # noqa: ANN001,ANN202
                posted_events.append((base_url, run_id, event, payload))

            with patch("job_agent.local_runner.http_get_json", side_effect=fake_get_json), patch(
                "job_agent.local_runner.http_download", side_effect=fake_download
            ), patch("job_agent.local_runner.subprocess.Popen", side_effect=fake_popen), patch(
                "job_agent.local_runner.post_runner_event", side_effect=fake_post
            ):
                launched_count = runner.poll_once()

            self.assertEqual(launched_count, 1)
            self.assertEqual(len(launched), 1)
            self.assertIn("google_apply_playwright.py", launched[0][0][1])
            self.assertEqual(posted_events[0][2], "launched")

    def test_clear_run_state_via_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            paths.profile.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            paths.sample_jobs.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            orchestrator = JobSearchOrchestrator(WorkflowStore(paths))

            with patch(
                "job_agent.orchestration.collect_live_jobs_with_diagnostics",
                return_value=(
                    [],
                    {
                        "Google": {
                            "status": "ok",
                            "jobs_collected": 0,
                            "requested_titles": ["software engineer"],
                            "response_type": "html",
                            "top_level_keys": [],
                            "response_preview": "empty",
                            "sample_titles": [],
                        }
                    },
                ),
            ):
                orchestrator.run_search(["software engineer"], ["Google"], 10)

            statuses = []

            def start_response(status, headers):  # noqa: ANN001,ANN202
                statuses.append((status, headers))

            with patch.object(web, "build_orchestrator", return_value=orchestrator), patch.object(
                web, "DEFAULT_QUEUE", paths.queue
            ), patch.object(web, "DEFAULT_SHORTLIST", paths.shortlist), patch.object(
                web, "DEFAULT_APPROVED", paths.approved
            ), patch.object(
                web, "DEFAULT_RUNTIME", paths.runtime
            ), patch.object(
                web, "DEFAULT_MEMORY", paths.memory
            ):
                body = b""
                application(
                    {
                        "REQUEST_METHOD": "POST",
                        "PATH_INFO": "/clear-run-state",
                        "CONTENT_LENGTH": str(len(body)),
                        "QUERY_STRING": "",
                        "wsgi.input": BytesIO(body),
                    },
                    start_response,
                )

            self.assertEqual(statuses[0][0], "303 See Other")
            self.assertEqual(json.loads(paths.shortlist.read_text(encoding="utf-8")), [])
            self.assertEqual(json.loads(paths.queue.read_text(encoding="utf-8")), [])
            runtime = json.loads(paths.runtime.read_text(encoding="utf-8"))
            self.assertEqual(runtime.get("jobs"), {})

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

    def test_parse_resume_source_command_invokes_orchestrator(self) -> None:
        with patch("job_agent.cli.JobSearchOrchestrator") as orchestrator_cls:
            instance = orchestrator_cls.return_value
            with patch(
                "sys.argv",
                ["job_agent", "parse-resume-source", "--resume-path", "/tmp/resume.txt"],
            ):
                main()
            instance.refresh_resume_source.assert_called_once_with("/tmp/resume.txt")


if __name__ == "__main__":
    unittest.main()
