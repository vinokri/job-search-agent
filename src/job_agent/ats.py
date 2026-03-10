from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from .models import dump_json, load_json, utc_now


def playwright_python_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


class ApplicationRunStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create_run(self, job_id: str, provider: str, payload: dict) -> dict:
        run_id = f"{job_id}-{provider.lower()}-{utc_now().replace(':', '-').replace('+', 'Z')}"
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        screenshots_dir = run_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload.update(
            {
                "run_id": run_id,
                "provider": provider,
                "run_dir": str(run_dir),
                "screenshots_dir": str(screenshots_dir),
                "events": [],
                "updated_at": utc_now(),
            }
        )
        self.save_run(payload)
        return payload

    def load_run(self, run_id: str) -> dict:
        return load_json(self.root / run_id / "run.json")

    def save_run(self, payload: dict) -> None:
        payload["updated_at"] = utc_now()
        dump_json(Path(payload["run_dir"]) / "run.json", payload)

    def append_event(self, run_id: str, event: str, message: str, payload: dict | None = None) -> dict:
        run = self.load_run(run_id)
        run.setdefault("events", []).append(
            {
                "timestamp": utc_now(),
                "event": event,
                "message": message,
                "payload": payload or {},
            }
        )
        self.save_run(run)
        return run


class ATSAdapter:
    provider = "generic"

    def supports(self, job: dict) -> bool:
        raise NotImplementedError

    def prepare_run(self, run_store: ApplicationRunStore, profile: dict, job: dict, resume_path: str) -> dict:
        raise NotImplementedError


class GoogleATSAdapter(ATSAdapter):
    provider = "Google"

    def supports(self, job: dict) -> bool:
        company = str(job.get("company", "")).lower()
        url = str(job.get("url", "")).lower()
        return company == "google" or "google.com/about/careers" in url

    def prepare_run(self, run_store: ApplicationRunStore, profile: dict, job: dict, resume_path: str) -> dict:
        run = run_store.create_run(
            job["job_id"],
            self.provider,
            {
                "job_id": job["job_id"],
                "job_url": job["url"],
                "job_title": job["title"],
                "company": job["company"],
                "resume_path": resume_path,
                "status": "browser_ready",
                "submit_mode": "review_before_submit",
                "playwright_available": playwright_python_available(),
                "form_state": {
                    "candidate_name": profile.get("candidate", {}).get("name", ""),
                    "candidate_email": profile.get("candidate", {}).get("email", ""),
                    "candidate_phone": profile.get("candidate", {}).get("phone", ""),
                },
                "errors": [],
            },
        )
        script_path = Path(run["run_dir"]) / "google_apply_playwright.py"
        script_path.write_text(self._build_script(run), encoding="utf-8")
        launch_command = f"python3 {shell_quote(str(script_path))}"
        run["playwright_script_path"] = str(script_path)
        run["launch_command"] = launch_command
        if not run["playwright_available"]:
            run["status"] = "awaiting_playwright_runtime"
            run["errors"].append("Install Playwright in the local runtime to launch browser automation.")
        run_store.save_run(run)
        return run

    def _build_script(self, run: dict) -> str:
        run_path = str(Path(run["run_dir"]) / "run.json")
        return f"""from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


RUN_PATH = Path({run_path!r})


async def click_first(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count():
                await locator.click()
                return selector
        except Exception:
            continue
    return ""


async def fill_first(page, selectors, value):
    if not value:
        return ""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count():
                await locator.fill(value)
                return selector
        except Exception:
            continue
    return ""


async def upload_first(page, selectors, file_path):
    if not file_path:
        return ""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count():
                await locator.set_input_files(file_path)
                return selector
        except Exception:
            continue
    return ""


async def main():
    run = json.loads(RUN_PATH.read_text(encoding="utf-8"))
    screenshots_dir = Path(run["screenshots_dir"])
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        await page.goto(run["job_url"], wait_until="domcontentloaded")
        await page.screenshot(path=str(screenshots_dir / "01-job-page.png"), full_page=True)
        await click_first(
            page,
            [
                "text=/apply/i",
                "text=/apply now/i",
                "button:has-text('Apply')",
                "a:has-text('Apply')",
            ],
        )
        await page.wait_for_timeout(2500)
        await page.screenshot(path=str(screenshots_dir / "02-after-apply-click.png"), full_page=True)
        form_state = run.get("form_state", {{}})
        await fill_first(page, ["input[name='name']", "input[type='text']"], form_state.get("candidate_name", ""))
        await fill_first(page, ["input[name='email']", "input[type='email']"], form_state.get("candidate_email", ""))
        await fill_first(page, ["input[name='phone']", "input[type='tel']"], form_state.get("candidate_phone", ""))
        await upload_first(page, ["input[type='file']"], run.get("resume_path", ""))
        await page.screenshot(path=str(screenshots_dir / "03-form-filled.png"), full_page=True)
        print("Browser apply flow is ready for manual review and final submit.")
        print("Leave the browser open, review the application, submit manually, then return here.")
        input("Press Enter after you have finished the browser review...")


if __name__ == "__main__":
    asyncio.run(main())
"""


def select_adapter(job: dict) -> ATSAdapter | None:
    adapters: list[ATSAdapter] = [GoogleATSAdapter()]
    for adapter in adapters:
        if adapter.supports(job):
            return adapter
    return None
