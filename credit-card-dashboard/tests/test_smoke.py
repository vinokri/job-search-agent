from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from credit_card_dashboard.models import load_json
from credit_card_dashboard.orchestration import DashboardOrchestrator, DashboardPaths, DashboardStore
from credit_card_dashboard.vault import LocalSecretsVault


class DashboardSmokeTest(unittest.TestCase):
    def make_paths(self, tmp: Path) -> DashboardPaths:
        return DashboardPaths(
            accounts=tmp / "accounts.json",
            runtime=tmp / "runtime.json",
            memory=tmp / "memory.json",
            payment_requests=tmp / "payment-requests.json",
            statement_requests=tmp / "statement-requests.json",
            statement_index=tmp / "statements" / "index.json",
            statement_files=tmp / "statements" / "files",
            secrets_vault=tmp / "secrets.vault",
        )

    def test_refresh_and_payment_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            store = DashboardStore(paths)
            store.save_accounts(
                [
                    {
                        "id": "card-1",
                        "issuer": "Chase",
                        "nickname": "Sapphire",
                        "last4": "1234",
                        "credit_limit": 10000,
                        "current_balance": 1500,
                        "minimum_due": 50,
                        "next_due_date": "2026-03-15",
                        "autopay_enabled": False,
                        "credential_saved": False,
                        "masked_username": "",
                    }
                ]
            )
            orchestrator = DashboardOrchestrator(store)
            runtime = orchestrator.refresh()
            self.assertEqual(runtime["summary"]["account_count"], 1)
            request = orchestrator.create_payment("card-1", 125.50, "2026-03-12")
            self.assertEqual(request["status"], "pending_approval")
            approved = orchestrator.approve_payment(request["id"])
            self.assertEqual(approved["status"], "approved_and_recorded")

    def test_statement_upload_updates_account(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            paths = self.make_paths(tmp)
            store = DashboardStore(paths)
            store.save_accounts(
                [
                    {
                        "id": "card-1",
                        "issuer": "Discover",
                        "nickname": "It",
                        "last4": "9999",
                        "credit_limit": 5000,
                        "current_balance": 0,
                        "minimum_due": 0,
                        "next_due_date": "",
                        "autopay_enabled": False,
                        "credential_saved": False,
                        "masked_username": "",
                    }
                ]
            )
            orchestrator = DashboardOrchestrator(store)
            entry = orchestrator.upload_statement(
                "card-1",
                "statement.pdf",
                b"fake-pdf",
                "2026-03-01",
                "2026-03-20",
                742.11,
                35.0,
            )
            self.assertEqual(entry["account_id"], "card-1")
            accounts = store.load_accounts()
            self.assertEqual(accounts[0]["current_balance"], 742.11)

    def test_vault_masking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            vault = LocalSecretsVault(tmp / "vault.enc")
            with patch.object(vault, "openssl_available", return_value=True), patch(
                "subprocess.run"
            ) as run_mock:
                run_mock.side_effect = [
                    type("Result", (), {"returncode": 0, "stdout": b"{}", "stderr": b""})(),
                    type("Result", (), {"returncode": 0, "stdout": b"encrypted", "stderr": b""})(),
                ]
                masked = vault.set_credentials("card-1", "vinodh@example.com", "secret", "passphrase")
                self.assertTrue(masked["credential_saved"])
                self.assertIn("*", masked["masked_username"])


if __name__ == "__main__":
    unittest.main()
