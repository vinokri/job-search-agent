from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from .models import dump_json, load_json, utc_now


def http_get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "job-search-agent-local-runner/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def http_download(url: str, destination: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "job-search-agent-local-runner/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def post_runner_event(base_url: str, run_id: str, event: str, payload: dict | None = None) -> None:
    body = urllib.parse.urlencode(
        {"payload": json.dumps({"run_id": run_id, "event": event, "payload": payload or {}})}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/runner-event",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "job-search-agent-local-runner/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        return


class LocalRunnerState:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {"processed_runs": {}, "updated_at": ""}
        return load_json(self.path)

    def save(self, payload: dict) -> None:
        payload["updated_at"] = utc_now()
        dump_json(self.path, payload)


class LocalApplyRunner:
    def __init__(self, base_url: str, workspace: str | Path, poll_seconds: int = 20):
        self.base_url = base_url.rstrip("/")
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state = LocalRunnerState(self.workspace / "runner-state.json")
        self.poll_seconds = poll_seconds

    def poll_once(self) -> int:
        payload = http_get_json(f"{self.base_url}/api/pending-apply-runs")
        items = payload.get("items", [])
        processed = self.state.load()
        processed_runs = processed.setdefault("processed_runs", {})
        launched_count = 0
        for item in items:
            run_path = str(item.get("application_run_path", ""))
            run_id = Path(run_path).name if run_path else ""
            if not run_id or processed_runs.get(run_id):
                continue
            try:
                launch_dir = self._download_and_extract(run_id, str(item.get("bundle_url", "")))
                script_path = self._find_script(launch_dir)
                subprocess.Popen(["python3", script_path.name], cwd=str(launch_dir))
                processed_runs[run_id] = {
                    "status": "launched",
                    "job_id": item.get("job_id", ""),
                    "launched_at": utc_now(),
                    "launch_dir": str(launch_dir),
                }
                self.state.save(processed)
                post_runner_event(
                    self.base_url,
                    run_id,
                    "launched",
                    {"job_id": item.get("job_id", ""), "launch_dir": str(launch_dir)},
                )
                launched_count += 1
            except Exception as exc:  # noqa: BLE001
                processed_runs[run_id] = {
                    "status": "launch_failed",
                    "job_id": item.get("job_id", ""),
                    "error": str(exc),
                    "failed_at": utc_now(),
                }
                self.state.save(processed)
                try:
                    post_runner_event(
                        self.base_url,
                        run_id,
                        "launch_failed",
                        {"job_id": item.get("job_id", ""), "error": str(exc)},
                    )
                except urllib.error.URLError:
                    pass
        return launched_count

    def run_forever(self) -> None:
        while True:
            self.poll_once()
            time.sleep(self.poll_seconds)

    def _download_and_extract(self, run_id: str, bundle_url: str) -> Path:
        if not bundle_url:
            raise ValueError("Missing bundle_url.")
        run_dir = self.workspace / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = run_dir / "apply-bundle.zip"
        http_download(bundle_url, bundle_path)
        with zipfile.ZipFile(bundle_path, "r") as archive:
            archive.extractall(run_dir)
        return run_dir

    def _find_script(self, launch_dir: Path) -> Path:
        matches = sorted(launch_dir.glob("*_apply_playwright.py"))
        if not matches:
            raise ValueError("No Playwright launcher script found in bundle.")
        return matches[0]
