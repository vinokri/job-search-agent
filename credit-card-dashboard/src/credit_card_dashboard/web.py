from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote_plus
from wsgiref.simple_server import make_server

from .models import load_json
from .orchestration import DashboardOrchestrator, DashboardStore, build_default_paths


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATHS = build_default_paths(ROOT)


def build_orchestrator() -> DashboardOrchestrator:
    return DashboardOrchestrator(DashboardStore(build_default_paths(ROOT)))


def html_escape(value: str) -> str:
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


def render_home(message: str = "") -> bytes:
    store = DashboardStore(DEFAULT_PATHS)
    accounts = store.load_accounts()
    runtime = store.load_runtime()
    memory = store.load_memory()
    payment_requests = store.load_payment_requests()
    statement_requests = store.load_statement_requests()
    statements = store.load_statement_index()

    reminder_rows = runtime.get("reminders", [])
    banner = f"<div class='banner'>{html_escape(message)}</div>" if message else ""

    def account_card(item: dict) -> str:
        utilization = 0.0
        if item.get("credit_limit"):
            utilization = round((float(item.get("current_balance", 0)) / float(item.get("credit_limit", 1))) * 100, 1)
        return f"""
<article class="card">
  <h3>{html_escape(item['nickname'])}</h3>
  <p><strong>{html_escape(item['issuer'])}</strong> ending {html_escape(item['last4'])}</p>
  <p>Balance: ${float(item.get('current_balance', 0)):.2f}</p>
  <p>Limit: ${float(item.get('credit_limit', 0)):.2f} · Utilization: {utilization:.1f}%</p>
  <p>Minimum due: ${float(item.get('minimum_due', 0)):.2f} · Next due: {html_escape(item.get('next_due_date', 'n/a'))}</p>
  <p>Credentials: {html_escape(item.get('masked_username', 'not saved'))}</p>
</article>
"""

    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Credit Card Dashboard</title>
  <style>
    body {{ margin:0; font-family: Georgia, serif; color:#16233f; background:linear-gradient(135deg,#f2e8dc,#f8f5ef); }}
    .shell {{ max-width: 1220px; margin:0 auto; padding: 24px; }}
    .hero, .panel {{ background: rgba(255,255,255,0.88); border:1px solid #d9c7b3; border-radius: 24px; box-shadow: 0 18px 50px rgba(22,35,63,0.08); }}
    .hero {{ padding: 28px; margin-bottom: 20px; }}
    .grid {{ display:grid; grid-template-columns: 1.1fr 0.9fr; gap: 20px; }}
    .panel {{ padding: 20px; }}
    .two {{ display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-top: 20px; }}
    .cards {{ display:grid; gap: 14px; }}
    .card {{ border:1px solid #d9c7b3; border-radius: 18px; padding: 16px; background:#fffdf9; }}
    h1 {{ font-size: 4rem; line-height: .95; margin: 0 0 12px; }}
    h2 {{ margin-top: 0; }}
    form {{ display:grid; gap: 10px; }}
    input {{ padding: 12px; border-radius: 12px; border:1px solid #d9c7b3; font: inherit; }}
    button {{ border:0; border-radius: 999px; padding: 11px 18px; background:#2f7a6d; color:#fff; font:inherit; cursor:pointer; }}
    .warning {{ background:#c4912f; color:#16233f; }}
    .inline {{ display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap:10px; }}
    .banner {{ margin-bottom: 16px; padding: 14px 16px; border-radius: 14px; background: rgba(47,122,109,0.12); border:1px solid rgba(47,122,109,0.24); }}
    .muted {{ color:#5b6677; }}
    @media (max-width: 920px) {{ .grid, .two, .inline {{ grid-template-columns: 1fr; }} h1 {{ font-size: 2.7rem; }} }}
  </style>
</head>
<body>
  <div class="shell">
    {banner}
    <section class="hero">
      <div class="muted" style="text-transform:uppercase; letter-spacing:.18em;">Local-first financial workflow</div>
      <h1>Credit Card Dashboard</h1>
      <p class="muted">Track balances, statements, reminders, and approval-based payments across multiple cards with a secure local vault.</p>
      <p><strong>{runtime.get('summary', {}).get('account_count', len(accounts))}</strong> accounts · <strong>${float(runtime.get('summary', {}).get('total_balance', 0)):.2f}</strong> total balance · <strong>{float(runtime.get('summary', {}).get('utilization_pct', 0)):.1f}%</strong> utilization</p>
      <form method="post" action="/refresh"><button type="submit">Refresh dashboard</button></form>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>Accounts</h2>
        <div class="cards">{''.join(account_card(item) for item in accounts) or "<p class='muted'>No accounts yet.</p>"}</div>
      </div>
      <div class="panel">
        <h2>Reminders</h2>
        <div class="cards">
          {''.join(f"<article class='card'><strong>{html_escape(item['nickname'])}</strong><p>{html_escape(item['issuer'])} · Due {html_escape(item['next_due_date'])}</p><p>Minimum due ${float(item['minimum_due']):.2f} · {int(item['days_left'])} days left</p></article>" for item in reminder_rows) or "<p class='muted'>No upcoming reminders.</p>"}
        </div>
      </div>
    </section>
    <section class="two">
      <div class="panel">
        <h2>Save Credentials</h2>
        <form method="post" action="/save-credentials">
          <div class="inline">
            <input name="account_id" placeholder="account id">
            <input name="username" placeholder="username">
          </div>
          <div class="inline">
            <input name="password" placeholder="password" type="password">
            <input name="passphrase" placeholder="vault passphrase" type="password">
          </div>
          <button type="submit">Store masked credentials</button>
        </form>
      </div>
      <div class="panel">
        <h2>Add Or Update Account</h2>
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
        <h2>Statements</h2>
        <form method="post" action="/request-statement-pull">
          <div class="inline">
            <input name="account_id" placeholder="account id">
            <input name="passphrase" placeholder="vault passphrase" type="password">
          </div>
          <button type="submit" class="warning">Queue statement pull</button>
        </form>
        <form method="post" action="/upload-statement" enctype="multipart/form-data" style="margin-top: 16px;">
          <div class="inline">
            <input name="account_id" placeholder="account id">
            <input name="statement_file" type="file">
          </div>
          <div class="inline">
            <input name="close_date" placeholder="close date YYYY-MM-DD">
            <input name="due_date" placeholder="due date YYYY-MM-DD">
          </div>
          <div class="inline">
            <input name="balance" placeholder="statement balance">
            <input name="minimum_due" placeholder="minimum due">
          </div>
          <button type="submit">Upload statement</button>
        </form>
        <div class="cards" style="margin-top:16px;">
          {''.join(f"<article class='card'><strong>{html_escape(item['issuer'])}</strong><p>{html_escape(item['filename'])}</p><p>Close {html_escape(item['close_date'])} · Due {html_escape(item['due_date'])}</p></article>" for item in statements[-6:][::-1]) or "<p class='muted'>No statements uploaded.</p>"}
        </div>
      </div>
      <div class="panel">
        <h2>Payments</h2>
        <form method="post" action="/create-payment">
          <div class="inline">
            <input name="account_id" placeholder="account id">
            <input name="amount" placeholder="amount">
          </div>
          <input name="scheduled_date" placeholder="scheduled date YYYY-MM-DD">
          <button type="submit">Create payment request</button>
        </form>
        <div class="cards" style="margin-top:16px;">
          {''.join(f"<article class='card'><strong>{html_escape(item['issuer'])}</strong><p>${float(item['amount']):.2f} · {html_escape(item['scheduled_date'])}</p><p>Status: {html_escape(item['status'])}</p><form method='post' action='/approve-payment'><input type='hidden' name='request_id' value='{html_escape(item['id'])}'><button type='submit'>Approve payment</button></form></article>" for item in payment_requests[::-1]) or "<p class='muted'>No payment requests.</p>"}
        </div>
      </div>
      <div class="panel" style="grid-column:1 / -1;">
        <h2>Agent Memory</h2>
        <div class="cards">{''.join(f"<article class='card'><strong>{html_escape(item['agent'])}</strong><p>{html_escape(item['message'])}</p><p class='muted'>{html_escape(item['timestamp'])}</p></article>" for item in memory[-8:][::-1]) or "<p class='muted'>No memory yet.</p>"}</div>
      </div>
    </section>
  </div>
</body>
</html>"""
    return page.encode("utf-8")


def handle_refresh() -> str:
    build_orchestrator().refresh()
    return "Dashboard refreshed."


def handle_save_credentials(form: dict[str, list[str]]) -> str:
    build_orchestrator().save_credentials(
        form.get("account_id", [""])[0],
        form.get("username", [""])[0],
        form.get("password", [""])[0],
        form.get("passphrase", [""])[0],
    )
    return "Credentials stored in the local vault."


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
    return "Account saved."


def handle_request_statement_pull(form: dict[str, list[str]]) -> str:
    request = build_orchestrator().queue_statement_pull(
        form.get("account_id", [""])[0],
        form.get("passphrase", [""])[0],
    )
    return f"Statement pull queued with status {request['status']}."


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
    return "Statement uploaded and account balance refreshed."


def handle_create_payment(form: dict[str, list[str]]) -> str:
    request = build_orchestrator().create_payment(
        form.get("account_id", [""])[0],
        float(str(form.get("amount", ["0"])[0] or "0")),
        form.get("scheduled_date", [""])[0],
    )
    return f"Payment request created for {request['issuer']}."


def handle_approve_payment(form: dict[str, list[str]]) -> str:
    request = build_orchestrator().approve_payment(form.get("request_id", [""])[0])
    return f"Payment request {request['id']} approved."


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()
    message = parse_qs(environ.get("QUERY_STRING", "")).get("message", [""])[0]
    if method == "GET" and path == "/":
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [render_home(message)]
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
