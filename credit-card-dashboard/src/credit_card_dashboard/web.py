from __future__ import annotations

import html
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote_plus
from wsgiref.simple_server import make_server

from .adapters import get_adapter
from .orchestration import DashboardOrchestrator, DashboardStore, build_default_paths


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATHS = build_default_paths(ROOT)


def build_orchestrator() -> DashboardOrchestrator:
    return DashboardOrchestrator(DashboardStore(build_default_paths(ROOT)))


def html_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def parse_form(environ) -> dict[str, list[object]]:
    size = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(size)
    content_type = environ.get("CONTENT_TYPE", "")
    if "multipart/form-data" in content_type:
        boundary = ""
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part.split("=", 1)[1]
        result: dict[str, list[object]] = {}
        if not boundary:
            return result
        for chunk in body.split(b"--" + boundary.encode("utf-8")):
            chunk = chunk.strip(b"\r\n")
            if not chunk or chunk == b"--":
                continue
            header_blob, _, data = chunk.partition(b"\r\n\r\n")
            headers = header_blob.decode("utf-8", errors="replace")
            disposition = next((line for line in headers.split("\r\n") if line.lower().startswith("content-disposition:")), "")
            name = ""
            filename = ""
            for item in disposition.split(";"):
                item = item.strip()
                if item.startswith("name="):
                    name = item.split("=", 1)[1].strip('"')
                if item.startswith("filename="):
                    filename = item.split("=", 1)[1].strip('"')
            data = data.rstrip(b"\r\n")
            if name:
                if filename:
                    result.setdefault(name, []).append({"filename": filename, "content": data})
                else:
                    result.setdefault(name, []).append(data.decode("utf-8", errors="replace"))
        return result
    parsed = parse_qs(body.decode("utf-8"))
    return {key: [unquote_plus(value) for value in values] for key, values in parsed.items()}


def redirect(start_response, message: str) -> list[bytes]:
    start_response("303 See Other", [("Location", f"/?message={quote_plus(message)}")])
    return [b""]


def _status_badge(value: str) -> str:
    tone = "slate"
    if "completed" in value:
        tone = "green"
    elif "pending" in value or "queued" in value:
        tone = "amber"
    elif "missing" in value:
        tone = "red"
    return f"<span class='badge {tone}'>{html_escape(value.replace('_', ' '))}</span>"


def _account_options(accounts: list[dict]) -> str:
    return "".join(
        f"<option value='{html_escape(item['id'])}'>{html_escape(item['nickname'])} · {html_escape(item['issuer'])}</option>"
        for item in accounts
    )


def render_home(message: str = "") -> bytes:
    store = DashboardStore(DEFAULT_PATHS)
    accounts = store.load_accounts()
    runtime = store.load_runtime()
    memory = store.load_memory()
    payment_requests = store.load_payment_requests()
    statement_requests = store.load_statement_requests()
    statements = store.load_statement_index()
    summary = runtime.get("summary", {})
    reminders = runtime.get("reminders", [])
    datalist = _account_options(accounts)
    banner = f"<div class='banner'>{html_escape(message)}</div>" if message else ""
    statement_requests_sorted = statement_requests[::-1]
    payment_requests_sorted = payment_requests[::-1]
    statements_sorted = statements[::-1]

    def summary_card(label: str, value: str, detail: str) -> str:
        return f"""
<article class="metric">
  <div class="eyebrow">{html_escape(label)}</div>
  <strong>{html_escape(value)}</strong>
  <p>{html_escape(detail)}</p>
</article>
"""

    def account_card(item: dict) -> str:
        adapter = get_adapter(item["issuer"])
        utilization = 0.0
        if item.get("credit_limit"):
            utilization = round((float(item.get("current_balance", 0)) / float(item.get("credit_limit", 1))) * 100, 1)
        credential_badge = _status_badge("credentials_ready" if item.get("credential_saved") else "credentials_missing")
        return f"""
<article class="card">
  <div class="card-head">
    <div>
      <h3>{html_escape(item['nickname'])}</h3>
      <p><strong>{html_escape(item['issuer'])}</strong> · ending {html_escape(item['last4'])}</p>
    </div>
    {credential_badge}
  </div>
  <p>Balance ${float(item.get('current_balance', 0)):.2f} of ${float(item.get('credit_limit', 0)):.2f} · Utilization {utilization:.1f}%</p>
  <p>Minimum due ${float(item.get('minimum_due', 0)):.2f} · Due {html_escape(item.get('next_due_date', 'n/a'))}</p>
  <p class="muted">{html_escape(adapter.portal_label)} · Statements: {html_escape(adapter.statement_mode)} · Payments: {html_escape(adapter.payment_mode)}</p>
  <p class="muted">Masked user: {html_escape(item.get('masked_username', 'not saved'))}</p>
</article>
"""

    def statement_request_card(item: dict) -> str:
        return f"""
<article class="card">
  <div class="card-head">
    <div>
      <strong>{html_escape(item['issuer'])}</strong>
      <p>{html_escape(item['account_id'])}</p>
    </div>
    {_status_badge(item.get('status', 'queued'))}
  </div>
  <p class="muted">Portal: {html_escape(item.get('portal_label', 'Issuer Portal'))}</p>
  <p>{html_escape(item.get('next_step', 'Upload the statement after retrieval.'))}</p>
  <p class="muted">{html_escape(item.get('notes', ''))}</p>
</article>
"""

    def statement_card(item: dict) -> str:
        filename = html_escape(item["filename"])
        return f"""
<article class="card">
  <div class="card-head">
    <div>
      <strong>{html_escape(item['issuer'])}</strong>
      <p>{filename}</p>
    </div>
    <a class="link-button" href="/download-statement?id={html_escape(item['id'])}">Download</a>
  </div>
  <p>Close {html_escape(item['close_date'])} · Due {html_escape(item['due_date'])}</p>
  <p>Balance ${float(item['statement_balance']):.2f} · Minimum ${float(item['minimum_due']):.2f}</p>
</article>
"""

    def payment_request_card(item: dict) -> str:
        approve_block = ""
        complete_block = ""
        if item.get("status") == "pending_approval":
            approve_block = f"""
<form method="post" action="/approve-payment" class="stacked-form">
  <input type="hidden" name="request_id" value="{html_escape(item['id'])}">
  <input name="passphrase" type="password" placeholder="vault passphrase (optional)">
  <button type="submit">Approve and stage payment</button>
</form>
"""
        if item.get("status") in {"approved_ready_for_confirmation", "approved_missing_credentials"}:
            complete_block = f"""
<form method="post" action="/mark-payment-complete" class="stacked-form">
  <input type="hidden" name="request_id" value="{html_escape(item['id'])}">
  <input name="confirmation_reference" placeholder="confirmation reference">
  <button type="submit" class="warning">Mark payment completed</button>
</form>
"""
        return f"""
<article class="card">
  <div class="card-head">
    <div>
      <strong>{html_escape(item['issuer'])}</strong>
      <p>${float(item['amount']):.2f} scheduled for {html_escape(item['scheduled_date'])}</p>
    </div>
    {_status_badge(item.get('status', 'pending_approval'))}
  </div>
  <p>{html_escape(item.get('next_step', 'Approve before proceeding.'))}</p>
  <p class="muted">{html_escape(item.get('notes', ''))}</p>
  {approve_block}
  {complete_block}
</article>
"""

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Credit Card Dashboard</title>
  <style>
    :root {{
      --ink:#172642;
      --muted:#5c6678;
      --edge:#d6c9b6;
      --paper:#fffdf9;
      --panel:rgba(255,255,255,0.9);
      --green:#2d7b67;
      --amber:#c4902f;
      --red:#b65444;
      --slate:#244067;
      --wash:#edf3f0;
      --bg1:#f7ecde;
      --bg2:#f6f1ea;
    }}
    body {{ margin:0; font-family: Georgia, serif; color:var(--ink); background: radial-gradient(circle at top right, rgba(223,189,171,.45), transparent 30%), linear-gradient(135deg,var(--bg1),var(--bg2)); }}
    .shell {{ max-width:1280px; margin:0 auto; padding:24px; }}
    .hero, .panel {{ background:var(--panel); border:1px solid var(--edge); border-radius:28px; box-shadow:0 20px 60px rgba(23,38,66,.08); }}
    .hero {{ padding:28px; margin-bottom:20px; display:grid; grid-template-columns: 1.2fr .8fr; gap:20px; }}
    .panel {{ padding:22px; }}
    .grid {{ display:grid; gap:20px; grid-template-columns: 1.1fr .9fr; }}
    .three {{ display:grid; gap:20px; grid-template-columns: repeat(3, minmax(0,1fr)); }}
    .cards {{ display:grid; gap:14px; }}
    .card {{ border:1px solid var(--edge); border-radius:18px; background:var(--paper); padding:16px; }}
    .card-head {{ display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }}
    .hero h1 {{ font-size:4rem; line-height:.92; margin:0 0 14px; }}
    h2, h3 {{ margin-top:0; }}
    p {{ margin:.35rem 0; }}
    .eyebrow {{ text-transform:uppercase; letter-spacing:.18em; color:#db6f45; font-size:.8rem; margin-bottom:10px; }}
    .metrics {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:14px; margin-top:18px; }}
    .metric {{ border:1px solid var(--edge); border-radius:18px; padding:14px; background:#fbfaf6; }}
    .metric strong {{ display:block; font-size:1.8rem; }}
    .metric p, .muted {{ color:var(--muted); }}
    .stack {{ display:grid; gap:20px; }}
    form {{ display:grid; gap:10px; }}
    .stacked-form {{ margin-top:12px; }}
    input {{ padding:12px; border-radius:12px; border:1px solid var(--edge); font:inherit; background:#fff; }}
    button, .link-button {{ display:inline-flex; align-items:center; justify-content:center; border:0; border-radius:999px; padding:11px 18px; background:var(--green); color:#fff; font:inherit; text-decoration:none; cursor:pointer; }}
    .warning {{ background:var(--amber); color:var(--ink); }}
    .inline {{ display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px; }}
    .banner {{ margin-bottom:16px; padding:14px 16px; border-radius:14px; background:rgba(47,122,103,.12); border:1px solid rgba(47,122,103,.24); }}
    .badge {{ border-radius:999px; padding:8px 12px; font-size:.85rem; color:#fff; text-transform:capitalize; }}
    .badge.green {{ background:var(--green); }}
    .badge.amber {{ background:var(--amber); color:var(--ink); }}
    .badge.red {{ background:var(--red); }}
    .badge.slate {{ background:var(--slate); }}
    .section-grid {{ display:grid; gap:20px; grid-template-columns: 1fr 1fr; }}
    .list-tight {{ display:grid; gap:10px; }}
    @media (max-width: 980px) {{
      .hero, .grid, .three, .section-grid, .inline, .metrics {{ grid-template-columns: 1fr; }}
      .hero h1 {{ font-size:2.8rem; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    {banner}
    <section class="hero">
      <div>
        <div class="eyebrow">Local-first financial control plane</div>
        <h1>Credit Card Operations Dashboard</h1>
        <p class="muted">Monitor balances, track statement cycles, manage approval-gated payments, and keep issuer credentials encrypted on disk with no external dependency.</p>
        <div class="metrics">
          {summary_card("Accounts", str(summary.get("account_count", len(accounts))), "Connected card accounts")}
          {summary_card("Balance", f"${float(summary.get('total_balance', 0)):.2f}", "Current total balance")}
          {summary_card("Utilization", f"{float(summary.get('utilization_pct', 0)):.1f}%", "Portfolio utilization")}
          {summary_card("Pending items", str(int(summary.get("statement_requests_open", 0)) + int(summary.get("payments_pending", 0))), "Open statement and payment tasks")}
        </div>
      </div>
      <div class="panel">
        <h2>Operations</h2>
        <p class="muted">Keep runtime state current before creating statement or payment actions.</p>
        <form method="post" action="/refresh"><button type="submit">Refresh portfolio runtime</button></form>
        <div class="list-tight" style="margin-top:16px;">
          <div class="card">
            <strong>Upcoming reminders</strong>
            <p class="muted">{len(reminders)} due-date alerts inside the next 10 days.</p>
          </div>
          <div class="card">
            <strong>Secrets vault</strong>
            <p class="muted">Encrypted vault file: data/secrets.vault</p>
            <p class="muted">Metadata file: data/secrets.meta.json</p>
          </div>
        </div>
      </div>
    </section>

    <section class="grid">
      <div class="panel">
        <h2>Accounts and Connectors</h2>
        <div class="cards">{''.join(account_card(item) for item in accounts) or "<p class='muted'>No accounts yet.</p>"}</div>
      </div>
      <div class="stack">
        <div class="panel">
          <h2>Reminders</h2>
          <div class="cards">
            {''.join(f"<article class='card'><strong>{html_escape(item['nickname'])}</strong><p>{html_escape(item['issuer'])} · Due {html_escape(item['next_due_date'])}</p><p>Minimum due ${float(item['minimum_due']):.2f} · {int(item['days_left'])} days left</p></article>" for item in reminders) or "<p class='muted'>No upcoming reminders.</p>"}
          </div>
        </div>
        <div class="panel">
          <h2>Secure Vault</h2>
          <form method="post" action="/save-credentials">
            <input list="account-options" name="account_id" placeholder="account id">
            <input name="username" placeholder="username">
            <input name="password" placeholder="password" type="password">
            <input name="passphrase" placeholder="vault passphrase" type="password">
            <button type="submit">Store masked credentials</button>
          </form>
        </div>
      </div>
    </section>

    <section class="three" style="margin-top:20px;">
      <div class="panel">
        <h2>Account Setup</h2>
        <form method="post" action="/upsert-account">
          <div class="inline">
            <input name="issuer" placeholder="issuer">
            <input name="nickname" placeholder="nickname">
          </div>
          <div class="inline">
            <input name="last4" placeholder="last 4 digits">
            <input name="credit_limit" placeholder="credit limit">
          </div>
          <div class="inline">
            <input name="current_balance" placeholder="current balance">
            <input name="minimum_due" placeholder="minimum due">
          </div>
          <input name="next_due_date" placeholder="next due date YYYY-MM-DD">
          <button type="submit">Save account</button>
        </form>
      </div>

      <div class="panel">
        <h2>Statement Lifecycle</h2>
        <form method="post" action="/request-statement-pull">
          <input list="account-options" name="account_id" placeholder="account id">
          <input name="passphrase" placeholder="vault passphrase (optional)" type="password">
          <button type="submit">Queue statement request</button>
        </form>
        <form method="post" action="/upload-statement" enctype="multipart/form-data" style="margin-top:16px;">
          <input list="account-options" name="account_id" placeholder="account id">
          <input name="statement_file" type="file">
          <div class="inline">
            <input name="close_date" placeholder="close date YYYY-MM-DD">
            <input name="due_date" placeholder="due date YYYY-MM-DD">
          </div>
          <div class="inline">
            <input name="balance" placeholder="statement balance">
            <input name="minimum_due" placeholder="minimum due">
          </div>
          <button type="submit">Upload statement artifact</button>
        </form>
      </div>

      <div class="panel">
        <h2>Payment Lifecycle</h2>
        <form method="post" action="/create-payment">
          <input list="account-options" name="account_id" placeholder="account id">
          <div class="inline">
            <input name="amount" placeholder="amount">
            <input name="scheduled_date" placeholder="scheduled date YYYY-MM-DD">
          </div>
          <button type="submit">Create payment request</button>
        </form>
      </div>
    </section>

    <section class="section-grid" style="margin-top:20px;">
      <div class="panel">
        <h2>Statement Request Queue</h2>
        <div class="cards">{''.join(statement_request_card(item) for item in statement_requests_sorted[:8]) or "<p class='muted'>No statement requests.</p>"}</div>
      </div>
      <div class="panel">
        <h2>Recent Statements</h2>
        <div class="cards">{''.join(statement_card(item) for item in statements_sorted[:8]) or "<p class='muted'>No statements uploaded.</p>"}</div>
      </div>
    </section>

    <section class="section-grid" style="margin-top:20px;">
      <div class="panel">
        <h2>Payment Queue</h2>
        <div class="cards">{''.join(payment_request_card(item) for item in payment_requests_sorted[:8]) or "<p class='muted'>No payment requests.</p>"}</div>
      </div>
      <div class="panel">
        <h2>Agent Memory</h2>
        <div class="cards">{''.join(f"<article class='card'><strong>{html_escape(item['agent'])}</strong><p>{html_escape(item['message'])}</p><p class='muted'>{html_escape(item['timestamp'])}</p></article>" for item in memory[-10:][::-1]) or "<p class='muted'>No memory yet.</p>"}</div>
      </div>
    </section>
  </div>
  <datalist id="account-options">{datalist}</datalist>
</body>
</html>"""
    return page.encode("utf-8")


def handle_refresh() -> str:
    build_orchestrator().refresh()
    return "Portfolio runtime refreshed."


def handle_save_credentials(form: dict[str, list[str]]) -> str:
    build_orchestrator().save_credentials(
        form.get("account_id", [""])[0],
        form.get("username", [""])[0],
        form.get("password", [""])[0],
        form.get("passphrase", [""])[0],
    )
    return "Credentials stored in the local encrypted vault."


def handle_upsert_account(form: dict[str, list[str]]) -> str:
    build_orchestrator().upsert_account(
        {
            "issuer": form.get("issuer", [""])[0],
            "nickname": form.get("nickname", [""])[0],
            "last4": form.get("last4", [""])[0],
            "credit_limit": form.get("credit_limit", ["0"])[0],
            "current_balance": form.get("current_balance", ["0"])[0],
            "minimum_due": form.get("minimum_due", ["0"])[0],
            "next_due_date": form.get("next_due_date", [""])[0],
        }
    )
    return "Account saved and portfolio refreshed."


def handle_request_statement_pull(form: dict[str, list[str]]) -> str:
    request = build_orchestrator().queue_statement_pull(
        form.get("account_id", [""])[0],
        form.get("passphrase", [""])[0],
    )
    return f"Statement request queued with status {request['status']}."


def handle_upload_statement(form: dict[str, list[object]]) -> str:
    upload = form.get("statement_file", [])
    if not upload or not isinstance(upload[0], dict):
        raise ValueError("Choose a statement file to upload.")
    file_payload = upload[0]
    build_orchestrator().upload_statement(
        str(form.get("account_id", [""])[0]),
        str(file_payload.get("filename", "statement.pdf")),
        file_payload.get("content", b""),
        str(form.get("close_date", [""])[0]),
        str(form.get("due_date", [""])[0]),
        float(str(form.get("balance", ["0"])[0] or "0")),
        float(str(form.get("minimum_due", ["0"])[0] or "0")),
    )
    return "Statement uploaded and linked to the request lifecycle."


def handle_create_payment(form: dict[str, list[str]]) -> str:
    request = build_orchestrator().create_payment(
        form.get("account_id", [""])[0],
        float(str(form.get("amount", ["0"])[0] or "0")),
        form.get("scheduled_date", [""])[0],
    )
    return f"Payment request created for {request['issuer']}."


def handle_approve_payment(form: dict[str, list[str]]) -> str:
    passphrase = form.get("passphrase", [""])[0]
    request_id = form.get("request_id", [""])[0]
    request = build_orchestrator().approve_payment_with_passphrase(request_id, passphrase)
    return f"Payment request moved to {request['status']}."


def handle_mark_payment_complete(form: dict[str, list[str]]) -> str:
    request = build_orchestrator().mark_payment_completed(
        form.get("request_id", [""])[0],
        form.get("confirmation_reference", [""])[0],
    )
    return f"Payment request {request['id']} marked completed."


def handle_download_statement(environ, start_response):
    query = parse_qs(environ.get("QUERY_STRING", ""))
    statement_id = query.get("id", [""])[0]
    store = DashboardStore(DEFAULT_PATHS)
    for item in store.load_statement_index():
        if item["id"] != statement_id:
            continue
        target = Path(item["stored_path"])
        if not target.exists():
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"Statement artifact not found"]
        mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        headers = [
            ("Content-Type", mime_type),
            ("Content-Disposition", f"attachment; filename=\"{target.name}\""),
        ]
        start_response("200 OK", headers)
        return [target.read_bytes()]
    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Statement not found"]


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    message = parse_qs(environ.get("QUERY_STRING", "")).get("message", [""])[0]
    if method == "GET" and path == "/":
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [render_home(message)]
    if method == "GET" and path == "/download-statement":
        return handle_download_statement(environ, start_response)
    if method == "POST":
        try:
            form = parse_form(environ)
            if path == "/refresh":
                message = handle_refresh()
            elif path == "/save-credentials":
                message = handle_save_credentials(form)
            elif path == "/upsert-account":
                message = handle_upsert_account(form)
            elif path == "/request-statement-pull":
                message = handle_request_statement_pull(form)
            elif path == "/upload-statement":
                message = handle_upload_statement(form)
            elif path == "/create-payment":
                message = handle_create_payment(form)
            elif path == "/approve-payment":
                message = handle_approve_payment(form)
            elif path == "/mark-payment-complete":
                message = handle_mark_payment_complete(form)
            else:
                raise ValueError("Unknown action.")
            return redirect(start_response, message)
        except Exception as exc:  # noqa: BLE001
            return redirect(start_response, str(exc))
    if method == "GET" and path == "/health":
        start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"ok"]
    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
    return [b"Not found"]


def serve_ui(host: str = "127.0.0.1", port: int = 8010) -> None:
    with make_server(host, port, application) as server:
        print(f"Credit Card Dashboard running at http://{host}:{port}")
        server.serve_forever()
