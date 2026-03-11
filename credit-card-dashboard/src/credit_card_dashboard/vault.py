from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

from .models import dump_json, load_json, mask_value


class LocalSecretsVault:
    def __init__(self, vault_path: str | Path):
        self.vault_path = Path(vault_path)

    def openssl_available(self) -> bool:
        return shutil.which("openssl") is not None

    def load(self, passphrase: str) -> dict:
        if not self.vault_path.exists():
            return {}
        self._ensure_openssl()
        encrypted = self.vault_path.read_bytes()
        process = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-d", "-pbkdf2", "-a", "-pass", f"pass:{passphrase}"],
            input=encrypted,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            raise ValueError("Unable to unlock vault. Check your passphrase.")
        data = process.stdout.decode("utf-8")
        return load_json_from_text(data)

    def save(self, payload: dict, passphrase: str) -> None:
        self._ensure_openssl()
        plain = dump_json_to_text(payload).encode("utf-8")
        process = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-a", "-salt", "-pass", f"pass:{passphrase}"],
            input=plain,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            raise ValueError("Unable to save vault.")
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_bytes(process.stdout)

    def set_credentials(self, account_id: str, username: str, password: str, passphrase: str) -> dict:
        payload = self.load(passphrase)
        payload[account_id] = {"username": username, "password": password}
        self.save(payload, passphrase)
        return {
            "credential_saved": True,
            "masked_username": mask_value(username),
            "masked_password": "********",
        }

    def has_credentials(self, account_id: str, passphrase: str) -> bool:
        payload = self.load(passphrase)
        return account_id in payload

    def _ensure_openssl(self) -> None:
        if not self.openssl_available():
            raise ValueError("openssl is required for the local secrets vault.")


def dump_json_to_text(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2)


def load_json_from_text(text: str) -> dict:
    import json

    return json.loads(text) if text.strip() else {}
