from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_agent.cli import main
from job_agent.queue import export_approved, seed_queue, update_status
from job_agent.shortlist import build_shortlist


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


if __name__ == "__main__":
    unittest.main()
