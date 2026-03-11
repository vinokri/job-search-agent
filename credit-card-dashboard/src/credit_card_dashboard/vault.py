from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import ensure_private_file, load_json, mask_value, utc_now


class LocalSecretsVault:
    def __init__(self, vault_path: str | Path, metadata_path: str | Path | None = None):
        self.vault_path = Path(vault_path)
        self.metadata_path = Path(metadata_path) if metadata_path else self.vault_path.with_suffix(".meta.json")

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
        with tempfile.NamedTemporaryFile("wb", dir=self.vault_path.parent, delete=False) as handle:
            handle.write(process.stdout)
            temp_name = handle.name
        Path(temp_name).replace(self.vault_path)
        ensure_private_file(self.vault_path)

    def set_credentials(self, account_id: str, username: str, password: str, passphrase: str) -> dict:
        payload = self.load(passphrase)
        payload[account_id] = {"username": username, "password": password}
        self.save(payload, passphrase)
        metadata = self.load_metadata()
        metadata[account_id] = {
            "masked_username": mask_value(username),
            "credential_saved": True,
            "updated_at": utc_now(),
            "secret_version": 1,
        }
        self.save_metadata(metadata)
        return {
            "credential_saved": True,
            "masked_username": mask_value(username),
            "masked_password": "********",
        }

    def has_credentials(self, account_id: str, passphrase: str) -> bool:
        payload = self.load(passphrase)
        return account_id in payload

    def load_metadata(self) -> dict:
        return load_json(self.metadata_path, {})

    def save_metadata(self, payload: dict) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.metadata_path.parent, delete=False) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(self.metadata_path)
        ensure_private_file(self.metadata_path)

    def masked_username(self, account_id: str) -> str:
        return self.load_metadata().get(account_id, {}).get("masked_username", "")

    def _ensure_openssl(self) -> None:
        if not self.openssl_available():
            raise ValueError("openssl is required for the local secrets vault.")


def dump_json_to_text(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2)


def load_json_from_text(text: str) -> dict:
    import json

    return json.loads(text) if text.strip() else {}
