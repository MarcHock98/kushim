"""Schlüsselverwaltung. Der Schlüssel liegt nie im Vault und nie auf dem NAS."""
from __future__ import annotations

import os
import secrets

import keyring

SERVICE = "kushim-vault"


def get_or_create_key(vault_id: str, create: bool = False) -> str:
    """Liefert den Vault-Schlüssel (hex). Reihenfolge: Env-Variable, Windows Credential Manager."""
    env = os.environ.get("KUSHIM_VAULT_KEY")
    if env:
        return env
    key = keyring.get_password(SERVICE, vault_id)
    if key:
        return key
    if not create:
        raise KeyError(
            f"Kein Schlüssel für Vault {vault_id}. Mit `kushim key export` auf dem alten "
            "Rechner sichern und mit `kushim key import` importieren."
        )
    key = secrets.token_hex(32)
    keyring.set_password(SERVICE, vault_id, key)
    return key


def store_key(vault_id: str, key: str) -> None:
    keyring.set_password(SERVICE, vault_id, key)
