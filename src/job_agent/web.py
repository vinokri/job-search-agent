from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus
from wsgiref.simple_server import make_server

from .queue import export_approved, update_status
from .shortlist import build_shortlist


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DEFAULT_PROFILE = DATA_DIR / "profile.json"
DEFAULT_JOBS = DATA_DIR / "jobs.sample.json"
DEFAULT_SHORTLIST = DATA_DIR / "shortlist.json"
DEFAULT_QUEUE = DATA_DIR / "review-queue.json"
DEFAULT_APPROVED = DATA_DIR / "approved-jobs.json"
DEFAULT_MARKDOWN = DATA_DIR / "shortlist.md"


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


def render_home(message: str = "") -> bytes:
    shortlist = load_json_if_present(DEFAULT_SHORTLIST)
    queue = load_json_if_present(DEFAULT_QUEUE)
    approved = load_json_if_present(DEFAULT_APPROVED)

    shortlist_cards = "\n".join(render_shortlist_card(item) for item in shortlist) or "<p class='empty'>No shortlist yet.</p>"
    queue_rows = "\n".join(render_queue_card(item) for item in queue) or "<p class='empty'>No review queue yet.</p>"
    approved_rows = "\n".join(render_approved_card(item) for item in approved) or "<p class='empty'>No approved jobs exported yet.</p>"
    banner = f"<div class='banner'>{html_escape(message)}</div>" if message else ""

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
          <div class="stat"><strong>{sum(1 for item in queue if item.get("status") == "approved")}</strong><span class="meta">Approved roles</span></div>
          <div class="stat"><strong>{sum(1 for item in queue if item.get("status") == "pending")}</strong><span class="meta">Pending review</span></div>
        </div>
      </div>
      <div class="panel">
        <h2>Current files</h2>
        <p class="muted">Profile: {html_escape(display_path(DEFAULT_PROFILE))}</p>
        <p class="muted">Jobs input: {html_escape(display_path(DEFAULT_JOBS))}</p>
        <p class="muted">Shortlist: {html_escape(display_path(DEFAULT_SHORTLIST))}</p>
        <p class="muted">Queue: {html_escape(display_path(DEFAULT_QUEUE))}</p>
        <p class="muted">Approved export: {html_escape(display_path(DEFAULT_APPROVED))}</p>
      </div>
    </section>
    <section class="grid">
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
        <h2>Approved Jobs</h2>
        <form method="post" action="/export-approved">
          <div class="actions">
            <button type="submit" class="secondary">Export approved jobs</button>
          </div>
        </form>
        <div class="list" style="margin-top: 16px;">{approved_rows}</div>
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
    return f"""
<article class="job-card">
  <h3>{html_escape(item.get("title", ""))}</h3>
  <p><strong>{html_escape(item.get("company", ""))}</strong> · Score {item.get("score", 0)} · {status_badge(item.get("status", "pending"))}</p>
  <p class="muted"><a href="{html_escape(item.get("url", ""))}" target="_blank" rel="noreferrer">Open job</a></p>
  <form class="inline-form" method="post" action="/set-status">
    <input type="hidden" name="job_id" value="{job_id}">
    <input type="text" name="notes" placeholder="Optional review note" value="{html_escape(item.get('notes', ''))}">
    <button type="submit" name="status" value="approved" class="secondary">Approve</button>
    <button type="submit" name="status" value="hold" class="warning">Hold</button>
    <button type="submit" name="status" value="rejected">Reject</button>
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


def redirect(start_response, location: str) -> list[bytes]:
    start_response("303 See Other", [("Location", location)])
    return [b""]


def handle_run_search(form: dict[str, list[str]]) -> str:
    job_titles = parse_multi_value(form, "job_title", 3)
    companies = parse_multi_value(form, "company", 5)
    build_shortlist(
        str(DEFAULT_PROFILE),
        str(DEFAULT_JOBS),
        str(DEFAULT_SHORTLIST),
        str(DEFAULT_MARKDOWN),
        25,
        job_titles or None,
        companies or None,
    )
    from .queue import seed_queue

    seed_queue(str(DEFAULT_SHORTLIST), str(DEFAULT_QUEUE))
    return "Search completed. Shortlist and review queue refreshed."


def handle_set_status(form: dict[str, list[str]]) -> str:
    job_id = form.get("job_id", [""])[0]
    status = form.get("status", ["pending"])[0]
    notes = form.get("notes", [""])[0].strip()
    update_status(str(DEFAULT_QUEUE), job_id, status, notes)
    return f"Updated {job_id} to {status}."


def handle_export_approved() -> str:
    export_approved(str(DEFAULT_QUEUE), str(DEFAULT_APPROVED))
    return "Approved jobs exported."


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    message = parse_qs(environ.get("QUERY_STRING", "")).get("message", [""])[0]

    if method == "GET" and path == "/":
        body = render_home(message)
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [body]

    if method == "POST" and path in {"/run-search", "/set-status", "/export-approved"}:
        size = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(size).decode("utf-8")
        form = parse_qs(body)
        try:
            if path == "/run-search":
                message = handle_run_search(form)
            elif path == "/set-status":
                message = handle_set_status(form)
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
