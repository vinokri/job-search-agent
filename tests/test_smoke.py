from __future__ import annotations

import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main
from job_agent.queue import export_approved, seed_queue, update_status
from job_agent.shortlist import build_shortlist
from job_agent import web
from job_agent.web import application


ROOT = Path(__file__).resolve().parents[1]


class SmokeTest(unittest.TestCase):
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

    def test_web_app_home_and_run_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            profile_path = tmp / "profile.json"
            jobs_path = tmp / "jobs.json"
            shortlist_path = tmp / "shortlist.json"
            queue_path = tmp / "queue.json"
            approved_path = tmp / "approved.json"
            markdown_path = tmp / "shortlist.md"

            profile_path.write_text((ROOT / "data/profile.json").read_text(encoding="utf-8"), encoding="utf-8")
            jobs_path.write_text((ROOT / "data/jobs.sample.json").read_text(encoding="utf-8"), encoding="utf-8")
            approved_path.write_text("[]\n", encoding="utf-8")

            statuses = []

            def start_response(status, headers):  # noqa: ANN001,ANN202
                statuses.append((status, headers))

            with patch.object(web, "DEFAULT_PROFILE", profile_path), patch.object(
                web, "DEFAULT_JOBS", jobs_path
            ), patch.object(web, "DEFAULT_SHORTLIST", shortlist_path), patch.object(
                web, "DEFAULT_QUEUE", queue_path
            ), patch.object(
                web, "DEFAULT_APPROVED", approved_path
            ), patch.object(
                web, "DEFAULT_MARKDOWN", markdown_path
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

                queue_payload = json.loads(queue_path.read_text(encoding="utf-8"))
                self.assertEqual(queue_payload[0]["id"], "snowflake-001")


if __name__ == "__main__":
    unittest.main()
