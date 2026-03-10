from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote_plus
from wsgiref.simple_server import make_server

from .orchestration import JobSearchOrchestrator, WorkflowStore, build_default_paths
from .resume import sanitize_filename, store_uploaded_resume_bytes


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_PATHS = build_default_paths(ROOT)
DEFAULT_PROFILE = DEFAULT_PATHS.profile
DEFAULT_JOBS = DEFAULT_PATHS.sample_jobs
DEFAULT_LIVE_JOBS = DEFAULT_PATHS.live_jobs
DEFAULT_SHORTLIST = DEFAULT_PATHS.shortlist
DEFAULT_QUEUE = DEFAULT_PATHS.queue
DEFAULT_APPROVED = DEFAULT_PATHS.approved
DEFAULT_RUNTIME = DEFAULT_PATHS.runtime
DEFAULT_MEMORY = DEFAULT_PATHS.memory
DEFAULT_RESUME_STRUCTURED = DEFAULT_PATHS.resume_structured
DEFAULT_RESUME_SOURCES = DEFAULT_PATHS.resume_sources
DEFAULT_MARKDOWN = DEFAULT_PATHS.shortlist_markdown
DEFAULT_APPLICATION_RUNS = DEFAULT_PATHS.application_runs


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_json_if_present(path: Path) -> list[dict]:
    if not path.exists():
        return []
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def parse_multi_value(form: dict[str, list[str]], prefix: str, maximum: int) -> list[str]:
    values: list[str] = []
    for index in range(1, maximum + 1):
        key = f"{prefix}{index}"
        value = form.get(key, [""])[0].strip()
        if value:
            values.append(value)
    return values


def html_escape(value: str) -> str:
    return html.escape(value, quote=True)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def status_badge(status: str) -> str:
    return f'<span class="badge badge-{html_escape(status)}">{html_escape(status)}</span>'


def artifact_href(path_value: str) -> str:
    if not path_value:
        return ""
    return f"/artifact?path={quote_plus(path_value)}"


def resolve_artifact_path(path_value: str) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value).resolve()
    allowed_roots = [DATA_DIR.resolve()]
    for root in allowed_roots:
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue
    return None


def build_orchestrator() -> JobSearchOrchestrator:
    paths = build_default_paths(ROOT)
    paths.profile = DEFAULT_PROFILE
    paths.sample_jobs = DEFAULT_JOBS
    paths.live_jobs = DEFAULT_LIVE_JOBS
    paths.shortlist = DEFAULT_SHORTLIST
    paths.shortlist_markdown = DEFAULT_MARKDOWN
    paths.queue = DEFAULT_QUEUE
    paths.approved = DEFAULT_APPROVED
    paths.runtime = DEFAULT_RUNTIME
    paths.memory = DEFAULT_MEMORY
    paths.resume_structured = DEFAULT_RESUME_STRUCTURED
    paths.resume_sources = DEFAULT_RESUME_SOURCES
    paths.application_runs = DEFAULT_APPLICATION_RUNS
    return JobSearchOrchestrator(WorkflowStore(paths))


def render_home(message: str = "") -> bytes:
    shortlist = load_json_if_present(DEFAULT_SHORTLIST)
    queue = load_json_if_present(DEFAULT_QUEUE)
    approved = load_json_if_present(DEFAULT_APPROVED)
    runtime = load_json_if_present(DEFAULT_RUNTIME) if DEFAULT_RUNTIME.exists() else {}
    memory = load_json_if_present(DEFAULT_MEMORY)
    structured_resume = load_json_if_present(DEFAULT_RESUME_STRUCTURED) if DEFAULT_RESUME_STRUCTURED.exists() else {}

    shortlist_cards = "\n".join(render_shortlist_card(item) for item in shortlist) or "<p class='empty'>No shortlist yet.</p>"
    queue_rows = "\n".join(render_queue_card(item) for item in queue) or "<p class='empty'>No review queue yet.</p>"
    approved_rows = "\n".join(render_approved_card(item) for item in approved) or "<p class='empty'>No approved jobs exported yet.</p>"
    memory_rows = "\n".join(render_memory_row(item) for item in memory[-8:][::-1]) or "<p class='empty'>No memory yet.</p>"
    banner = f"<div class='banner'>{html_escape(message)}</div>" if message else ""
    last_search = runtime.get("last_search", {}) if isinstance(runtime, dict) else {}
    diagnostics = last_search.get("diagnostics", {}) if isinstance(last_search, dict) else {}
    diagnostics_rows = "\n".join(render_diagnostic_row(name, item) for name, item in diagnostics.items()) or "<p class='empty'>No diagnostics yet.</p>"

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Search Agent</title>
  <style>
    :root {{
      --ink: #13233b;
      --muted: #5b6677;
      --paper: #f5f0e8;
      --panel: #fffdf8;
      --line: #d7cab8;
      --accent: #d95d39;
      --accent-2: #2c6e62;
      --gold: #c28f2c;
      --shadow: 0 18px 50px rgba(19, 35, 59, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(217, 93, 57, 0.12), transparent 28%),
        linear-gradient(135deg, #efe2d2 0%, #f8f4ee 50%, #f0ede7 100%);
    }}
    .shell {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }}
    .hero {{
      display: grid;
      gap: 18px;
      grid-template-columns: 1.3fr 0.9fr;
      align-items: start;
      margin-bottom: 24px;
    }}
    .hero-card, .panel {{
      background: rgba(255, 253, 248, 0.94);
      border: 1px solid rgba(215, 202, 184, 0.9);
      border-radius: 24px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(6px);
    }}
    .hero-card {{
      padding: 28px;
      overflow: hidden;
      position: relative;
    }}
    .hero-card:after {{
      content: "";
      position: absolute;
      width: 180px;
      height: 180px;
      right: -28px;
      top: -28px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(217, 93, 57, 0.28), rgba(217, 93, 57, 0));
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: clamp(2rem, 5vw, 4rem);
      line-height: 0.96;
      letter-spacing: -0.03em;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: var(--accent);
      font-size: 0.78rem;
      margin-bottom: 10px;
    }}
    .lede, .meta, .empty {{
      color: var(--muted);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-top: 20px;
    }}
    .stat {{
      padding: 14px;
      border-radius: 16px;
      background: rgba(44, 110, 98, 0.07);
      border: 1px solid rgba(44, 110, 98, 0.16);
    }}
    .stat strong {{
      display: block;
      font-size: 1.45rem;
    }}
    .panel {{
      padding: 20px;
    }}
    .banner {{
      margin-bottom: 18px;
      padding: 14px 18px;
      border-radius: 14px;
      background: rgba(44, 110, 98, 0.12);
      border: 1px solid rgba(44, 110, 98, 0.28);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 20px;
      margin-bottom: 20px;
    }}
    .full {{
      grid-column: 1 / -1;
    }}
    label {{
      display: block;
      font-size: 0.88rem;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    input, textarea {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fff;
      font: inherit;
      color: var(--ink);
    }}
    textarea {{
      min-height: 92px;
      resize: vertical;
    }}
    .field-row {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .field-row.five {{
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 11px 18px;
      font: inherit;
      cursor: pointer;
      color: #fff;
      background: var(--ink);
    }}
    button.secondary {{
      background: var(--accent-2);
    }}
    button.warning {{
      background: var(--gold);
      color: var(--ink);
    }}
    .list {{
      display: grid;
      gap: 14px;
    }}
    .job-card {{
      padding: 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(247,242,234,0.95));
    }}
    .job-card h3 {{
      margin: 0 0 8px;
      font-size: 1.15rem;
    }}
    .job-card p {{
      margin: 6px 0;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: rgba(19, 35, 59, 0.09);
    }}
    .badge-approved {{ background: rgba(44, 110, 98, 0.15); color: #1f5e52; }}
    .badge-rejected {{ background: rgba(217, 93, 57, 0.15); color: #9d3d22; }}
    .badge-hold {{ background: rgba(194, 143, 44, 0.18); color: #7b5b1e; }}
    .badge-pending {{ background: rgba(19, 35, 59, 0.09); color: var(--ink); }}
    .muted {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .inline-form {{
      display: grid;
      grid-template-columns: 1fr auto auto auto;
      gap: 10px;
      margin-top: 14px;
      align-items: center;
    }}
    .inline-form input {{
      min-width: 0;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    @media (max-width: 920px) {{
      .hero, .grid, .field-row, .field-row.five, .inline-form {{
        grid-template-columns: 1fr;
      }}
      .stats {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    {banner}
    <section class="hero">
      <div class="hero-card">
        <div class="eyebrow">Human-in-the-loop job workflow</div>
        <h1>Job Search Agent</h1>
        <p class="lede">Run a profile-based search, inspect the shortlist, approve the roles that matter, and stop before application submission.</p>
        <div class="stats">
          <div class="stat"><strong>{len(shortlist)}</strong><span class="meta">Shortlisted jobs</span></div>
          <div class="stat"><strong>{sum(1 for item in queue if item.get("review_status") == "approved")}</strong><span class="meta">Approved roles</span></div>
          <div class="stat"><strong>{sum(1 for item in queue if item.get("apply_status") == "submitted")}</strong><span class="meta">Applications submitted</span></div>
        </div>
      </div>
      <div class="panel">
        <h2>Runtime</h2>
        <p class="muted">Profile: {html_escape(display_path(DEFAULT_PROFILE))}</p>
        <p class="muted">Sample jobs: {html_escape(display_path(DEFAULT_JOBS))}</p>
        <p class="muted">Live jobs cache: {html_escape(display_path(DEFAULT_LIVE_JOBS))}</p>
        <p class="muted">Shortlist: {html_escape(display_path(DEFAULT_SHORTLIST))}</p>
        <p class="muted">Queue: {html_escape(display_path(DEFAULT_QUEUE))}</p>
        <p class="muted">Approved export: {html_escape(display_path(DEFAULT_APPROVED))}</p>
        <p class="muted">Agent runtime: {html_escape(display_path(DEFAULT_RUNTIME))}</p>
        <p class="muted">Agent memory: {html_escape(display_path(DEFAULT_MEMORY))}</p>
        <p class="muted">Structured resume: {html_escape(display_path(DEFAULT_RESUME_STRUCTURED))}</p>
        <p class="muted">Application runs: {html_escape(display_path(DEFAULT_APPLICATION_RUNS))}</p>
        <p class="muted">Last search companies: {html_escape(', '.join(last_search.get('companies', [])) or 'profile defaults')}</p>
        <p class="muted">Last search source: {html_escape(last_search.get('jobs_source', 'unknown'))}</p>
      </div>
    </section>
    <section class="grid">
      <div class="panel full">
        <h2>Resume Source</h2>
        <form method="post" action="/resume-source" enctype="multipart/form-data">
          <div class="field-row">
            <div>
              <label for="resume_path">Existing resume path</label>
              <input id="resume_path" name="resume_path" placeholder="/absolute/path/to/resume.pdf">
            </div>
            <div>
              <label for="resume_file">Upload resume file</label>
              <input id="resume_file" name="resume_file" type="file">
            </div>
            <div>
              <label for="resume_filename">Optional filename label</label>
              <input id="resume_filename" name="resume_filename" placeholder="vinodh-resume.pdf">
            </div>
          </div>
          <div class="actions">
            <button type="submit" class="secondary">Parse resume source</button>
          </div>
        </form>
        <p class="muted">Parsed sections: {html_escape(', '.join(sorted(structured_resume.get('sections', {}).keys())) or 'none yet')}</p>
      </div>
      <div class="panel full">
        <h2>Run Search</h2>
        <form method="post" action="/run-search">
          <div class="field-row">
            <div>
              <label for="job_title1">Job title 1</label>
              <input id="job_title1" name="job_title1" placeholder="software engineer">
            </div>
            <div>
              <label for="job_title2">Job title 2</label>
              <input id="job_title2" name="job_title2" placeholder="data engineer">
            </div>
            <div>
              <label for="job_title3">Job title 3</label>
              <input id="job_title3" name="job_title3" placeholder="machine learning engineer">
            </div>
          </div>
          <div class="field-row five" style="margin-top: 12px;">
            <div>
              <label for="company1">Company 1</label>
              <input id="company1" name="company1" placeholder="NVIDIA">
            </div>
            <div>
              <label for="company2">Company 2</label>
              <input id="company2" name="company2" placeholder="Snowflake">
            </div>
            <div>
              <label for="company3">Company 3</label>
              <input id="company3" name="company3" placeholder="Google">
            </div>
            <div>
              <label for="company4">Company 4</label>
              <input id="company4" name="company4" placeholder="Databricks">
            </div>
            <div>
              <label for="company5">Company 5</label>
              <input id="company5" name="company5" placeholder="Optional">
            </div>
          </div>
          <div class="actions">
            <button type="submit">Run search</button>
          </div>
        </form>
      </div>
      <div class="panel">
        <h2>Shortlist</h2>
        <div class="list">{shortlist_cards}</div>
      </div>
      <div class="panel">
        <h2>Review Queue</h2>
        <div class="list">{queue_rows}</div>
      </div>
      <div class="panel full">
        <h2>Search Diagnostics</h2>
        <div class="list">{diagnostics_rows}</div>
      </div>
      <div class="panel full">
        <h2>Approved Jobs</h2>
        <form method="post" action="/export-approved">
          <div class="actions">
            <button type="submit" class="secondary">Export approved jobs</button>
          </div>
        </form>
        <div class="list" style="margin-top: 16px;">{approved_rows}</div>
      </div>
      <div class="panel full">
        <h2>Agent Memory</h2>
        <div class="list">{memory_rows}</div>
      </div>
    </section>
  </div>
</body>
</html>
"""
    return page.encode("utf-8")


def render_shortlist_card(item: dict) -> str:
    reasons = "; ".join(item.get("reasons", [])[:4])
    matched = ", ".join(item.get("matched_skills", [])[:6])
    return f"""
<article class="job-card">
  <h3>{html_escape(item.get("title", ""))}</h3>
  <p><strong>{html_escape(item.get("company", ""))}</strong> · Score {item.get("score", 0)}</p>
  <p class="muted"><a href="{html_escape(item.get("url", ""))}" target="_blank" rel="noreferrer">Open job</a></p>
  <p class="muted">{html_escape(reasons)}</p>
  <p class="muted">Matched skills: {html_escape(matched or "None")}</p>
</article>
"""


def render_queue_card(item: dict) -> str:
    job_id = html_escape(item.get("id", ""))
    review = item.get("review_status", item.get("status", "pending"))
    resume = item.get("resume_status", "idle")
    apply = item.get("apply_status", "idle")
    resume_path = item.get("resume_draft_path", "")
    packet_path = item.get("application_packet_path", "")
    run_path = item.get("application_run_path", "")
    apply_command = item.get("apply_launch_command", "")
    rendered_docx = item.get("rendered_resume_docx_path", "")
    rendered_pdf = item.get("rendered_resume_pdf_path", "")
    bundle_path = item.get("apply_bundle_path", "")
    preview = ""
    if resume_path and Path(resume_path).exists():
        preview = "\n".join(Path(resume_path).read_text(encoding="utf-8").splitlines()[:8])
    draft_link = artifact_href(resume_path)
    docx_link = artifact_href(rendered_docx)
    pdf_link = artifact_href(rendered_pdf)
    bundle_link = artifact_href(bundle_path)
    packet_link = artifact_href(packet_path)
    return f"""
<article class="job-card">
  <h3>{html_escape(item.get("title", ""))}</h3>
  <p><strong>{html_escape(item.get("company", ""))}</strong> · Score {item.get("score", 0)} · Review {status_badge(review)}</p>
  <p class="muted"><a href="{html_escape(item.get("url", ""))}" target="_blank" rel="noreferrer">Open job</a></p>
  <p class="muted"><a href="{html_escape(item.get("url", ""))}" target="_blank" rel="noreferrer">Open ATS page</a></p>
  <p class="muted">Resume agent: {html_escape(resume)}{f" · Draft: {html_escape(resume_path)}" if resume_path else ""}</p>
  <p class="muted">Rendered files: {html_escape(rendered_docx or 'no docx yet')} · {html_escape(rendered_pdf or 'no pdf yet')}</p>
  <p class="muted">{f'<a href="{html_escape(draft_link)}">Download resume draft</a>' if draft_link else 'Resume draft not generated yet.'}{f' · <a href="{html_escape(docx_link)}">Download DOCX</a>' if docx_link else ''}{f' · <a href="{html_escape(pdf_link)}">Download PDF</a>' if pdf_link else ''}</p>
  <p class="muted">Apply agent: {html_escape(apply)}{f" · Packet: {html_escape(packet_path)}" if packet_path else ""}</p>
  <p class="muted">Apply run: {html_escape(run_path or 'not prepared yet')}</p>
  <p class="muted">Local launch: {html_escape(apply_command or 'Download the bundle and run it locally.')}</p>
  <p class="muted">{f'<a href="{html_escape(bundle_link)}">Download apply bundle</a>' if bundle_link else 'Apply bundle not prepared yet.'}{f' · <a href="{html_escape(packet_link)}">Download packet</a>' if packet_link else ''}</p>
  {f'<pre class="muted" style="white-space: pre-wrap; overflow-x: auto; background: rgba(19,35,59,0.04); padding: 12px; border-radius: 12px;">{html_escape(preview)}</pre>' if preview else ''}
  <form class="inline-form" method="post" action="/approve-job">
    <input type="hidden" name="job_id" value="{job_id}">
    <input type="text" name="notes" placeholder="Optional review note" value="{html_escape(item.get('notes', ''))}">
    <button type="submit" class="secondary">Approve</button>
  </form>
  <form class="inline-form" method="post" action="/approve-resume">
    <input type="hidden" name="job_id" value="{job_id}">
    <input type="text" disabled value="{html_escape(item.get('resume_preview_path', 'no preview yet'))}">
    <button type="submit" class="secondary">Approve Resume</button>
    <button type="button" class="warning" disabled>Resume {html_escape(resume)}</button>
    <button type="button" disabled>{html_escape(item.get('selected_resume_path', ''))}</button>
  </form>
  <form class="inline-form" method="post" action="/apply-job">
    <input type="hidden" name="job_id" value="{job_id}">
    <input type="text" disabled value="{html_escape(apply_command or 'Run locally after preparation')}">
    <button type="submit" class="secondary">Apply In Browser</button>
    <button type="button" class="warning" disabled>Resume {html_escape(resume)}</button>
    <button type="button" disabled>{html_escape(apply)}</button>
  </form>
  <form class="inline-form" method="post" action="/mark-submitted">
    <input type="hidden" name="job_id" value="{job_id}">
    <input type="text" disabled value="{html_escape(item.get('apply_provider', 'no adapter'))}">
    <button type="submit" class="secondary">Mark Submitted</button>
    <button type="button" class="warning" disabled>Review before submit</button>
    <button type="button" disabled>{html_escape(run_path or '')}</button>
  </form>
</article>
"""


def render_approved_card(item: dict) -> str:
    return f"""
<article class="job-card">
  <h3>{html_escape(item.get("title", ""))}</h3>
  <p><strong>{html_escape(item.get("company", ""))}</strong> · Score {item.get("score", 0)}</p>
  <p class="muted"><a href="{html_escape(item.get("url", ""))}" target="_blank" rel="noreferrer">Open job</a></p>
  <p class="muted">{html_escape(item.get("notes", ""))}</p>
</article>
"""


def render_memory_row(item: dict) -> str:
    return f"""
<article class="job-card">
  <h3>{html_escape(item.get("agent", ""))}</h3>
  <p class="muted">{html_escape(item.get("timestamp", ""))}</p>
  <p>{html_escape(item.get("message", ""))}</p>
  <p class="muted">Action: {html_escape(item.get("action", ""))}{f" · Job {html_escape(item.get('job_id', ''))}" if item.get('job_id') else ""}</p>
</article>
"""


def render_diagnostic_row(name: str, item: dict) -> str:
    error_text = f" · Error: {item.get('error', '')}" if item.get("error") else ""
    sample_titles = ", ".join(item.get("sample_titles", []))
    return f"""
<article class="job-card">
  <h3>{html_escape(name)}</h3>
  <p class="muted">Status: {html_escape(str(item.get("status", "unknown")))} · Jobs collected: {html_escape(str(item.get("jobs_collected", 0)))}</p>
  <p class="muted">Response type: {html_escape(str(item.get("response_type", "unknown")))} · Keys: {html_escape(', '.join(item.get("top_level_keys", [])) or 'none')}</p>
  <p class="muted">Requested titles: {html_escape(', '.join(item.get('requested_titles', [])) or 'none')}</p>
  <p class="muted">Sample titles: {html_escape(sample_titles or 'none')}</p>
  <p class="muted">Preview: {html_escape(item.get("response_preview", "") or 'none')}</p>
  <p class="muted">{html_escape(error_text or 'No collector error reported.')}</p>
</article>
"""


def parse_multipart(body: bytes, content_type: str) -> dict[str, list[object]]:
    boundary_match = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary_match = part.split("=", 1)[1]
            break
    if not boundary_match:
        return {}
    boundary = boundary_match.encode("utf-8")
    chunks = body.split(b"--" + boundary)
    result: dict[str, list[object]] = {}
    for chunk in chunks:
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        header_blob, _, data = chunk.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", errors="replace")
        disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
        name_match = None
        filename_match = None
        for part in disposition.split(";"):
            part = part.strip()
            if part.startswith("name="):
                name_match = part.split("=", 1)[1].strip('"')
            elif part.startswith("filename="):
                filename_match = part.split("=", 1)[1].strip('"')
        if not name_match:
            continue
        data = data.rstrip(b"\r\n")
        if filename_match:
            result.setdefault(name_match, []).append(
                {"filename": filename_match, "content": data}
            )
        else:
            result.setdefault(name_match, []).append(data.decode("utf-8", errors="replace"))
    return result


def parse_request_form(environ) -> dict[str, list[object]]:
    size = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(size)
    content_type = environ.get("CONTENT_TYPE", "")
    if "multipart/form-data" in content_type:
        return parse_multipart(body, content_type)
    decoded = body.decode("utf-8")
    return {key: [unquote_plus(value) for value in values] for key, values in parse_qs(decoded).items()}


def redirect(start_response, location: str) -> list[bytes]:
    start_response("303 See Other", [("Location", location)])
    return [b""]


def handle_run_search(form: dict[str, list[str]]) -> str:
    job_titles = parse_multi_value(form, "job_title", 3)
    companies = parse_multi_value(form, "company", 5)
    orchestrator = build_orchestrator()
    result = orchestrator.run_search(job_titles or None, companies or None, 25)
    source = "live company career pages" if result.get("live_jobs_count") else "the sample job file"
    return f"Search completed using {source}. {result.get('shortlist_count', 0)} jobs shortlisted."


def handle_resume_source(form: dict[str, list[object]]) -> str:
    orchestrator = build_orchestrator()
    resume_path = str(form.get("resume_path", [""])[0]).strip() if form.get("resume_path") else ""
    upload = form.get("resume_file", [])
    if upload and isinstance(upload[0], dict) and upload[0].get("content"):
        uploaded = upload[0]
        filename = sanitize_filename(
            str(form.get("resume_filename", [""])[0]).strip() or uploaded.get("filename", "resume-upload.txt")
        )
        destination = DEFAULT_RESUME_SOURCES / filename
        resume_path = store_uploaded_resume_bytes(destination, uploaded["content"])
    if not resume_path:
        raise ValueError("Provide an existing resume path or upload a resume file.")
    structured = orchestrator.refresh_resume_source(resume_path)
    return f"Resume source parsed. Sections found: {', '.join(sorted(structured.get('sections', {}).keys())) or 'none'}."


def handle_approve_job(form: dict[str, list[str]]) -> str:
    job_id = form.get("job_id", [""])[0]
    orchestrator = build_orchestrator()
    result = orchestrator.approve_job(job_id)
    return f"Approved {job_id}. Resume agent prepared {result.get('resume_draft_path', '')}."


def handle_apply_job(form: dict[str, list[str]]) -> str:
    job_id = form.get("job_id", [""])[0]
    orchestrator = build_orchestrator()
    result = orchestrator.apply_job(job_id)
    command = result.get("apply_launch_command", "")
    return (
        f"Browser apply prepared for {job_id}. "
        f"Download the apply bundle from the queue card, run {command or 'python3 <provider>_apply_playwright.py'} locally, "
        "and the script will open the ATS page automatically."
    )


def handle_mark_submitted(form: dict[str, list[str]]) -> str:
    job_id = form.get("job_id", [""])[0]
    orchestrator = build_orchestrator()
    result = orchestrator.mark_submitted(job_id)
    return f"External submission confirmed for {job_id}. Packet: {result.get('application_packet_path', '')}."


def handle_approve_resume(form: dict[str, list[str]]) -> str:
    job_id = form.get("job_id", [""])[0]
    orchestrator = build_orchestrator()
    result = orchestrator.approve_resume(job_id)
    return f"Resume approved for {job_id}. Selected file: {result.get('selected_resume_path', '')}."


def handle_export_approved() -> str:
    build_orchestrator().store.save_approved(
        [item for item in load_json_if_present(DEFAULT_QUEUE) if item.get("review_status") == "approved"]
    )
    return "Approved jobs exported."


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    message = parse_qs(environ.get("QUERY_STRING", "")).get("message", [""])[0]

    if method == "GET" and path == "/":
        body = render_home(message)
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [body]

    if method == "GET" and path == "/artifact":
        requested = parse_qs(environ.get("QUERY_STRING", "")).get("path", [""])[0]
        resolved = resolve_artifact_path(requested)
        if not resolved or not resolved.exists():
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Artifact not found"]
        content_type = "application/octet-stream"
        if resolved.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        elif resolved.suffix == ".zip":
            content_type = "application/zip"
        elif resolved.suffix == ".md":
            content_type = "text/markdown; charset=utf-8"
        start_response(
            "200 OK",
            [
                ("Content-Type", content_type),
                ("Content-Disposition", f'attachment; filename="{resolved.name}"'),
            ],
        )
        return [resolved.read_bytes()]

    if method == "POST" and path in {"/resume-source", "/run-search", "/approve-job", "/approve-resume", "/apply-job", "/mark-submitted", "/export-approved"}:
        form = parse_request_form(environ)
        try:
            if path == "/resume-source":
                message = handle_resume_source(form)
            elif path == "/run-search":
                message = handle_run_search(form)
            elif path == "/approve-job":
                message = handle_approve_job(form)
            elif path == "/approve-resume":
                message = handle_approve_resume(form)
            elif path == "/apply-job":
                message = handle_apply_job(form)
            elif path == "/mark-submitted":
                message = handle_mark_submitted(form)
            else:
                message = handle_export_approved()
            return redirect(start_response, f"/?message={quote_plus(message)}")
        except Exception as exc:  # noqa: BLE001
            return redirect(start_response, f"/?message={quote_plus(str(exc))}")

    if method == "GET" and path == "/health":
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"ok"]

    if method == "GET" and path == "/favicon.ico":
        start_response("204 No Content", [])
        return [b""]

    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Not found"]


def serve_ui(host: str = "127.0.0.1", port: int | None = None) -> None:
    actual_port = port or int(os.environ.get("PORT", "8000"))
    with make_server(host, actual_port, application) as server:
        print(f"Job Search Agent UI running at http://{host}:{actual_port}")
        server.serve_forever()
