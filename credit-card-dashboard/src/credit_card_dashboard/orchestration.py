from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .adapters import get_adapter, normalize_issuer_key
from .models import dump_json, load_json, slugify, today_iso, utc_now
from .vault import LocalSecretsVault


@dataclass
class DashboardPaths:
    accounts: Path
    runtime: Path
    memory: Path
    payment_requests: Path
    statement_requests: Path
    statement_index: Path
    statement_files: Path
    secrets_vault: Path
    secrets_metadata: Path


def build_default_paths(root: Path) -> DashboardPaths:
    data_dir = root / "data"
    statements_dir = data_dir / "statements"
    return DashboardPaths(
        accounts=data_dir / "accounts.json",
        runtime=data_dir / "runtime.json",
        memory=data_dir / "memory.json",
        payment_requests=data_dir / "payment-requests.json",
        statement_requests=data_dir / "statement-requests.json",
        statement_index=statements_dir / "index.json",
        statement_files=statements_dir / "files",
        secrets_vault=data_dir / "secrets.vault",
        secrets_metadata=data_dir / "secrets.meta.json",
    )


class DashboardStore:
    def __init__(self, paths: DashboardPaths):
        self.paths = paths

    def load_accounts(self) -> list[dict]:
        return load_json(self.paths.accounts, [])

    def save_accounts(self, payload: list[dict]) -> None:
        dump_json(self.paths.accounts, payload)

    def load_runtime(self) -> dict:
        return load_json(
            self.paths.runtime,
            {"updated_at": "", "summary": {}, "reminders": [], "connectors": {}, "lifecycle": {}},
        )

    def save_runtime(self, payload: dict) -> None:
        payload["updated_at"] = utc_now()
        dump_json(self.paths.runtime, payload)

    def load_memory(self) -> list[dict]:
        return load_json(self.paths.memory, [])

    def append_memory(self, agent: str, action: str, message: str, payload: dict | None = None) -> None:
        memory = self.load_memory()
        memory.append(
            {
                "timestamp": utc_now(),
                "agent": agent,
                "action": action,
                "message": message,
                "payload": payload or {},
            }
        )
        dump_json(self.paths.memory, memory)

    def load_payment_requests(self) -> list[dict]:
        return load_json(self.paths.payment_requests, [])

    def save_payment_requests(self, payload: list[dict]) -> None:
        dump_json(self.paths.payment_requests, payload)

    def load_statement_requests(self) -> list[dict]:
        return load_json(self.paths.statement_requests, [])

    def save_statement_requests(self, payload: list[dict]) -> None:
        dump_json(self.paths.statement_requests, payload)

    def load_statement_index(self) -> list[dict]:
        return load_json(self.paths.statement_index, [])

    def save_statement_index(self, payload: list[dict]) -> None:
        dump_json(self.paths.statement_index, payload)


class PortfolioRefreshAgent:
    name = "portfolio-refresh-agent"

    def __init__(self, store: DashboardStore):
        self.store = store

    def run(self) -> dict:
        accounts = self.store.load_accounts()
        reminders = ReminderAgent(self.store).run(accounts)
        payment_requests = self.store.load_payment_requests()
        statement_requests = self.store.load_statement_requests()
        total_balance = round(sum(float(item.get("current_balance", 0) or 0) for item in accounts), 2)
        total_limit = round(sum(float(item.get("credit_limit", 0) or 0) for item in accounts), 2)
        summary = {
            "account_count": len(accounts),
            "total_balance": total_balance,
            "total_credit_limit": total_limit,
            "utilization_pct": round((total_balance / total_limit) * 100, 1) if total_limit else 0.0,
            "statement_requests_open": sum(1 for item in statement_requests if item.get("status") not in {"completed_with_upload", "cancelled"}),
            "payments_pending": sum(1 for item in payment_requests if item.get("status") in {"pending_approval", "approved_ready_for_confirmation"}),
            "last_refreshed_at": utc_now(),
        }
        connector_summary: dict[str, dict] = {}
        for account in accounts:
            adapter = get_adapter(account["issuer"])
            connector_summary[account["id"]] = {
                "issuer_key": adapter.issuer_key,
                "portal_label": adapter.portal_label,
                "statement_mode": adapter.statement_mode,
                "payment_mode": adapter.payment_mode,
                "credential_saved": bool(account.get("credential_saved")),
            }
        runtime = self.store.load_runtime()
        runtime["summary"] = summary
        runtime["reminders"] = reminders
        runtime["connectors"] = connector_summary
        runtime["lifecycle"] = {
            "open_statement_requests": summary["statement_requests_open"],
            "pending_payment_requests": summary["payments_pending"],
        }
        self.store.save_runtime(runtime)
        self.store.append_memory(self.name, "refresh", "Refreshed account summary and reminders.", payload=summary)
        return runtime


class ReminderAgent:
    name = "reminder-agent"

    def __init__(self, store: DashboardStore):
        self.store = store

    def run(self, accounts: list[dict]) -> list[dict]:
        today = date.fromisoformat(today_iso())
        reminders: list[dict] = []
        for account in accounts:
            due_date = account.get("next_due_date")
            if not due_date:
                continue
            try:
                due = date.fromisoformat(due_date)
            except ValueError:
                continue
            delta = (due - today).days
            if delta <= 10:
                reminders.append(
                    {
                        "account_id": account["id"],
                        "issuer": account["issuer"],
                        "nickname": account["nickname"],
                        "next_due_date": due_date,
                        "minimum_due": account.get("minimum_due", 0),
                        "days_left": delta,
                        "severity": "urgent" if delta <= 3 else "upcoming",
                    }
                )
        self.store.append_memory(self.name, "compute-reminders", f"Computed {len(reminders)} payment reminders.")
        return reminders


class StatementPullAgent:
    name = "statement-pull-agent"

    def __init__(self, store: DashboardStore, vault: LocalSecretsVault):
        self.store = store
        self.vault = vault

    def queue_pull(self, account_id: str, passphrase: str) -> dict:
        accounts = {item["id"]: item for item in self.store.load_accounts()}
        if account_id not in accounts:
            raise ValueError(f"Account '{account_id}' not found.")
        account = accounts[account_id]
        adapter = get_adapter(account["issuer"])
        has_credentials = False
        if passphrase:
            has_credentials = self.vault.has_credentials(account_id, passphrase)
        credential_status = "credentials_ready" if has_credentials else "credentials_missing"
        requests = self.store.load_statement_requests()
        request = {
            "id": f"pull-{account_id}-{utc_now()}",
            "account_id": account_id,
            "issuer_key": adapter.issuer_key,
            "status": "queued_for_manual_import" if has_credentials else "queued_missing_credentials",
            "credential_status": credential_status,
            "requested_at": utc_now(),
            "issuer": account["issuer"],
            "portal_label": adapter.portal_label,
            "next_step": "Download the latest statement locally, then upload it into the dashboard.",
            "notes": adapter.statement_notes,
        }
        requests.append(request)
        self.store.save_statement_requests(requests)
        self.store.append_memory(self.name, "queue-pull", f"Queued statement pull for {account_id}.", payload=request)
        return request

    def upload_statement(
        self,
        account_id: str,
        filename: str,
        payload: bytes,
        close_date: str,
        due_date: str,
        balance: float,
        minimum_due: float,
    ) -> dict:
        accounts = self.store.load_accounts()
        account_map = {item["id"]: item for item in accounts}
        if account_id not in account_map:
            raise ValueError(f"Account '{account_id}' not found.")
        safe_name = f"{account_id}-{slugify(filename)}"
        target = self.store.paths.statement_files / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        index = self.store.load_statement_index()
        entry = {
            "id": f"statement-{account_id}-{utc_now()}",
            "account_id": account_id,
            "issuer": account_map[account_id]["issuer"],
            "filename": filename,
            "stored_path": str(target),
            "close_date": close_date,
            "due_date": due_date,
            "statement_balance": balance,
            "minimum_due": minimum_due,
            "uploaded_at": utc_now(),
        }
        index.append(entry)
        self.store.save_statement_index(index)

        account_map[account_id]["last_statement_balance"] = balance
        account_map[account_id]["current_balance"] = balance
        account_map[account_id]["minimum_due"] = minimum_due
        account_map[account_id]["next_due_date"] = due_date
        self.store.save_accounts(list(account_map.values()))
        requests = self.store.load_statement_requests()
        for request in reversed(requests):
            if request["account_id"] == account_id and request["status"] in {"queued_missing_credentials", "queued_for_manual_import"}:
                request["status"] = "completed_with_upload"
                request["completed_at"] = utc_now()
                request["statement_id"] = entry["id"]
                break
        self.store.save_statement_requests(requests)
        self.store.append_memory(self.name, "upload-statement", f"Uploaded statement for {account_id}.", payload=entry)
        return entry


class PaymentExecutionAgent:
    name = "payment-execution-agent"

    def __init__(self, store: DashboardStore, vault: LocalSecretsVault):
        self.store = store
        self.vault = vault

    def create_request(self, account_id: str, amount: float, scheduled_date: str) -> dict:
        accounts = {item["id"]: item for item in self.store.load_accounts()}
        if account_id not in accounts:
            raise ValueError(f"Account '{account_id}' not found.")
        account = accounts[account_id]
        adapter = get_adapter(account["issuer"])
        requests = self.store.load_payment_requests()
        request = {
            "id": f"payment-{account_id}-{utc_now()}",
            "account_id": account_id,
            "issuer": account["issuer"],
            "issuer_key": adapter.issuer_key,
            "amount": round(amount, 2),
            "scheduled_date": scheduled_date,
            "status": "pending_approval",
            "created_at": utc_now(),
            "next_step": "Approve this payment before any external bank action occurs.",
            "notes": adapter.payment_notes,
        }
        requests.append(request)
        self.store.save_payment_requests(requests)
        self.store.append_memory(self.name, "create-payment", f"Created payment request for {account_id}.", payload=request)
        return request

    def approve(self, request_id: str, passphrase: str = "") -> dict:
        requests = self.store.load_payment_requests()
        accounts = {item["id"]: item for item in self.store.load_accounts()}
        for item in requests:
            if item["id"] == request_id:
                account = accounts.get(item["account_id"], {})
                adapter = get_adapter(item["issuer"])
                has_credentials = False
                if passphrase:
                    has_credentials = self.vault.has_credentials(item["account_id"], passphrase)
                item["status"] = "approved_ready_for_confirmation" if has_credentials else "approved_missing_credentials"
                item["approved_at"] = utc_now()
                item["credential_status"] = "credentials_ready" if has_credentials else "credentials_missing"
                item["next_step"] = (
                    f"Use {adapter.portal_label} to confirm payment locally."
                    if has_credentials
                    else "Add credentials to the local vault before confirming payment."
                )
                self.store.save_payment_requests(requests)
                self.store.append_memory(self.name, "approve-payment", f"Approved payment {request_id}.", payload=item)
                return item
        raise ValueError(f"Payment request '{request_id}' not found.")

    def mark_completed(self, request_id: str, confirmation_reference: str) -> dict:
        requests = self.store.load_payment_requests()
        for item in requests:
            if item["id"] == request_id:
                item["status"] = "completed"
                item["completed_at"] = utc_now()
                item["confirmation_reference"] = confirmation_reference.strip() or "manual-confirmation"
                item["next_step"] = "Payment lifecycle completed."
                self.store.save_payment_requests(requests)
                self.store.append_memory(self.name, "mark-payment-complete", f"Completed payment {request_id}.", payload=item)
                return item
        raise ValueError(f"Payment request '{request_id}' not found.")


class DashboardOrchestrator:
    def __init__(self, store: DashboardStore):
        self.store = store
        self.vault = LocalSecretsVault(store.paths.secrets_vault, store.paths.secrets_metadata)
        self.refresh_agent = PortfolioRefreshAgent(store)
        self.statement_agent = StatementPullAgent(store, self.vault)
        self.payment_agent = PaymentExecutionAgent(store, self.vault)

    def refresh(self) -> dict:
        return self.refresh_agent.run()

    def save_credentials(self, account_id: str, username: str, password: str, passphrase: str) -> dict:
        masked = self.vault.set_credentials(account_id, username, password, passphrase)
        accounts = self.store.load_accounts()
        for account in accounts:
            if account["id"] == account_id:
                account["credential_saved"] = True
                account["masked_username"] = masked["masked_username"]
        self.store.save_accounts(accounts)
        self.store.append_memory("vault-agent", "save-credentials", f"Stored masked credentials for {account_id}.")
        self.refresh()
        return masked

    def upsert_account(self, payload: dict) -> dict:
        accounts = self.store.load_accounts()
        account_id = payload.get("id") or slugify(f"{payload['issuer']}-{payload['nickname']}-{payload['last4']}")
        record = {
            "id": account_id,
            "issuer": payload["issuer"],
            "issuer_key": payload.get("issuer_key") or normalize_issuer_key(payload["issuer"]),
            "nickname": payload["nickname"],
            "last4": payload["last4"],
            "credit_limit": float(payload.get("credit_limit", 0) or 0),
            "current_balance": float(payload.get("current_balance", 0) or 0),
            "minimum_due": float(payload.get("minimum_due", 0) or 0),
            "next_due_date": payload.get("next_due_date", ""),
            "autopay_enabled": bool(payload.get("autopay_enabled", False)),
            "credential_saved": bool(payload.get("credential_saved", False)),
            "masked_username": payload.get("masked_username", ""),
        }
        updated = False
        for index, account in enumerate(accounts):
            if account["id"] == account_id:
                accounts[index] = {**account, **record}
                updated = True
                break
        if not updated:
            accounts.append(record)
        self.store.save_accounts(accounts)
        self.store.append_memory("portfolio-agent", "upsert-account", f"Saved account {account_id}.", payload=record)
        self.refresh()
        return record

    def queue_statement_pull(self, account_id: str, passphrase: str) -> dict:
        return self.statement_agent.queue_pull(account_id, passphrase)

    def upload_statement(self, account_id: str, filename: str, payload: bytes, close_date: str, due_date: str, balance: float, minimum_due: float) -> dict:
        statement = self.statement_agent.upload_statement(account_id, filename, payload, close_date, due_date, balance, minimum_due)
        self.refresh()
        return statement

    def create_payment(self, account_id: str, amount: float, scheduled_date: str) -> dict:
        return self.payment_agent.create_request(account_id, amount, scheduled_date)

    def approve_payment(self, request_id: str) -> dict:
        approved = self.payment_agent.approve(request_id)
        self.refresh()
        return approved

    def approve_payment_with_passphrase(self, request_id: str, passphrase: str) -> dict:
        approved = self.payment_agent.approve(request_id, passphrase)
        self.refresh()
        return approved

    def mark_payment_completed(self, request_id: str, confirmation_reference: str) -> dict:
        completed = self.payment_agent.mark_completed(request_id, confirmation_reference)
        self.refresh()
        return completed
